//! HID++ 2.0 Battery Status module for Logitech devices
//!
//! Queries battery level from MX Master 4 via HID++ protocol over hidraw.
//!
//! SPDX-License-Identifier: GPL-3.0

use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;

/// HID++ feature IDs
const FEATURE_BATTERY_STATUS: u16 = 0x1000;
const FEATURE_UNIFIED_BATTERY: u16 = 0x1004;

/// HID++ report types
const HIDPP_SHORT: u8 = 0x10;
const HIDPP_LONG: u8 = 0x11;

/// Software ID for our requests
const SOFTWARE_ID: u8 = 0x01;

/// Battery state shared across threads
#[derive(Debug, Clone, Default)]
pub struct BatteryState {
    /// Battery percentage (0-100)
    pub percentage: u8,
    /// Whether the device is charging
    pub charging: bool,
    /// Whether battery info is available
    pub available: bool,
    /// Last error message if any
    pub error: Option<String>,
    /// Whether logid is controlling HID++ (battery unavailable)
    pub logid_active: bool,
}

/// Shared battery state type
pub type SharedBatteryState = Arc<RwLock<BatteryState>>;

/// Create a new shared battery state
pub fn new_shared_state() -> SharedBatteryState {
    Arc::new(RwLock::new(BatteryState::default()))
}

/// HID++ Battery query handler
pub struct BatteryHandler {
    /// Path to the hidraw device
    device_path: Option<PathBuf>,
    /// Device file handle
    device: Option<File>,
    /// Device index (for Bolt receiver)
    device_index: u8,
    /// Cached feature index for battery
    battery_feature_index: Option<u8>,
    /// Whether using UNIFIED_BATTERY (true) or BATTERY_STATUS (false)
    is_unified_battery: bool,
    /// Shared battery state
    state: SharedBatteryState,
}

impl BatteryHandler {
    /// Create a new battery handler
    pub fn new(state: SharedBatteryState) -> Self {
        Self {
            device_path: None,
            device: None,
            device_index: 0x02, // Default for Bolt receiver
            battery_feature_index: None,
            is_unified_battery: false,
            state,
        }
    }

    /// Find all Logitech hidraw devices for HID++ communication
    ///
    /// Supports multiple receiver types:
    /// - Bolt receiver (046D:C548)
    /// - Unifying receiver (046D:C52B)
    /// - Direct USB connection (046D:B034, etc.)
    ///
    /// Returns ALL candidates sorted by priority, with interface 2 devices first.
    fn find_all_devices() -> Vec<PathBuf> {
        let hidraw_dir = PathBuf::from("/sys/class/hidraw");
        if !hidraw_dir.exists() {
            return Vec::new();
        }

        let mut candidates: Vec<(PathBuf, String, u8)> = Vec::new();

        let entries = match std::fs::read_dir(&hidraw_dir) {
            Ok(e) => e,
            Err(_) => return Vec::new(),
        };

        for entry in entries.flatten() {
            let path = entry.path();

            let uevent_path = path.join("device/uevent");
            if let Ok(uevent) = std::fs::read_to_string(&uevent_path) {
                // Check for Logitech vendor ID (046D)
                if !uevent.contains("046D") && !uevent.contains("046d") {
                    continue;
                }

                // Prioritize by connection type
                // Higher priority = better choice for HID++ battery queries
                let priority = if uevent.contains("C548") || uevent.contains("c548") {
                    // Bolt receiver - highest priority
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

        // Sort by priority (highest first), then by interface 2 preference
        candidates.sort_by(|a, b| {
            let priority_cmp = b.2.cmp(&a.2);
            if priority_cmp != std::cmp::Ordering::Equal {
                return priority_cmp;
            }
            // Same priority: prefer input2
            let a_is_input2 = a.1.contains("input2");
            let b_is_input2 = b.1.contains("input2");
            b_is_input2.cmp(&a_is_input2)
        });

        candidates.into_iter().map(|(p, _, _)| p).collect()
    }

    /// Try to open a specific hidraw device for read/write
    fn try_open_device(&mut self, path: &PathBuf) -> Result<(), BatteryError> {
        // Open with read/write and non-blocking
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(path)
            .map_err(|e| {
                if e.kind() == std::io::ErrorKind::PermissionDenied {
                    BatteryError::PermissionDenied
                } else {
                    BatteryError::IoError(e)
                }
            })?;

        self.device_path = Some(path.clone());
        self.device = Some(file);
        Ok(())
    }

    /// Open the best hidraw device for read/write, trying all candidates
    fn open(&mut self) -> Result<(), BatteryError> {
        let candidates = Self::find_all_devices();

        if candidates.is_empty() {
            return Err(BatteryError::DeviceNotFound);
        }

        for path in candidates {
            // Try to open this device
            if self.try_open_device(&path).is_err() {
                continue;
            }

            // Try a simple HID++ ping to validate the device has a mouse connected
            // IRoot function 0x01 (ping) with test data
            let ping_params = [0, 0, 0xAA];
            match self.hidpp_request(0x00, 0x01, &ping_params) {
                Ok(resp) if resp.len() >= 7 && resp[6] == 0xAA => {
                    tracing::info!(path = %path.display(), "Found Logitech HID++ device (validated)");
                    return Ok(());
                }
                _ => {
                    // This device didn't respond correctly, try next
                    tracing::debug!(path = %path.display(), "HID++ device did not validate, trying next");
                    self.device = None;
                    self.device_path = None;
                    continue;
                }
            }
        }

        Err(BatteryError::DeviceNotFound)
    }

    /// Send a HID++ request and read the response
    fn hidpp_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Result<Vec<u8>, BatteryError> {
        let device = self.device.as_mut().ok_or(BatteryError::DeviceNotFound)?;

        // Drain any pending data first to avoid stale responses
        let mut drain_buf = [0u8; 64];
        loop {
            match device.read(&mut drain_buf) {
                Ok(_) => continue, // Discard stale data
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }

        // Build HID++ short report (7 bytes)
        let mut request = [0u8; 7];
        request[0] = HIDPP_SHORT;
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
        device.write_all(&request).map_err(BatteryError::IoError)?;

        // Read response with timeout (non-blocking, so we poll)
        let mut response = [0u8; 20];
        let mut attempts = 0;

        loop {
            match device.read(&mut response) {
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
                    if response[0] == HIDPP_SHORT || response[0] == HIDPP_LONG {
                        // Must match: device index, feature index, function, AND software ID
                        if response[1] == self.device_index
                            && response[2] == feature_index
                            && resp_function == function
                            && resp_sw_id == SOFTWARE_ID
                        {
                            return Ok(response[..len].to_vec());
                        }
                        // Check for error response (0x8F = error report)
                        if response[2] == 0x8F || (response[2] == feature_index && response[4] == 0x05) {
                            tracing::debug!("HID++ error response: {:02X?}", &response[..len]);
                            return Err(BatteryError::ProtocolError("Device returned error".into()));
                        }
                        // Ignore unrelated notifications (button events, etc)
                    }
                }
                Ok(_) => {
                    // Short read, continue
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    // No data yet
                }
                Err(e) => {
                    return Err(BatteryError::IoError(e));
                }
            }

            attempts += 1;
            if attempts > 100 {
                return Err(BatteryError::Timeout);
            }

            std::thread::sleep(std::time::Duration::from_millis(10));
        }
    }

    /// Get the feature index for a given feature ID using IRoot
    fn get_feature_index(&mut self, feature_id: u16) -> Result<u8, BatteryError> {
        // IRoot (0x0000) function 0: getFeature(featureID) -> featureIndex
        let params = [(feature_id >> 8) as u8, (feature_id & 0xFF) as u8];

        let response = self.hidpp_request(0x00, 0x00, &params)?;

        if response.len() >= 5 {
            let index = response[4];
            if index == 0 {
                return Err(BatteryError::FeatureNotSupported);
            }
            Ok(index)
        } else {
            Err(BatteryError::ProtocolError("Invalid response".into()))
        }
    }

    /// Query battery status from the device
    pub fn query_battery(&mut self) -> Result<(u8, bool), BatteryError> {
        // Open device if not already open
        if self.device.is_none() {
            self.open()?;
        }

        // Get battery feature index if not cached
        if self.battery_feature_index.is_none() {
            // Try UNIFIED_BATTERY first (newer devices), then BATTERY_STATUS
            match self.get_feature_index(FEATURE_UNIFIED_BATTERY) {
                Ok(index) => {
                    tracing::info!(index, "Found UNIFIED_BATTERY feature");
                    self.battery_feature_index = Some(index);
                    self.is_unified_battery = true;
                }
                Err(_) => {
                    match self.get_feature_index(FEATURE_BATTERY_STATUS) {
                        Ok(index) => {
                            tracing::info!(index, "Found BATTERY_STATUS feature");
                            self.battery_feature_index = Some(index);
                            self.is_unified_battery = false;
                        }
                        Err(e) => {
                            return Err(e);
                        }
                    }
                }
            }
        }

        let feature_index = self.battery_feature_index.ok_or(BatteryError::FeatureNotSupported)?;

        // Query battery status
        // UNIFIED_BATTERY (0x1004): function 1 = get_status
        // BATTERY_STATUS (0x1000): function 0 = GetBatteryLevelStatus
        let function = if self.is_unified_battery { 0x01 } else { 0x00 };
        let response = self.hidpp_request(feature_index, function, &[])?;

        // Log raw response for debugging
        tracing::info!(
            response_len = response.len(),
            is_unified = self.is_unified_battery,
            "Battery response: {:02X?}",
            &response[..response.len().min(12)]
        );

        // HID++ UNIFIED_BATTERY (0x1004) response format:
        // [0] report_type, [1] device_index, [2] feature_index, [3] function_id
        // [4] state_of_charge (percentage), [5] level (0-4), [6] flags, [7] charging_status
        //
        // HID++ BATTERY_STATUS (0x1000) response format:
        // [4] level, [5] next_level, [6] status
        if response.len() >= 8 && self.is_unified_battery {
            let percentage = response[4];
            let charging_status = response[7]; // Charging status is at byte 7 for UNIFIED_BATTERY

            // UNIFIED_BATTERY charging_status: 0=discharging, 1=charging, 2=charging_slow, 3=charging_complete, 5=invalid
            let charging = charging_status >= 1 && charging_status <= 3;

            tracing::debug!(
                percentage,
                charging_status,
                charging,
                "Battery query result (UNIFIED_BATTERY)"
            );

            Ok((percentage, charging))
        } else if response.len() >= 7 {
            let percentage = response[4];
            let charging_status = response[6];

            // BATTERY_STATUS status: 0=discharging, 1-4=various charging states
            let charging = charging_status >= 1 && charging_status <= 4;

            tracing::debug!(
                percentage,
                charging_status,
                charging,
                "Battery query result (BATTERY_STATUS)"
            );

            Ok((percentage, charging))
        } else {
            Err(BatteryError::ProtocolError("Invalid battery response".into()))
        }
    }

    /// Update the shared battery state
    pub async fn update_state(&mut self) {
        match self.query_battery() {
            Ok((percentage, charging)) => {
                let mut state = self.state.write().await;
                state.percentage = percentage;
                state.charging = charging;
                state.available = true;
                state.error = None;
                tracing::debug!(percentage, charging, "Battery state updated");
            }
            Err(e) => {
                let mut state = self.state.write().await;
                state.available = false;
                state.error = Some(e.to_string());
                tracing::warn!(error = %e, "Failed to query battery");
            }
        }
    }
}

/// Battery error type
#[derive(Debug)]
pub enum BatteryError {
    DeviceNotFound,
    PermissionDenied,
    IoError(std::io::Error),
    ProtocolError(String),
    FeatureNotSupported,
    Timeout,
}

impl std::fmt::Display for BatteryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BatteryError::DeviceNotFound => write!(f, "Device not found"),
            BatteryError::PermissionDenied => write!(f, "Permission denied"),
            BatteryError::IoError(e) => write!(f, "I/O error: {}", e),
            BatteryError::ProtocolError(msg) => write!(f, "Protocol error: {}", msg),
            BatteryError::FeatureNotSupported => write!(f, "Battery feature not supported"),
            BatteryError::Timeout => write!(f, "Request timeout"),
        }
    }
}

impl std::error::Error for BatteryError {}

/// Check if logid (LogiOps) is running
fn is_logid_running() -> bool {
    std::process::Command::new("pgrep")
        .arg("-x")
        .arg("logid")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Start a periodic battery update task (legacy - uses its own hidraw handle)
#[deprecated(note = "Use start_battery_updater_shared instead to share hidraw with haptic")]
pub async fn start_battery_updater(state: SharedBatteryState) {
    let mut handler = BatteryHandler::new(state.clone());
    let mut consecutive_errors = 0u32;
    let mut logid_warned = false;

    // Check if logid is running - if so, battery queries will fail
    if is_logid_running() {
        tracing::info!("LogiOps (logid) detected - battery status via HID++ unavailable");
        let mut s = state.write().await;
        s.available = false;
        s.logid_active = true;
        s.error = Some("LogiOps controls HID++".to_string());
        logid_warned = true;
    }

    // Initial update
    handler.update_state().await;

    // Update every 2 seconds for instant charging status detection
    let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(2));

    loop {
        interval.tick().await;

        // Re-check logid periodically (every 30 seconds worth of ticks)
        if consecutive_errors > 0 && consecutive_errors % 15 == 0 {
            if is_logid_running() && !logid_warned {
                tracing::info!("LogiOps (logid) detected - battery queries will fail");
                let mut s = state.write().await;
                s.logid_active = true;
                logid_warned = true;
            }
        }

        match handler.query_battery() {
            Ok((percentage, charging)) => {
                consecutive_errors = 0;
                let mut s = state.write().await;
                s.percentage = percentage;
                s.charging = charging;
                s.available = true;
                s.error = None;
                s.logid_active = false;
                tracing::debug!(percentage, charging, "Battery state updated");
            }
            Err(e) => {
                consecutive_errors += 1;
                let mut s = state.write().await;
                s.available = false;
                s.error = Some(e.to_string());

                // Only log warning for first few errors, then go quiet
                if consecutive_errors <= 3 {
                    tracing::warn!(error = %e, "Failed to query battery");
                } else if consecutive_errors == 4 {
                    tracing::info!("Battery queries failing repeatedly - suppressing further warnings");
                }
                // After 4 errors, stay quiet to avoid log spam
            }
        }
    }
}

/// Start a periodic battery update task using shared HapticManager
///
/// This version shares the HidppDevice with haptic feedback to avoid
/// conflicts when both need to access the same hidraw device.
pub async fn start_battery_updater_shared(
    state: SharedBatteryState,
    haptic_manager: crate::hidpp::SharedHapticManager,
) {
    let mut consecutive_errors = 0u32;
    let mut logid_warned = false;

    // Check if logid is running - if so, battery queries will fail
    if is_logid_running() {
        tracing::info!("LogiOps (logid) detected - battery status via HID++ unavailable");
        let mut s = state.write().await;
        s.available = false;
        s.logid_active = true;
        s.error = Some("LogiOps controls HID++".to_string());
        logid_warned = true;
    }

    // Initial update - get result first, then update state (don't hold lock across await)
    let initial_result = {
        let mut manager = haptic_manager.lock().unwrap();
        manager.query_battery()
    };

    match initial_result {
        Ok((percentage, charging)) => {
            let mut s = state.write().await;
            s.percentage = percentage;
            s.charging = charging;
            s.available = true;
            s.error = None;
            tracing::info!(percentage, charging, "Initial battery state");
        }
        Err(e) => {
            let mut s = state.write().await;
            s.available = false;
            s.error = Some(format!("{}", e));
            tracing::warn!(error = %e, "Failed initial battery query");
        }
    }

    // Update every 2 seconds for instant charging status detection
    let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(2));

    loop {
        interval.tick().await;

        // Re-check logid periodically (every 30 seconds worth of ticks)
        if consecutive_errors > 0 && consecutive_errors % 15 == 0 {
            if is_logid_running() && !logid_warned {
                tracing::info!("LogiOps (logid) detected - battery queries will fail");
                let mut s = state.write().await;
                s.logid_active = true;
                logid_warned = true;
            }
        }

        // Lock the haptic manager briefly to query battery
        let result = {
            let mut manager = haptic_manager.lock().unwrap();
            manager.query_battery()
        };

        match result {
            Ok((percentage, charging)) => {
                consecutive_errors = 0;
                let mut s = state.write().await;
                s.percentage = percentage;
                s.charging = charging;
                s.available = true;
                s.error = None;
                s.logid_active = false;
                tracing::debug!(percentage, charging, "Battery state updated (shared)");
            }
            Err(e) => {
                consecutive_errors += 1;
                let mut s = state.write().await;
                s.available = false;
                s.error = Some(format!("{}", e));

                // Only log warning for first few errors, then go quiet
                if consecutive_errors <= 3 {
                    tracing::warn!(error = %e, "Failed to query battery (shared)");
                } else if consecutive_errors == 4 {
                    tracing::info!("Battery queries failing repeatedly - suppressing further warnings");
                }
                // After 4 errors, stay quiet to avoid log spam
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_battery_state_default() {
        let state = BatteryState::default();
        assert_eq!(state.percentage, 0);
        assert!(!state.charging);
        assert!(!state.available);
    }
}
