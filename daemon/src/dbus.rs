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
}

impl JuhRadialService {
    /// Create a new D-Bus service instance with battery state and config
    pub fn new(battery_state: SharedBatteryState, config: SharedConfig) -> Self {
        Self {
            current_profile: "default".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            battery_state,
            config,
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
                // Update the shared config
                match self.config.write() {
                    Ok(mut config) => {
                        *config = new_config;
                        tracing::info!(
                            haptics_enabled = config.haptics.enabled,
                            haptic_intensity = config.haptics.intensity,
                            theme = %config.theme,
                            "Configuration reloaded successfully"
                        );
                        Ok(())
                    }
                    Err(e) => {
                        tracing::error!(error = %e, "Failed to acquire config write lock");
                        Err(fdo::Error::Failed(format!("Lock error: {}", e)))
                    }
                }
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
///
/// # Returns
/// A `zbus::Connection` that should be kept alive for the service to run.
pub async fn init_dbus_service(
    battery_state: SharedBatteryState,
    config: SharedConfig,
) -> zbus::Result<zbus::Connection> {
    let service = JuhRadialService::new(battery_state, config);

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
        let service = JuhRadialService::new(battery_state, config);
        assert_eq!(service.current_profile, "default");
        // Check haptics from config
        let haptics = service.config.read().unwrap().haptics.enabled;
        assert!(haptics);
        assert!(!service.version.is_empty());
    }
}
