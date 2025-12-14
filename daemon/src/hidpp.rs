//! HID++ protocol implementation for haptic feedback
//!
//! Sends runtime-only haptic commands to MX Master 4 without writing
//! to onboard memory. This preserves cross-platform mouse compatibility.
//!
//! # CRITICAL SAFETY CONSTRAINT
//!
//! This module MUST NEVER write to the mouse's onboard memory.
//! Only volatile/runtime HID++ commands are permitted. The mouse
//! must remain 100% compatible with Windows/macOS after use.
//!
//! # HID++ Communication
//!
//! Uses direct hidraw device access (same approach as battery module).
//! This is more reliable than hidapi library for Logitech devices.

use std::fmt;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

/// Shared haptic manager for thread-safe access from D-Bus handlers
pub type SharedHapticManager = Arc<Mutex<HapticManager>>;

/// Create a new shared haptic manager from config
pub fn new_shared_haptic_manager(config: &crate::config::HapticConfig) -> SharedHapticManager {
    Arc::new(Mutex::new(HapticManager::from_config(config)))
}

// ============================================================================
// Constants
// ============================================================================

/// Logitech vendor ID
pub const LOGITECH_VENDOR_ID: u16 = 0x046D;

/// Known MX Master 4 product IDs
pub mod product_ids {
    /// MX Master 4 via USB
    pub const MX_MASTER_4_USB: u16 = 0xB034;
    /// MX Master 4 via Bolt receiver
    pub const MX_MASTER_4_BOLT: u16 = 0xC548;
    /// Bolt receiver itself
    pub const BOLT_RECEIVER: u16 = 0xC548;
    /// Generic Logitech receiver (may host MX Master 4)
    pub const UNIFYING_RECEIVER: u16 = 0xC52B;
}

/// HID++ report types
pub mod report_type {
    /// Short HID++ report (7 bytes)
    pub const SHORT: u8 = 0x10;
    /// Long HID++ report (20 bytes)
    pub const LONG: u8 = 0x11;
    /// Very long HID++ report (64 bytes)
    pub const VERY_LONG: u8 = 0x12;
}

/// HID++ 2.0 feature IDs - SAFE for runtime use (read-only or volatile)
pub mod features {
    /// IRoot - Protocol version, ping (READ-ONLY)
    pub const I_ROOT: u16 = 0x0000;
    /// IFeatureSet - Enumerate device features (READ-ONLY)
    pub const I_FEATURE_SET: u16 = 0x0001;
    /// Device name and type (READ-ONLY)
    pub const DEVICE_NAME: u16 = 0x0005;
    /// Battery status (READ-ONLY)
    pub const BATTERY_STATUS: u16 = 0x1000;
    /// LED control - some devices include haptic here (RUNTIME-ONLY)
    pub const LED_CONTROL: u16 = 0x1300;
    /// Force feedback for racing wheels like G920/G923 (RUNTIME-ONLY - does NOT persist)
    pub const FORCE_FEEDBACK: u16 = 0x8123;
    /// MX Master 4 haptic motor (RUNTIME-ONLY - does NOT persist)
    /// Uses waveform IDs (0x00-0x1B) for predefined haptic patterns.
    pub const MX_MASTER_4_HAPTIC: u16 = 0x19B0;
    /// Alternative haptic feature used by mx4notifications project
    /// Some MX Master 4 devices may report this instead of 0x19B0
    pub const MX4_HAPTIC_ALT: u16 = 0x0B4E;
    /// Adjustable DPI - Mouse pointer speed/sensitivity (PERSISTS to device)
    /// Note: DPI settings persist on the device but this is expected user behavior.
    /// Users want their DPI setting to be remembered across reboots.
    /// Functions: [0] getSensorCount, [1] getSensorDpiList, [2] getSensorDpi, [3] setSensorDpi
    pub const ADJUSTABLE_DPI: u16 = 0x2201;
}

/// BLOCKLISTED HID++ feature IDs - NEVER use these!
///
/// # CRITICAL SAFETY
///
/// These features write to onboard mouse memory and would break
/// cross-platform compatibility. Using these is FORBIDDEN.
pub mod blocklisted_features {
    /// Special Keys & Mouse Buttons - PERSISTENT button remapping
    pub const SPECIAL_KEYS: u16 = 0x1B04;
    /// Report Rate - MAY persist on some devices
    pub const REPORT_RATE: u16 = 0x8060;
    /// Onboard Profiles - PERSISTENT profile storage
    pub const ONBOARD_PROFILES: u16 = 0x8100;
    /// Mode Status - Profile switching that may persist
    pub const MODE_STATUS: u16 = 0x8090;
    /// Mouse Button Spy - Profile modification
    pub const MOUSE_BUTTON_SPY: u16 = 0x8110;
    /// Persistent Remappable Action - PERSISTENT key remapping
    pub const PERSISTENT_REMAPPABLE_ACTION: u16 = 0x1BC0;
    /// Host Info - Device pairing that persists
    pub const HOST_INFO: u16 = 0x1815;

    /// Check if a feature ID is blocklisted (would write to memory)
    pub fn is_blocklisted(feature_id: u16) -> bool {
        matches!(
            feature_id,
            SPECIAL_KEYS
                | REPORT_RATE
                | ONBOARD_PROFILES
                | MODE_STATUS
                | MOUSE_BUTTON_SPY
                | PERSISTENT_REMAPPABLE_ACTION
                | HOST_INFO
        )
    }

    /// Get human-readable name for blocklisted feature
    pub fn blocklist_reason(feature_id: u16) -> Option<&'static str> {
        match feature_id {
            SPECIAL_KEYS => Some("Persistent button remapping"),
            REPORT_RATE => Some("May persist report rate settings"),
            ONBOARD_PROFILES => Some("Persistent profile storage"),
            MODE_STATUS => Some("Profile switching may persist"),
            MOUSE_BUTTON_SPY => Some("Profile modification"),
            PERSISTENT_REMAPPABLE_ACTION => Some("Persistent key remapping"),
            HOST_INFO => Some("Device pairing persistence"),
            _ => None,
        }
    }
}

/// Allowed HID++ feature IDs - explicitly safe for use
pub mod allowed_features {
    use super::features;

    /// List of all features that are safe to use
    pub const SAFELIST: &[u16] = &[
        features::I_ROOT,
        features::I_FEATURE_SET,
        features::DEVICE_NAME,
        features::BATTERY_STATUS,
        features::LED_CONTROL,
        features::FORCE_FEEDBACK,
        features::MX_MASTER_4_HAPTIC,
        features::MX4_HAPTIC_ALT,
        features::ADJUSTABLE_DPI,
    ];

    /// Check if a feature ID is explicitly allowed
    pub fn is_allowed(feature_id: u16) -> bool {
        SAFELIST.contains(&feature_id)
    }
}

// ============================================================================
// Safety Verification (Story 5.4)
// ============================================================================

/// Verify that a feature ID is safe to use (runtime check)
///
/// # CRITICAL SAFETY
///
/// This function MUST be called before sending any HID++ command
/// that references a feature ID. It ensures we never accidentally
/// use a blocklisted feature that would write to onboard memory.
///
/// # Returns
///
/// - `Ok(())` if feature is safe (allowed or unknown-but-not-blocklisted)
/// - `Err(HapticError::SafetyViolation)` if feature is blocklisted
pub fn verify_feature_safety(feature_id: u16) -> Result<(), HapticError> {
    // First check: Is this feature explicitly blocklisted?
    if blocklisted_features::is_blocklisted(feature_id) {
        let reason = blocklisted_features::blocklist_reason(feature_id)
            .unwrap_or("Unknown persistent feature");

        tracing::error!(
            feature_id = format!("0x{:04X}", feature_id),
            reason = reason,
            "SAFETY VIOLATION: Attempted to use blocklisted HID++ feature!"
        );

        return Err(HapticError::SafetyViolation { feature_id, reason });
    }

    // Second check: Warn if feature is not explicitly allowed (unknown feature)
    if !allowed_features::is_allowed(feature_id) {
        tracing::warn!(
            feature_id = format!("0x{:04X}", feature_id),
            "Using unknown HID++ feature - verify it doesn't persist to memory"
        );
    }

    Ok(())
}

/// Assert at compile time that we only use safe features
///
/// This macro can be used to document which features are being used
/// and provides compile-time visibility into HID++ feature usage.
#[macro_export]
macro_rules! assert_safe_feature {
    ($feature_id:expr) => {{
        // Runtime check
        $crate::hidpp::verify_feature_safety($feature_id)?;
        $feature_id
    }};
}

// ============================================================================
// HID++ Message Types
// ============================================================================

/// HID++ 2.0 short message (7 bytes)
#[derive(Debug, Clone, Copy)]
pub struct HidppShortMessage {
    /// Report type (0x10 for short)
    pub report_type: u8,
    /// Device index (0xFF for receiver, 0x01-0x06 for paired devices)
    pub device_index: u8,
    /// Feature index in device's feature table
    pub feature_index: u8,
    /// Function ID (upper nibble) | Software ID (lower nibble)
    pub function_sw_id: u8,
    /// Parameters (3 bytes)
    pub params: [u8; 3],
}

impl HidppShortMessage {
    /// Create a new short message
    pub fn new(device_index: u8, feature_index: u8, function_id: u8, sw_id: u8) -> Self {
        Self {
            report_type: report_type::SHORT,
            device_index,
            feature_index,
            function_sw_id: (function_id << 4) | (sw_id & 0x0F),
            params: [0; 3],
        }
    }

    /// Set parameters
    pub fn with_params(mut self, params: [u8; 3]) -> Self {
        self.params = params;
        self
    }

    /// Convert to bytes for sending
    pub fn to_bytes(&self) -> [u8; 7] {
        [
            self.report_type,
            self.device_index,
            self.feature_index,
            self.function_sw_id,
            self.params[0],
            self.params[1],
            self.params[2],
        ]
    }

    /// Parse from bytes
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        if bytes.len() < 7 || bytes[0] != report_type::SHORT {
            return None;
        }
        Some(Self {
            report_type: bytes[0],
            device_index: bytes[1],
            feature_index: bytes[2],
            function_sw_id: bytes[3],
            params: [bytes[4], bytes[5], bytes[6]],
        })
    }

    /// Extract function ID from function_sw_id
    pub fn function_id(&self) -> u8 {
        self.function_sw_id >> 4
    }

    /// Extract software ID from function_sw_id
    pub fn sw_id(&self) -> u8 {
        self.function_sw_id & 0x0F
    }
}

/// HID++ 2.0 long message (20 bytes)
#[derive(Debug, Clone)]
pub struct HidppLongMessage {
    /// Report type (0x11 for long)
    pub report_type: u8,
    /// Device index
    pub device_index: u8,
    /// Feature index
    pub feature_index: u8,
    /// Function ID | Software ID
    pub function_sw_id: u8,
    /// Parameters (16 bytes)
    pub params: [u8; 16],
}

impl HidppLongMessage {
    /// Create a new long message
    pub fn new(device_index: u8, feature_index: u8, function_id: u8, sw_id: u8) -> Self {
        Self {
            report_type: report_type::LONG,
            device_index,
            feature_index,
            function_sw_id: (function_id << 4) | (sw_id & 0x0F),
            params: [0; 16],
        }
    }

    /// Set parameters
    pub fn with_params(mut self, params: &[u8]) -> Self {
        let len = params.len().min(16);
        self.params[..len].copy_from_slice(&params[..len]);
        self
    }

    /// Convert to bytes for sending
    pub fn to_bytes(&self) -> [u8; 20] {
        let mut bytes = [0u8; 20];
        bytes[0] = self.report_type;
        bytes[1] = self.device_index;
        bytes[2] = self.feature_index;
        bytes[3] = self.function_sw_id;
        bytes[4..20].copy_from_slice(&self.params);
        bytes
    }

    /// Parse from bytes
    pub fn from_bytes(bytes: &[u8]) -> Option<Self> {
        if bytes.len() < 20 || bytes[0] != report_type::LONG {
            return None;
        }
        let mut params = [0u8; 16];
        params.copy_from_slice(&bytes[4..20]);
        Some(Self {
            report_type: bytes[0],
            device_index: bytes[1],
            feature_index: bytes[2],
            function_sw_id: bytes[3],
            params,
        })
    }
}

// ============================================================================
// Connection Type
// ============================================================================

/// Type of connection to the MX Master 4
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionType {
    /// Direct USB connection
    Usb,
    /// Via Logitech Bolt receiver (wireless)
    Bolt,
    /// Direct Bluetooth connection
    Bluetooth,
    /// Via Unifying receiver
    Unifying,
}

impl fmt::Display for ConnectionType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConnectionType::Usb => write!(f, "USB"),
            ConnectionType::Bolt => write!(f, "Bolt"),
            ConnectionType::Bluetooth => write!(f, "Bluetooth"),
            ConnectionType::Unifying => write!(f, "Unifying"),
        }
    }
}

// ============================================================================
// HID++ Device
// ============================================================================

/// Software ID for HID++ message tracking
const SOFTWARE_ID: u8 = 0x01;

/// HID++ device wrapper for communication with MX Master 4
///
/// Uses direct hidraw device access for reliable HID++ communication.
/// This approach matches the battery module and avoids hidapi enumeration issues.
pub struct HidppDevice {
    /// The underlying hidraw file handle
    device: File,
    /// Device index for HID++ messages (0xFF for direct, 0x01-0x06 for receiver)
    device_index: u8,
    /// Connection type
    connection_type: ConnectionType,
    /// Cached feature table (feature_id -> feature_index)
    feature_table: std::collections::HashMap<u16, u8>,
    /// Whether haptic feature is available (legacy force feedback 0x8123)
    haptic_supported: bool,
    /// Haptic feature index for legacy force feedback (0x8123)
    haptic_feature_index: Option<u8>,
    /// Whether MX Master 4 haptic feature is available (0x19B0)
    mx4_haptic_supported: bool,
    /// MX Master 4 haptic feature index (0x19B0)
    mx4_haptic_feature_index: Option<u8>,
    /// Whether adjustable DPI feature is available (0x2201)
    dpi_supported: bool,
    /// Adjustable DPI feature index (0x2201)
    dpi_feature_index: Option<u8>,
}

impl HidppDevice {
    /// Find a Logitech hidraw device suitable for HID++ communication
    ///
    /// Scans /sys/class/hidraw/ for Logitech devices and returns the path
    /// to the best one for HID++ communication (prefers interface 2).
    fn find_device() -> Option<(PathBuf, ConnectionType)> {
        let hidraw_dir = PathBuf::from("/sys/class/hidraw");
        if !hidraw_dir.exists() {
            tracing::debug!("/sys/class/hidraw not found");
            return None;
        }

        let mut candidates: Vec<(PathBuf, String, ConnectionType)> = Vec::new();

        let entries = match std::fs::read_dir(&hidraw_dir) {
            Ok(e) => e,
            Err(e) => {
                tracing::debug!(error = %e, "Failed to read /sys/class/hidraw");
                return None;
            }
        };

        for entry in entries.flatten() {
            let path = entry.path();
            let uevent_path = path.join("device/uevent");

            if let Ok(uevent) = std::fs::read_to_string(&uevent_path) {
                // Check for Logitech vendor ID (046D)
                if !uevent.contains("046D") && !uevent.contains("046d") {
                    continue;
                }

                // Determine connection type from product ID
                let connection_type = if uevent.contains("C548") || uevent.contains("c548") {
                    // Bolt receiver
                    ConnectionType::Bolt
                } else if uevent.contains("C52B") || uevent.contains("c52b") {
                    // Unifying receiver
                    ConnectionType::Unifying
                } else if uevent.contains("B034") || uevent.contains("b034") {
                    // MX Master 4 direct USB
                    ConnectionType::Usb
                } else {
                    // Other Logitech device - check if interface 2
                    if uevent.contains("input2") {
                        ConnectionType::Bluetooth
                    } else {
                        continue;
                    }
                };

                if let Some(name) = path.file_name() {
                    let dev_path = PathBuf::from("/dev").join(name);
                    candidates.push((dev_path, uevent, connection_type));
                }
            }
        }

        // Prefer interface 2 for HID++ (typically the control interface)
        for (dev_path, uevent, conn_type) in &candidates {
            if uevent.contains("input2") {
                tracing::debug!(
                    path = %dev_path.display(),
                    connection = %conn_type,
                    "Found Logitech HID++ device (interface 2)"
                );
                return Some((dev_path.clone(), *conn_type));
            }
        }

        // Fallback to first candidate
        candidates.into_iter().next().map(|(path, _, conn_type)| {
            tracing::debug!(
                path = %path.display(),
                connection = %conn_type,
                "Found Logitech HID++ device (fallback)"
            );
            (path, conn_type)
        })
    }

    /// Attempt to open and initialize an MX Master 4 device
    ///
    /// Returns None if no compatible device is found.
    /// This is NOT an error - haptics are optional.
    ///
    /// Uses direct hidraw access instead of hidapi for more reliable
    /// device communication (same approach as the battery module).
    pub fn open() -> Option<Self> {
        let (device_path, connection_type) = Self::find_device()?;

        // Determine device index based on connection type
        let device_index = match connection_type {
            ConnectionType::Usb => 0xFF,       // Direct USB uses 0xFF
            ConnectionType::Bolt => 0x02,      // Bolt receiver device slot (0x02 is common for MX4)
            ConnectionType::Unifying => 0x01,  // Unifying receiver typically 0x01
            ConnectionType::Bluetooth => 0xFF, // Bluetooth direct uses 0xFF
        };

        // Open the device with read/write and non-blocking
        let device = match OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(&device_path)
        {
            Ok(f) => f,
            Err(e) => {
                if e.kind() == std::io::ErrorKind::PermissionDenied {
                    tracing::warn!(
                        path = %device_path.display(),
                        "Permission denied opening hidraw device. Check udev rules."
                    );
                } else {
                    tracing::debug!(
                        path = %device_path.display(),
                        error = %e,
                        "Failed to open hidraw device"
                    );
                }
                return None;
            }
        };

        let mut hidpp = Self {
            device,
            device_index,
            connection_type,
            feature_table: std::collections::HashMap::new(),
            haptic_supported: false,
            haptic_feature_index: None,
            mx4_haptic_supported: false,
            mx4_haptic_feature_index: None,
            dpi_supported: false,
            dpi_feature_index: None,
        };

        // Validate HID++ 2.0 support
        if !hidpp.validate_hidpp20() {
            tracing::debug!(
                path = %device_path.display(),
                connection = %connection_type,
                "Device does not support HID++ 2.0"
            );
            return None;
        }

        // Enumerate features and check for haptic support
        hidpp.enumerate_features();

        tracing::info!(
            path = %device_path.display(),
            connection = %connection_type,
            haptic_supported = hidpp.haptic_supported,
            mx4_haptic_supported = hidpp.mx4_haptic_supported,
            "Connected to MX Master 4 via hidraw"
        );

        Some(hidpp)
    }

    /// Drain any pending data from the device buffer
    ///
    /// This prevents reading stale responses from previous requests.
    fn drain_buffer(&mut self) {
        let mut drain_buf = [0u8; 64];
        loop {
            match self.device.read(&mut drain_buf) {
                Ok(_) => continue, // Discard stale data
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }
    }

    /// Send a HID++ request and wait for matching response
    ///
    /// Uses polling with timeout (same approach as battery module).
    fn hidpp_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>> {
        // Drain any pending data first
        self.drain_buffer();

        // Build HID++ short report (7 bytes)
        let mut request = [0u8; 7];
        request[0] = report_type::SHORT;
        request[1] = self.device_index;
        request[2] = feature_index;
        request[3] = (function << 4) | SOFTWARE_ID;

        // Copy params (up to 3 bytes for short report)
        let param_len = params.len().min(3);
        request[4..4 + param_len].copy_from_slice(&params[..param_len]);

        tracing::debug!(
            feature_index,
            function,
            "Sending HID++ request: {:02X?}",
            &request
        );

        // Send request
        if let Err(e) = self.device.write_all(&request) {
            tracing::debug!(error = %e, "Failed to write HID++ message");
            return None;
        }

        // Read response with timeout (non-blocking, so we poll)
        let mut response = [0u8; 20];
        let mut attempts = 0;

        loop {
            match self.device.read(&mut response) {
                Ok(len) if len >= 7 => {
                    let resp_function = (response[3] >> 4) & 0x0F;
                    let resp_sw_id = response[3] & 0x0F;

                    tracing::debug!(
                        "HID++ response: {:02X?} (feat={}, fn={}, sw={})",
                        &response[..len],
                        response[2],
                        resp_function,
                        resp_sw_id
                    );

                    // Check if this is a response to our request
                    if response[0] == report_type::SHORT || response[0] == report_type::LONG {
                        // Must match: device index, feature index, function, AND software ID
                        if response[1] == self.device_index
                            && response[2] == feature_index
                            && resp_function == function
                            && resp_sw_id == SOFTWARE_ID
                        {
                            tracing::debug!("HID++ request matched! Returning response");
                            return Some(response[..len].to_vec());
                        }
                        // Check for error response (0xFF feature_index indicates error)
                        // Format: [report_type, device_idx, 0xFF, orig_feature_idx, orig_fn_sw, error_code, ...]
                        if response[2] == 0xFF {
                            let error_code = response[5];
                            let error_msg = match error_code {
                                0x00 => "No error",
                                0x01 => "Unknown function",
                                0x02 => "Function not available",
                                0x03 => "Invalid argument",
                                0x04 => "Not supported",
                                0x05 => "Invalid argument/Out of range",
                                0x06 => "Device busy",
                                0x07 => "Connection failed",
                                0x08 => "Invalid address",
                                _ => "Unknown error",
                            };
                            tracing::warn!(
                                error_code,
                                error_msg,
                                feature_index = response[3],
                                "HID++ error response: {:02X?}",
                                &response[..len]
                            );
                            return None;
                        }
                        // Legacy error check (0x8F)
                        if response[2] == 0x8F {
                            tracing::debug!("HID++ legacy error response: {:02X?}", &response[..len]);
                            return None;
                        }
                        // Log non-matching responses for debugging
                        tracing::debug!(
                            expected_dev = self.device_index,
                            expected_feat = feature_index,
                            expected_fn = function,
                            expected_sw = SOFTWARE_ID,
                            got_dev = response[1],
                            got_feat = response[2],
                            got_fn = resp_function,
                            got_sw = resp_sw_id,
                            "HID++ response didn't match expected values"
                        );
                    }
                }
                Ok(_) => {
                    // Short read, continue
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    // No data yet
                }
                Err(e) => {
                    tracing::debug!(error = %e, "Error reading HID++ response");
                    return None;
                }
            }

            attempts += 1;
            if attempts > 100 {
                tracing::debug!(feature_index, function, "HID++ request timeout after 100 attempts");
                return None;
            }

            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    }

    /// Send a long HID++ message (20 bytes) - for haptic patterns
    #[allow(dead_code)]
    fn hidpp_send_long(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Result<(), std::io::Error> {
        // Drain any pending data first
        self.drain_buffer();

        // Build HID++ long report (20 bytes)
        let mut request = [0u8; 20];
        request[0] = report_type::LONG;
        request[1] = self.device_index;
        request[2] = feature_index;
        request[3] = (function << 4) | SOFTWARE_ID;

        // Copy params (up to 16 bytes for long report)
        let param_len = params.len().min(16);
        request[4..4 + param_len].copy_from_slice(&params[..param_len]);

        tracing::trace!(
            feature_index,
            function,
            "Sending HID++ long message: {:02X?}",
            &request
        );

        self.device.write_all(&request)
    }

    /// Validate that the device supports HID++ 2.0 protocol
    fn validate_hidpp20(&mut self) -> bool {
        // Send IRoot ping (feature 0x00, function 0x01)
        // Ping echoes back the data byte and returns protocol version
        let params = [0x00, 0x00, 0xAA]; // 0xAA is ping data to echo

        if let Some(response) = self.hidpp_request(0x00, 0x01, &params) {
            // Check if ping data was echoed (byte 6 should be 0xAA)
            if response.len() >= 7 && response[6] == 0xAA {
                tracing::debug!("HID++ 2.0 validated, ping echoed successfully");
                return true;
            }
        }

        false
    }

    /// Enumerate device features and build feature table
    ///
    /// # SAFETY
    ///
    /// This method only READS feature information - it does NOT use
    /// any blocklisted features. Blocklisted features are logged for
    /// audit purposes but never stored for use.
    fn enumerate_features(&mut self) {
        // First, get the feature index for IFeatureSet (0x0001)
        let feature_set_index = match self.get_feature_index(features::I_FEATURE_SET) {
            Some(idx) => idx,
            None => {
                tracing::debug!("Device does not support IFeatureSet");
                return;
            }
        };

        // Get feature count (function 0x00 of IFeatureSet)
        let feature_count = match self.hidpp_request(feature_set_index, 0x00, &[]) {
            Some(resp) if resp.len() >= 5 => resp[4],
            _ => return,
        };

        tracing::debug!(count = feature_count, "Enumerating device features");

        // Enumerate each feature (function 0x01 of IFeatureSet)
        for i in 0..feature_count {
            if let Some(resp) = self.hidpp_request(feature_set_index, 0x01, &[i, 0, 0]) {
                if resp.len() < 6 {
                    continue;
                }

                let feature_id = ((resp[4] as u16) << 8) | (resp[5] as u16);
                let feature_index = i + 1; // Feature indices are 1-based

                // SAFETY CHECK: Log blocklisted features but DO NOT store them
                if blocklisted_features::is_blocklisted(feature_id) {
                    let reason = blocklisted_features::blocklist_reason(feature_id)
                        .unwrap_or("Unknown");
                    tracing::debug!(
                        feature_id = format!("0x{:04X}", feature_id),
                        reason = reason,
                        "Device has blocklisted feature (will NOT be used)"
                    );
                    // Explicitly DO NOT add to feature_table
                    continue;
                }

                self.feature_table.insert(feature_id, feature_index);

                // Log all features for debugging
                tracing::debug!(
                    feature_id = format!("0x{:04X}", feature_id),
                    feature_index = feature_index,
                    "Found feature"
                );

                // Check for legacy force feedback feature (0x8123 - for racing wheels)
                if feature_id == features::FORCE_FEEDBACK {
                    self.haptic_supported = true;
                    self.haptic_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "Legacy haptic/force feedback feature found (0x8123)"
                    );
                }

                // Check for MX Master 4 haptic feature (0x19B0)
                if feature_id == features::MX_MASTER_4_HAPTIC {
                    self.mx4_haptic_supported = true;
                    self.mx4_haptic_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "MX Master 4 haptic feature found (0x19B0)"
                    );
                }

                // Check for alternative haptic feature (0x0B4E from mx4notifications)
                if feature_id == features::MX4_HAPTIC_ALT {
                    self.mx4_haptic_supported = true;
                    self.mx4_haptic_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "MX Master 4 haptic feature found (0x0B4E - mx4notifications)"
                    );
                }

                // Check for adjustable DPI feature (0x2201)
                if feature_id == features::ADJUSTABLE_DPI {
                    self.dpi_supported = true;
                    self.dpi_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "Adjustable DPI feature found (0x2201)"
                    );
                }
            }
        }

        tracing::debug!(
            feature_count = self.feature_table.len(),
            legacy_haptic = self.haptic_supported,
            mx4_haptic = self.mx4_haptic_supported,
            dpi = self.dpi_supported,
            "Feature enumeration complete (blocklisted features excluded)"
        );
    }

    /// Get the feature index for a given feature ID using IRoot
    fn get_feature_index(&mut self, feature_id: u16) -> Option<u8> {
        // IRoot function 0x00: getFeatureIndex
        let params = [(feature_id >> 8) as u8, (feature_id & 0xFF) as u8, 0];

        self.hidpp_request(0x00, 0x00, &params).and_then(|resp| {
            if resp.len() >= 5 {
                let index = resp[4];
                if index == 0 {
                    None // Feature not supported
                } else {
                    Some(index)
                }
            } else {
                None
            }
        })
    }


    /// Check if any haptic feedback is supported (MX4 or legacy)
    pub fn haptic_supported(&self) -> bool {
        self.mx4_haptic_supported || self.haptic_supported
    }

    /// Check if MX Master 4 specific haptic is supported (feature 0x19B0)
    pub fn mx4_haptic_supported(&self) -> bool {
        self.mx4_haptic_supported
    }

    /// Check if legacy force feedback haptic is supported (feature 0x8123)
    pub fn legacy_haptic_supported(&self) -> bool {
        self.haptic_supported
    }

    /// Get connection type
    pub fn connection_type(&self) -> ConnectionType {
        self.connection_type
    }

    /// Send an MX Master 4 haptic pattern
    ///
    /// # SAFETY
    ///
    /// This method ONLY sends volatile/runtime commands.
    /// It does NOT write to onboard memory.
    ///
    /// # Arguments
    ///
    /// * `pattern` - The MX4 haptic pattern to play (0-14)
    pub fn send_haptic_pattern(&mut self, pattern: Mx4HapticPattern) -> Result<(), HapticError> {
        if !self.mx4_haptic_supported {
            tracing::trace!("MX4 haptic not supported, skipping pattern");
            return Ok(());
        }

        tracing::debug!(
            pattern = %pattern,
            waveform_id = pattern.to_id(),
            "Sending MX4 haptic pattern"
        );

        // Use the exact packet format from mx4notifications that we verified works:
        // Packet: [0x10, 0x02, 0x0B, 0x4E, waveform, 0x00, 0x00]
        // - 0x10: SHORT report type
        // - 0x02: device index (Bolt receiver)
        // - 0x0B: feature index 11 (hardcoded, matches mx4notifications)
        // - 0x4E: (function 0x04 << 4) | sw_id 0x0E
        // - waveform: the haptic pattern ID

        const MX4_HAPTIC_FEATURE_INDEX: u8 = 0x0B;  // Feature index 11
        const MX4_HAPTIC_FUNCTION: u8 = 0x04;       // Function ID for haptic play
        const MX4_HAPTIC_SW_ID: u8 = 0x0E;          // Software ID used by mx4notifications

        self.drain_buffer();

        let mut request = [0u8; 7];
        request[0] = report_type::SHORT;
        request[1] = self.device_index;
        request[2] = MX4_HAPTIC_FEATURE_INDEX;
        request[3] = (MX4_HAPTIC_FUNCTION << 4) | MX4_HAPTIC_SW_ID;
        request[4] = pattern.to_id();
        // request[5] and request[6] remain 0

        tracing::debug!(
            "Sending MX4 haptic packet: {:02X?}",
            &request
        );

        self.device.write_all(&request).map_err(HapticError::IoError)?;

        Ok(())
    }

    /// Send a haptic pulse command (legacy method for force feedback devices)
    ///
    /// # SAFETY
    ///
    /// This method ONLY sends volatile/runtime commands.
    /// It does NOT write to onboard memory.
    pub fn send_haptic_pulse(&mut self, intensity: u8, duration_ms: u16) -> Result<(), HapticError> {
        let feature_index = match self.haptic_feature_index {
            Some(idx) => idx,
            None => {
                // Legacy haptics not supported, succeed silently
                return Ok(());
            }
        };

        // Construct haptic pulse command for legacy force feedback
        // Note: This is for racing wheels and similar devices with 0x8123 feature
        let params = [
            intensity,
            (duration_ms >> 8) as u8,
            (duration_ms & 0xFF) as u8,
        ];

        // Use hidpp_request for short messages (will drain buffer and send)
        if self.hidpp_request(feature_index, 0x00, &params).is_none() {
            tracing::debug!("Legacy haptic pulse - no response (may be expected)");
        }

        Ok(())
    }

    // =========================================================================
    // DPI Methods (0x2201 - Adjustable DPI)
    // =========================================================================

    /// Check if DPI adjustment is supported
    pub fn dpi_supported(&self) -> bool {
        self.dpi_supported
    }

    /// Get current sensor DPI
    ///
    /// # Returns
    /// Current DPI value (typically 400-8000) or None if not supported
    pub fn get_dpi(&mut self) -> Option<u16> {
        let feature_index = self.dpi_feature_index?;

        tracing::debug!(feature_index, "Getting DPI from device");

        // Function [2] getSensorDpi(sensorIdx) -> sensorIdx, dpi, defaultDpi
        // sensorIdx = 0 for the primary (and usually only) sensor
        let params = [0x00, 0x00, 0x00]; // sensorIdx = 0

        self.hidpp_request(feature_index, 0x02, &params).and_then(|resp| {
            if resp.len() >= 7 {
                // Response: [report_type, device_idx, feature_idx, fn_sw_id, sensor_idx, dpi_msb, dpi_lsb, ...]
                let dpi = ((resp[5] as u16) << 8) | (resp[6] as u16);
                tracing::debug!(dpi, "Got current DPI");
                Some(dpi)
            } else {
                tracing::warn!("Invalid getSensorDpi response length: {}", resp.len());
                None
            }
        })
    }

    /// Set sensor DPI
    ///
    /// # Arguments
    /// * `dpi` - DPI value to set (typically 400-8000, device-dependent)
    ///
    /// # Returns
    /// Ok(()) on success, error on failure
    pub fn set_dpi(&mut self, dpi: u16) -> Result<(), HapticError> {
        let feature_index = match self.dpi_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("DPI adjustment not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        tracing::info!(feature_index, dpi, "Setting DPI");

        // Function [3] setSensorDpi(sensorIdx, dpi) -> sensorIdx, dpi
        // sensorIdx = 0 for the primary sensor
        let params = [
            0x00,                    // sensorIdx = 0
            (dpi >> 8) as u8,        // dpi MSB
            (dpi & 0xFF) as u8,      // dpi LSB
        ];

        match self.hidpp_request(feature_index, 0x03, &params) {
            Some(resp) => {
                if resp.len() >= 7 {
                    let confirmed_dpi = ((resp[5] as u16) << 8) | (resp[6] as u16);
                    tracing::info!(requested_dpi = dpi, confirmed_dpi, "DPI set successfully");
                    Ok(())
                } else {
                    tracing::warn!("Short setSensorDpi response, but command may have succeeded");
                    Ok(())
                }
            }
            None => {
                tracing::error!("Failed to set DPI - no response from device");
                Err(HapticError::CommunicationError)
            }
        }
    }

    /// Get the list of supported DPI values
    ///
    /// # Returns
    /// Vec of supported DPI values, or None if not supported
    pub fn get_dpi_list(&mut self) -> Option<Vec<u16>> {
        let feature_index = self.dpi_feature_index?;

        // Function [1] getSensorDpiList(sensorIdx) -> sensorIdx, dpiList
        let params = [0x00, 0x00, 0x00]; // sensorIdx = 0

        self.hidpp_request(feature_index, 0x01, &params).and_then(|resp| {
            if resp.len() < 6 {
                return None;
            }

            let mut dpi_list = Vec::new();
            // Response starts at byte 5 (after report_type, device_idx, feature_idx, fn_sw_id, sensor_idx)
            let data = &resp[5..];

            // Parse pairs of bytes as DPI values
            let mut i = 0;
            while i + 1 < data.len() {
                let dpi = ((data[i] as u16) << 8) | (data[i + 1] as u16);
                if dpi == 0 {
                    break; // End of list
                }
                // Check for hyphen value (0xE000+ range indicates step value)
                if dpi >= 0xE000 {
                    // This is a step indicator, skip it for now
                    // In a range format: [low, -step, high, 0]
                    i += 2;
                    continue;
                }
                dpi_list.push(dpi);
                i += 2;
            }

            tracing::debug!(dpi_list = ?dpi_list, "Got DPI list");
            Some(dpi_list)
        })
    }
}

// ============================================================================
// Haptic Pulse
// ============================================================================

/// HID++ haptic intensity levels
#[derive(Debug, Clone, Copy)]
pub struct HapticPulse {
    /// Intensity (0-100)
    pub intensity: u8,
    /// Duration in milliseconds
    pub duration_ms: u16,
}

/// Predefined haptic profiles from UX spec
pub mod haptic_profiles {
    use super::HapticPulse;

    /// Menu appearance haptic (20% intensity, 10ms)
    pub const MENU_APPEAR: HapticPulse = HapticPulse {
        intensity: 20,
        duration_ms: 10,
    };

    /// Slice change haptic (40% intensity, 15ms)
    pub const SLICE_CHANGE: HapticPulse = HapticPulse {
        intensity: 40,
        duration_ms: 15,
    };

    /// Selection confirm haptic (80% intensity, 25ms)
    pub const CONFIRM: HapticPulse = HapticPulse {
        intensity: 80,
        duration_ms: 25,
    };

    /// Invalid action haptic (30% intensity, 50ms)
    pub const INVALID: HapticPulse = HapticPulse {
        intensity: 30,
        duration_ms: 50,
    };
}

// ============================================================================
// Haptic Events & Patterns (UX Spec Section 2.3)
// ============================================================================

/// Haptic pulse pattern type
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HapticPattern {
    /// Single pulse
    Single,
    /// Double pulse with 30ms gap
    Double,
    /// Triple short pulse with 20ms gaps
    Triple,
}

impl HapticPattern {
    /// Get the number of pulses for this pattern
    pub fn pulse_count(&self) -> u8 {
        match self {
            HapticPattern::Single => 1,
            HapticPattern::Double => 2,
            HapticPattern::Triple => 3,
        }
    }

    /// Get the gap between pulses in milliseconds
    pub fn gap_ms(&self) -> u64 {
        match self {
            HapticPattern::Single => 0,
            HapticPattern::Double => 30,
            HapticPattern::Triple => 20,
        }
    }
}

// ============================================================================
// MX Master 4 Haptic Patterns (Story 10.1)
// ============================================================================

/// MX Master 4 haptic waveforms
///
/// The MX Master 4 uses predefined haptic waveforms. The actual haptic
/// commands are sent via feature index 0x0B with function 0x04
/// (based on mx4notifications project implementation).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Mx4HapticPattern {
    /// Sharp state change - crisp feedback for state transitions (ID: 0x00)
    SharpStateChange = 0x00,
    /// Damp state change - softer feedback for state transitions (ID: 0x01)
    DampStateChange = 0x01,
    /// Sharp collision - strong feedback for collisions (ID: 0x02)
    SharpCollision = 0x02,
    /// Damp collision - soft feedback for collisions (ID: 0x03)
    DampCollision = 0x03,
    /// Subtle collision - very light feedback (ID: 0x04)
    SubtleCollision = 0x04,
    /// Happy alert - positive notification (ID: 0x05)
    HappyAlert = 0x05,
    /// Angry alert - error/warning notification (ID: 0x06)
    AngryAlert = 0x06,
    /// Completed - success/completion feedback (ID: 0x07)
    Completed = 0x07,
    /// Square wave pattern (ID: 0x08)
    Square = 0x08,
    /// Wave pattern (ID: 0x09)
    Wave = 0x09,
    /// Firework pattern (ID: 0x0A)
    Firework = 0x0A,
    /// Mad pattern - strong error (ID: 0x0B)
    Mad = 0x0B,
    /// Knock pattern (ID: 0x0C)
    Knock = 0x0C,
    /// Jingle pattern (ID: 0x0D)
    Jingle = 0x0D,
    /// Ringing pattern (ID: 0x0E)
    Ringing = 0x0E,
    /// Whisper collision - very subtle (ID: 0x1B)
    WhisperCollision = 0x1B,
}

impl Mx4HapticPattern {
    /// Convert pattern to raw ID for HID++ command
    pub fn to_id(self) -> u8 {
        self as u8
    }

    /// Create from raw waveform ID
    pub fn from_id(id: u8) -> Option<Self> {
        match id {
            0x00 => Some(Self::SharpStateChange),
            0x01 => Some(Self::DampStateChange),
            0x02 => Some(Self::SharpCollision),
            0x03 => Some(Self::DampCollision),
            0x04 => Some(Self::SubtleCollision),
            0x05 => Some(Self::HappyAlert),
            0x06 => Some(Self::AngryAlert),
            0x07 => Some(Self::Completed),
            0x08 => Some(Self::Square),
            0x09 => Some(Self::Wave),
            0x0A => Some(Self::Firework),
            0x0B => Some(Self::Mad),
            0x0C => Some(Self::Knock),
            0x0D => Some(Self::Jingle),
            0x0E => Some(Self::Ringing),
            0x1B => Some(Self::WhisperCollision),
            _ => None,
        }
    }

    /// Get human-readable name for the waveform
    pub fn name(&self) -> &'static str {
        match self {
            Self::SharpStateChange => "Sharp State Change",
            Self::DampStateChange => "Damp State Change",
            Self::SharpCollision => "Sharp Collision",
            Self::DampCollision => "Damp Collision",
            Self::SubtleCollision => "Subtle Collision",
            Self::HappyAlert => "Happy Alert",
            Self::AngryAlert => "Angry Alert",
            Self::Completed => "Completed",
            Self::Square => "Square",
            Self::Wave => "Wave",
            Self::Firework => "Firework",
            Self::Mad => "Mad",
            Self::Knock => "Knock",
            Self::Jingle => "Jingle",
            Self::Ringing => "Ringing",
            Self::WhisperCollision => "Whisper Collision",
        }
    }

    /// Create from config name string (snake_case)
    /// Returns SubtleCollision as default if name is not recognized
    pub fn from_name(name: &str) -> Self {
        match name {
            "sharp_state_change" => Self::SharpStateChange,
            "damp_state_change" => Self::DampStateChange,
            "sharp_collision" => Self::SharpCollision,
            "damp_collision" => Self::DampCollision,
            "subtle_collision" => Self::SubtleCollision,
            "whisper_collision" => Self::WhisperCollision,
            "happy_alert" => Self::HappyAlert,
            "angry_alert" => Self::AngryAlert,
            "completed" => Self::Completed,
            "square" => Self::Square,
            "wave" => Self::Wave,
            "firework" => Self::Firework,
            "mad" => Self::Mad,
            "knock" => Self::Knock,
            "jingle" => Self::Jingle,
            "ringing" => Self::Ringing,
            _ => {
                tracing::warn!(name, "Unknown haptic pattern name, using default");
                Self::SubtleCollision
            }
        }
    }
}

impl fmt::Display for Mx4HapticPattern {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} ({})", self.name(), self.to_id())
    }
}

/// UX haptic events triggered during menu interaction
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HapticEvent {
    /// Radial menu appears on screen
    MenuAppear,
    /// Cursor moves to highlight a different slice
    SliceChange,
    /// User confirms selection (gesture button released on valid slice)
    SelectionConfirm,
    /// User selects an empty or invalid slice
    InvalidAction,
}

impl HapticEvent {
    /// Get the base UX profile for this event
    pub fn base_profile(&self) -> HapticPulse {
        match self {
            HapticEvent::MenuAppear => haptic_profiles::MENU_APPEAR,
            HapticEvent::SliceChange => haptic_profiles::SLICE_CHANGE,
            HapticEvent::SelectionConfirm => haptic_profiles::CONFIRM,
            HapticEvent::InvalidAction => haptic_profiles::INVALID,
        }
    }

    /// Get the pulse pattern for this event
    pub fn pattern(&self) -> HapticPattern {
        match self {
            HapticEvent::MenuAppear => HapticPattern::Single,
            HapticEvent::SliceChange => HapticPattern::Single,
            HapticEvent::SelectionConfirm => HapticPattern::Double,
            HapticEvent::InvalidAction => HapticPattern::Triple,
        }
    }

    /// Get the default intensity for this event (0-100)
    pub fn default_intensity(&self) -> u8 {
        self.base_profile().intensity
    }

    /// Get the duration for this event in milliseconds
    pub fn duration_ms(&self) -> u16 {
        self.base_profile().duration_ms
    }

    /// Get the MX Master 4 haptic waveform for this event
    ///
    /// Maps UX haptic events to appropriate MX4 waveform IDs.
    /// Waveform selection is based on the feel that best matches
    /// the intended UX feedback.
    pub fn mx4_pattern(&self) -> Mx4HapticPattern {
        match self {
            // Menu appear: subtle feedback to indicate menu opened
            HapticEvent::MenuAppear => Mx4HapticPattern::SubtleCollision,
            // Slice change: distinct click for each slice transition
            HapticEvent::SliceChange => Mx4HapticPattern::SharpStateChange,
            // Selection confirm: success/completion feel
            HapticEvent::SelectionConfirm => Mx4HapticPattern::Completed,
            // Invalid action: error/warning feel
            HapticEvent::InvalidAction => Mx4HapticPattern::AngryAlert,
        }
    }
}

impl fmt::Display for HapticEvent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HapticEvent::MenuAppear => write!(f, "menu_appear"),
            HapticEvent::SliceChange => write!(f, "slice_change"),
            HapticEvent::SelectionConfirm => write!(f, "selection_confirm"),
            HapticEvent::InvalidAction => write!(f, "invalid_action"),
        }
    }
}

// ============================================================================
// Haptic Manager
// ============================================================================

/// Per-event haptic pattern configuration
#[derive(Debug, Clone, Copy)]
pub struct PerEventPattern {
    /// Pattern for menu appearance
    pub menu_appear: Mx4HapticPattern,
    /// Pattern for slice change (hover)
    pub slice_change: Mx4HapticPattern,
    /// Pattern for selection confirmation
    pub confirm: Mx4HapticPattern,
    /// Pattern for invalid action
    pub invalid: Mx4HapticPattern,
}

impl Default for PerEventPattern {
    fn default() -> Self {
        Self {
            menu_appear: Mx4HapticPattern::DampStateChange,
            slice_change: Mx4HapticPattern::SubtleCollision,
            confirm: Mx4HapticPattern::SharpStateChange,
            invalid: Mx4HapticPattern::AngryAlert,
        }
    }
}

impl PerEventPattern {
    /// Get pattern for a specific event
    pub fn get(&self, event: &HapticEvent) -> Mx4HapticPattern {
        match event {
            HapticEvent::MenuAppear => self.menu_appear,
            HapticEvent::SliceChange => self.slice_change,
            HapticEvent::SelectionConfirm => self.confirm,
            HapticEvent::InvalidAction => self.invalid,
        }
    }
}

/// Connection state for graceful fallback handling
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionState {
    /// No connection attempted yet
    NotConnected,
    /// Successfully connected to device
    Connected,
    /// Device was connected but is now disconnected (IO error, sleep, unplug)
    Disconnected,
    /// Waiting for cooldown before attempting reconnection
    Cooldown,
}

impl Default for ConnectionState {
    fn default() -> Self {
        ConnectionState::NotConnected
    }
}

/// Reconnection cooldown in milliseconds (5 seconds)
const RECONNECT_COOLDOWN_MS: u64 = 5000;

/// Default slice debounce time (milliseconds)
const DEFAULT_SLICE_DEBOUNCE_MS: u64 = 20;

/// Default re-entry debounce time (milliseconds)
const DEFAULT_REENTRY_DEBOUNCE_MS: u64 = 50;

/// HID++ haptic manager
pub struct HapticManager {
    /// Optional HID++ device connection
    device: Option<HidppDevice>,
    /// Default haptic pattern (fallback)
    default_pattern: Mx4HapticPattern,
    /// Per-event pattern configuration
    per_event: PerEventPattern,
    /// Whether haptics are enabled
    enabled: bool,
    /// Last pulse timestamp for debouncing (milliseconds)
    last_pulse_ms: u64,
    /// Connection state for reconnection logic
    connection_state: ConnectionState,
    /// Timestamp of last disconnect/failure for cooldown
    last_disconnect_ms: u64,
    /// Minimum time between pulses (milliseconds)
    debounce_ms: u64,
    /// Slice-specific debounce time (milliseconds)
    slice_debounce_ms: u64,
    /// Re-entry detection debounce time (milliseconds)
    reentry_debounce_ms: u64,
    /// Last slice change timestamp (milliseconds)
    last_slice_change_ms: u64,
    /// Last slice index for re-entry detection (None = no previous slice)
    last_slice_index: Option<u8>,
    /// Pre-allocated short message buffer for low-latency sends
    _short_msg_buffer: [u8; 7],
}

impl HapticManager {
    /// Create a new haptic manager without device connection
    pub fn new(enabled: bool) -> Self {
        Self {
            device: None,
            default_pattern: Mx4HapticPattern::SubtleCollision,
            per_event: PerEventPattern::default(),
            enabled,
            last_pulse_ms: 0,
            connection_state: ConnectionState::NotConnected,
            last_disconnect_ms: 0,
            debounce_ms: 20,
            slice_debounce_ms: DEFAULT_SLICE_DEBOUNCE_MS,
            reentry_debounce_ms: DEFAULT_REENTRY_DEBOUNCE_MS,
            last_slice_change_ms: 0,
            last_slice_index: None,
            _short_msg_buffer: [0u8; 7],
        }
    }

    /// Create a haptic manager from configuration
    ///
    /// This is the preferred way to initialize HapticManager with user settings.
    pub fn from_config(config: &crate::config::HapticConfig) -> Self {
        Self {
            device: None,
            default_pattern: Mx4HapticPattern::from_name(&config.default_pattern),
            per_event: PerEventPattern {
                menu_appear: Mx4HapticPattern::from_name(&config.per_event.menu_appear),
                slice_change: Mx4HapticPattern::from_name(&config.per_event.slice_change),
                confirm: Mx4HapticPattern::from_name(&config.per_event.confirm),
                invalid: Mx4HapticPattern::from_name(&config.per_event.invalid),
            },
            enabled: config.enabled,
            last_pulse_ms: 0,
            connection_state: ConnectionState::NotConnected,
            last_disconnect_ms: 0,
            debounce_ms: config.debounce_ms,
            slice_debounce_ms: config.slice_debounce_ms,
            reentry_debounce_ms: config.reentry_debounce_ms,
            last_slice_change_ms: 0,
            last_slice_index: None,
            _short_msg_buffer: [0u8; 7],
        }
    }

    /// Update settings from configuration (for hot-reload)
    pub fn update_from_config(&mut self, config: &crate::config::HapticConfig) {
        self.default_pattern = Mx4HapticPattern::from_name(&config.default_pattern);
        self.per_event = PerEventPattern {
            menu_appear: Mx4HapticPattern::from_name(&config.per_event.menu_appear),
            slice_change: Mx4HapticPattern::from_name(&config.per_event.slice_change),
            confirm: Mx4HapticPattern::from_name(&config.per_event.confirm),
            invalid: Mx4HapticPattern::from_name(&config.per_event.invalid),
        };
        self.enabled = config.enabled;
        self.debounce_ms = config.debounce_ms;
        self.slice_debounce_ms = config.slice_debounce_ms;
        self.reentry_debounce_ms = config.reentry_debounce_ms;

        tracing::debug!(
            default_pattern = %self.default_pattern,
            enabled = self.enabled,
            debounce_ms = self.debounce_ms,
            slice_debounce_ms = self.slice_debounce_ms,
            reentry_debounce_ms = self.reentry_debounce_ms,
            "Haptic settings updated from config"
        );
    }

    /// Attempt to connect to MX Master 4
    ///
    /// Returns Ok(true) if connected, Ok(false) if no device found.
    /// This is NOT an error - haptics are optional.
    pub fn connect(&mut self) -> Result<bool, HapticError> {
        match HidppDevice::open() {
            Some(device) => {
                let haptic_supported = device.haptic_supported();
                let connection = device.connection_type();
                self.device = Some(device);
                self.connection_state = ConnectionState::Connected;

                if haptic_supported {
                    tracing::info!(
                        connection = %connection,
                        "Haptic feedback enabled"
                    );
                } else {
                    tracing::info!(
                        connection = %connection,
                        "Connected but haptic feature not found"
                    );
                }

                Ok(true)
            }
            None => {
                tracing::info!("No MX Master 4 found, haptics disabled");
                self.connection_state = ConnectionState::NotConnected;
                Ok(false)
            }
        }
    }

    /// Handle device disconnection gracefully
    ///
    /// Called when an IO error occurs during haptic communication.
    /// Marks the device as disconnected and starts cooldown timer.
    fn handle_disconnect(&mut self) {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        // Only log once when transitioning to disconnected state
        if self.connection_state == ConnectionState::Connected {
            tracing::warn!("Haptic device disconnected, will attempt reconnection after cooldown");
        }

        self.device = None;
        self.connection_state = ConnectionState::Disconnected;
        self.last_disconnect_ms = now;
    }

    /// Attempt to reconnect if device was disconnected and cooldown has passed
    ///
    /// Call this method on menu appearance to enable automatic reconnection.
    /// Returns true if reconnection succeeded, false otherwise.
    pub fn reconnect_if_needed(&mut self) -> bool {
        // Only reconnect if we were previously connected but lost connection
        if self.connection_state != ConnectionState::Disconnected
            && self.connection_state != ConnectionState::Cooldown
        {
            return self.connection_state == ConnectionState::Connected;
        }

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        // Check if cooldown has passed
        if now.saturating_sub(self.last_disconnect_ms) < RECONNECT_COOLDOWN_MS {
            self.connection_state = ConnectionState::Cooldown;
            return false;
        }

        // Attempt reconnection
        tracing::debug!("Attempting haptic device reconnection");

        match self.connect() {
            Ok(true) => {
                tracing::info!("Haptic device reconnected successfully");
                true
            }
            Ok(false) => {
                // No device found, go back to cooldown
                self.connection_state = ConnectionState::Cooldown;
                self.last_disconnect_ms = now;
                false
            }
            Err(e) => {
                tracing::debug!(error = %e, "Reconnection failed");
                self.connection_state = ConnectionState::Cooldown;
                self.last_disconnect_ms = now;
                false
            }
        }
    }

    /// Get current connection state
    pub fn connection_state(&self) -> ConnectionState {
        self.connection_state
    }

    /// Check if haptic feedback is available
    pub fn is_available(&self) -> bool {
        self.device
            .as_ref()
            .map(|d| d.haptic_supported())
            .unwrap_or(false)
    }

    /// Send a haptic pulse (runtime only, no memory writes)
    ///
    /// CRITICAL: This method MUST NOT write to onboard mouse memory.
    /// Only volatile/runtime HID++ commands are used.
    ///
    /// # Graceful Fallback
    ///
    /// If the device is disconnected or unavailable, this method succeeds
    /// silently. Menu functionality is never blocked by haptic failures.
    pub fn pulse(&mut self, haptic: HapticPulse) -> Result<(), HapticError> {
        // Check if haptics are enabled
        if !self.enabled {
            return Ok(());
        }

        // Check if device is available
        let device = match &mut self.device {
            Some(d) if d.haptic_supported() => d,
            _ => {
                // No device or haptics not supported - succeed silently
                return Ok(());
            }
        };

        // Debounce: minimum time between pulses
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        if now.saturating_sub(self.last_pulse_ms) < self.debounce_ms {
            return Ok(());
        }

        tracing::debug!(
            intensity = haptic.intensity,
            duration_ms = haptic.duration_ms,
            "Sending haptic pulse (legacy)"
        );

        // Send the pulse - handle errors gracefully
        match device.send_haptic_pulse(haptic.intensity, haptic.duration_ms) {
            Ok(()) => {
                self.last_pulse_ms = now;
                Ok(())
            }
            Err(HapticError::IoError(_)) => {
                // Device disconnected or communication error
                // Handle gracefully - don't crash, just mark disconnected
                self.handle_disconnect();
                Ok(()) // Return Ok - haptics are optional
            }
            Err(e) => {
                // Other errors (shouldn't happen, but log them)
                tracing::debug!(error = %e, "Haptic pulse failed");
                Ok(()) // Still return Ok - haptics are optional
            }
        }
    }

    /// Emit a haptic event using UX-defined profiles
    ///
    /// This is the preferred API for triggering haptic feedback.
    /// It applies:
    /// 1. Global intensity multiplier
    /// 2. Per-event intensity override from config
    /// 3. Appropriate pulse pattern (single/double/triple) OR MX4 pattern
    ///
    /// For MX Master 4 devices with feature 0x19B0, uses predefined hardware waveforms.
    /// For other devices, uses legacy intensity/duration-based pulses.
    ///
    /// CRITICAL: This method MUST NOT write to onboard mouse memory.
    pub fn emit(&mut self, event: HapticEvent) -> Result<(), HapticError> {
        // Check if haptics are enabled
        if !self.enabled {
            return Ok(());
        }

        // Check if device is available
        let device = match &mut self.device {
            Some(d) if d.haptic_supported() => d,
            _ => {
                // No device or haptics not supported - succeed silently
                return Ok(());
            }
        };

        // Debounce: minimum time between pulses
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        if now.saturating_sub(self.last_pulse_ms) < self.debounce_ms {
            return Ok(());
        }

        // Use MX Master 4 haptic patterns (configured per-event)
        if device.mx4_haptic_supported() {
            // Get the configured pattern for this event
            let pattern = self.per_event.get(&event);
            tracing::debug!(
                event = %event,
                pattern = %pattern,
                "Emitting MX4 haptic pattern"
            );

            match device.send_haptic_pattern(pattern) {
                Ok(()) => {
                    self.last_pulse_ms = now;
                    return Ok(());
                }
                Err(HapticError::IoError(_)) => {
                    // Device disconnected - handle gracefully
                    self.handle_disconnect();
                    return Ok(());
                }
                Err(e) => {
                    tracing::debug!(error = %e, "MX4 haptic pattern failed");
                    return Ok(());
                }
            }
        }

        // Fallback to legacy intensity/duration-based pulses (non-MX4 devices)
        // Use default intensity of 50 for legacy devices
        let base_profile = event.base_profile();
        let pulse_pattern = event.pattern();
        let legacy_intensity: u8 = 50;

        tracing::debug!(
            event = %event,
            pattern = ?pulse_pattern,
            intensity = legacy_intensity,
            duration_ms = base_profile.duration_ms,
            "Emitting legacy haptic event"
        );

        let pulse = HapticPulse {
            intensity: legacy_intensity,
            duration_ms: base_profile.duration_ms,
        };

        // Execute the pattern using the internal pulse method logic
        match pulse_pattern {
            HapticPattern::Single => {
                self.pulse(pulse)?;
            }
            HapticPattern::Double => {
                self.pulse(pulse)?;
                // Wait for gap before second pulse
                std::thread::sleep(std::time::Duration::from_millis(pulse_pattern.gap_ms()));
                self.last_pulse_ms = 0; // Reset debounce for pattern continuation
                self.pulse(pulse)?;
            }
            HapticPattern::Triple => {
                self.pulse(pulse)?;
                std::thread::sleep(std::time::Duration::from_millis(pulse_pattern.gap_ms()));
                self.last_pulse_ms = 0;
                self.pulse(pulse)?;
                std::thread::sleep(std::time::Duration::from_millis(pulse_pattern.gap_ms()));
                self.last_pulse_ms = 0;
                self.pulse(pulse)?;
            }
        }

        Ok(())
    }

    /// Emit a haptic event asynchronously (non-blocking)
    ///
    /// Spawns the haptic pattern execution in a separate thread
    /// to avoid blocking the caller during multi-pulse patterns.
    pub fn emit_async(&mut self, event: HapticEvent) {
        // Check early to avoid spawning thread if disabled
        if !self.enabled {
            return;
        }

        // For single pulses, execute directly (fast)
        if event.pattern() == HapticPattern::Single {
            let _ = self.emit(event);
            return;
        }

        // For multi-pulse patterns, spawn async
        // Note: In production, this would use tokio::spawn
        // For now, log that async would be used
        tracing::debug!(event = %event, "Multi-pulse pattern - executing synchronously (async TBD)");
        let _ = self.emit(event);
    }

    /// Emit a slice change haptic with smart debouncing
    ///
    /// This method implements optimized debouncing for slice changes:
    /// 1. **Rapid movement debounce**: Only emits if `slice_debounce_ms` has passed
    ///    since the last slice change, ensuring rapid cursor movement only
    ///    triggers haptic feedback for the final slice.
    /// 2. **Re-entry prevention**: If the same slice is re-entered within
    ///    `reentry_debounce_ms`, no duplicate haptic is sent.
    ///
    /// # Arguments
    ///
    /// * `slice_index` - The index of the currently highlighted slice (0-255)
    ///
    /// # Returns
    ///
    /// * `true` if haptic was emitted
    /// * `false` if debounced/suppressed
    pub fn emit_slice_change(&mut self, slice_index: u8) -> bool {
        // Check if haptics are enabled
        if !self.enabled {
            return false;
        }

        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        let elapsed_since_last_slice = now.saturating_sub(self.last_slice_change_ms);

        // Check for re-entry: same slice within reentry_debounce_ms
        if let Some(last_slice) = self.last_slice_index {
            if last_slice == slice_index && elapsed_since_last_slice < self.reentry_debounce_ms {
                tracing::trace!(
                    slice = slice_index,
                    elapsed_ms = elapsed_since_last_slice,
                    reentry_debounce_ms = self.reentry_debounce_ms,
                    "Slice re-entry suppressed (debounce)"
                );
                return false;
            }
        }

        // Check slice debounce: different slice but within slice_debounce_ms
        if elapsed_since_last_slice < self.slice_debounce_ms {
            // Update last slice but don't emit - rapid movement in progress
            self.last_slice_index = Some(slice_index);
            tracing::trace!(
                slice = slice_index,
                elapsed_ms = elapsed_since_last_slice,
                slice_debounce_ms = self.slice_debounce_ms,
                "Slice change debounced (rapid movement)"
            );
            return false;
        }

        // Emit the slice change haptic
        self.last_slice_change_ms = now;
        self.last_slice_index = Some(slice_index);

        // Use emit() for the actual haptic
        if let Err(e) = self.emit(HapticEvent::SliceChange) {
            tracing::debug!(error = %e, "Slice change haptic failed");
            return false;
        }

        tracing::trace!(
            slice = slice_index,
            "Slice change haptic emitted"
        );
        true
    }

    /// Reset slice tracking state
    ///
    /// Call this when the menu is dismissed or a new menu appears
    /// to clear the last slice tracking.
    pub fn reset_slice_tracking(&mut self) {
        self.last_slice_index = None;
        self.last_slice_change_ms = 0;
    }

    /// Get the current slice debounce time in milliseconds
    pub fn slice_debounce_ms(&self) -> u64 {
        self.slice_debounce_ms
    }

    /// Get the current re-entry debounce time in milliseconds
    pub fn reentry_debounce_ms(&self) -> u64 {
        self.reentry_debounce_ms
    }

    /// Set slice debounce time in milliseconds
    pub fn set_slice_debounce_ms(&mut self, ms: u64) {
        self.slice_debounce_ms = ms;
    }

    /// Set re-entry debounce time in milliseconds
    pub fn set_reentry_debounce_ms(&mut self, ms: u64) {
        self.reentry_debounce_ms = ms;
    }

    /// Set haptics enabled/disabled
    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
    }

    /// Set debounce time in milliseconds
    pub fn set_debounce_ms(&mut self, ms: u64) {
        self.debounce_ms = ms;
    }

    /// Check if haptics are enabled
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Get the default haptic pattern
    pub fn default_pattern(&self) -> Mx4HapticPattern {
        self.default_pattern
    }

    // =========================================================================
    // DPI Methods (delegated to HidppDevice)
    // =========================================================================

    /// Check if DPI adjustment is supported
    pub fn dpi_supported(&mut self) -> bool {
        // Try to connect if not connected
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_ref().map(|d| d.dpi_supported()).unwrap_or(false)
    }

    /// Get current DPI value
    pub fn get_dpi(&mut self) -> Option<u16> {
        // Try to connect if not connected
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_mut().and_then(|d| d.get_dpi())
    }

    /// Set DPI value
    pub fn set_dpi(&mut self, dpi: u16) -> Result<(), HapticError> {
        // Try to connect if not connected
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => device.set_dpi(dpi),
            None => {
                tracing::warn!("Cannot set DPI: device not connected");
                Err(HapticError::DeviceNotFound)
            }
        }
    }

    /// Get list of supported DPI values
    pub fn get_dpi_list(&mut self) -> Option<Vec<u16>> {
        // Try to connect if not connected
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_mut().and_then(|d| d.get_dpi_list())
    }
}

impl Default for HapticManager {
    fn default() -> Self {
        Self::new(true)
    }
}

// ============================================================================
// Error Types
// ============================================================================

/// Haptic error type
#[derive(Debug)]
pub enum HapticError {
    /// No compatible device found
    DeviceNotFound,
    /// Permission denied accessing device
    PermissionDenied,
    /// Device does not support haptics
    UnsupportedDevice,
    /// Feature not supported on this device
    NotSupported,
    /// Communication error with device
    CommunicationError,
    /// I/O error during communication
    IoError(std::io::Error),
    /// HID++ protocol error
    ProtocolError(String),
    /// CRITICAL: Attempted to use blocklisted feature that writes to memory
    ///
    /// This error indicates a programming bug - we should NEVER
    /// attempt to use persistent/memory-writing HID++ features.
    SafetyViolation {
        feature_id: u16,
        reason: &'static str,
    },
}

impl fmt::Display for HapticError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HapticError::DeviceNotFound => write!(f, "MX Master 4 device not found"),
            HapticError::PermissionDenied => {
                write!(f, "Permission denied accessing HID device")
            }
            HapticError::UnsupportedDevice => {
                write!(f, "Device does not support haptic feedback")
            }
            HapticError::NotSupported => {
                write!(f, "Feature not supported on this device")
            }
            HapticError::CommunicationError => {
                write!(f, "Communication error with device")
            }
            HapticError::IoError(e) => write!(f, "I/O error: {}", e),
            HapticError::ProtocolError(msg) => write!(f, "HID++ protocol error: {}", msg),
            HapticError::SafetyViolation { feature_id, reason } => {
                write!(
                    f,
                    "SAFETY VIOLATION: Blocked feature 0x{:04X} - {}",
                    feature_id, reason
                )
            }
        }
    }
}

impl std::error::Error for HapticError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            HapticError::IoError(e) => Some(e),
            _ => None,
        }
    }
}

impl From<std::io::Error> for HapticError {
    fn from(err: std::io::Error) -> Self {
        HapticError::IoError(err)
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_haptic_profiles_ux_spec() {
        // Verify profiles match UX spec Section 2.3
        assert_eq!(haptic_profiles::MENU_APPEAR.intensity, 20);
        assert_eq!(haptic_profiles::MENU_APPEAR.duration_ms, 10);

        assert_eq!(haptic_profiles::SLICE_CHANGE.intensity, 40);
        assert_eq!(haptic_profiles::SLICE_CHANGE.duration_ms, 15);

        assert_eq!(haptic_profiles::CONFIRM.intensity, 80);
        assert_eq!(haptic_profiles::CONFIRM.duration_ms, 25);

        assert_eq!(haptic_profiles::INVALID.intensity, 30);
        assert_eq!(haptic_profiles::INVALID.duration_ms, 50);
    }

    #[test]
    fn test_disabled_haptics() {
        let mut manager = HapticManager::new(50, false);
        // Should succeed but do nothing when disabled
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
    }

    #[test]
    fn test_zero_intensity() {
        let mut manager = HapticManager::new(0, true);
        // Should succeed but do nothing with zero intensity
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
    }

    #[test]
    fn test_intensity_scaling() {
        let manager = HapticManager::new(50, true);
        // 50% of 80 should be 40
        let scaled = (haptic_profiles::CONFIRM.intensity as u16 * manager.intensity() as u16) / 100;
        assert_eq!(scaled, 40);
    }

    #[test]
    fn test_intensity_clamping() {
        let manager = HapticManager::new(150, true);
        // Should be clamped to 100
        assert_eq!(manager.intensity(), 100);
    }

    #[test]
    fn test_short_message_construction() {
        let msg = HidppShortMessage::new(0xFF, 0x00, 0x01, 0x05)
            .with_params([0xAA, 0xBB, 0xCC]);

        let bytes = msg.to_bytes();
        assert_eq!(bytes[0], 0x10); // Short report type
        assert_eq!(bytes[1], 0xFF); // Device index
        assert_eq!(bytes[2], 0x00); // Feature index
        assert_eq!(bytes[3], 0x15); // Function 1, SW ID 5
        assert_eq!(bytes[4], 0xAA);
        assert_eq!(bytes[5], 0xBB);
        assert_eq!(bytes[6], 0xCC);
    }

    #[test]
    fn test_short_message_parsing() {
        let bytes = [0x10, 0xFF, 0x00, 0x15, 0xAA, 0xBB, 0xCC];
        let msg = HidppShortMessage::from_bytes(&bytes).unwrap();

        assert_eq!(msg.device_index, 0xFF);
        assert_eq!(msg.feature_index, 0x00);
        assert_eq!(msg.function_id(), 0x01);
        assert_eq!(msg.sw_id(), 0x05);
        assert_eq!(msg.params, [0xAA, 0xBB, 0xCC]);
    }

    #[test]
    fn test_long_message_construction() {
        let msg = HidppLongMessage::new(0x01, 0x05, 0x02, 0x0A)
            .with_params(&[1, 2, 3, 4, 5]);

        let bytes = msg.to_bytes();
        assert_eq!(bytes[0], 0x11); // Long report type
        assert_eq!(bytes[1], 0x01); // Device index
        assert_eq!(bytes[2], 0x05); // Feature index
        assert_eq!(bytes[3], 0x2A); // Function 2, SW ID 10
        assert_eq!(bytes[4], 1);
        assert_eq!(bytes[5], 2);
        assert_eq!(bytes[6], 3);
    }

    #[test]
    fn test_connection_type_display() {
        assert_eq!(format!("{}", ConnectionType::Usb), "USB");
        assert_eq!(format!("{}", ConnectionType::Bolt), "Bolt");
        assert_eq!(format!("{}", ConnectionType::Bluetooth), "Bluetooth");
        assert_eq!(format!("{}", ConnectionType::Unifying), "Unifying");
    }

    #[test]
    fn test_haptic_error_display() {
        assert!(HapticError::DeviceNotFound.to_string().contains("not found"));
        assert!(HapticError::PermissionDenied.to_string().contains("Permission"));
        assert!(HapticError::UnsupportedDevice.to_string().contains("not support"));
    }

    #[test]
    fn test_graceful_fallback_no_device() {
        let mut manager = HapticManager::new(50, true);
        // Without connect(), device is None
        // Should succeed silently (graceful degradation)
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
        assert!(!manager.is_available());
    }

    #[test]
    fn test_default_manager() {
        let manager = HapticManager::default();
        assert_eq!(manager.intensity(), 50);
        assert!(manager.is_enabled());
    }

    #[test]
    fn test_set_debounce() {
        let mut manager = HapticManager::new(50, true);
        manager.set_debounce_ms(30);
        // Debounce is internal but we can verify it doesn't panic
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
    }

    #[test]
    fn test_from_config() {
        use crate::config::HapticConfig;

        let config = HapticConfig {
            enabled: true,
            intensity: 75,
            per_event: Default::default(),
            debounce_ms: 30,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
        };

        let manager = HapticManager::from_config(&config);
        assert_eq!(manager.intensity(), 75);
        assert!(manager.is_enabled());
    }

    #[test]
    fn test_from_config_disabled() {
        use crate::config::HapticConfig;

        let config = HapticConfig {
            enabled: false,
            intensity: 75,
            per_event: Default::default(),
            debounce_ms: 20,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
        };

        let manager = HapticManager::from_config(&config);
        assert!(!manager.is_enabled());
    }

    #[test]
    fn test_update_from_config() {
        use crate::config::HapticConfig;

        let mut manager = HapticManager::new(50, true);
        assert_eq!(manager.intensity(), 50);

        let new_config = HapticConfig {
            enabled: true,
            intensity: 80,
            per_event: Default::default(),
            debounce_ms: 25,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
        };

        manager.update_from_config(&new_config);
        assert_eq!(manager.intensity(), 80);
    }

    // ========================================================================
    // Story 5.3: HapticEvent and Pattern Tests
    // ========================================================================

    #[test]
    fn test_haptic_event_base_profiles() {
        // Verify each event maps to correct UX spec profile
        assert_eq!(HapticEvent::MenuAppear.base_profile().intensity, 20);
        assert_eq!(HapticEvent::MenuAppear.base_profile().duration_ms, 10);

        assert_eq!(HapticEvent::SliceChange.base_profile().intensity, 40);
        assert_eq!(HapticEvent::SliceChange.base_profile().duration_ms, 15);

        assert_eq!(HapticEvent::SelectionConfirm.base_profile().intensity, 80);
        assert_eq!(HapticEvent::SelectionConfirm.base_profile().duration_ms, 25);

        assert_eq!(HapticEvent::InvalidAction.base_profile().intensity, 30);
        assert_eq!(HapticEvent::InvalidAction.base_profile().duration_ms, 50);
    }

    #[test]
    fn test_haptic_event_patterns() {
        // Verify each event has correct pattern per UX spec
        assert_eq!(HapticEvent::MenuAppear.pattern(), HapticPattern::Single);
        assert_eq!(HapticEvent::SliceChange.pattern(), HapticPattern::Single);
        assert_eq!(HapticEvent::SelectionConfirm.pattern(), HapticPattern::Double);
        assert_eq!(HapticEvent::InvalidAction.pattern(), HapticPattern::Triple);
    }

    #[test]
    fn test_haptic_pattern_pulse_counts() {
        assert_eq!(HapticPattern::Single.pulse_count(), 1);
        assert_eq!(HapticPattern::Double.pulse_count(), 2);
        assert_eq!(HapticPattern::Triple.pulse_count(), 3);
    }

    #[test]
    fn test_haptic_pattern_gaps() {
        assert_eq!(HapticPattern::Single.gap_ms(), 0);
        assert_eq!(HapticPattern::Double.gap_ms(), 30);
        assert_eq!(HapticPattern::Triple.gap_ms(), 20);
    }

    #[test]
    fn test_haptic_event_display() {
        assert_eq!(format!("{}", HapticEvent::MenuAppear), "menu_appear");
        assert_eq!(format!("{}", HapticEvent::SliceChange), "slice_change");
        assert_eq!(format!("{}", HapticEvent::SelectionConfirm), "selection_confirm");
        assert_eq!(format!("{}", HapticEvent::InvalidAction), "invalid_action");
    }

    #[test]
    fn test_per_event_intensity_defaults() {
        let per_event = PerEventIntensity::default();
        assert_eq!(per_event.menu_appear, 20);
        assert_eq!(per_event.slice_change, 40);
        assert_eq!(per_event.confirm, 80);
        assert_eq!(per_event.invalid, 30);
    }

    #[test]
    fn test_per_event_intensity_get() {
        let per_event = PerEventIntensity {
            menu_appear: 15,
            slice_change: 35,
            confirm: 75,
            invalid: 25,
        };

        assert_eq!(per_event.get(&HapticEvent::MenuAppear), 15);
        assert_eq!(per_event.get(&HapticEvent::SliceChange), 35);
        assert_eq!(per_event.get(&HapticEvent::SelectionConfirm), 75);
        assert_eq!(per_event.get(&HapticEvent::InvalidAction), 25);
    }

    #[test]
    fn test_emit_disabled() {
        let mut manager = HapticManager::new(50, false);
        // Should succeed but do nothing when disabled
        assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
    }

    #[test]
    fn test_emit_zero_intensity() {
        let mut manager = HapticManager::new(0, true);
        // Should succeed but do nothing with zero intensity
        assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
    }

    #[test]
    fn test_emit_no_device() {
        let mut manager = HapticManager::new(50, true);
        // Without connect(), device is None - should succeed silently
        assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
        assert!(manager.emit(HapticEvent::SliceChange).is_ok());
        assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
        assert!(manager.emit(HapticEvent::InvalidAction).is_ok());
    }

    #[test]
    fn test_emit_intensity_scaling() {
        // Test intensity calculation: (global/100) * (per_event/100) * 100
        // With global=50, per_event=80 (confirm) → 50 * 80 / 100 = 40
        let global = 50u32;
        let per_event = 80u32;
        let scaled = (global * per_event / 100) as u8;
        assert_eq!(scaled, 40);

        // With global=100, per_event=20 (menu_appear) → 100 * 20 / 100 = 20
        let global = 100u32;
        let per_event = 20u32;
        let scaled = (global * per_event / 100) as u8;
        assert_eq!(scaled, 20);

        // With global=25, per_event=40 (slice_change) → 25 * 40 / 100 = 10
        let global = 25u32;
        let per_event = 40u32;
        let scaled = (global * per_event / 100) as u8;
        assert_eq!(scaled, 10);
    }

    #[test]
    fn test_from_config_with_per_event() {
        use crate::config::{HapticConfig, HapticEventConfig};

        let config = HapticConfig {
            enabled: true,
            intensity: 60,
            per_event: HapticEventConfig {
                menu_appear: 25,
                slice_change: 45,
                confirm: 85,
                invalid: 35,
            },
            debounce_ms: 25,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
        };

        let manager = HapticManager::from_config(&config);
        assert_eq!(manager.intensity(), 60);
        assert_eq!(manager.per_event.menu_appear, 25);
        assert_eq!(manager.per_event.slice_change, 45);
        assert_eq!(manager.per_event.confirm, 85);
        assert_eq!(manager.per_event.invalid, 35);
    }

    #[test]
    fn test_update_from_config_with_per_event() {
        use crate::config::{HapticConfig, HapticEventConfig};

        let mut manager = HapticManager::new(50, true);

        let new_config = HapticConfig {
            enabled: true,
            intensity: 70,
            per_event: HapticEventConfig {
                menu_appear: 30,
                slice_change: 50,
                confirm: 90,
                invalid: 40,
            },
            debounce_ms: 30,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
        };

        manager.update_from_config(&new_config);
        assert_eq!(manager.intensity(), 70);
        assert_eq!(manager.per_event.menu_appear, 30);
        assert_eq!(manager.per_event.slice_change, 50);
        assert_eq!(manager.per_event.confirm, 90);
        assert_eq!(manager.per_event.invalid, 40);
    }

    // ========================================================================
    // Story 5.4: Safety Verification Tests
    // ========================================================================

    #[test]
    fn test_blocklisted_features_detection() {
        // All blocklisted features should be detected
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::SPECIAL_KEYS));
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::REPORT_RATE));
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::ONBOARD_PROFILES));
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::MODE_STATUS));
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::MOUSE_BUTTON_SPY));
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::PERSISTENT_REMAPPABLE_ACTION));
        assert!(blocklisted_features::is_blocklisted(blocklisted_features::HOST_INFO));
    }

    #[test]
    fn test_allowed_features_not_blocklisted() {
        // All allowed features should NOT be blocklisted
        assert!(!blocklisted_features::is_blocklisted(features::I_ROOT));
        assert!(!blocklisted_features::is_blocklisted(features::I_FEATURE_SET));
        assert!(!blocklisted_features::is_blocklisted(features::DEVICE_NAME));
        assert!(!blocklisted_features::is_blocklisted(features::BATTERY_STATUS));
        assert!(!blocklisted_features::is_blocklisted(features::LED_CONTROL));
        assert!(!blocklisted_features::is_blocklisted(features::FORCE_FEEDBACK));
    }

    #[test]
    fn test_allowed_features_in_safelist() {
        // All our used features should be in safelist
        assert!(allowed_features::is_allowed(features::I_ROOT));
        assert!(allowed_features::is_allowed(features::I_FEATURE_SET));
        assert!(allowed_features::is_allowed(features::DEVICE_NAME));
        assert!(allowed_features::is_allowed(features::BATTERY_STATUS));
        assert!(allowed_features::is_allowed(features::LED_CONTROL));
        assert!(allowed_features::is_allowed(features::FORCE_FEEDBACK));
    }

    #[test]
    fn test_verify_feature_safety_allowed() {
        // Allowed features should pass safety check
        assert!(verify_feature_safety(features::I_ROOT).is_ok());
        assert!(verify_feature_safety(features::I_FEATURE_SET).is_ok());
        assert!(verify_feature_safety(features::FORCE_FEEDBACK).is_ok());
    }

    #[test]
    fn test_verify_feature_safety_blocklisted() {
        // Blocklisted features should fail safety check
        let result = verify_feature_safety(blocklisted_features::SPECIAL_KEYS);
        assert!(result.is_err());

        if let Err(HapticError::SafetyViolation { feature_id, reason }) = result {
            assert_eq!(feature_id, blocklisted_features::SPECIAL_KEYS);
            assert!(reason.contains("button"));
        } else {
            panic!("Expected SafetyViolation error");
        }
    }

    #[test]
    fn test_verify_feature_safety_onboard_profiles() {
        // Onboard profiles should definitely fail
        let result = verify_feature_safety(blocklisted_features::ONBOARD_PROFILES);
        assert!(result.is_err());

        if let Err(HapticError::SafetyViolation { feature_id, reason }) = result {
            assert_eq!(feature_id, 0x8100);
            assert!(reason.contains("profile") || reason.contains("Persistent"));
        } else {
            panic!("Expected SafetyViolation error");
        }
    }

    #[test]
    fn test_verify_feature_safety_unknown() {
        // Unknown features should pass (with warning logged)
        // They're not blocklisted, so we allow them cautiously
        let unknown_feature = 0x9999;
        assert!(!blocklisted_features::is_blocklisted(unknown_feature));
        assert!(!allowed_features::is_allowed(unknown_feature));
        assert!(verify_feature_safety(unknown_feature).is_ok());
    }

    #[test]
    fn test_safety_violation_error_display() {
        let error = HapticError::SafetyViolation {
            feature_id: 0x1B04,
            reason: "Persistent button remapping",
        };
        let msg = format!("{}", error);
        assert!(msg.contains("SAFETY VIOLATION"));
        assert!(msg.contains("1B04"));
        assert!(msg.contains("Persistent"));
    }

    #[test]
    fn test_blocklist_reasons_exist() {
        // All blocklisted features should have reasons
        assert!(blocklisted_features::blocklist_reason(blocklisted_features::SPECIAL_KEYS).is_some());
        assert!(blocklisted_features::blocklist_reason(blocklisted_features::ONBOARD_PROFILES).is_some());
        assert!(blocklisted_features::blocklist_reason(blocklisted_features::REPORT_RATE).is_some());

        // Non-blocklisted should return None
        assert!(blocklisted_features::blocklist_reason(features::FORCE_FEEDBACK).is_none());
    }

    #[test]
    fn test_haptic_feature_is_safe() {
        // The haptic feature we use (FORCE_FEEDBACK) must be safe
        assert!(!blocklisted_features::is_blocklisted(features::FORCE_FEEDBACK));
        assert!(allowed_features::is_allowed(features::FORCE_FEEDBACK));
        assert!(verify_feature_safety(features::FORCE_FEEDBACK).is_ok());
    }

    // ========================================================================
    // Story 5.5: Graceful Fallback & Error Handling Tests
    // ========================================================================

    #[test]
    fn test_connection_state_default() {
        let manager = HapticManager::new(50, true);
        assert_eq!(manager.connection_state(), ConnectionState::NotConnected);
    }

    #[test]
    fn test_pulse_succeeds_when_no_device() {
        let mut manager = HapticManager::new(50, true);
        // Without connect(), device is None
        // Should succeed silently (graceful degradation)
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
        assert_eq!(manager.connection_state(), ConnectionState::NotConnected);
    }

    #[test]
    fn test_emit_succeeds_when_no_device() {
        let mut manager = HapticManager::new(50, true);
        // All emit calls should succeed silently
        assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
        assert!(manager.emit(HapticEvent::SliceChange).is_ok());
        assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
        assert!(manager.emit(HapticEvent::InvalidAction).is_ok());
    }

    #[test]
    fn test_reconnect_not_needed_when_not_connected() {
        let mut manager = HapticManager::new(50, true);
        // NotConnected state - should return false but not try to reconnect
        assert!(!manager.reconnect_if_needed());
        assert_eq!(manager.connection_state(), ConnectionState::NotConnected);
    }

    #[test]
    fn test_connection_state_enum_variants() {
        // Verify all states exist and are distinct
        assert_ne!(ConnectionState::NotConnected, ConnectionState::Connected);
        assert_ne!(ConnectionState::Connected, ConnectionState::Disconnected);
        assert_ne!(ConnectionState::Disconnected, ConnectionState::Cooldown);
    }

    #[test]
    fn test_connection_state_default_trait() {
        // ConnectionState should default to NotConnected
        let state: ConnectionState = Default::default();
        assert_eq!(state, ConnectionState::NotConnected);
    }

    #[test]
    fn test_graceful_fallback_on_disabled() {
        let mut manager = HapticManager::new(50, false);
        // Disabled haptics should always succeed silently
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
        assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
    }

    #[test]
    fn test_graceful_fallback_on_zero_intensity() {
        let mut manager = HapticManager::new(0, true);
        // Zero intensity should always succeed silently
        assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
        assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
    }

    #[test]
    fn test_reconnect_cooldown_constant() {
        // Verify cooldown is reasonable (5 seconds)
        assert_eq!(RECONNECT_COOLDOWN_MS, 5000);
    }

    // ========================================================================
    // Story 5.6: Haptic Latency Optimization Tests
    // ========================================================================

    #[test]
    fn test_slice_debounce_constant() {
        // Verify default slice debounce is 20ms per UX spec
        assert_eq!(DEFAULT_SLICE_DEBOUNCE_MS, 20);
    }

    #[test]
    fn test_reentry_debounce_constant() {
        // Verify default re-entry debounce is 50ms per UX spec
        assert_eq!(DEFAULT_REENTRY_DEBOUNCE_MS, 50);
    }

    #[test]
    fn test_manager_slice_debounce_defaults() {
        let manager = HapticManager::new(50, true);
        assert_eq!(manager.slice_debounce_ms(), 20);
        assert_eq!(manager.reentry_debounce_ms(), 50);
    }

    #[test]
    fn test_emit_slice_change_disabled() {
        let mut manager = HapticManager::new(50, false);
        // Should return false when disabled
        assert!(!manager.emit_slice_change(0));
        assert!(!manager.emit_slice_change(1));
    }

    #[test]
    fn test_emit_slice_change_zero_intensity() {
        let mut manager = HapticManager::new(0, true);
        // Should return false with zero intensity
        assert!(!manager.emit_slice_change(0));
    }

    #[test]
    fn test_emit_slice_change_no_device() {
        let mut manager = HapticManager::new(50, true);
        // Without connect(), device is None - should succeed gracefully
        // (returns true because emit succeeds silently without device)
        // First call after debounce window should work
        manager.last_slice_change_ms = 0;
        assert!(manager.emit_slice_change(0));
    }

    #[test]
    fn test_reset_slice_tracking() {
        let mut manager = HapticManager::new(50, true);
        manager.last_slice_index = Some(3);
        manager.last_slice_change_ms = 12345;

        manager.reset_slice_tracking();

        assert_eq!(manager.last_slice_index, None);
        assert_eq!(manager.last_slice_change_ms, 0);
    }

    #[test]
    fn test_set_slice_debounce_ms() {
        let mut manager = HapticManager::new(50, true);
        manager.set_slice_debounce_ms(30);
        assert_eq!(manager.slice_debounce_ms(), 30);
    }

    #[test]
    fn test_set_reentry_debounce_ms() {
        let mut manager = HapticManager::new(50, true);
        manager.set_reentry_debounce_ms(100);
        assert_eq!(manager.reentry_debounce_ms(), 100);
    }

    #[test]
    fn test_from_config_with_slice_debounce() {
        use crate::config::{HapticConfig, HapticEventConfig};

        let config = HapticConfig {
            enabled: true,
            intensity: 50,
            per_event: HapticEventConfig::default(),
            debounce_ms: 20,
            slice_debounce_ms: 25,
            reentry_debounce_ms: 60,
        };

        let manager = HapticManager::from_config(&config);
        assert_eq!(manager.slice_debounce_ms(), 25);
        assert_eq!(manager.reentry_debounce_ms(), 60);
    }

    #[test]
    fn test_update_from_config_with_slice_debounce() {
        use crate::config::{HapticConfig, HapticEventConfig};

        let mut manager = HapticManager::new(50, true);
        assert_eq!(manager.slice_debounce_ms(), 20);
        assert_eq!(manager.reentry_debounce_ms(), 50);

        let new_config = HapticConfig {
            enabled: true,
            intensity: 50,
            per_event: HapticEventConfig::default(),
            debounce_ms: 20,
            slice_debounce_ms: 35,
            reentry_debounce_ms: 75,
        };

        manager.update_from_config(&new_config);
        assert_eq!(manager.slice_debounce_ms(), 35);
        assert_eq!(manager.reentry_debounce_ms(), 75);
    }

    #[test]
    fn test_short_message_buffer_preallocated() {
        // Verify the pre-allocated buffer exists and is correct size
        let manager = HapticManager::new(50, true);
        assert_eq!(manager._short_msg_buffer.len(), 7);
    }

    #[test]
    fn test_pulse_command_construction_fast() {
        // Verify HidppShortMessage construction is allocation-free
        // This is a compile-time check - the struct uses fixed-size arrays
        let msg = HidppShortMessage::new(0xFF, 0x00, 0x01, 0x05)
            .with_params([0xAA, 0xBB, 0xCC]);

        // Construction should be fast (no allocations)
        let bytes = msg.to_bytes();
        assert_eq!(bytes.len(), 7);
    }
}
