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

/// HID++ 1.0 receiver notification sub-id: "device connection". Bolt and
/// Unifying receivers emit this SHORT report when a paired device's radio
/// link comes up or goes down, with byte 4 bit 6 set when the link is NOT
/// established. It arrives on the same hidraw node as the 2.0 feature
/// events, with the sub-id in the byte that 2.0 uses for the feature index.
pub const RECEIVER_CONNECTION_SUB_ID: u8 = 0x41;

/// Minimum spacing between divert-refresh triggers. A flapping radio link
/// (mouse at the edge of range) can emit connection notifications in bursts;
/// re-applying diverts is idempotent but costs HID++ round-trips, so bursts
/// are coalesced instead of refreshing per report (same spirit as the 500ms
/// hotplug debounce that guards issue #15).
const DIVERT_REFRESH_DEBOUNCE: std::time::Duration = std::time::Duration::from_secs(2);

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
    /// ThumbWheel feature index (0x2150), used to disambiguate diverted
    /// thumb-wheel rotation notifications from diverted button events.
    thumbwheel_feature_index: Option<u8>,
    /// Feature indices for device-originated hardware notifications (battery,
    /// host, DPI, ratchet), used for live hardware readback.
    notification_indices: crate::hidpp::notifications::NotificationIndices,
    /// Live KWin availability (D-Bus name ownership), used to pick the cursor
    /// backend on KDE instead of the XDG_CURRENT_DESKTOP env var (issue #32).
    kwin_available: Option<crate::compositor::KWinAvailability>,
    /// Set when the device announced it came (back) online, meaning its
    /// volatile HID++ state (button/thumb-wheel divert) is gone and must be
    /// re-applied (issue #102). `start()` returns so the hidraw loop can run
    /// its existing refresh path; the loop reads the flag via
    /// `take_divert_refresh_needed()`.
    divert_refresh_needed: bool,
    /// Timestamp of the last accepted refresh trigger, for debouncing.
    last_refresh_trigger: Option<Instant>,
    /// Native KWin scripting client backed by the daemon's session connection.
    kwin_scripting: Option<crate::compositor::KWinScripting>,
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
            thumbwheel_feature_index: None,
            notification_indices: Default::default(),
            kwin_available: None,
            divert_refresh_needed: false,
            last_refresh_trigger: None,
            kwin_scripting: None,
        }
    }

    /// Share the live KWin availability flag so the gesture handler can pick the
    /// cursor backend by D-Bus capability rather than an environment string.
    pub fn set_kwin_availability(&mut self, kwin: crate::compositor::KWinAvailability) {
        self.kwin_available = Some(kwin);
    }

    /// Reuse the daemon's native D-Bus connection for KWin cursor scripts.
    pub fn set_kwin_scripting(&mut self, scripting: crate::compositor::KWinScripting) {
        self.kwin_scripting = Some(scripting);
    }

    /// Register CIDs that are diverted for macro triggers (not gesture buttons)
    pub fn set_macro_cids(&mut self, cids: Vec<u16>) {
        self.macro_cids = cids;
    }

    /// Register the ThumbWheel feature index so diverted rotation notifications
    /// can be told apart from diverted button events (both use function id 0).
    pub fn set_thumbwheel_feature_index(&mut self, index: Option<u8>) {
        self.thumbwheel_feature_index = index;
    }

    /// Register the feature indices used to decode device-originated hardware
    /// notifications (battery, host, DPI, ratchet) for live readback.
    pub fn set_notification_indices(
        &mut self,
        indices: crate::hidpp::notifications::NotificationIndices,
    ) {
        self.notification_indices = indices;
    }

    /// Set the shared configuration for button action lookup
    pub fn set_shared_config(&mut self, config: crate::config::SharedConfig) {
        self.shared_config = Some(config);
    }

    /// Record that the device came (back) online and needs its volatile
    /// diverts re-applied. Debounced so a flapping radio link cannot turn
    /// into a refresh storm.
    fn flag_divert_refresh(&mut self, reason: &str) {
        let now = Instant::now();
        if let Some(last) = self.last_refresh_trigger {
            if now.duration_since(last) < DIVERT_REFRESH_DEBOUNCE {
                tracing::debug!(reason, "Divert refresh trigger debounced");
                return;
            }
        }
        self.last_refresh_trigger = Some(now);
        self.divert_refresh_needed = true;
        tracing::info!(reason, "Device back online - volatile diverts need re-apply");
    }

    /// Consume the divert-refresh flag. Returns true when `start()` exited
    /// because the device came back online (issue #102).
    pub fn take_divert_refresh_needed(&mut self) -> bool {
        std::mem::take(&mut self.divert_refresh_needed)
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

    /// Whether a diverted CID should be dispatched as a configured button
    /// action. Gesture and haptic buttons always are; the other reprogrammable
    /// buttons (back/forward/middle/shift-wheel) only when the user reassigned
    /// them away from their native default, which matches what divert applies.
    fn is_action_button(&self, cid: u16) -> bool {
        if cid == button_cid::GESTURE_BUTTON || cid == button_cid::HAPTIC {
            return true;
        }
        if let Some(ref config) = self.shared_config {
            if let Ok(cfg) = config.read() {
                return cfg.remapped_button_cids().contains(&cid);
            }
        }
        false
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
        candidates.sort_by_key(|c| std::cmp::Reverse(c.2));

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
                        "Permission denied opening {:?}. The node should be root:input mode 0660 \
                         (check: ls -l {:?}) and this daemon's user must be in the 'input' group. \
                         Fix: sudo usermod -aG input $USER, then REBOOT (or fully log out and back \
                         in) so the systemd --user manager picks up the group — a stale session \
                         that predates the group change cannot access the device. See issue #52.",
                        path, path
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
                    // The device announced it came back online (power switch,
                    // radio sleep): its volatile diverts are gone. Return so
                    // the hidraw loop re-applies them (issue #102).
                    if self.divert_refresh_needed {
                        return Ok(());
                    }
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

        // Receiver-protocol "device connection" notification: the Bolt keeps
        // its hidraw node while the mouse is off or asleep, so this SHORT
        // report (not any node hotplug) is what signals the radio coming back.
        // Byte 4 bit 6 set means "link not established" - only a link-up
        // report triggers a divert refresh (issue #102).
        if report_type == HIDPP_SHORT && feature_index == RECEIVER_CONNECTION_SUB_ID {
            if data.len() >= 5 && (data[4] & 0x40) == 0 {
                self.flag_divert_refresh("receiver device-connection notification");
            }
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

        // Live hardware readback: a report whose function/software-id low nibble
        // is zero is a SPONTANEOUS device event (not a response to a method we
        // issued). Route it by feature index to the notification decoder and, if
        // it decodes, surface it as a Hardware event and stop. Diverted button
        // and thumb-wheel events also have sw_id 0 but live on different feature
        // indices, so they fall through to their existing handlers below.
        if (function_sw_id & 0x0F) == 0 {
            if let Some(note) = self.notification_indices.route(feature_index, data) {
                tracing::debug!(?note, "Hardware notification decoded");
                use crate::hidpp::notifications::HardwareNotification as HN;
                match note {
                    // Wireless Device Status broadcast: the mouse just came
                    // back online and has cleared its volatile HID++ state.
                    // Internal signal only - nothing to surface on D-Bus.
                    HN::DeviceConnected => {
                        self.flag_divert_refresh("wireless device status broadcast");
                        return;
                    }
                    // An Easy-Switch return also clears volatile state; keep
                    // emitting the D-Bus signal as before, but refresh too.
                    HN::HostChanged { .. } => {
                        self.flag_divert_refresh("Easy-Switch host change");
                    }
                    _ => {}
                }
                let _ = self.event_tx.send(GestureEvent::Hardware(note)).await;
                return;
            }

            // Diverted thumb-wheel rotation events are spontaneous (sw_id 0) and
            // arrive on the ThumbWheel feature index (0x2150). Gating on sw_id
            // here is essential: the SetThumbwheelReporting *response* lands on
            // the same feature index with a non-zero sw_id, and must NOT be read
            // as a rotation (that fired a phantom volume/zoom the instant the
            // mode was enabled).
            if let Some(tw_idx) = self.thumbwheel_feature_index {
                if feature_index == tw_idx {
                    self.handle_thumbwheel_event(data).await;
                    return;
                }
            }
        }

        // Check for diverted button event (feature 0x1B04, function 0x00)
        // The feature index varies per device, so we check function_id.
        // We also validate the CID in handle_button_event to ignore unknown buttons.
        if function_id == DIVERTED_BUTTONS_EVENT {
            self.handle_button_event(data).await;
        }
    }

    /// Handle a diverted thumb-wheel rotation notification.
    ///
    /// The HID++ ThumbWheel (0x2150) rotation event carries a signed 16-bit
    /// rotation delta in bytes 4-5 (big endian). The delta is mapped to an
    /// action (volume / horizontal scroll / zoom) per the `thumbwheel` config
    /// section.
    async fn handle_thumbwheel_event(&self, data: &[u8]) {
        if data.len() < 6 {
            return;
        }

        // Rotation delta: signed 16-bit, big endian.
        let delta = i16::from_be_bytes([data[4], data[5]]);
        if delta == 0 {
            return; // Status-only event (rotation start/stop), no movement.
        }

        let cfg = match self.shared_config.as_ref().and_then(|c| c.read().ok()) {
            Some(c) => c.thumbwheel.clone(),
            None => return,
        };

        let output = match cfg.resolve(delta) {
            Some(o) => o,
            None => return, // Off or zero.
        };
        let repeats = cfg.repeats();

        tracing::debug!(delta, ?output, repeats, "ThumbWheel rotation");

        match output {
            crate::config::ThumbwheelOutput::Button(action) => {
                // Keep the whole rotation in one channel message so configured
                // speed does not multiply queue traffic and helper processes.
                let _ = self
                    .event_tx
                    .send(GestureEvent::ButtonActionEvent {
                        action,
                        pressed: true,
                        repeats,
                    })
                    .await;
            }
            crate::config::ThumbwheelOutput::HorizontalScroll(dir) => {
                let _ = self
                    .event_tx
                    .send(GestureEvent::ThumbwheelScroll {
                        clicks: dir * repeats as i32,
                    })
                    .await;
            }
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

        // Whether this CID maps to a configured action (gesture/haptic, or a
        // reassigned back/forward/middle/shift-wheel) or is the release marker.
        let is_known = self.is_action_button(cid) || cid == 0;

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

        if self.is_action_button(cid) {
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
                        repeats: 1,
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
                                repeats: 1,
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
            // Pick the cursor backend by whether KWin owns its D-Bus name, not
            // by XDG_CURRENT_DESKTOP, which is empty when systemd starts the
            // daemon at cold boot and made KDE look non-KDE (issue #32).
            let kwin_owned = self
                .kwin_available
                .as_ref()
                .map(|k| k.is_owned())
                .unwrap_or(false);
            match crate::compositor::cursor_backend(kwin_owned) {
                crate::compositor::CursorBackend::KWin => {
                    tracing::info!(
                        kwin_owned,
                        "Gesture button PRESSED - triggering KWin cursor query"
                    );
                    let scripting = self.kwin_scripting.clone();
                    let event_tx = self.event_tx.clone();
                    crate::compositor::trigger_kwin_cursor_script(
                        scripting.as_ref(),
                        move || async move {
                            let (x, y) = Self::get_cursor_position();
                            tracing::warn!(
                                x,
                                y,
                                "KWin script failed, using fallback cursor position"
                            );
                            let _ = event_tx.send(GestureEvent::Pressed { x, y }).await;
                        },
                    )
                    .await;
                    // If KWin script succeeded, it calls ShowMenuAtCursor via D-Bus
                }
                crate::compositor::CursorBackend::Fallback => {
                    let (x, y) = Self::get_cursor_position();
                    tracing::info!(x, y, kwin_owned, "Gesture button PRESSED - cursor query");
                    let _ = self.event_tx.send(GestureEvent::Pressed { x, y }).await;
                }
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

    #[tokio::test]
    async fn thumbwheel_repetitions_are_batched_into_one_event() {
        let config = crate::config::new_shared_config();
        {
            let mut config = config.write().unwrap();
            config.thumbwheel.mode = crate::config::ThumbwheelMode::Volume;
            config.thumbwheel.speed = 8;
        }

        let (tx, mut rx) = mpsc::channel(16);
        let mut handler = HidrawHandler::new(tx);
        handler.set_shared_config(config);

        handler
            .handle_thumbwheel_event(&[HIDPP_LONG, 0, 0, 0, 0, 1])
            .await;

        assert_eq!(
            rx.recv().await,
            Some(GestureEvent::ButtonActionEvent {
                action: crate::config::ButtonAction::VolumeUp,
                pressed: true,
                repeats: 8,
            })
        );
        assert!(matches!(
            rx.try_recv(),
            Err(mpsc::error::TryRecvError::Empty)
        ));
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

    fn test_handler() -> HidrawHandler {
        // The receiver is dropped: none of these reports reach the event
        // channel (connection paths return before sending), and the handler
        // ignores send failures anyway.
        let (tx, _rx) = mpsc::channel(4);
        HidrawHandler::new(tx)
    }

    // Issue #102: a receiver "device connection" notification with the link
    // established must request a divert refresh...
    #[tokio::test]
    async fn receiver_link_up_requests_divert_refresh() {
        let mut h = test_handler();
        // [report, device idx, sub-id 0x41, protocol, device info (bit6 clear)]
        let report = [0x10, 0x01, 0x41, 0x04, 0x02, 0x00, 0x00];
        h.process_hidpp_report(&report).await;
        assert!(h.take_divert_refresh_needed());
        // take() consumes the flag
        assert!(!h.take_divert_refresh_needed());
    }

    // ...while a link-DOWN notification (bit 6 set: mouse switched off) must not.
    #[tokio::test]
    async fn receiver_link_down_does_not_request_refresh() {
        let mut h = test_handler();
        let report = [0x10, 0x01, 0x41, 0x04, 0x42, 0x00, 0x00];
        h.process_hidpp_report(&report).await;
        assert!(!h.take_divert_refresh_needed());
    }

    // A LONG report whose feature index happens to be 0x41 is device feature
    // traffic, not a receiver notification, and must not trigger a refresh.
    #[tokio::test]
    async fn long_report_with_0x41_index_is_not_a_connection_notification() {
        let mut h = test_handler();
        let report = [0x11, 0x01, 0x41, 0x00, 0x02, 0x00, 0x00];
        h.process_hidpp_report(&report).await;
        assert!(!h.take_divert_refresh_needed());
    }

    // Issue #102: the Wireless Device Status (0x1D4B) broadcast the mouse
    // sends after power-on / radio sleep must request a divert refresh.
    #[tokio::test]
    async fn wireless_status_broadcast_requests_divert_refresh() {
        let mut h = test_handler();
        h.set_notification_indices(crate::hidpp::notifications::NotificationIndices {
            wireless_status: Some(0x0c),
            ..Default::default()
        });
        // statusBroadcast: sw_id nibble 0, status=1, request=1
        let report = [0x11, 0x01, 0x0c, 0x00, 0x01, 0x01, 0x00];
        h.process_hidpp_report(&report).await;
        assert!(h.take_divert_refresh_needed());
    }

    // Issue #15 spirit: a burst of connection notifications (flapping link)
    // must coalesce into one refresh, not a refresh storm.
    #[tokio::test]
    async fn refresh_triggers_are_debounced() {
        let mut h = test_handler();
        let report = [0x10, 0x01, 0x41, 0x04, 0x02, 0x00, 0x00];
        h.process_hidpp_report(&report).await;
        assert!(h.take_divert_refresh_needed());
        // Immediately after, within the debounce window: no second trigger.
        h.process_hidpp_report(&report).await;
        assert!(!h.take_divert_refresh_needed());
    }
}
