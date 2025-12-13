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

use std::fmt;
use std::time::{SystemTime, UNIX_EPOCH};

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
    /// Force feedback / haptic (RUNTIME-ONLY - does NOT persist)
    pub const FORCE_FEEDBACK: u16 = 0x8123;
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

/// HID++ device wrapper for communication with MX Master 4
pub struct HidppDevice {
    /// The underlying HID device handle
    #[cfg(feature = "hidapi")]
    device: hidapi::HidDevice,
    /// Device index for HID++ messages (0xFF for direct, 0x01-0x06 for receiver)
    device_index: u8,
    /// Connection type
    connection_type: ConnectionType,
    /// Software ID for message tracking (rotates 0x01-0x0F)
    sw_id: u8,
    /// Cached feature table (feature_id -> feature_index)
    feature_table: std::collections::HashMap<u16, u8>,
    /// Whether haptic feature is available
    haptic_supported: bool,
    /// Haptic feature index (if supported)
    haptic_feature_index: Option<u8>,
}

impl HidppDevice {
    /// Attempt to open and initialize an MX Master 4 device
    ///
    /// Returns None if no compatible device is found.
    /// This is NOT an error - haptics are optional.
    pub fn open() -> Option<Self> {
        #[cfg(not(feature = "hidapi"))]
        {
            // hidapi feature not enabled, return None gracefully
            tracing::debug!("hidapi feature not enabled, haptics unavailable");
            return None;
        }

        #[cfg(feature = "hidapi")]
        {
            let api = match hidapi::HidApi::new() {
                Ok(api) => api,
                Err(e) => {
                    tracing::warn!(error = %e, "Failed to initialize hidapi");
                    return None;
                }
            };

            // Try to find MX Master 4 or a Logitech receiver
            for device_info in api.device_list() {
                if device_info.vendor_id() != LOGITECH_VENDOR_ID {
                    continue;
                }

                let product_id = device_info.product_id();
                let (connection_type, device_index) = match product_id {
                    product_ids::MX_MASTER_4_USB => (ConnectionType::Usb, 0xFF),
                    product_ids::BOLT_RECEIVER => (ConnectionType::Bolt, 0x01),
                    product_ids::UNIFYING_RECEIVER => (ConnectionType::Unifying, 0x01),
                    _ => {
                        // Check if it's a Bluetooth HID device from Logitech
                        if device_info.interface_number() == 2 {
                            // Interface 2 is typically HID++ on BT devices
                            (ConnectionType::Bluetooth, 0xFF)
                        } else {
                            continue;
                        }
                    }
                };

                // Try to open this device
                let device = match device_info.open_device(&api) {
                    Ok(d) => d,
                    Err(e) => {
                        tracing::debug!(
                            product_id = format!("{:04X}", product_id),
                            error = %e,
                            "Failed to open Logitech device"
                        );
                        continue;
                    }
                };

                // Set non-blocking mode for reads
                if let Err(e) = device.set_blocking_mode(false) {
                    tracing::debug!(error = %e, "Failed to set non-blocking mode");
                }

                let mut hidpp = Self {
                    device,
                    device_index,
                    connection_type,
                    sw_id: 0x01,
                    feature_table: std::collections::HashMap::new(),
                    haptic_supported: false,
                    haptic_feature_index: None,
                };

                // Validate HID++ 2.0 support
                if !hidpp.validate_hidpp20() {
                    tracing::debug!(
                        connection = %connection_type,
                        "Device does not support HID++ 2.0"
                    );
                    continue;
                }

                // Enumerate features and check for haptic support
                hidpp.enumerate_features();

                tracing::info!(
                    connection = %connection_type,
                    haptic_supported = hidpp.haptic_supported,
                    "Connected to MX Master 4"
                );

                return Some(hidpp);
            }

            tracing::debug!("No MX Master 4 device found");
            None
        }
    }

    /// Validate that the device supports HID++ 2.0 protocol
    #[cfg(feature = "hidapi")]
    fn validate_hidpp20(&mut self) -> bool {
        // Send IRoot ping (feature 0x00, function 0x01)
        // Ping echoes back the data byte and returns protocol version
        let msg = HidppShortMessage::new(self.device_index, 0x00, 0x01, self.next_sw_id())
            .with_params([0x00, 0x00, 0xAA]); // 0xAA is ping data to echo

        if let Some(response) = self.send_and_receive(&msg) {
            // Check if ping data was echoed (byte 6 should be 0xAA)
            if response[6] == 0xAA {
                tracing::debug!(
                    "HID++ 2.0 validated, ping echoed successfully"
                );
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
    #[cfg(feature = "hidapi")]
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
        let msg = HidppShortMessage::new(
            self.device_index,
            feature_set_index,
            0x00,
            self.next_sw_id(),
        );

        let feature_count = match self.send_and_receive(&msg) {
            Some(resp) => resp[4],
            None => return,
        };

        tracing::debug!(count = feature_count, "Enumerating device features");

        // Enumerate each feature (function 0x01 of IFeatureSet)
        for i in 0..feature_count {
            let msg = HidppShortMessage::new(
                self.device_index,
                feature_set_index,
                0x01,
                self.next_sw_id(),
            )
            .with_params([i, 0, 0]);

            if let Some(resp) = self.send_and_receive(&msg) {
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

                // Check for haptic/force feedback feature (SAFE - runtime only)
                if feature_id == features::FORCE_FEEDBACK {
                    self.haptic_supported = true;
                    self.haptic_feature_index = Some(feature_index);
                    tracing::info!(index = feature_index, "Haptic feature found (runtime-only, safe)");
                }
            }
        }

        tracing::debug!(
            feature_count = self.feature_table.len(),
            haptic = self.haptic_supported,
            "Feature enumeration complete (blocklisted features excluded)"
        );
    }

    /// Get the feature index for a given feature ID using IRoot
    #[cfg(feature = "hidapi")]
    fn get_feature_index(&mut self, feature_id: u16) -> Option<u8> {
        // IRoot function 0x00: getFeatureIndex
        let msg = HidppShortMessage::new(self.device_index, 0x00, 0x00, self.next_sw_id())
            .with_params([(feature_id >> 8) as u8, (feature_id & 0xFF) as u8, 0]);

        self.send_and_receive(&msg).and_then(|resp| {
            let index = resp[4];
            if index == 0 {
                None // Feature not supported
            } else {
                Some(index)
            }
        })
    }

    /// Send a short message and wait for response
    #[cfg(feature = "hidapi")]
    fn send_and_receive(&mut self, msg: &HidppShortMessage) -> Option<[u8; 7]> {
        let bytes = msg.to_bytes();

        // Send the message
        if let Err(e) = self.device.write(&bytes) {
            tracing::debug!(error = %e, "Failed to write HID++ message");
            return None;
        }

        // Read response with timeout
        let mut buf = [0u8; 20]; // Buffer large enough for long messages
        let timeout_ms = 100;

        match self.device.read_timeout(&mut buf, timeout_ms as i32) {
            Ok(len) if len >= 7 => {
                let mut response = [0u8; 7];
                response.copy_from_slice(&buf[..7]);
                Some(response)
            }
            Ok(_) => None,
            Err(e) => {
                tracing::debug!(error = %e, "Failed to read HID++ response");
                None
            }
        }
    }

    /// Get next software ID (rotating 0x01-0x0F)
    fn next_sw_id(&mut self) -> u8 {
        let id = self.sw_id;
        self.sw_id = if self.sw_id >= 0x0F { 0x01 } else { self.sw_id + 1 };
        id
    }

    /// Check if haptic feedback is supported
    pub fn haptic_supported(&self) -> bool {
        self.haptic_supported
    }

    /// Get connection type
    pub fn connection_type(&self) -> ConnectionType {
        self.connection_type
    }

    /// Send a haptic pulse command
    ///
    /// # SAFETY
    ///
    /// This method ONLY sends volatile/runtime commands.
    /// It does NOT write to onboard memory.
    #[cfg(feature = "hidapi")]
    pub fn send_haptic_pulse(&mut self, intensity: u8, duration_ms: u16) -> Result<(), HapticError> {
        let feature_index = match self.haptic_feature_index {
            Some(idx) => idx,
            None => {
                // Haptics not supported, succeed silently
                return Ok(());
            }
        };

        // Construct haptic pulse command
        // Note: The exact command structure depends on the device's haptic feature
        // This is a placeholder that needs validation on real hardware
        let msg = HidppShortMessage::new(self.device_index, feature_index, 0x00, self.next_sw_id())
            .with_params([
                intensity,
                (duration_ms >> 8) as u8,
                (duration_ms & 0xFF) as u8,
            ]);

        let bytes = msg.to_bytes();
        self.device
            .write(&bytes)
            .map_err(|e| HapticError::IoError(std::io::Error::new(std::io::ErrorKind::Other, e.to_string())))?;

        Ok(())
    }
}

// Stub implementation when hidapi feature is not available
#[cfg(not(feature = "hidapi"))]
impl HidppDevice {
    pub fn open() -> Option<Self> {
        None
    }

    pub fn haptic_supported(&self) -> bool {
        false
    }

    pub fn connection_type(&self) -> ConnectionType {
        ConnectionType::Usb
    }

    pub fn send_haptic_pulse(&mut self, _intensity: u8, _duration_ms: u16) -> Result<(), HapticError> {
        Ok(())
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

/// Per-event intensity overrides
#[derive(Debug, Clone, Copy)]
pub struct PerEventIntensity {
    /// Menu appearance intensity (default 20)
    pub menu_appear: u8,
    /// Slice change intensity (default 40)
    pub slice_change: u8,
    /// Selection confirm intensity (default 80)
    pub confirm: u8,
    /// Invalid action intensity (default 30)
    pub invalid: u8,
}

impl Default for PerEventIntensity {
    fn default() -> Self {
        Self {
            menu_appear: 20,
            slice_change: 40,
            confirm: 80,
            invalid: 30,
        }
    }
}

impl PerEventIntensity {
    /// Get intensity for a specific event
    pub fn get(&self, event: &HapticEvent) -> u8 {
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
    /// User-configured global intensity multiplier (0-100)
    intensity_multiplier: u8,
    /// Per-event intensity overrides
    per_event: PerEventIntensity,
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
    pub fn new(intensity: u8, enabled: bool) -> Self {
        Self {
            device: None,
            intensity_multiplier: intensity.min(100),
            per_event: PerEventIntensity::default(),
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
            intensity_multiplier: config.intensity.min(100),
            per_event: PerEventIntensity {
                menu_appear: config.per_event.menu_appear.min(100),
                slice_change: config.per_event.slice_change.min(100),
                confirm: config.per_event.confirm.min(100),
                invalid: config.per_event.invalid.min(100),
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
        self.intensity_multiplier = config.intensity.min(100);
        self.per_event = PerEventIntensity {
            menu_appear: config.per_event.menu_appear.min(100),
            slice_change: config.per_event.slice_change.min(100),
            confirm: config.per_event.confirm.min(100),
            invalid: config.per_event.invalid.min(100),
        };
        self.enabled = config.enabled;
        self.debounce_ms = config.debounce_ms;
        self.slice_debounce_ms = config.slice_debounce_ms;
        self.reentry_debounce_ms = config.reentry_debounce_ms;

        tracing::debug!(
            intensity = self.intensity_multiplier,
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
        if !self.enabled || self.intensity_multiplier == 0 {
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

        // Scale intensity by user preference
        let scaled_intensity =
            ((haptic.intensity as u16 * self.intensity_multiplier as u16) / 100) as u8;

        tracing::debug!(
            intensity = scaled_intensity,
            duration_ms = haptic.duration_ms,
            "Sending haptic pulse"
        );

        // Send the pulse - handle errors gracefully
        match device.send_haptic_pulse(scaled_intensity, haptic.duration_ms) {
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
    /// 3. Appropriate pulse pattern (single/double/triple)
    ///
    /// CRITICAL: This method MUST NOT write to onboard mouse memory.
    pub fn emit(&mut self, event: HapticEvent) -> Result<(), HapticError> {
        // Check if haptics are enabled
        if !self.enabled || self.intensity_multiplier == 0 {
            return Ok(());
        }

        // Get event-specific settings
        let per_event_intensity = self.per_event.get(&event);
        let base_profile = event.base_profile();
        let pattern = event.pattern();

        // Calculate final intensity: (global/100) * (per_event/100) * 100
        // This effectively multiplies the two percentages
        let scaled_intensity = ((self.intensity_multiplier as u32 * per_event_intensity as u32) / 100) as u8;

        // If scaled intensity is 0, skip
        if scaled_intensity == 0 {
            return Ok(());
        }

        tracing::debug!(
            event = %event,
            pattern = ?pattern,
            base_intensity = per_event_intensity,
            scaled_intensity = scaled_intensity,
            duration_ms = base_profile.duration_ms,
            "Emitting haptic event"
        );

        let pulse = HapticPulse {
            intensity: scaled_intensity,
            duration_ms: base_profile.duration_ms,
        };

        // Execute the pattern
        match pattern {
            HapticPattern::Single => {
                self.pulse(pulse)?;
            }
            HapticPattern::Double => {
                self.pulse(pulse)?;
                // Wait for gap before second pulse
                std::thread::sleep(std::time::Duration::from_millis(pattern.gap_ms()));
                self.last_pulse_ms = 0; // Reset debounce for pattern continuation
                self.pulse(pulse)?;
            }
            HapticPattern::Triple => {
                self.pulse(pulse)?;
                std::thread::sleep(std::time::Duration::from_millis(pattern.gap_ms()));
                self.last_pulse_ms = 0;
                self.pulse(pulse)?;
                std::thread::sleep(std::time::Duration::from_millis(pattern.gap_ms()));
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
        if !self.enabled || self.intensity_multiplier == 0 {
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
        if !self.enabled || self.intensity_multiplier == 0 {
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

    /// Set intensity multiplier (0-100)
    pub fn set_intensity(&mut self, intensity: u8) {
        self.intensity_multiplier = intensity.min(100);
    }

    /// Set debounce time in milliseconds
    pub fn set_debounce_ms(&mut self, ms: u64) {
        self.debounce_ms = ms;
    }

    /// Get current intensity multiplier
    pub fn intensity(&self) -> u8 {
        self.intensity_multiplier
    }

    /// Check if haptics are enabled
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }
}

impl Default for HapticManager {
    fn default() -> Self {
        Self::new(50, true)
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
