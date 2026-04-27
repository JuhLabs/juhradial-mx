//! HID++ protocol handler for reading diverted button events via hidraw
//!
//! When buttons are diverted via HID++ configuration (Logitech's proprietary
//! protocol), they send HID++ notifications instead of standard evdev events.
//! This module reads those notifications from the hidraw device.
//!
//! SPDX-License-Identifier: GPL-3.0

use std::fs::{File, OpenOptions};
use std::io::{self, Read};
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::time::Instant;
use tokio::sync::mpsc;

use crate::evdev::GestureEvent;

/// Logitech vendor ID
pub const LOGITECH_VENDOR_ID: u16 = 0x046D;

/// Bolt receiver product ID
pub const BOLT_RECEIVER_PID: u16 = 0xC548;

/// HID++ report types
pub const HIDPP_SHORT: u8 = 0x10;
pub const HIDPP_LONG: u8 = 0x11;

/// HID++ 2.0 feature for diverted buttons
pub const FEATURE_REPROG_CONTROLS_V4: u16 = 0x1B04;

/// Diverted button notification function ID
pub const DIVERTED_BUTTONS_EVENT: u8 = 0x00;

/// Known button CIDs (Control IDs) for MX Master 4
pub mod button_cid {
    /// Middle button
    pub const MIDDLE_BUTTON: u16 = 82;
    /// Back button
    pub const BACK_BUTTON: u16 = 83;
    /// Forward button
    pub const FORWARD_BUTTON: u16 = 86;
    /// Gesture button (thumb button)
    pub const GESTURE_BUTTON: u16 = 195;
    /// Smart shift (scroll wheel click)
    pub const SMART_SHIFT: u16 = 196;
    /// Haptic feedback button (if present)
    pub const HAPTIC: u16 = 416;
}

/// HID++ hidraw handler for reading diverted button events
pub struct HidrawHandler {
    /// Channel to send gesture events
    event_tx: mpsc::Sender<GestureEvent>,
    /// Path to the hidraw device
    device_path: Option<PathBuf>,
    /// Time when gesture button was pressed
    press_time: Option<Instant>,
    /// Device file handle
    device: Option<File>,
    /// Device index (for Bolt receiver, typically 0x02)
    /// Reserved for future HID++ feature discovery
    _device_index: u8,
    /// Feature index for REPROG_CONTROLS_V4 (discovered at runtime)
    /// Reserved for future HID++ feature discovery
    _reprog_feature_index: Option<u8>,
    /// CIDs diverted for macros (not gesture buttons)
    macro_cids: Vec<u16>,
    /// Track which macro CID is currently pressed (for release detection)
    active_macro_cid: Option<u16>,
    /// Shared configuration for button action lookup
    shared_config: Option<crate::config::SharedConfig>,
    /// The action that was triggered on button press (for release handling)
    active_button_action: Option<crate::config::ButtonAction>,
}

/// Map HID++ CID to evdev key code for macro trigger forwarding
pub fn cid_to_evdev_keycode(cid: u16) -> Option<u16> {
    match cid {
        button_cid::BACK_BUTTON => Some(0x113),    // BTN_SIDE
        button_cid::FORWARD_BUTTON => Some(0x114), // BTN_EXTRA
        button_cid::MIDDLE_BUTTON => Some(0x112),  // BTN_MIDDLE
        _ => None,
    }
}

/// Map evdev key code to HID++ CID (reverse of cid_to_evdev_keycode)
pub fn evdev_keycode_to_cid(keycode: u16) -> Option<u16> {
    match keycode {
        0x113 => Some(button_cid::BACK_BUTTON),    // BTN_SIDE -> Back
        0x114 => Some(button_cid::FORWARD_BUTTON), // BTN_EXTRA -> Forward
        0x112 => Some(button_cid::MIDDLE_BUTTON),  // BTN_MIDDLE -> Middle
        _ => None,
    }
}

impl HidrawHandler {
    /// Create a new hidraw handler
    pub fn new(event_tx: mpsc::Sender<GestureEvent>) -> Self {
        Self {
            event_tx,
            device_path: None,
            press_time: None,
            device: None,
            _device_index: 0x02, // Default for Bolt receiver
            _reprog_feature_index: None,
            macro_cids: Vec::new(),
            active_macro_cid: None,
            shared_config: None,
            active_button_action: None,
        }
    }

    /// Register CIDs that are diverted for macro triggers (not gesture buttons)
    pub fn set_macro_cids(&mut self, cids: Vec<u16>) {
        self.macro_cids = cids;
    }

    /// Set the shared configuration for button action lookup
    pub fn set_shared_config(&mut self, config: crate::config::SharedConfig) {
        self.shared_config = Some(config);
    }

    /// Look up the configured action for a CID from shared config
    fn get_action_for_cid(&self, cid: u16) -> crate::config::ButtonAction {
        if let Some(ref config) = self.shared_config {
            if let Ok(cfg) = config.read() {
                return cfg.action_for_cid(cid);
            }
        }
        // Fallback: gesture/haptic buttons default to radial menu
        match cid {
            button_cid::GESTURE_BUTTON => crate::config::ButtonAction::VirtualDesktops,
            button_cid::HAPTIC => crate::config::ButtonAction::RadialMenu,
            _ => crate::config::ButtonAction::None,
        }
    }

    /// Find the Logitech hidraw device for HID++ button events
    ///
    /// Supports multiple receiver types:
    /// - Bolt receiver (046D:C548)
    /// - Unifying receiver (046D:C52B)
    /// - Direct USB connection (046D:B034, etc.)
    pub fn find_device() -> Result<PathBuf, HidrawError> {
        // Scan /sys/class/hidraw/ for Logitech devices
        let hidraw_dir = PathBuf::from("/sys/class/hidraw");
        if !hidraw_dir.exists() {
            return Err(HidrawError::DeviceNotFound);
        }

        let mut candidates: Vec<(PathBuf, String, u8)> = Vec::new();

        for entry in std::fs::read_dir(&hidraw_dir).map_err(HidrawError::IoError)? {
            let entry = entry.map_err(HidrawError::IoError)?;
            let path = entry.path();

            // Check uevent for vendor/product ID
            let uevent_path = path.join("device/uevent");
            if let Ok(uevent) = std::fs::read_to_string(&uevent_path) {
                // Check for Logitech vendor ID (046D)
                if !uevent.contains("046D") && !uevent.contains("046d") {
                    continue;
                }

                // Prioritize by connection type
                let priority = if uevent.contains("C548") || uevent.contains("c548") {
                    // Bolt receiver - highest priority for HID++ events
                    3
                } else if uevent.contains("C52B") || uevent.contains("c52b") {
                    // Unifying receiver
                    2
                } else if uevent.contains("B034") || uevent.contains("b034") {
                    // MX Master 4 direct USB
                    2
                } else {
                    // Other Logitech device
                    1
                };

                if let Some(name) = path.file_name() {
                    let dev_path = PathBuf::from("/dev").join(name);
                    candidates.push((dev_path, uevent, priority));
                }
            }
        }

        // Sort by priority (highest first)
        candidates.sort_by(|a, b| b.2.cmp(&a.2));

        // Prefer interface 2 (input2) which is typically used for HID++ communication
        let max_priority = candidates.first().map(|(_, _, p)| *p).unwrap_or(0);
        for (dev_path, uevent, priority) in &candidates {
            if *priority == max_priority && uevent.contains("input2") {
                tracing::info!(
                    path = %dev_path.display(),
                    "Found Logitech hidraw device (interface 2)"
                );
                return Ok(dev_path.clone());
            }
        }

        // Fall back to first highest-priority candidate if no input2 found
        if let Some((dev_path, _, _)) = candidates.into_iter().next() {
            tracing::info!(
                path = %dev_path.display(),
                "Found Logitech hidraw device (fallback)"
            );
            return Ok(dev_path);
        }

        tracing::warn!("Logitech hidraw device not found");
        Err(HidrawError::DeviceNotFound)
    }

    /// Open the hidraw device for reading (auto-detect)
    pub fn open(&mut self) -> Result<(), HidrawError> {
        let path = Self::find_device()?;
        self.open_path(&path)
    }

    /// Open a specific hidraw device path for reading
    ///
    /// Used when the HidppDevice has already identified which Bolt receiver
    /// has the MX Master 4, to avoid connecting to the wrong receiver.
    pub fn open_path(&mut self, path: &std::path::Path) -> Result<(), HidrawError> {
        // Open with O_RDONLY and O_NONBLOCK
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(path)
            .map_err(|e| {
                if e.kind() == io::ErrorKind::PermissionDenied {
                    tracing::error!(
                        "Permission denied opening {:?}. Make sure udev rules are installed.",
                        path
                    );
                    HidrawError::PermissionDenied
                } else if e.kind() == io::ErrorKind::NotFound {
                    HidrawError::DeviceNotFound
                } else {
                    HidrawError::IoError(e)
                }
            })?;

        self.device_path = Some(path.to_path_buf());
        self.device = Some(file);

        tracing::info!(path = %path.display(), "Opened hidraw device for HID++ events");
        Ok(())
    }

    /// Start listening for HID++ diverted button events
    pub async fn start(&mut self) -> Result<(), HidrawError> {
        if self.device.is_none() {
            self.open()?;
        }

        let mut buf = [0u8; 64]; // HID++ reports are max 64 bytes

        tracing::info!("Listening for HID++ diverted button events...");

        loop {
            // Get device reference for read
            let read_result = {
                let device = self.device.as_mut().ok_or(HidrawError::DeviceNotFound)?;
                device.read(&mut buf)
            };

            // Process result outside of borrow
            match read_result {
                Ok(len) if len >= 7 => {
                    self.process_hidpp_report(&buf[..len]).await;
                }
                Ok(_) => {
                    // Short read, ignore
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    // No data available — sleep before retry. The previous 1ms
                    // poll generated 1000 wakeups/sec on an idle mouse, which
                    // contended with the evdev forwarding task on the same
                    // tokio runtime. 10ms still keeps button latency well below
                    // the ~50ms human-perceptible threshold for click-to-action.
                    tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
                }
                Err(e) => {
                    tracing::error!(error = %e, "Error reading hidraw device");
                    return Err(HidrawError::IoError(e));
                }
            }
        }
    }

    /// Process a HID++ report
    async fn process_hidpp_report(&mut self, data: &[u8]) {
        if data.is_empty() {
            return;
        }

        let report_type = data[0];

        // Check for HID++ short or long report
        if report_type != HIDPP_SHORT && report_type != HIDPP_LONG {
            return; // Not a HID++ report
        }

        let _device_index = data[1];
        let feature_index = data[2];
        let function_sw_id = data[3];
        let function_id = function_sw_id >> 4;

        // Skip HID++ error responses (feature_index 0xFF) - these are NOT button events.
        // Error responses have function_id=0 in upper nibble which would falsely match
        // DIVERTED_BUTTONS_EVENT, producing bogus CIDs from error payload bytes.
        if feature_index == 0xFF {
            return;
        }

        // Log all HID++ reports for debugging
        tracing::debug!(
            report_type = format!("0x{:02X}", report_type),
            device_index = format!("0x{:02X}", _device_index),
            feature_index = format!("0x{:02X}", feature_index),
            function_id = function_id,
            data = format!("{:02X?}", &data[4..data.len().min(10)]),
            "HID++ report received"
        );

        // Check for diverted button event (feature 0x1B04, function 0x00)
        // The feature index varies per device, so we check function_id.
        // We also validate the CID in handle_button_event to ignore unknown buttons.
        if function_id == DIVERTED_BUTTONS_EVENT {
            self.handle_button_event(data).await;
        }
    }

    /// Handle a diverted button event
    async fn handle_button_event(&mut self, data: &[u8]) {
        if data.len() < 7 {
            return;
        }

        // HID++ REPROG_CONTROLS_V4 diverted button notification format:
        // Byte 4-5: CID (Control ID) of the first pressed button (big endian)
        // Byte 6: Additional info or second button CID high byte
        // When no buttons are pressed, bytes 4-5 are 0x0000

        // Parse button CID from bytes 4-5 (big endian)
        let cid = ((data[4] as u16) << 8) | (data[5] as u16);

        // A CID of 0 means all buttons released
        let pressed = cid != 0;

        // Check if this is the gesture button OR haptic button (both can trigger radial menu)
        let is_known = cid == button_cid::GESTURE_BUTTON || cid == button_cid::HAPTIC || cid == 0;

        if is_known {
            tracing::info!(
                cid = cid,
                pressed = pressed,
                raw_bytes = format!("{:02X} {:02X} {:02X}", data[4], data[5], data[6]),
                "Diverted button event"
            );
        } else {
            tracing::debug!(
                cid = cid,
                pressed = pressed,
                raw_bytes = format!("{:02X} {:02X} {:02X}", data[4], data[5], data[6]),
                "Diverted button event (unknown CID)"
            );
        }

        if cid == button_cid::GESTURE_BUTTON || cid == button_cid::HAPTIC {
            // Look up configured action for this button
            let action = self.get_action_for_cid(cid);
            tracing::info!(cid, %action, "Button pressed - config action lookup");

            if action == crate::config::ButtonAction::RadialMenu {
                // Radial menu flow: cursor query + ShowMenu via existing path
                self.active_button_action = Some(action);
                self.handle_gesture_button(true).await;
            } else {
                // Non-radial action: dispatch immediately via event channel
                self.active_button_action = Some(action);
                self.press_time = Some(Instant::now());
                let _ = self
                    .event_tx
                    .send(GestureEvent::ButtonActionEvent {
                        action,
                        pressed: true,
                    })
                    .await;
            }
        } else if self.macro_cids.contains(&cid) {
            // Diverted macro button pressed - forward as MacroTriggered
            if let Some(key_code) = cid_to_evdev_keycode(cid) {
                tracing::info!(
                    cid = cid,
                    key_code = format!("0x{:04X}", key_code),
                    "Macro button pressed (diverted)"
                );
                self.active_macro_cid = Some(cid);
                let _ = self
                    .event_tx
                    .send(GestureEvent::MacroTriggered {
                        key_code,
                        pressed: true,
                    })
                    .await;
            }
        } else if cid == 0 {
            // All buttons released
            if self.press_time.is_some() {
                let active_action = self.active_button_action.take();
                match active_action {
                    Some(crate::config::ButtonAction::RadialMenu) | None => {
                        // Radial menu: send release to hide menu
                        self.handle_gesture_button(false).await;
                    }
                    Some(action) => {
                        // Non-radial action: send release event (no HideMenu)
                        let duration_ms = self
                            .press_time
                            .map(|t| t.elapsed().as_millis() as u64)
                            .unwrap_or(0);
                        self.press_time = None;
                        tracing::info!(duration_ms, %action, "Button released (non-radial action)");
                        let _ = self
                            .event_tx
                            .send(GestureEvent::ButtonActionEvent {
                                action,
                                pressed: false,
                            })
                            .await;
                    }
                }
            }
            if let Some(macro_cid) = self.active_macro_cid.take() {
                // Forward release event for the macro button
                if let Some(key_code) = cid_to_evdev_keycode(macro_cid) {
                    tracing::info!(
                        cid = macro_cid,
                        key_code = format!("0x{:04X}", key_code),
                        "Macro button released (diverted)"
                    );
                    let _ = self
                        .event_tx
                        .send(GestureEvent::MacroTriggered {
                            key_code,
                            pressed: false,
                        })
                        .await;
                }
            }
        }
    }

    /// Handle gesture button press/release
    async fn handle_gesture_button(&mut self, pressed: bool) {
        if pressed {
            // Button pressed
            self.press_time = Some(Instant::now());

            // Desktop-aware cursor query:
            // - KDE: KWin script for accurate multi-monitor Wayland cursor
            // - Others (GNOME, Hyprland, Sway, COSMIC): direct query cascade
            let is_kde = std::env::var("XDG_CURRENT_DESKTOP")
                .map(|d| {
                    let u = d.to_uppercase();
                    u.contains("KDE") || u.contains("PLASMA")
                })
                .unwrap_or(false);

            if is_kde {
                tracing::info!("Gesture button PRESSED - triggering KWin cursor query");
                if !Self::trigger_kwin_cursor_script() {
                    let (x, y) = Self::get_cursor_position();
                    tracing::warn!(x, y, "KWin script failed, using fallback cursor position");
                    let _ = self.event_tx.send(GestureEvent::Pressed { x, y }).await;
                }
                // If KWin script succeeded, it calls ShowMenuAtCursor via D-Bus
            } else {
                let (x, y) = Self::get_cursor_position();
                tracing::info!(x, y, "Gesture button PRESSED - cursor query");
                let _ = self.event_tx.send(GestureEvent::Pressed { x, y }).await;
            }
        } else {
            // Button released
            let duration_ms = self
                .press_time
                .map(|t| t.elapsed().as_millis() as u64)
                .unwrap_or(0);

            self.press_time = None;

            tracing::info!(duration_ms, "Gesture button RELEASED");

            let _ = self
                .event_tx
                .send(GestureEvent::Released { duration_ms })
                .await;
        }
    }

    /// Get current cursor position (fallback method)
    fn get_cursor_position() -> (i32, i32) {
        let pos = crate::cursor::get_cursor_position();
        (pos.x, pos.y)
    }

    /// Trigger KWin script to get cursor position and call ShowMenuAtCursor
    ///
    /// This method works correctly on Plasma 6 Wayland with multiple monitors,
    /// unlike xdotool/XWayland which clamps cursor to a single screen.
    fn trigger_kwin_cursor_script() -> bool {
        use std::io::Write;
        use std::process::Command;
        use tempfile::Builder;

        // Create KWin script that calls ShowMenuAtCursor with cursor position
        // converted from KWin logical coords to Qt XCB (XWayland) coords.
        // On HiDPI screens, KWin logical coords differ from XWayland coords
        // by the per-screen scale factor. We find which screen contains the
        // cursor and multiply the local offset by that screen's DPR.
        let script = r#"
var pos = workspace.cursorPos;
var dpr = 1.0;
var sx = 0, sy = 0;
var screens = workspace.screens;
if (screens) {
    for (var i = 0; i < screens.length; i++) {
        var geo = screens[i].geometry;
        if (pos.x >= geo.x && pos.x < geo.x + geo.width &&
            pos.y >= geo.y && pos.y < geo.y + geo.height) {
            dpr = screens[i].devicePixelRatio;
            sx = geo.x;
            sy = geo.y;
            break;
        }
    }
}
callDBus("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
         "org.kde.juhradialmx.Daemon", "ShowMenuAtCursor",
         sx + Math.round((pos.x - sx) * dpr),
         sy + Math.round((pos.y - sy) * dpr));
"#;

        // Create a temporary file with .js suffix securely
        let mut temp_file = match Builder::new().suffix(".js").tempfile() {
            Ok(file) => file,
            Err(e) => {
                tracing::warn!("Failed to create temp file for KWin script: {}", e);
                return false;
            }
        };

        // Write script to temp file
        if let Err(e) = write!(temp_file, "{}", script) {
            tracing::warn!("Failed to write KWin script: {}", e);
            return false;
        }

        // Get the path as a string
        let script_path = temp_file.path().to_string_lossy();

        // Load script via D-Bus
        let load_result = Command::new("dbus-send")
            .args([
                "--session",
                "--print-reply",
                "--dest=org.kde.KWin",
                "/Scripting",
                "org.kde.kwin.Scripting.loadScript",
                &format!("string:{}", script_path),
            ])
            .output();

        let load_output = match load_result {
            Ok(output) if output.status.success() => output,
            _ => {
                tracing::warn!("Failed to load KWin script");
                return false;
            }
        };

        // Parse script ID from output (looks like "int32 5")
        let stdout = String::from_utf8_lossy(&load_output.stdout);
        let script_id: Option<i32> = stdout
            .lines()
            .find(|line| line.contains("int32"))
            .and_then(|line| line.split_whitespace().last())
            .and_then(|s| s.parse().ok());

        let script_id = match script_id {
            Some(id) => id,
            None => {
                tracing::warn!("Failed to parse KWin script ID");
                return false;
            }
        };

        // Run the script
        let run_result = Command::new("dbus-send")
            .args([
                "--session",
                "--print-reply",
                "--dest=org.kde.KWin",
                &format!("/Scripting/Script{}", script_id),
                "org.kde.kwin.Script.run",
            ])
            .output();

        match run_result {
            Ok(output) if output.status.success() => {
                tracing::debug!(script_id, "KWin cursor script triggered successfully");
                true
            }
            _ => {
                tracing::warn!("Failed to run KWin script");
                false
            }
        }
    }

    /// Check if handler is connected
    pub fn is_connected(&self) -> bool {
        self.device.is_some()
    }

    /// Get the currently opened hidraw path.
    pub fn device_path(&self) -> Option<PathBuf> {
        self.device_path.clone()
    }

    /// Close the current hidraw handle and clear transient press state.
    pub fn close(&mut self) {
        self.device = None;
        self.device_path = None;
        self.press_time = None;
        self.active_macro_cid = None;
        self.active_button_action = None;
    }
}

/// Hidraw error type
#[derive(Debug)]
pub enum HidrawError {
    /// Device not found
    DeviceNotFound,
    /// Permission denied
    PermissionDenied,
    /// I/O error
    IoError(std::io::Error),
}

impl std::fmt::Display for HidrawError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            HidrawError::DeviceNotFound => write!(f, "Logitech hidraw device not found"),
            HidrawError::PermissionDenied => {
                write!(f, "Permission denied. Ensure udev rules are installed.")
            }
            HidrawError::IoError(e) => write!(f, "I/O error: {}", e),
        }
    }
}

impl std::error::Error for HidrawError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_button_cids() {
        assert_eq!(button_cid::GESTURE_BUTTON, 195);
        assert_eq!(button_cid::MIDDLE_BUTTON, 82);
        assert_eq!(button_cid::BACK_BUTTON, 83);
        assert_eq!(button_cid::FORWARD_BUTTON, 86);
    }

    #[test]
    fn test_hidpp_constants() {
        assert_eq!(HIDPP_SHORT, 0x10);
        assert_eq!(HIDPP_LONG, 0x11);
    }

    #[test]
    fn test_missing_hidraw_path_maps_to_device_not_found() {
        let (tx, _rx) = mpsc::channel(1);
        let mut handler = HidrawHandler::new(tx);
        let missing_path =
            std::env::temp_dir().join(format!("juhradial-missing-hidraw-{}", std::process::id()));

        let result = handler.open_path(&missing_path);

        assert!(matches!(result, Err(HidrawError::DeviceNotFound)));
    }

    #[test]
    fn test_hidraw_close_resets_connection_state() {
        let temp_file = tempfile::NamedTempFile::new().unwrap();
        let (tx, _rx) = mpsc::channel(1);
        let mut handler = HidrawHandler::new(tx);

        handler.open_path(temp_file.path()).unwrap();
        assert!(handler.is_connected());
        assert_eq!(handler.device_path(), Some(temp_file.path().to_path_buf()));

        handler.close();

        assert!(!handler.is_connected());
        assert_eq!(handler.device_path(), None);
    }
}
