//! D-Bus IPC server for JuhRadial MX
//!
//! Implements the org.kde.juhradialmx.Daemon interface for communication
//! with KWin script and Plasma widget.
//!
//! ## Interface: org.kde.juhradialmx.Daemon
//!
//! ### Methods:
//! - `ShowMenu(x: i32, y: i32)` - Display radial menu at coordinates
//! - `HideMenu()` - Dismiss the radial menu
//! - `ExecuteAction(action_id: String)` - Execute an action by ID
//!
//! ### Signals:
//! - `MenuRequested(x: i32, y: i32)` - Emitted when menu should appear
//! - `SliceSelected(index: u8)` - Emitted when a slice is highlighted
//! - `ActionExecuted(action_id: String)` - Emitted after action runs

use zbus::{interface, object_server::SignalEmitter, fdo};
use crate::battery::SharedBatteryState;
use crate::config::{Config, SharedConfig};
use crate::hidpp::{SharedHapticManager, HapticEvent};

/// D-Bus interface name
pub const DBUS_INTERFACE: &str = "org.kde.juhradialmx.Daemon";

/// D-Bus object path
pub const DBUS_PATH: &str = "/org/kde/juhradialmx/Daemon";

/// D-Bus bus name
pub const DBUS_NAME: &str = "org.kde.juhradialmx";

/// JuhRadial MX D-Bus service
///
/// Implements the D-Bus interface for IPC between daemon, KWin overlay, and Plasma widget.
pub struct JuhRadialService {
    /// Current profile name
    current_profile: String,
    /// Daemon version
    version: String,
    /// Shared battery state
    battery_state: SharedBatteryState,
    /// Shared configuration for hot-reload
    config: SharedConfig,
    /// Shared haptic manager for triggering haptic feedback
    haptic_manager: SharedHapticManager,
}

impl JuhRadialService {
    /// Create a new D-Bus service instance with battery state, config, and haptic manager
    pub fn new(
        battery_state: SharedBatteryState,
        config: SharedConfig,
        haptic_manager: SharedHapticManager,
    ) -> Self {
        Self {
            current_profile: "default".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            battery_state,
            config,
            haptic_manager,
        }
    }
}

#[interface(name = "org.kde.juhradialmx.Daemon")]
impl JuhRadialService {
    // =========================================================================
    // METHODS (as per Story 1.2 AC1)
    // =========================================================================

    /// Show the radial menu at the specified coordinates
    ///
    /// Called by daemon when gesture button is pressed.
    /// Emits `MenuRequested` signal for KWin overlay to display menu.
    ///
    /// # Arguments
    /// * `x` - Screen X coordinate for menu center
    /// * `y` - Screen Y coordinate for menu center
    async fn show_menu(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        x: i32,
        y: i32,
    ) -> fdo::Result<()> {
        tracing::info!(x, y, "ShowMenu called - emitting MenuRequested signal");
        Self::menu_requested(&emitter, x, y).await?;
        Ok(())
    }

    /// Hide the radial menu
    ///
    /// Called when gesture button is released or menu should be dismissed.
    /// Emits `HideMenu` signal for overlay to dismiss menu.
    async fn hide_menu(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
    ) -> fdo::Result<()> {
        tracing::info!("HideMenu called - emitting HideMenu signal");
        Self::hide_menu_signal(&emitter).await?;
        Ok(())
    }

    /// Execute an action by its identifier
    ///
    /// Called when user selects a slice and releases gesture button.
    /// Executes the configured action and emits `ActionExecuted` signal.
    ///
    /// # Arguments
    /// * `action_id` - Unique identifier for the action to execute
    async fn execute_action(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        action_id: String,
    ) -> fdo::Result<()> {
        tracing::info!(action_id = %action_id, "ExecuteAction called");
        // TODO: Execute the actual action based on action_id
        Self::action_executed(&emitter, action_id).await?;
        Ok(())
    }

    // =========================================================================
    // SIGNALS (as per Story 1.2 AC2)
    // =========================================================================

    /// Signal emitted when radial menu should be displayed
    ///
    /// KWin overlay listens for this signal to render the menu.
    ///
    /// # Arguments
    /// * `x` - Screen X coordinate for menu center
    /// * `y` - Screen Y coordinate for menu center
    #[zbus(signal)]
    async fn menu_requested(emitter: &SignalEmitter<'_>, x: i32, y: i32) -> zbus::Result<()>;

    /// Signal emitted when radial menu should be hidden
    ///
    /// Overlay listens for this signal to dismiss the menu.
    #[zbus(signal, name = "HideMenu")]
    async fn hide_menu_signal(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;

    /// Signal emitted when a slice is selected/highlighted
    ///
    /// Sent when cursor moves over a new slice.
    ///
    /// # Arguments
    /// * `index` - Slice index (0-7 for 8 slices, or 255 for center/none)
    #[zbus(signal)]
    async fn slice_selected(emitter: &SignalEmitter<'_>, index: u8) -> zbus::Result<()>;

    /// Signal emitted after an action has been executed
    ///
    /// Sent after ExecuteAction completes, for feedback/logging.
    ///
    /// # Arguments
    /// * `action_id` - The identifier of the action that was executed
    #[zbus(signal)]
    async fn action_executed(emitter: &SignalEmitter<'_>, action_id: String) -> zbus::Result<()>;

    /// Signal emitted when cursor position changes while menu is active
    ///
    /// Sent by daemon while tracking relative mouse movement from evdev.
    /// Overlay uses this for hover detection on Wayland where QCursor.pos() is frozen.
    ///
    /// # Arguments
    /// * `x` - Current screen X coordinate
    /// * `y` - Current screen Y coordinate
    #[zbus(signal)]
    async fn cursor_moved(emitter: &SignalEmitter<'_>, x: i32, y: i32) -> zbus::Result<()>;

    // =========================================================================
    // ADDITIONAL METHODS (extended functionality)
    // =========================================================================

    /// Notify that a slice is being hovered
    ///
    /// Called by KWin overlay when cursor moves to a new slice.
    async fn notify_slice_hover(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        index: u8,
    ) -> fdo::Result<()> {
        tracing::debug!(index, "Slice hover notification");
        Self::slice_selected(&emitter, index).await?;
        Ok(())
    }

    /// Trigger haptic feedback for a specific event
    ///
    /// Called by the overlay when haptic feedback should be triggered:
    /// - "menu_appear" - Menu is shown
    /// - "slice_change" - Cursor moved to a different slice
    /// - "confirm" - Selection confirmed
    /// - "invalid" - Invalid action attempted
    ///
    /// # Arguments
    /// * `event` - The haptic event type (menu_appear, slice_change, confirm, invalid)
    async fn trigger_haptic(&self, event: &str) -> fdo::Result<()> {
        tracing::info!(event, "TriggerHaptic D-Bus method called");
        let haptic_event = match event {
            "menu_appear" => HapticEvent::MenuAppear,
            "slice_change" => HapticEvent::SliceChange,
            "confirm" => HapticEvent::SelectionConfirm,
            "invalid" => HapticEvent::InvalidAction,
            _ => {
                tracing::warn!(event, "Unknown haptic event type");
                return Ok(());
            }
        };

        tracing::debug!("Attempting to lock haptic_manager");
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                tracing::debug!("Lock acquired, calling emit()");
                match manager.emit(haptic_event) {
                    Ok(()) => tracing::info!("Haptic emit succeeded"),
                    Err(e) => tracing::warn!(error = %e, "Haptic emit failed"),
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager");
            }
        }

        Ok(())
    }

    /// Set the active profile
    async fn set_profile(&self, name: &str) -> fdo::Result<()> {
        tracing::info!(name, "SetProfile called");
        // TODO: Load profile configuration
        Ok(())
    }

    /// Reload configuration from disk
    ///
    /// Reloads config.json and updates the shared configuration.
    /// This allows settings changes to take effect without restarting the daemon.
    async fn reload_config(&self) -> fdo::Result<()> {
        tracing::info!("ReloadConfig called - reloading configuration from disk");

        match Config::load_default() {
            Ok(new_config) => {
                // Clone haptic config for updating the haptic manager
                let haptic_config = new_config.haptics.clone();

                // Update the shared config
                match self.config.write() {
                    Ok(mut config) => {
                        *config = new_config;
                        tracing::info!(
                            haptics_enabled = config.haptics.enabled,
                            default_pattern = %config.haptics.default_pattern,
                            theme = %config.theme,
                            "Configuration reloaded successfully"
                        );
                    }
                    Err(e) => {
                        tracing::error!(error = %e, "Failed to acquire config write lock");
                        return Err(fdo::Error::Failed(format!("Lock error: {}", e)));
                    }
                }

                // Update the haptic manager with new settings
                match self.haptic_manager.lock() {
                    Ok(mut manager) => {
                        manager.update_from_config(&haptic_config);
                        tracing::info!(
                            default_pattern = %haptic_config.default_pattern,
                            menu_appear = %haptic_config.per_event.menu_appear,
                            slice_change = %haptic_config.per_event.slice_change,
                            confirm = %haptic_config.per_event.confirm,
                            invalid = %haptic_config.per_event.invalid,
                            "Haptic manager updated with new patterns"
                        );
                    }
                    Err(e) => {
                        tracing::error!(error = %e, "Failed to lock haptic manager for update");
                        return Err(fdo::Error::Failed(format!("Haptic manager lock error: {}", e)));
                    }
                }

                Ok(())
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to reload configuration");
                Err(fdo::Error::Failed(format!("Config reload failed: {}", e)))
            }
        }
    }

    /// Called by KWin script to report cursor position and show menu
    ///
    /// This method is called by the JuhRadial KWin script which has access
    /// to the actual cursor position on Wayland.
    async fn show_menu_at_cursor(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        x: i32,
        y: i32,
    ) -> fdo::Result<()> {
        tracing::info!(x, y, "ShowMenuAtCursor called from KWin script");
        Self::menu_requested(&emitter, x, y).await?;
        Ok(())
    }

    /// Get battery status from the device
    ///
    /// Returns the battery percentage and charging state.
    ///
    /// # Returns
    /// Tuple of (percentage: u8, is_charging: bool)
    async fn get_battery_status(&self) -> fdo::Result<(u8, bool)> {
        let state = self.battery_state.read().await;
        if state.available {
            Ok((state.percentage, state.charging))
        } else {
            // Return 0, false if battery info not available
            Ok((0, false))
        }
    }

    // =========================================================================
    // DPI METHODS
    // =========================================================================

    /// Get current DPI value from the mouse
    ///
    /// # Returns
    /// Current DPI value (typically 400-8000), or 0 if not supported
    async fn get_dpi(&self) -> fdo::Result<u16> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                Ok(manager.get_dpi().unwrap_or(0))
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_dpi");
                Ok(0)
            }
        }
    }

    /// Set DPI value on the mouse
    ///
    /// # Arguments
    /// * `dpi` - DPI value to set (typically 400-8000)
    ///
    /// # Returns
    /// Ok on success, error on failure
    async fn set_dpi(&self, dpi: u16) -> fdo::Result<()> {
        tracing::info!(dpi, "SetDpi called");

        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.set_dpi(dpi) {
                    Ok(()) => {
                        tracing::info!(dpi, "DPI set successfully");
                        Ok(())
                    }
                    Err(e) => {
                        tracing::error!(error = %e, dpi, "Failed to set DPI");
                        Err(fdo::Error::Failed(format!("Failed to set DPI: {}", e)))
                    }
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for set_dpi");
                Err(fdo::Error::Failed(format!("Lock error: {}", e)))
            }
        }
    }

    /// Check if DPI adjustment is supported on the connected device
    async fn dpi_supported(&self) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                Ok(manager.dpi_supported())
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for dpi_supported");
                Ok(false)
            }
        }
    }

    // =========================================================================
    // SMARTSHIFT METHODS
    // =========================================================================

    /// Get current SmartShift configuration from the mouse
    ///
    /// # Returns
    /// Tuple of (enabled: bool, threshold: u8) where:
    /// - enabled: true if SmartShift auto-mode is enabled (auto_disengage > 0)
    /// - threshold: sensitivity threshold (0-255), from auto_disengage value
    /// Returns (false, 0) if SmartShift is not supported
    async fn get_smart_shift(&self) -> fdo::Result<(bool, u8)> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.get_smartshift() {
                    Some((_wheel_mode, auto_disengage, _auto_disengage_default)) => {
                        // If auto_disengage > 0, SmartShift is enabled
                        let enabled = auto_disengage > 0;
                        // Return the threshold value
                        let threshold = if enabled { auto_disengage } else { 30 };
                        Ok((enabled, threshold))
                    }
                    None => Ok((false, 0))
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_smart_shift");
                Ok((false, 0))
            }
        }
    }

    /// Set SmartShift configuration on the mouse
    ///
    /// # Arguments
    /// * `enabled` - true to enable SmartShift auto-mode, false for manual ratchet mode
    /// * `threshold` - sensitivity threshold (1-255), N/4 turns/sec for auto-disengage
    ///   Typical range: 10-50, recommended: 30
    ///
    /// # Returns
    /// Ok on success, error on failure
    async fn set_smart_shift(&self, enabled: bool, threshold: u8) -> fdo::Result<()> {
        tracing::info!(enabled, threshold, "SetSmartShift called");

        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                // wheel_mode: 1 = Freespin, 2 = Ratchet
                // auto_disengage: 0 = disabled (no auto-switch), 1-254 = threshold, 255 = always engaged
                //
                // SmartShift behavior (like Logi Options+):
                // - enabled=true: wheel starts in freespin mode with auto-disengage at threshold
                //   (auto-switches to ratchet when scrolling fast)
                // - enabled=false: wheel is locked in ratchet mode (traditional click-by-click)
                let wheel_mode = if enabled { 1u8 } else { 2u8 };
                let auto_disengage = if enabled { threshold } else { 0u8 };
                let auto_disengage_default = auto_disengage;

                match manager.set_smartshift(wheel_mode, auto_disengage, auto_disengage_default) {
                    Ok(()) => {
                        tracing::info!(enabled, threshold, "SmartShift set successfully");
                        Ok(())
                    }
                    Err(e) => {
                        tracing::error!(error = %e, enabled, threshold, "Failed to set SmartShift");
                        Err(fdo::Error::Failed(format!("Failed to set SmartShift: {}", e)))
                    }
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for set_smart_shift");
                Err(fdo::Error::Failed(format!("Lock error: {}", e)))
            }
        }
    }

    /// Check if SmartShift is supported on the connected device
    async fn smart_shift_supported(&self) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                Ok(manager.smartshift_supported())
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for smart_shift_supported");
                Ok(false)
            }
        }
    }

    // =========================================================================
    // HIRESSCROLL METHODS
    // =========================================================================

    /// Get current HiResScroll mode configuration from the mouse
    ///
    /// # Returns
    /// Tuple of (hires: bool, invert: bool, target: bool) where:
    /// - hires: true if high-resolution scrolling is enabled (more events, faster feel)
    /// - invert: true if natural/inverted scrolling is enabled
    /// - target: true if scroll events go directly to focused window
    /// Returns (true, false, false) as default if not supported
    async fn get_hiresscroll_mode(&self) -> fdo::Result<(bool, bool, bool)> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.get_hiresscroll_mode() {
                    Some((hires, invert, target)) => Ok((hires, invert, target)),
                    None => Ok((true, false, false)) // Default values
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_hiresscroll_mode");
                Ok((true, false, false))
            }
        }
    }

    /// Set HiResScroll mode configuration on the mouse
    ///
    /// # Arguments
    /// * `hires` - true for high-resolution scrolling (more events, faster feel)
    /// * `invert` - true for natural/inverted scrolling
    /// * `target` - true to send scroll events directly to focused window
    ///
    /// # Returns
    /// Ok on success, error on failure
    async fn set_hiresscroll_mode(&self, hires: bool, invert: bool, target: bool) -> fdo::Result<()> {
        tracing::info!(hires, invert, target, "SetHiResScrollMode called");

        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.set_hiresscroll_mode(hires, invert, target) {
                    Ok(()) => {
                        tracing::info!(hires, invert, target, "HiResScroll mode set successfully");
                        Ok(())
                    }
                    Err(e) => {
                        tracing::error!(error = %e, hires, invert, target, "Failed to set HiResScroll mode");
                        Err(fdo::Error::Failed(format!("Failed to set HiResScroll mode: {}", e)))
                    }
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for set_hiresscroll_mode");
                Err(fdo::Error::Failed(format!("Lock error: {}", e)))
            }
        }
    }

    // =========================================================================
    // EASY-SWITCH METHODS
    // =========================================================================

    /// Get host names for Easy-Switch slots
    ///
    /// Uses HID++ 0x1815 (HOSTS_INFO) feature to read paired host names.
    /// This is a READ-ONLY operation that does not modify device memory.
    ///
    /// # Returns
    /// Vec of host names, one per slot. Empty strings for unpaired slots.
    async fn get_host_names(&self) -> fdo::Result<Vec<String>> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                let names = manager.get_host_names();
                tracing::info!(host_names = ?names, "Easy-Switch host names retrieved");
                Ok(names)
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_host_names");
                Ok(Vec::new())
            }
        }
    }

    /// Get Easy-Switch info: number of hosts and current host
    ///
    /// # Returns
    /// (num_hosts, current_host) - current_host is 0-indexed
    async fn get_easy_switch_info(&self) -> fdo::Result<(u8, u8)> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.get_easy_switch_info() {
                    Some((num, current)) => {
                        tracing::info!(num_hosts = num, current_host = current, "Easy-Switch info retrieved");
                        Ok((num, current))
                    }
                    None => {
                        tracing::debug!("Easy-Switch not supported or unavailable");
                        Ok((0, 0))
                    }
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_easy_switch_info");
                Ok((0, 0))
            }
        }
    }

    /// Switch to a different Easy-Switch host
    ///
    /// Uses HID++ to switch the mouse to a different paired host.
    ///
    /// # Arguments
    /// * `host_index` - The host slot to switch to (0, 1, or 2)
    ///
    /// # Returns
    /// true if the switch was successful, false otherwise
    async fn set_host(&self, host_index: u8) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.set_current_host(host_index) {
                    Ok(()) => {
                        tracing::info!(host_index, "Switched to Easy-Switch host");
                        Ok(true)
                    }
                    Err(e) => {
                        tracing::error!(error = %e, host_index, "Failed to switch host");
                        Ok(false)
                    }
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for set_host");
                Ok(false)
            }
        }
    }

    // =========================================================================
    // PROPERTIES
    // =========================================================================

    /// Get current profile name
    #[zbus(property)]
    async fn current_profile(&self) -> &str {
        &self.current_profile
    }

    /// Get haptics enabled status
    #[zbus(property)]
    async fn haptics_enabled(&self) -> bool {
        self.config
            .read()
            .map(|c| c.haptics.enabled)
            .unwrap_or(true)
    }

    /// Get daemon version
    #[zbus(property)]
    async fn daemon_version(&self) -> &str {
        &self.version
    }
}

/// Initialize and run the D-Bus service
///
/// Connects to the session bus, registers the service name, and exports
/// the interface at the specified object path.
///
/// # Arguments
/// * `battery_state` - Shared battery state for GetBatteryStatus method
/// * `config` - Shared configuration for hot-reload support
/// * `haptic_manager` - Shared haptic manager for triggering haptic feedback
///
/// # Returns
/// A `zbus::Connection` that should be kept alive for the service to run.
pub async fn init_dbus_service(
    battery_state: SharedBatteryState,
    config: SharedConfig,
    haptic_manager: SharedHapticManager,
) -> zbus::Result<zbus::Connection> {
    let service = JuhRadialService::new(battery_state, config, haptic_manager);

    let connection = zbus::connection::Builder::session()?
        .name(DBUS_NAME)?
        .serve_at(DBUS_PATH, service)?
        .build()
        .await?;

    tracing::info!(
        name = DBUS_NAME,
        path = DBUS_PATH,
        "D-Bus service registered"
    );

    Ok(connection)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::battery::new_shared_state;
    use crate::config::new_shared_config;
    use crate::hidpp::new_shared_haptic_manager;

    #[test]
    fn test_dbus_constants() {
        assert_eq!(DBUS_INTERFACE, "org.kde.juhradialmx.Daemon");
        assert_eq!(DBUS_PATH, "/org/kde/juhradialmx/Daemon");
        assert_eq!(DBUS_NAME, "org.kde.juhradialmx");
    }

    #[test]
    fn test_service_creation() {
        let battery_state = new_shared_state();
        let config = new_shared_config();
        let haptic_config = config.read().unwrap().haptics.clone();
        let haptic_manager = new_shared_haptic_manager(&haptic_config);
        let service = JuhRadialService::new(battery_state, config, haptic_manager);
        assert_eq!(service.current_profile, "default");
        // Check haptics from config
        let haptics = service.config.read().unwrap().haptics.enabled;
        assert!(haptics);
        assert!(!service.version.is_empty());
    }
}
