//! HID++ device communication
//!
//! Low-level HidppDevice for direct hidraw access to MX Master 4.
//! Handles device discovery, HID++ 2.0 protocol, feature enumeration,
//! button divert, haptics, DPI, SmartShift, battery, and Easy-Switch.

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

use super::constants::{blocklisted_features, features, report_type};
use super::error::HapticError;
use super::messages::ConnectionType;
use super::patterns::Mx4HapticPattern;

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
    /// Whether SmartShift feature is available (0x2110)
    smartshift_supported: bool,
    /// SmartShift feature index (0x2110)
    smartshift_feature_index: Option<u8>,
    /// Whether unified battery feature is available (0x1004)
    battery_supported: bool,
    /// Battery feature index (0x1004 or 0x1000)
    battery_feature_index: Option<u8>,
    /// Whether using UNIFIED_BATTERY (true) or BATTERY_STATUS (false)
    is_unified_battery: bool,
    /// Whether REPROG_CONTROLS_V4 feature is available (0x1B04)
    reprog_controls_supported: bool,
    /// REPROG_CONTROLS_V4 feature index (0x1B04) - for button divert
    reprog_controls_feature_index: Option<u8>,
    /// Path to the hidraw device we connected to
    device_path: PathBuf,
}

impl HidppDevice {
    /// Find a Logitech hidraw device suitable for HID++ communication
    ///
    /// Scans /sys/class/hidraw/ for Logitech devices and returns ALL candidates
    /// for HID++ communication (prefers interface 2).
    fn find_all_devices() -> Vec<(PathBuf, ConnectionType)> {
        let hidraw_dir = PathBuf::from("/sys/class/hidraw");
        if !hidraw_dir.exists() {
            tracing::debug!("/sys/class/hidraw not found");
            return Vec::new();
        }

        let mut candidates: Vec<(PathBuf, String, ConnectionType)> = Vec::new();

        let entries = match std::fs::read_dir(&hidraw_dir) {
            Ok(e) => e,
            Err(e) => {
                tracing::debug!(error = %e, "Failed to read /sys/class/hidraw");
                return Vec::new();
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

        // Sort: interface 2 devices first (preferred for HID++)
        candidates.sort_by(|a, b| {
            let a_is_input2 = a.1.contains("input2");
            let b_is_input2 = b.1.contains("input2");
            b_is_input2.cmp(&a_is_input2)
        });

        // Log all candidates
        for (dev_path, uevent, conn_type) in &candidates {
            let is_input2 = uevent.contains("input2");
            tracing::debug!(
                path = %dev_path.display(),
                connection = %conn_type,
                is_input2,
                "Found Logitech HID++ candidate"
            );
        }

        candidates.into_iter().map(|(path, _, conn_type)| (path, conn_type)).collect()
    }

    /// Attempt to open and initialize an MX Master 4 device
    ///
    /// Returns None if no compatible device is found.
    /// This is NOT an error - haptics are optional.
    ///
    /// Uses direct hidraw access instead of hidapi for more reliable
    /// device communication (same approach as the battery module).
    ///
    /// Tries ALL candidate devices until one validates HID++ 2.0.
    /// This handles setups with multiple Logitech receivers (e.g., MX Master 4
    /// on one Bolt receiver, Keys S on another).
    pub fn open() -> Option<Self> {
        let candidates = Self::find_all_devices();

        if candidates.is_empty() {
            tracing::debug!("No Logitech HID++ devices found");
            return None;
        }

        tracing::debug!(count = candidates.len(), "Trying HID++ device candidates");

        for (device_path, connection_type) in candidates {
            // Determine device indices to try based on connection type
            // Bolt receivers can have the mouse on any slot (1-6), so try them all
            let indices_to_try: Vec<u8> = match connection_type {
                ConnectionType::Usb => vec![0xFF],
                ConnectionType::Bolt => vec![0x01, 0x02, 0x03, 0x04, 0x05, 0x06],
                ConnectionType::Unifying => vec![0x01, 0x02, 0x03, 0x04, 0x05, 0x06],
                ConnectionType::Bluetooth => vec![0xFF],
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
                    continue; // Try next candidate
                }
            };

            for device_index in &indices_to_try {
                // Clone the file handle for each index attempt (reuse same fd)
                let device_clone = match device.try_clone() {
                    Ok(d) => d,
                    Err(_) => continue,
                };

                let mut hidpp = Self {
                    device: device_clone,
                    device_index: *device_index,
                    connection_type,
                    feature_table: std::collections::HashMap::new(),
                    haptic_supported: false,
                    haptic_feature_index: None,
                    mx4_haptic_supported: false,
                    mx4_haptic_feature_index: None,
                    dpi_supported: false,
                    dpi_feature_index: None,
                    smartshift_supported: false,
                    smartshift_feature_index: None,
                    battery_supported: false,
                    battery_feature_index: None,
                    is_unified_battery: false,
                    reprog_controls_supported: false,
                    reprog_controls_feature_index: None,
                    device_path: device_path.clone(),
                };

                // Try HID++ validation with retry for sleeping devices
                // First attempt may fail if device is in deep sleep; second attempt
                // gives it time to wake up after the first ping
                let validated = hidpp.validate_hidpp20() || {
                    tracing::debug!(
                        path = %device_path.display(),
                        device_index,
                        "First HID++ ping failed, retrying after wake-up delay"
                    );
                    std::thread::sleep(std::time::Duration::from_millis(500));
                    hidpp.validate_hidpp20()
                };

                if !validated {
                    tracing::debug!(
                        path = %device_path.display(),
                        device_index,
                        connection = %connection_type,
                        "Device index does not support HID++ 2.0"
                    );
                    continue; // Try next device index
                }

                // Enumerate features and check for haptic support
                hidpp.enumerate_features();

                // Skip devices that aren't the MX Master 4
                // The MX Master 4 has feature 0x19B0 (haptic) or 0x1B04 (reprog controls)
                // This prevents connecting to a Keys MX S keyboard on another Bolt receiver
                if !hidpp.mx4_haptic_supported && !hidpp.reprog_controls_supported {
                    tracing::debug!(
                        path = %device_path.display(),
                        device_index,
                        "Device is HID++ 2.0 but not MX Master 4 (no haptic/reprog), trying next"
                    );
                    continue;
                }

                tracing::info!(
                    path = %device_path.display(),
                    device_index,
                    connection = %connection_type,
                    haptic_supported = hidpp.haptic_supported,
                    mx4_haptic_supported = hidpp.mx4_haptic_supported,
                    reprog_controls = hidpp.reprog_controls_supported,
                    "Connected to MX Master 4 via hidraw"
                );

                return Some(hidpp);
            }
        }

        tracing::debug!("No valid HID++ 2.0 device found among candidates");
        None
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

    /// Send a long HID++ message (20 bytes) - fire and forget
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

    /// Send a long HID++ request (20 bytes) and wait for response
    ///
    /// Used for commands that need more than 3 parameter bytes
    /// (e.g. setCidReporting which needs 5 bytes).
    fn hidpp_long_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>> {
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

        tracing::debug!(
            feature_index,
            function,
            "Sending HID++ long request: {:02X?}",
            &request
        );

        // Send request
        if let Err(e) = self.device.write_all(&request) {
            tracing::debug!(error = %e, "Failed to write HID++ long message");
            return None;
        }

        // Read response with timeout (same as hidpp_request)
        let mut response = [0u8; 20];
        let mut attempts = 0;

        loop {
            match self.device.read(&mut response) {
                Ok(len) if len >= 7 => {
                    let resp_function = (response[3] >> 4) & 0x0F;
                    let resp_sw_id = response[3] & 0x0F;

                    // Check for matching response
                    if (response[0] == report_type::SHORT || response[0] == report_type::LONG)
                        && response[1] == self.device_index
                        && response[2] == feature_index
                        && resp_function == function
                        && resp_sw_id == SOFTWARE_ID
                    {
                        tracing::debug!("HID++ long request matched: {:02X?}", &response[..len]);
                        return Some(response[..len].to_vec());
                    }

                    // Check for error response
                    if response[2] == 0xFF {
                        let error_code = response[5];
                        tracing::warn!(
                            error_code,
                            "HID++ error response to long request: {:02X?}",
                            &response[..len]
                        );
                        return None;
                    }
                }
                Ok(_) => {}
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                Err(e) => {
                    tracing::debug!(error = %e, "Error reading HID++ long response");
                    return None;
                }
            }

            attempts += 1;
            if attempts > 100 {
                tracing::debug!(feature_index, function, "HID++ long request timeout");
                return None;
            }

            std::thread::sleep(std::time::Duration::from_millis(10));
        }
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
                let feature_index = i; // Feature indices are 0-based (slot = index)

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

                // Check for HiResScroll feature (0x2111) - MX Master 3/4 SmartShift control
                if feature_id == features::HIRES_SCROLL {
                    self.smartshift_supported = true;
                    self.smartshift_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "HiResScroll feature found (0x2111) - SmartShift control available"
                    );
                }

                // Also check for legacy SmartShift feature (0x2110) for older mice
                if feature_id == features::SMARTSHIFT_LEGACY {
                    // Only set if not already detected via HiResScroll
                    if !self.smartshift_supported {
                        self.smartshift_supported = true;
                        self.smartshift_feature_index = Some(feature_index);
                        tracing::info!(
                            index = feature_index,
                            "Legacy SmartShift feature found (0x2110)"
                        );
                    }
                }

                // Check for UNIFIED_BATTERY feature (0x1004) - preferred for MX Master 4
                if feature_id == features::UNIFIED_BATTERY {
                    self.battery_supported = true;
                    self.battery_feature_index = Some(feature_index);
                    self.is_unified_battery = true;
                    tracing::info!(
                        index = feature_index,
                        "Unified Battery feature found (0x1004)"
                    );
                }

                // Check for BATTERY_STATUS feature (0x1000) - fallback for older devices
                if feature_id == features::BATTERY_STATUS && !self.battery_supported {
                    self.battery_supported = true;
                    self.battery_feature_index = Some(feature_index);
                    self.is_unified_battery = false;
                    tracing::info!(
                        index = feature_index,
                        "Battery Status feature found (0x1000)"
                    );
                }

                // Check for REPROG_CONTROLS_V4 feature (0x1B04) - button divert
                if feature_id == features::REPROG_CONTROLS_V4 {
                    self.reprog_controls_supported = true;
                    self.reprog_controls_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "REPROG_CONTROLS_V4 feature found (0x1B04) - button divert available"
                    );
                }
            }
        }

        tracing::debug!(
            feature_count = self.feature_table.len(),
            legacy_haptic = self.haptic_supported,
            mx4_haptic = self.mx4_haptic_supported,
            dpi = self.dpi_supported,
            smartshift = self.smartshift_supported,
            battery = self.battery_supported,
            reprog_controls = self.reprog_controls_supported,
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

    // =========================================================================
    // Button Divert (REPROG_CONTROLS_V4)
    // =========================================================================

    /// Divert gesture buttons via REPROG_CONTROLS_V4 (0x1B04)
    ///
    /// Tells the mouse to send button presses as HID++ notifications
    /// instead of standard HID reports. This is how we receive the
    /// haptic/gesture thumb button press without logid.
    ///
    /// # SAFETY
    ///
    /// The divert command (setCidReporting function 3) is VOLATILE.
    /// It resets on mouse disconnect or host switch. It does NOT
    /// persist to onboard memory.
    ///
    /// # Target CIDs
    ///
    /// - 0x00C3 (195): Gesture button (thumb button on MX Master 4)
    /// - 0x01A0 (416): Haptic button (if present as separate control)
    pub fn divert_buttons(&mut self) -> Result<u8, HapticError> {
        let feature_index = match self.reprog_controls_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("REPROG_CONTROLS_V4 not available, cannot divert buttons");
                return Ok(0);
            }
        };

        tracing::info!(feature_index, "Diverting gesture buttons via REPROG_CONTROLS_V4");

        // Function 0: getCount() - get number of remappable controls
        let count = match self.hidpp_request(feature_index, 0x00, &[]) {
            Some(resp) if resp.len() >= 5 => resp[4],
            _ => {
                tracing::warn!("Failed to get control count from REPROG_CONTROLS_V4");
                return Ok(0);
            }
        };

        tracing::debug!(count, "Device has remappable controls");

        // Target CIDs to divert
        const GESTURE_BUTTON_CID: u16 = 0x00C3; // 195
        const HAPTIC_BUTTON_CID: u16 = 0x01A0;  // 416

        let mut diverted = 0u8;

        // Function 1: getCidInfo(index) - enumerate controls to find our targets
        for i in 0..count {
            let resp = match self.hidpp_request(feature_index, 0x01, &[i, 0, 0]) {
                Some(r) if r.len() >= 9 => r,
                _ => continue,
            };

            // getCidInfo response format (long report):
            // Byte 4-5: CID (big endian)
            // Byte 6-7: Task ID
            // Byte 8: flags (bit 0 = mouse btn, bit 1 = fKey, bit 2 = hotKey,
            //          bit 3 = fnToggle, bit 4 = reprogrammable, bit 5 = divertable)
            let cid = ((resp[4] as u16) << 8) | (resp[5] as u16);
            let flags = resp[8];
            let divertable = (flags & 0x20) != 0;

            tracing::debug!(
                index = i,
                cid = format!("0x{:04X}", cid),
                flags = format!("0x{:02X}", flags),
                divertable,
                "Control info"
            );

            // Check if this is one of our target buttons AND it's divertable
            if (cid == GESTURE_BUTTON_CID || cid == HAPTIC_BUTTON_CID) && divertable {
                tracing::info!(
                    cid = format!("0x{:04X}", cid),
                    "Diverting button"
                );

                // Function 3: setCidReporting - MUST use long report (5 param bytes)
                //
                // Flag byte uses "change gate" pattern from HID++ 2.0 spec:
                //   bit 0: TemporaryDiverted     (0x01) - enable volatile divert
                //   bit 1: ChangeTemporaryDivert (0x02) - MUST set to apply bit 0
                //   bit 2: PersistentlyDiverted  (0x04) - DO NOT USE
                //   bit 3: ChangePersistentDivert(0x08) - DO NOT USE
                //   bit 4: RawXYDiverted         (0x10) - divert raw XY movement
                //   bit 5: ChangeRawXYDivert     (0x20) - MUST set to apply bit 4
                //
                // We set divert + change gate = 0x03. No persist, no rawXY.
                let divert_flags: u8 = 0x03; // TemporaryDiverted | ChangeTemporaryDivert
                let params: &[u8] = &[
                    (cid >> 8) as u8,   // CID high byte
                    (cid & 0xFF) as u8, // CID low byte
                    divert_flags,       // 0x03: divert=true with change gate
                    0x00,               // remap target CID high (0 = no remap)
                    0x00,               // remap target CID low  (0 = no remap)
                ];

                match self.hidpp_long_request(feature_index, 0x03, params) {
                    Some(resp) => {
                        tracing::info!(
                            cid = format!("0x{:04X}", cid),
                            response = format!("{:02X?}", &resp[4..resp.len().min(9)]),
                            "Button diverted successfully"
                        );
                        diverted += 1;
                    }
                    None => {
                        tracing::warn!(
                            cid = format!("0x{:04X}", cid),
                            "Failed to divert button (setCidReporting returned no response)"
                        );
                    }
                }
            }
        }

        if diverted > 0 {
            tracing::info!(count = diverted, "Gesture buttons diverted - HID++ notifications enabled");
        } else {
            tracing::warn!("No gesture buttons found to divert. Button detection may not work.");
        }

        Ok(diverted)
    }

    // =========================================================================
    // Public Accessors
    // =========================================================================

    /// Check if REPROG_CONTROLS_V4 is available for button divert
    pub fn reprog_controls_supported(&self) -> bool {
        self.reprog_controls_supported
    }

    /// Get the hidraw device path this device is connected to
    pub fn device_path(&self) -> &std::path::Path {
        &self.device_path
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

    // =========================================================================
    // Haptic Methods
    // =========================================================================

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

    // =========================================================================
    // SmartShift Methods (0x2110/0x2111)
    // =========================================================================

    /// Check if SmartShift is supported
    pub fn smartshift_supported(&self) -> bool {
        self.smartshift_supported
    }

    /// Get SmartShift configuration
    ///
    /// Returns the current SmartShift wheel mode and auto-disengage threshold.
    ///
    /// # Returns
    /// Some((wheel_mode, auto_disengage, auto_disengage_default)) where:
    /// - wheel_mode: 1 = Freespin, 2 = Ratchet
    /// - auto_disengage: Threshold for automatic ratchet disengagement (1-254 = N/4 turns/sec, 255 = always engaged)
    /// - auto_disengage_default: Default threshold stored in device
    /// None if SmartShift is not supported
    pub fn get_smartshift(&mut self) -> Option<(u8, u8, u8)> {
        let feature_index = self.smartshift_feature_index?;

        tracing::debug!(feature_index, "Getting SmartShift config from device");

        // Function [0] getRatchetControlMode() -> wheelMode, autoDisengage, autoDisengageDefault
        let params = [0x00, 0x00, 0x00];

        self.hidpp_request(feature_index, 0x00, &params).and_then(|resp| {
            if resp.len() >= 7 {
                // Response: [report_type, device_idx, feature_idx, fn_sw_id, wheel_mode, auto_disengage, auto_disengage_default, ...]
                let wheel_mode = resp[4];
                let auto_disengage = resp[5];
                let auto_disengage_default = resp[6];

                tracing::debug!(
                    wheel_mode,
                    auto_disengage,
                    auto_disengage_default,
                    "Got SmartShift config"
                );
                Some((wheel_mode, auto_disengage, auto_disengage_default))
            } else {
                tracing::warn!("Invalid getRatchetControlMode response length: {}", resp.len());
                None
            }
        })
    }

    /// Set SmartShift configuration
    ///
    /// Configures the wheel mode and auto-disengage threshold.
    ///
    /// # Arguments
    /// * `wheel_mode` - 0 = no change, 1 = Freespin, 2 = Ratchet
    /// * `auto_disengage` - 0 = no change, 1-254 = N/4 turns/sec threshold, 255 = always engaged
    /// * `auto_disengage_default` - 0 = no change, 1-254 = default threshold, 255 = always engaged
    ///
    /// # Returns
    /// Ok(()) on success, error on failure
    pub fn set_smartshift(
        &mut self,
        wheel_mode: u8,
        auto_disengage: u8,
        auto_disengage_default: u8,
    ) -> Result<(), HapticError> {
        let feature_index = match self.smartshift_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("SmartShift not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        tracing::info!(
            feature_index,
            wheel_mode,
            auto_disengage,
            auto_disengage_default,
            "Setting SmartShift config"
        );

        // Function [1] setRatchetControlMode(wheelMode, autoDisengage, autoDisengageDefault)
        let params = [wheel_mode, auto_disengage, auto_disengage_default];

        match self.hidpp_request(feature_index, 0x01, &params) {
            Some(resp) if resp.len() >= 7 => {
                // Response echoes the parameters
                let returned_wheel_mode = resp[4];
                let returned_auto_disengage = resp[5];
                let returned_auto_disengage_default = resp[6];

                tracing::debug!(
                    returned_wheel_mode,
                    returned_auto_disengage,
                    returned_auto_disengage_default,
                    "SmartShift config set successfully"
                );
                Ok(())
            }
            Some(resp) => {
                tracing::warn!("Invalid setRatchetControlMode response length: {}", resp.len());
                Err(HapticError::IoError(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "Invalid SmartShift response",
                )))
            }
            None => {
                tracing::warn!("Failed to set SmartShift config");
                Err(HapticError::IoError(std::io::Error::new(
                    std::io::ErrorKind::Other,
                    "Failed to set SmartShift",
                )))
            }
        }
    }

    /// Get HiResScroll mode configuration
    pub fn get_hiresscroll_mode(&mut self) -> Option<(bool, bool, bool)> {
        let feature_index = self.smartshift_feature_index?;

        tracing::debug!(feature_index, "Getting HiResScroll mode from device");

        // Function [1] getMode() -> mode byte
        let params = [0x00, 0x00, 0x00];

        self.hidpp_request(feature_index, 0x01, &params).and_then(|resp| {
            if resp.len() >= 5 {
                let mode = resp[4];
                let target = (mode & 0x01) != 0;
                let hires = (mode & 0x02) != 0;
                let invert = (mode & 0x04) != 0;

                tracing::debug!(
                    mode,
                    hires,
                    invert,
                    target,
                    "Got HiResScroll mode"
                );
                Some((hires, invert, target))
            } else {
                tracing::warn!("Invalid getMode response length: {}", resp.len());
                None
            }
        })
    }

    /// Set HiResScroll mode configuration
    pub fn set_hiresscroll_mode(
        &mut self,
        hires: bool,
        invert: bool,
        target: bool,
    ) -> Result<(), HapticError> {
        let feature_index = match self.smartshift_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("HiResScroll not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        // Build mode byte
        let mut mode: u8 = 0;
        if target {
            mode |= 0x01;
        }
        if hires {
            mode |= 0x02;
        }
        if invert {
            mode |= 0x04;
        }

        tracing::info!(
            feature_index,
            mode,
            hires,
            invert,
            target,
            "Setting HiResScroll mode"
        );

        // Function [2] setMode(mode)
        let params = [mode, 0x00, 0x00];

        match self.hidpp_request(feature_index, 0x02, &params) {
            Some(resp) if resp.len() >= 5 => {
                let returned_mode = resp[4];
                tracing::debug!(
                    returned_mode,
                    "HiResScroll mode set successfully"
                );
                Ok(())
            }
            Some(resp) => {
                tracing::warn!("Invalid setMode response length: {}", resp.len());
                Err(HapticError::IoError(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "Invalid HiResScroll response",
                )))
            }
            None => {
                tracing::warn!("Failed to set HiResScroll mode");
                Err(HapticError::IoError(std::io::Error::new(
                    std::io::ErrorKind::Other,
                    "Failed to set HiResScroll",
                )))
            }
        }
    }

    // =========================================================================
    // Battery Methods
    // =========================================================================

    /// Query battery status from the device
    pub fn query_battery(&mut self) -> Result<(u8, bool), HapticError> {
        let feature_index = match self.battery_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("Battery feature not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        // Query battery status
        let function = if self.is_unified_battery { 0x01 } else { 0x00 };

        match self.hidpp_request(feature_index, function, &[]) {
            Some(resp) => {
                tracing::debug!(
                    response_len = resp.len(),
                    is_unified = self.is_unified_battery,
                    "Battery response: {:02X?}",
                    &resp[..resp.len().min(12)]
                );

                if self.is_unified_battery && resp.len() >= 8 {
                    let percentage = resp[4];
                    let charging_status = resp[7];
                    let charging = charging_status >= 1 && charging_status <= 3;

                    tracing::debug!(
                        percentage,
                        charging_status,
                        charging,
                        "Battery query result (UNIFIED_BATTERY)"
                    );

                    Ok((percentage, charging))
                } else if resp.len() >= 7 {
                    let percentage = resp[4];
                    let charging_status = resp[6];
                    let charging = charging_status >= 1 && charging_status <= 4;

                    tracing::debug!(
                        percentage,
                        charging_status,
                        charging,
                        "Battery query result (BATTERY_STATUS)"
                    );

                    Ok((percentage, charging))
                } else {
                    Err(HapticError::ProtocolError("Invalid battery response".into()))
                }
            }
            None => {
                tracing::warn!("No response from battery query");
                Err(HapticError::CommunicationError)
            }
        }
    }

    /// Check if battery feature is supported
    pub fn battery_supported(&self) -> bool {
        self.battery_supported
    }

    // =========================================================================
    // Easy-Switch Methods
    // =========================================================================

    /// Get host names for Easy-Switch slots using HID++ 0x1815 (HOSTS_INFO)
    ///
    /// This is a READ-ONLY operation that retrieves the friendly names of
    /// paired hosts. It does NOT write to device memory.
    pub fn get_host_names(&mut self) -> Vec<String> {
        // Query HOSTS_INFO feature (0x1815) directly using IRoot
        // This bypasses the blocklist check since we only READ, never WRITE
        let hosts_info_index = match self.get_feature_index(features::HOSTS_INFO) {
            Some(idx) => idx,
            None => {
                tracing::debug!("HOSTS_INFO feature (0x1815) not supported on this device");
                return Vec::new();
            }
        };

        tracing::debug!(index = hosts_info_index, "Found HOSTS_INFO feature");

        // Function 0x00: getHostInfo - get number of hosts and capabilities
        let resp = match self.hidpp_request(hosts_info_index, 0x00, &[]) {
            Some(r) => r,
            None => {
                tracing::debug!("Failed to get host info");
                return Vec::new();
            }
        };

        if resp.len() < 6 {
            return Vec::new();
        }

        // Response: [4]=capability_flags, [5]=numHosts, [6]=currentHost
        let num_hosts = resp[5];
        let _current_host = resp[6];
        tracing::debug!(num_hosts, "Got host count from device");

        let mut host_names = Vec::new();

        // Get name for each host slot
        for host_idx in 0..num_hosts {
            // Function 0x01: getHostDescriptor - get status and name length
            let resp = match self.hidpp_request(hosts_info_index, 0x01, &[host_idx, 0, 0]) {
                Some(r) => r,
                None => {
                    host_names.push(String::new());
                    continue;
                }
            };

            if resp.len() < 9 {
                host_names.push(String::new());
                continue;
            }

            // Response: [4]=host, [5]=busType, [6]=flags, [7]=status, [8]=nameLen, [9]=maxNameLen
            let name_len = resp[8] as usize;
            if name_len == 0 {
                host_names.push(String::new());
                continue;
            }

            // Function 0x03: getHostFriendlyName - get actual name (chunked, 14 bytes per call)
            let mut name_bytes = Vec::new();
            let mut offset = 0u8;

            while (offset as usize) < name_len {
                let resp = match self.hidpp_request(hosts_info_index, 0x03, &[host_idx, offset, 0]) {
                    Some(r) => r,
                    None => break,
                };

                if resp.len() < 6 {
                    break;
                }

                // Response: [4]=host, [5]=offset, [6..20]=name (up to 14 bytes)
                let chunk_start = 6;
                let chunk_len = std::cmp::min(14, name_len - offset as usize);
                if resp.len() >= chunk_start + chunk_len {
                    name_bytes.extend_from_slice(&resp[chunk_start..chunk_start + chunk_len]);
                }

                offset += 14;
            }

            // Convert to string, trimming null bytes
            let name = String::from_utf8_lossy(&name_bytes)
                .trim_end_matches('\0')
                .to_string();

            tracing::debug!(host = host_idx, name = %name, "Got host name");
            host_names.push(name);
        }

        host_names
    }

    /// Get Easy-Switch info: (num_hosts, current_host)
    pub fn get_easy_switch_info(&mut self) -> Option<(u8, u8)> {
        // Query CHANGE_HOST feature (0x1814)
        let change_host_index = self.get_feature_index(features::CHANGE_HOST)?;

        // Function 0: getHostInfo
        let resp = self.hidpp_request(change_host_index, 0x00, &[])?;

        if resp.len() < 6 {
            return None;
        }

        // Response: [4]=numHosts, [5]=currentHost
        let num_hosts = resp[4];
        let current_host = resp[5];

        Some((num_hosts, current_host))
    }

    /// Switch to a different paired host (Easy-Switch)
    pub fn set_current_host(&mut self, host_index: u8) -> Result<(), String> {
        // Query CHANGE_HOST feature (0x1814)
        let change_host_index = self.get_feature_index(features::CHANGE_HOST)
            .ok_or_else(|| "CHANGE_HOST feature (0x1814) not supported".to_string())?;

        // Validate host_index (typically 0, 1, or 2)
        if host_index > 2 {
            return Err(format!("Invalid host_index: {}. Must be 0, 1, or 2", host_index));
        }

        tracing::info!(host_index, "Switching to Easy-Switch host slot");

        // Function 0x01: setCurrentHost with param = host_index
        let resp = self.hidpp_request(change_host_index, 0x01, &[host_index]);

        match resp {
            Some(_) => {
                tracing::info!(host_index, "Successfully sent host switch command");
                Ok(())
            }
            None => {
                // Note: The device may disconnect before sending a response
                // when switching hosts, so a missing response might still mean success
                tracing::warn!(host_index, "No response from host switch command (device may have disconnected)");
                Ok(())
            }
        }
    }
}
