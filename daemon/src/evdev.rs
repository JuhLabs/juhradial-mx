//! evdev input handling for MX Master 4 gesture button detection
//!
//! Listens to Linux input events via evdev subsystem without requiring root
//! privileges (uses udev rules for device access).
//!
//! ## Device Detection
//! Scans `/dev/input/event*` for Logitech devices (vendor ID 0x046D)
//! and identifies the MX Master 4 by product ID. If no MX device is found,
//! falls back to detecting any mouse with EV_REL + REL_X + REL_Y capabilities
//! (generic mouse mode).
//!
//! ## Event Handling
//! Listens for EV_KEY events on the gesture button and emits
//! `GestureEvent::Pressed` and `GestureEvent::Released` accordingly.

use std::path::PathBuf;
use std::time::Instant;
use tokio::sync::mpsc;

/// MX Master 4 vendor ID (Logitech)
pub const LOGITECH_VENDOR_ID: u16 = 0x046D;

/// Known MX Master 4 product IDs (varies by connection type)
pub const MX_MASTER_4_PRODUCT_IDS: &[u16] = &[
    0xB034, // USB receiver
    0xB035, // Bluetooth
    0x4082, // Bolt receiver (variant)
    0xC548, // Unifying receiver (fallback)
];

/// Gesture button key code (MX Master 4 haptic thumb button)
pub const GESTURE_BUTTON_CODES: &[u16] = &[
    0x116, // BTN_BACK - this is the haptic/gesture button on MX Master 4
];

/// Default trigger button for generic mice (BTN_SIDE = 0x113, button 8 - common thumb button)
pub const GENERIC_TRIGGER_BUTTON: u16 = 0x113;

/// Primary mouse buttons that should never be treated as macro triggers
/// (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE)
const PRIMARY_BUTTONS: &[u16] = &[0x110, 0x111, 0x112];

/// Event types for gesture button
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum GestureEvent {
    /// Gesture button pressed, includes cursor position
    Pressed { x: i32, y: i32 },
    /// Gesture button released, includes hold duration
    Released { duration_ms: u64 },
    /// Cursor moved while button is held (for hover detection on Wayland)
    CursorMoved { x: i32, y: i32 },
    /// A non-gesture button was pressed/released (for macro trigger detection)
    MacroTriggered { key_code: u16, pressed: bool },
}

/// Information about a detected input device
#[derive(Debug, Clone)]
pub struct DeviceInfo {
    /// Path to the event device (e.g., /dev/input/event5)
    pub path: PathBuf,
    /// Device name as reported by the kernel
    pub name: String,
    /// Vendor ID
    pub vendor_id: u16,
    /// Product ID
    pub product_id: u16,
    /// Whether this appears to be an MX Master 4
    pub is_mx_master_4: bool,
    /// Whether this is a generic (non-Logitech) mouse detected as fallback
    pub is_generic_mouse: bool,
}

/// evdev handler for MX Master 4 and generic mice
pub struct EvdevHandler {
    /// Channel to send gesture events
    event_tx: mpsc::Sender<GestureEvent>,
    /// Currently connected device path
    device_path: Option<PathBuf>,
    /// Time when gesture button was pressed
    press_time: Option<Instant>,
    /// Whether we're currently polling for device connection
    polling: bool,
    /// Current cursor X position (tracked while button held)
    cursor_x: i32,
    /// Current cursor Y position (tracked while button held)
    cursor_y: i32,
    /// Whether menu is currently active (button held)
    menu_active: bool,
    /// Trigger button code (GESTURE_BUTTON_CODES for MX, GENERIC_TRIGGER_BUTTON for generic)
    trigger_button: u16,
    /// Whether we are running in generic mouse mode
    generic_mode: bool,
    /// Last time we checked config file for trigger button changes
    last_config_check: Instant,
}

impl EvdevHandler {
    /// Create a new evdev handler
    pub fn new(event_tx: mpsc::Sender<GestureEvent>) -> Self {
        Self {
            event_tx,
            device_path: None,
            press_time: None,
            polling: false,
            cursor_x: 0,
            cursor_y: 0,
            menu_active: false,
            trigger_button: GESTURE_BUTTON_CODES[0],
            generic_mode: false,
            last_config_check: Instant::now(),
        }
    }

    /// Create a new evdev handler for generic mouse mode
    pub fn new_generic(event_tx: mpsc::Sender<GestureEvent>, trigger_button: Option<u16>) -> Self {
        Self {
            event_tx,
            device_path: None,
            press_time: None,
            polling: false,
            cursor_x: 0,
            cursor_y: 0,
            menu_active: false,
            trigger_button: trigger_button.unwrap_or(GENERIC_TRIGGER_BUTTON),
            generic_mode: true,
            last_config_check: Instant::now(),
        }
    }

    /// Update the trigger button (e.g. after config reload)
    pub fn set_trigger_button(&mut self, code: u16) {
        self.trigger_button = code;
    }

    /// Re-read trigger button from config file if it changed (throttled to every 2s)
    fn reload_trigger_from_config(&mut self) {
        if self.last_config_check.elapsed().as_secs() < 2 {
            return;
        }
        self.last_config_check = Instant::now();

        let home = match std::env::var("HOME") {
            Ok(h) => h,
            Err(_) => return,
        };
        let path = std::path::PathBuf::from(home)
            .join(".config/juhradial/config.json");
        let data = match std::fs::read_to_string(&path) {
            Ok(d) => d,
            Err(_) => return,
        };
        let json: serde_json::Value = match serde_json::from_str(&data) {
            Ok(v) => v,
            Err(_) => return,
        };
        if let Some(code) = json.get("generic_trigger_button").and_then(|v| v.as_u64()) {
            let new_trigger = code as u16;
            if new_trigger != self.trigger_button {
                tracing::info!(
                    old = format!("{:#x}", self.trigger_button),
                    new = format!("{:#x}", new_trigger),
                    "Generic trigger button updated from config"
                );
                self.trigger_button = new_trigger;
            }
        }
    }

    /// Scan /dev/input/ for MX Master 4 device
    ///
    /// Returns the first matching device found.
    pub fn find_device() -> Result<DeviceInfo, EvdevError> {
        // On non-Linux systems, return an error
        #[cfg(not(target_os = "linux"))]
        {
            tracing::warn!("evdev is only available on Linux");
            return Err(EvdevError::DeviceNotFound);
        }

        #[cfg(target_os = "linux")]
        {
            Self::scan_linux_devices()
        }
    }

    /// Scan all input devices on Linux
    #[cfg(target_os = "linux")]
    fn scan_linux_devices() -> Result<DeviceInfo, EvdevError> {
        use std::fs;

        let input_dir = PathBuf::from("/dev/input");
        if !input_dir.exists() {
            tracing::error!("Input directory does not exist: {:?}", input_dir);
            return Err(EvdevError::DeviceNotFound);
        }

        // Sort entries numerically so event4 is checked before event10.
        // This matters when two Bolt receivers have identical vendor:product IDs
        // (e.g. mouse on event4, keyboard on event10).
        let mut sorted_entries: Vec<_> = fs::read_dir(&input_dir)
            .map_err(EvdevError::IoError)?
            .flatten()
            .collect();
        sorted_entries.sort_by_key(|e| {
            e.file_name()
                .to_str()
                .and_then(|n| n.strip_prefix("event").and_then(|num| num.parse::<u32>().ok()))
                .unwrap_or(u32::MAX)
        });

        for entry in sorted_entries {
            let path = entry.path();
            let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

            // Only check event devices
            if !filename.starts_with("event") {
                continue;
            }

            match Self::check_device(&path) {
                Ok(Some(info)) => {
                    tracing::info!(
                        path = %path.display(),
                        name = %info.name,
                        vendor = format!("0x{:04X}", info.vendor_id),
                        product = format!("0x{:04X}", info.product_id),
                        "Found device"
                    );

                    if info.is_mx_master_4 {
                        tracing::info!("MX Master 4 detected at {:?}", path);
                        return Ok(info);
                    }
                }
                Ok(None) => continue,
                Err(e) => {
                    tracing::debug!("Could not check device {:?}: {:?}", path, e);
                    continue;
                }
            }
        }

        tracing::warn!("MX Master 4 not found. Waiting for connection...");
        Err(EvdevError::DeviceNotFound)
    }

    /// Scan /dev/input/ for ANY mouse device (generic fallback)
    ///
    /// Looks for devices with EV_REL + REL_X + REL_Y capabilities (i.e., a mouse).
    /// Returns the first matching device found.
    pub fn find_any_mouse() -> Result<DeviceInfo, EvdevError> {
        #[cfg(not(target_os = "linux"))]
        {
            tracing::warn!("Generic mouse detection is only available on Linux");
            return Err(EvdevError::DeviceNotFound);
        }

        #[cfg(target_os = "linux")]
        {
            Self::scan_generic_mouse()
        }
    }

    /// Scan all input devices for any mouse on Linux
    #[cfg(target_os = "linux")]
    fn scan_generic_mouse() -> Result<DeviceInfo, EvdevError> {
        use std::fs;
        use evdev::{Device, EventType, RelativeAxisCode};

        let input_dir = PathBuf::from("/dev/input");
        if !input_dir.exists() {
            tracing::error!("Input directory does not exist: {:?}", input_dir);
            return Err(EvdevError::DeviceNotFound);
        }

        let entries = fs::read_dir(&input_dir).map_err(EvdevError::IoError)?;

        for entry in entries.flatten() {
            let path = entry.path();
            let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

            // Only check event devices
            if !filename.starts_with("event") {
                continue;
            }

            // Try to open the device
            let device = match Device::open(&path) {
                Ok(d) => d,
                Err(_) => continue,
            };

            // Check for mouse capabilities: EV_REL with REL_X and REL_Y
            let has_rel = device.supported_events().contains(EventType::RELATIVE);
            if !has_rel {
                continue;
            }

            let has_rel_axes = device.supported_relative_axes().map(|axes| {
                axes.contains(RelativeAxisCode::REL_X) && axes.contains(RelativeAxisCode::REL_Y)
            }).unwrap_or(false);

            if !has_rel_axes {
                continue;
            }

            // Must also have EV_KEY (buttons) to be a real mouse, not just a trackball sensor
            let has_keys = device.supported_events().contains(EventType::KEY);
            if !has_keys {
                continue;
            }

            let input_id = device.input_id();
            let vendor_id = input_id.vendor();
            let product_id = input_id.product();
            let name = device.name().unwrap_or("Unknown Mouse").to_string();

            // Skip Logitech devices - those should be handled by find_device()
            if vendor_id == LOGITECH_VENDOR_ID {
                continue;
            }

            tracing::info!(
                path = %path.display(),
                name = %name,
                vendor = format!("0x{:04X}", vendor_id),
                product = format!("0x{:04X}", product_id),
                "Found generic mouse"
            );

            return Ok(DeviceInfo {
                path: path.clone(),
                name,
                vendor_id,
                product_id,
                is_mx_master_4: false,
                is_generic_mouse: true,
            });
        }

        tracing::warn!("No generic mouse found");
        Err(EvdevError::DeviceNotFound)
    }

    /// Check if a device path is a Logitech MX Master 4 with gesture buttons
    #[cfg(target_os = "linux")]
    fn check_device(path: &PathBuf) -> Result<Option<DeviceInfo>, EvdevError> {
        use evdev::Device;

        let device = Device::open(path).map_err(|e| {
            if e.kind() == std::io::ErrorKind::PermissionDenied {
                EvdevError::PermissionDenied
            } else {
                EvdevError::IoError(e)
            }
        })?;

        let input_id = device.input_id();
        let vendor_id = input_id.vendor();
        let product_id = input_id.product();
        let name = device.name().unwrap_or("Unknown").to_string();

        // Check if this is a Logitech device
        if vendor_id != LOGITECH_VENDOR_ID {
            return Ok(None);
        }

        // Check if this device has the gesture button keys (BTN_SIDE or BTN_EXTRA)
        // This filters out touchpad devices that have same vendor/product ID
        // BTN_SIDE = 0x113 (275), BTN_EXTRA = 0x114 (276)
        let supported_keys = device.supported_keys();
        let has_gesture_buttons = supported_keys.map(|keys| {
            // Check by raw key codes
            keys.iter().any(|k| k.code() == 0x113 || k.code() == 0x114)
        }).unwrap_or(false);

        // Only consider devices with gesture buttons as MX Master 4
        let is_mx_master_4 = MX_MASTER_4_PRODUCT_IDS.contains(&product_id) && has_gesture_buttons;

        if is_mx_master_4 {
            tracing::debug!(
                path = %path.display(),
                name = %name,
                "Found device with gesture buttons"
            );
        }

        Ok(Some(DeviceInfo {
            path: path.clone(),
            name,
            vendor_id,
            product_id,
            is_mx_master_4,
            is_generic_mouse: false,
        }))
    }

    /// Get a list of all Logitech input devices
    pub fn list_logitech_devices() -> Vec<DeviceInfo> {
        #[cfg(not(target_os = "linux"))]
        {
            Vec::new()
        }

        #[cfg(target_os = "linux")]
        {
            use std::fs;

            let input_dir = PathBuf::from("/dev/input");
            let mut devices = Vec::new();

            if let Ok(entries) = fs::read_dir(&input_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if let Ok(Some(info)) = Self::check_device(&path) {
                        devices.push(info);
                    }
                }
            }

            devices
        }
    }

    /// Start listening for gesture button events
    ///
    /// This is an async function that runs until the device is disconnected
    /// or an error occurs.
    pub async fn start(&mut self) -> Result<(), EvdevError> {
        #[cfg(not(target_os = "linux"))]
        {
            tracing::warn!("evdev event listening is only available on Linux");
            // On non-Linux, just return Ok to allow development
            Ok(())
        }

        #[cfg(target_os = "linux")]
        {
            self.run_event_loop().await
        }
    }

    /// Run the event loop on Linux
    #[cfg(target_os = "linux")]
    async fn run_event_loop(&mut self) -> Result<(), EvdevError> {
        use evdev::{Device, EventType, RelativeAxisCode};

        // Find the device based on mode
        let device_info = if self.generic_mode {
            Self::find_any_mouse()?
        } else {
            Self::find_device()?
        };
        self.device_path = Some(device_info.path.clone());

        // Open the device for reading
        let device = Device::open(&device_info.path).map_err(|e| {
            if e.kind() == std::io::ErrorKind::PermissionDenied {
                tracing::error!(
                    "Permission denied opening {:?}. Make sure udev rules are installed \
                     and user is in 'input' group.",
                    device_info.path
                );
                EvdevError::PermissionDenied
            } else {
                EvdevError::IoError(e)
            }
        })?;

        let mode_label = if self.generic_mode { "generic" } else { "MX" };
        tracing::info!(
            "Listening for events on {} ({:?}) [{}]",
            device_info.name,
            device_info.path,
            mode_label
        );

        // Create async event stream using into_event_stream()
        let mut events = device.into_event_stream()
            .map_err(EvdevError::IoError)?;

        loop {
            match events.next_event().await {
                Ok(event) => {
                    match event.event_type() {
                        EventType::KEY => {
                            let key_code = event.code();
                            let is_trigger = if self.generic_mode {
                                // Re-read trigger from config on each key event
                                // so rebinds in settings take effect immediately
                                self.reload_trigger_from_config();
                                key_code == self.trigger_button
                            } else {
                                GESTURE_BUTTON_CODES.contains(&key_code)
                            };
                            if is_trigger {
                                self.handle_gesture_event(event.value()).await;
                            } else if !PRIMARY_BUTTONS.contains(&key_code) {
                                // Forward non-primary, non-gesture buttons for macro trigger detection
                                let value = event.value();
                                if value == 0 || value == 1 {
                                    let _ = self.event_tx.send(GestureEvent::MacroTriggered {
                                        key_code,
                                        pressed: value == 1,
                                    }).await;
                                }
                            }
                        }
                        EventType::RELATIVE => {
                            // Track mouse movement while menu is active
                            if self.menu_active {
                                let code = RelativeAxisCode(event.code());
                                let value = event.value();

                                match code {
                                    RelativeAxisCode::REL_X => {
                                        self.cursor_x += value;
                                        let _ = self.event_tx.send(GestureEvent::CursorMoved {
                                            x: self.cursor_x,
                                            y: self.cursor_y,
                                        }).await;
                                    }
                                    RelativeAxisCode::REL_Y => {
                                        self.cursor_y += value;
                                        let _ = self.event_tx.send(GestureEvent::CursorMoved {
                                            x: self.cursor_x,
                                            y: self.cursor_y,
                                        }).await;
                                    }
                                    _ => {}
                                }
                            }
                        }
                        _ => {}
                    }
                }
                Err(e) => {
                    if e.kind() == std::io::ErrorKind::WouldBlock {
                        // No events available, continue waiting
                        continue;
                    }
                    tracing::error!("Error reading event: {:?}", e);
                    return Err(EvdevError::IoError(e));
                }
            }
        }
    }

    /// Handle a gesture button event
    async fn handle_gesture_event(&mut self, value: i32) {
        match value {
            1 => {
                // Button pressed - get cursor position
                self.press_time = Some(Instant::now());
                self.menu_active = true;
                // Initialize relative cursor tracking (0,0 = menu center)
                self.cursor_x = 0;
                self.cursor_y = 0;

                // Check for Hyprland - use direct cursor query (no KWin script)
                if std::env::var("HYPRLAND_INSTANCE_SIGNATURE").is_ok() {
                    tracing::info!("Gesture button pressed - using Hyprland cursor query");
                    let pos = crate::cursor::get_cursor_position();
                    tracing::info!(x = pos.x, y = pos.y, "Cursor position from Hyprland");
                    let _ = self.event_tx.send(GestureEvent::Pressed { x: pos.x, y: pos.y }).await;
                } else {
                    // KDE/other - try KWin script first for multi-monitor accuracy
                    tracing::info!("Gesture button pressed - triggering KWin cursor query");
                    if !Self::trigger_kwin_cursor_script() {
                        // Fallback to get_cursor_position if KWin script fails
                        let pos = crate::cursor::get_cursor_position();
                        tracing::warn!(x = pos.x, y = pos.y, "KWin script failed, using fallback");
                        let _ = self.event_tx.send(GestureEvent::Pressed { x: pos.x, y: pos.y }).await;
                    }
                    // If KWin script succeeded, it calls ShowMenuAtCursor via D-Bus directly
                }
            }
            0 => {
                // Button released
                self.menu_active = false;
                let duration_ms = self
                    .press_time
                    .map(|t| t.elapsed().as_millis() as u64)
                    .unwrap_or(0);

                self.press_time = None;

                tracing::info!(duration_ms, "Gesture button released");

                let _ = self.event_tx.send(GestureEvent::Released { duration_ms }).await;
            }
            _ => {
                // Repeat events (value=2) are ignored
            }
        }
    }

    /// Trigger KWin script to get cursor position and call ShowMenuAtCursor
    ///
    /// This works correctly on Plasma 6 Wayland with multiple monitors.
    fn trigger_kwin_cursor_script() -> bool {
        use std::process::Command;
        use std::io::Write;
        use tempfile::Builder;

        // Create KWin script that calls ShowMenuAtCursor with true cursor position
        let script = r#"
var pos = workspace.cursorPos;
callDBus("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
         "org.kde.juhradialmx.Daemon", "ShowMenuAtCursor",
         pos.x, pos.y);
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

    /// Poll for device connection
    ///
    /// Call this periodically when device is not connected.
    pub async fn poll_for_device(&mut self) -> Option<DeviceInfo> {
        if self.device_path.is_some() {
            return None;
        }

        self.polling = true;
        let result = if self.generic_mode {
            Self::find_any_mouse()
        } else {
            Self::find_device()
        };
        match result {
            Ok(info) => {
                self.polling = false;
                Some(info)
            }
            Err(_) => {
                self.polling = false;
                None
            }
        }
    }

    /// Check if handler is currently connected to a device
    pub fn is_connected(&self) -> bool {
        self.device_path.is_some()
    }

    /// Check if handler is polling for device
    pub fn is_polling(&self) -> bool {
        self.polling
    }
}

/// evdev error type
#[derive(Debug)]
pub enum EvdevError {
    /// MX Master 4 device not found
    DeviceNotFound,
    /// Permission denied accessing device
    PermissionDenied,
    /// I/O error
    IoError(std::io::Error),
}

impl std::fmt::Display for EvdevError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EvdevError::DeviceNotFound => write!(f, "MX Master 4 not found"),
            EvdevError::PermissionDenied => write!(
                f,
                "Permission denied. Ensure udev rules are installed and user is in 'input' group."
            ),
            EvdevError::IoError(e) => write!(f, "I/O error: {}", e),
        }
    }
}

impl std::error::Error for EvdevError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_vendor_id() {
        assert_eq!(LOGITECH_VENDOR_ID, 0x046D);
    }

    #[test]
    fn test_mx_master_4_product_ids() {
        assert!(!MX_MASTER_4_PRODUCT_IDS.is_empty());
        assert!(MX_MASTER_4_PRODUCT_IDS.contains(&0xB034));
    }

    #[test]
    fn test_gesture_button_codes() {
        assert!(!GESTURE_BUTTON_CODES.is_empty());
        // BTN_BACK - haptic/gesture button on MX Master 4
        assert!(GESTURE_BUTTON_CODES.contains(&0x116));
    }

    #[test]
    fn test_generic_trigger_button() {
        // BTN_SIDE = 0x113 (button 8 - common thumb button on gaming mice)
        assert_eq!(GENERIC_TRIGGER_BUTTON, 0x113);
    }

    #[test]
    fn test_gesture_event_equality() {
        let e1 = GestureEvent::Pressed { x: 100, y: 200 };
        let e2 = GestureEvent::Pressed { x: 100, y: 200 };
        let e3 = GestureEvent::Released { duration_ms: 500 };

        assert_eq!(e1, e2);
        assert_ne!(e1, e3);
    }

    #[test]
    fn test_evdev_error_display() {
        let err = EvdevError::DeviceNotFound;
        assert_eq!(format!("{}", err), "MX Master 4 not found");

        let err = EvdevError::PermissionDenied;
        assert!(format!("{}", err).contains("Permission denied"));
    }
}
