//! Haptic manager
//!
//! High-level API for haptic feedback, managing device connection,
//! debouncing, reconnection, and delegation to HidppDevice.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use super::device::HidppDevice;
use super::error::HapticError;
use super::patterns::*;

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

/// Cooldown after a successful host switch (disabled - 0ms).
/// Previously suppressed reconnection to prevent loops, but this caused
/// lag in Flow handoffs. The reconnect loop is now handled differently.
const HOST_SWITCH_COOLDOWN_MS: u64 = 0;

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
    pub(crate) per_event: PerEventPattern,
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
    pub(crate) last_slice_change_ms: u64,
    /// Last slice index for re-entry detection (None = no previous slice)
    pub(crate) last_slice_index: Option<u8>,
    /// Pre-allocated short message buffer for low-latency sends
    pub(crate) _short_msg_buffer: [u8; 7],
    /// Timestamp of last successful host switch (suppresses reconnection)
    last_host_switch_ms: u64,
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
            last_host_switch_ms: 0,
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
            last_host_switch_ms: 0,
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
                tracing::debug!("No MX Master 4 found, haptics disabled");
                self.connection_state = ConnectionState::NotConnected;
                Ok(false)
            }
        }
    }

    /// Divert gesture buttons so HID++ notifications are sent
    pub fn divert_buttons(&mut self) -> Result<u8, HapticError> {
        match &mut self.device {
            Some(device) => device.divert_buttons(),
            None => {
                tracing::debug!("No device connected, cannot divert buttons");
                Ok(0)
            }
        }
    }

    /// Divert a single button by CID for macro interception
    pub fn divert_single_button(&mut self, cid: u16) -> Result<bool, HapticError> {
        match &mut self.device {
            Some(device) => device.divert_single_button(cid),
            None => Ok(false),
        }
    }

    /// Handle device disconnection gracefully
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

        // After a host switch, the device leaves this receiver (expected).
        // Don't spam reconnect attempts during the host switch cooldown.
        if self.last_host_switch_ms > 0
            && now.saturating_sub(self.last_host_switch_ms) < HOST_SWITCH_COOLDOWN_MS
        {
            return false;
        }

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
                // Re-divert buttons after reconnect (divert is volatile)
                match self.divert_buttons() {
                    Ok(n) if n > 0 => tracing::info!(count = n, "Re-diverted buttons after reconnect"),
                    Ok(_) => tracing::debug!("No buttons to re-divert after reconnect"),
                    Err(e) => tracing::warn!(error = %e, "Failed to re-divert buttons after reconnect"),
                }
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

    /// Get the hidraw device path the MX Master 4 is connected to
    pub fn device_path(&self) -> Option<PathBuf> {
        self.device.as_ref().map(|d| d.device_path().to_path_buf())
    }

    /// Get the device name via HID++ DEVICE_NAME feature (0x0005)
    pub fn get_device_name_string(&mut self) -> Option<String> {
        self.device.as_mut().and_then(|d| d.get_device_name())
    }

    /// Send a haptic pulse (runtime only, no memory writes)
    pub fn pulse(&mut self, haptic: HapticPulse) -> Result<(), HapticError> {
        // Check if haptics are enabled
        if !self.enabled {
            return Ok(());
        }

        // Check if device is available (legacy haptic OR MX4 haptic)
        let device = match &mut self.device {
            Some(d) if d.haptic_supported() || d.mx4_haptic_supported() => d,
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
                self.handle_disconnect();
                Ok(()) // Return Ok - haptics are optional
            }
            Err(e) => {
                tracing::debug!(error = %e, "Haptic pulse failed");
                Ok(()) // Still return Ok - haptics are optional
            }
        }
    }

    /// Emit a haptic event using UX-defined profiles
    ///
    /// This is the preferred API for triggering haptic feedback.
    /// For MX Master 4 devices with feature 0x19B0, uses predefined hardware waveforms.
    /// For other devices, uses legacy intensity/duration-based pulses.
    ///
    /// CRITICAL: This method MUST NOT write to onboard mouse memory.
    pub fn emit(&mut self, event: HapticEvent) -> Result<(), HapticError> {
        tracing::debug!(event = %event, enabled = self.enabled, has_device = self.device.is_some(), "HapticManager.emit() called");

        // Check if haptics are enabled
        if !self.enabled {
            tracing::debug!("Haptic disabled - returning early");
            return Ok(());
        }

        // Check if device is available (legacy haptic OR MX4 haptic)
        let device = match &mut self.device {
            Some(d) if d.haptic_supported() || d.mx4_haptic_supported() => d,
            Some(d) => {
                tracing::debug!(haptic = d.haptic_supported(), mx4_haptic = d.mx4_haptic_supported(), "Device exists but no haptic support");
                return Ok(());
            }
            None => {
                tracing::debug!("No device available");
                return Ok(());
            }
        };

        // Debounce: minimum time between pulses
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        if now.saturating_sub(self.last_pulse_ms) < self.debounce_ms {
            tracing::debug!(last_pulse_ms = self.last_pulse_ms, now = now, debounce_ms = self.debounce_ms, "Debounce - skipping");
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
    pub fn emit_async(&mut self, event: HapticEvent) {
        if !self.enabled {
            return;
        }

        // For single pulses, execute directly (fast)
        if event.pattern() == HapticPattern::Single {
            let _ = self.emit(event);
            return;
        }

        // For multi-pulse patterns, spawn async
        tracing::debug!(event = %event, "Multi-pulse pattern - executing synchronously (async TBD)");
        let _ = self.emit(event);
    }

    /// Emit a slice change haptic with smart debouncing
    pub fn emit_slice_change(&mut self, slice_index: u8) -> bool {
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
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_ref().map(|d| d.dpi_supported()).unwrap_or(false)
    }

    /// Get current DPI value
    pub fn get_dpi(&mut self) -> Option<u16> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_mut().and_then(|d| d.get_dpi())
    }

    /// Set DPI value
    pub fn set_dpi(&mut self, dpi: u16) -> Result<(), HapticError> {
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
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_mut().and_then(|d| d.get_dpi_list())
    }

    // =========================================================================
    // SmartShift Methods (delegated to HidppDevice)
    // =========================================================================

    /// Check if SmartShift is supported
    pub fn smartshift_supported(&mut self) -> bool {
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_ref().map(|d| d.smartshift_supported()).unwrap_or(false)
    }

    /// Get SmartShift configuration
    pub fn get_smartshift(&mut self) -> Option<(u8, u8, u8)> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_mut().and_then(|d| d.get_smartshift())
    }

    /// Set SmartShift configuration
    pub fn set_smartshift(
        &mut self,
        wheel_mode: u8,
        auto_disengage: u8,
        auto_disengage_default: u8,
    ) -> Result<(), HapticError> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => device.set_smartshift(wheel_mode, auto_disengage, auto_disengage_default),
            None => {
                tracing::warn!("Cannot set SmartShift: device not connected");
                Err(HapticError::DeviceNotFound)
            }
        }
    }

    /// Get SmartShift configuration (simplified API for DBus)
    pub fn get_smart_shift(&mut self) -> Option<(bool, u8)> {
        self.get_smartshift().map(|(wheel_mode, auto_disengage, _default)| {
            let enabled = wheel_mode == 1;
            let threshold = 255u8.saturating_sub(auto_disengage);
            (enabled, threshold)
        })
    }

    /// Set SmartShift configuration (simplified API for DBus)
    pub fn set_smart_shift(&mut self, enabled: bool, threshold: u8) -> Result<(), HapticError> {
        let wheel_mode = if enabled { 1 } else { 2 };
        let auto_disengage = 255u8.saturating_sub(threshold);
        self.set_smartshift(wheel_mode, auto_disengage, auto_disengage)
    }

    // =========================================================================
    // HiResScroll Methods (delegated to HidppDevice)
    // =========================================================================

    /// Get HiResScroll mode configuration
    pub fn get_hiresscroll_mode(&mut self) -> Option<(bool, bool, bool)> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        self.device.as_mut().and_then(|d| d.get_hiresscroll_mode())
    }

    /// Set HiResScroll mode configuration
    pub fn set_hiresscroll_mode(
        &mut self,
        hires: bool,
        invert: bool,
        target: bool,
    ) -> Result<(), HapticError> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => device.set_hiresscroll_mode(hires, invert, target),
            None => {
                tracing::warn!("Cannot set HiResScroll: device not connected");
                Err(HapticError::DeviceNotFound)
            }
        }
    }

    // =========================================================================
    // Battery Methods (delegated to HidppDevice)
    // =========================================================================

    /// Query battery status from the device
    ///
    /// On IO error (stale fd), forces reconnect and retries once.
    pub fn query_battery(&mut self) -> Result<(u8, bool), HapticError> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => {
                match device.query_battery() {
                    Ok(v) => Ok(v),
                    Err(HapticError::IoError(_)) | Err(HapticError::CommunicationError) => {
                        self.handle_disconnect();
                        if let Ok(true) = self.connect() {
                            match self.device.as_mut() {
                                Some(dev) => dev.query_battery(),
                                None => Err(HapticError::DeviceNotFound),
                            }
                        } else {
                            Err(HapticError::DeviceNotFound)
                        }
                    }
                    Err(e) => Err(e),
                }
            }
            None => {
                tracing::debug!("Cannot query battery: device not connected");
                Err(HapticError::DeviceNotFound)
            }
        }
    }

    /// Check if battery feature is supported
    pub fn battery_supported(&self) -> bool {
        self.device.as_ref().map(|d| d.battery_supported()).unwrap_or(false)
    }

    // =========================================================================
    // Easy-Switch Methods (delegated to HidppDevice)
    // =========================================================================

    /// Get host names for Easy-Switch slots
    pub fn get_host_names(&mut self) -> Vec<String> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => device.get_host_names(),
            None => Vec::new(),
        }
    }

    /// Get Easy-Switch info: (num_hosts, current_host)
    pub fn get_easy_switch_info(&mut self) -> Option<(u8, u8)> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => device.get_easy_switch_info(),
            None => None,
        }
    }

    /// Switch to a different paired host (Easy-Switch)
    ///
    /// If the first attempt fails (e.g. stale fd after a host switch round-trip),
    /// forces a reconnect with a fresh hidraw fd and retries once.
    pub fn set_current_host(&mut self, host_index: u8) -> Result<(), String> {
        if self.device.is_none() {
            let _ = self.connect();
        }
        match self.device.as_mut() {
            Some(device) => {
                match device.set_current_host(host_index) {
                    Ok(()) => {
                        // Record host switch time - suppress reconnection for a while.
                        // After CHANGE_HOST, the device leaves this receiver (expected).
                        let now = SystemTime::now()
                            .duration_since(UNIX_EPOCH)
                            .unwrap()
                            .as_millis() as u64;
                        self.last_host_switch_ms = now;
                        Ok(())
                    }
                    Err(e) => {
                        // Device fd may be stale after a host switch round-trip.
                        // The HidrawHandler reconnects independently but the
                        // manager's HidppDevice still holds the old fd.
                        // Force reconnect and retry once.
                        tracing::info!(
                            error = %e,
                            "SetHost failed, forcing reconnect and retry"
                        );
                        self.handle_disconnect();
                        if let Ok(true) = self.connect() {
                            match self.device.as_mut() {
                                Some(dev) => {
                                    let result = dev.set_current_host(host_index);
                                    if result.is_ok() {
                                        let now = SystemTime::now()
                                            .duration_since(UNIX_EPOCH)
                                            .unwrap()
                                            .as_millis() as u64;
                                        self.last_host_switch_ms = now;
                                    }
                                    result
                                }
                                None => Err("No device after reconnect".to_string()),
                            }
                        } else {
                            Err(e)
                        }
                    }
                }
            }
            None => Err("No device connected".to_string()),
        }
    }
}

impl Default for HapticManager {
    fn default() -> Self {
        Self::new(true)
    }
}
