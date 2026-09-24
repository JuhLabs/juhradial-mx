//! D-Bus interface implementation
//!
//! All methods, signals, and properties for org.kde.juhradialmx.Daemon.
//! This must be a single `#[interface]` impl block per zbus requirements.

use zbus::{interface, object_server::SignalEmitter, fdo};
use crate::config::Config;
use crate::hidpp::{HapticEvent, Mx4HapticPattern};
use crate::macros::events_to_actions;
use super::service::JuhRadialService;

#[interface(name = "org.kde.juhradialmx.Daemon")]
impl JuhRadialService {
    // ---- MX Keypad ----
    fn get_keypad_status(&self) -> (bool, String, u8, u8) {
        crate::keypad::status(&self.config)
    }

    fn set_keypad_page(&self, page: u8) -> fdo::Result<()> {
        crate::keypad::set_page(&self.config, page).map_err(fdo::Error::InvalidArgs)
    }

    fn refresh_keypad_plates(&self) {
        crate::keypad::refresh();
    }

    #[zbus(signal)]
    async fn keypad_key_pressed(emitter: &SignalEmitter<'_>, page: u8, key: u8) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn keypad_status_changed(emitter: &SignalEmitter<'_>, connected: bool) -> zbus::Result<()>;
    // ---- End MX Keypad ----

    // =========================================================================
    // MENU METHODS
    // =========================================================================

    /// Show the radial menu at the specified coordinates
    async fn show_menu(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        x: i32,
        y: i32,
    ) -> fdo::Result<()> {
        if let Ok(gm) = self.gaming_mode.read() {
            if gm.should_suppress_overlay() {
                tracing::debug!(x, y, "ShowMenu suppressed - gaming mode active");
                return Ok(());
            }
        }

        tracing::info!(x, y, "ShowMenu called - emitting MenuRequested signal");
        Self::menu_requested(&emitter, x, y).await?;
        Ok(())
    }

    /// Hide the radial menu
    async fn hide_menu(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
    ) -> fdo::Result<()> {
        tracing::info!("HideMenu called - emitting HideMenu signal");
        Self::hide_menu_signal(&emitter).await?;
        Ok(())
    }

    /// Execute an action by its identifier
    async fn execute_action(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        action_id: String,
    ) -> fdo::Result<()> {
        tracing::info!(action_id = %action_id, "ExecuteAction called");
        Self::action_executed(&emitter, action_id).await?;
        Ok(())
    }

    /// Execute a desktop-portable preset by its snake_case id.
    ///
    /// Resolution/execution reuses the async preset path, but the KWin/dbus arms
    /// block on `dbus-send`. This method runs on the zbus executor, so the work
    /// is driven on a dedicated std thread with its own current-thread runtime to
    /// keep the executor responsive (never `spawn_blocking` here).
    async fn execute_preset(&self, name: String) -> fdo::Result<()> {
        tracing::info!(name = %name, "ExecutePreset called");
        let preset = crate::presets::Preset::from_name(&name)
            .ok_or_else(|| fdo::Error::InvalidArgs(format!("Unknown preset: {}", name)))?;

        std::thread::spawn(move || {
            let rt = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
                Ok(rt) => rt,
                Err(e) => {
                    tracing::error!(error = %e, "Failed to build runtime for preset execution");
                    return;
                }
            };
            rt.block_on(async move {
                if let Err(e) = crate::presets::execute_preset(preset).await {
                    tracing::warn!(error = %e, preset = preset.as_str(), "Preset execution failed");
                }
            });
        });

        Ok(())
    }

    /// Press a key chord ("ctrl+shift+t", "F13") for a ring slice of type
    /// `shortcut`: the daemon owns the uinput path native Wayland windows
    /// need. Runs on its own thread like ExecutePreset.
    async fn run_shortcut(&self, keys: String) -> fdo::Result<()> {
        let keys = keys.trim().to_string();
        if !crate::actions::is_shortcut_text(&keys) {
            return Err(fdo::Error::InvalidArgs(format!("Not a key chord: {keys:?}")));
        }
        tracing::info!(keys = %keys, "RunShortcut called");
        std::thread::spawn(move || {
            let rt = match tokio::runtime::Builder::new_current_thread().enable_all().build() {
                Ok(rt) => rt,
                Err(e) => {
                    tracing::error!(error = %e, "Failed to build runtime for shortcut");
                    return;
                }
            };
            rt.block_on(async move {
                let action = crate::actions::Action {
                    action_type: crate::actions::ActionType::Shortcut(keys),
                    label: None,
                    icon: None,
                };
                if let Err(e) = crate::actions::ActionExecutor::execute(&action).await {
                    tracing::warn!(error = %e, "Shortcut failed");
                }
            });
        });
        Ok(())
    }

    // =========================================================================
    // MENU SIGNALS
    // =========================================================================

    #[zbus(signal)]
    async fn menu_requested(emitter: &SignalEmitter<'_>, x: i32, y: i32) -> zbus::Result<()>;

    #[zbus(signal, name = "HideMenu")]
    async fn hide_menu_signal(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn slice_selected(emitter: &SignalEmitter<'_>, index: u8) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn action_executed(emitter: &SignalEmitter<'_>, action_id: String) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn cursor_moved(emitter: &SignalEmitter<'_>, x: i32, y: i32) -> zbus::Result<()>;

    // =========================================================================
    // LIVE HARDWARE READBACK SIGNALS
    //
    // Pushed from the hidraw notification path (see process_gesture_events) when
    // the device reports a spontaneous state change. Declared here so clients can
    // introspect them; the daemon broadcasts them directly on the connection.
    // =========================================================================

    #[zbus(signal)]
    async fn battery_changed(emitter: &SignalEmitter<'_>, percent: u8, status: String) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn ratchet_changed(emitter: &SignalEmitter<'_>, ratchet: bool) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn host_changed(emitter: &SignalEmitter<'_>, host: u8) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn dpi_changed(emitter: &SignalEmitter<'_>, dpi: u16) -> zbus::Result<()>;

    /// Pushed when the daemon learns a better device name after startup (e.g.
    /// HID++ finishes connecting over Bolt after the evdev-fallback name was
    /// already reported). See run_hidraw_loop in main.rs. Named distinctly
    /// from the `device_name` property's own zbus-generated `device_name_changed`
    /// invalidation helper, which this signal isn't and can't reuse (no
    /// `SignalEmitter`/`InterfaceRef` available from main.rs's raw connection).
    #[zbus(signal)]
    async fn device_name_refreshed(emitter: &SignalEmitter<'_>, name: String) -> zbus::Result<()>;

    /// Mouse reachability changed (see GetDeviceConnection). Clients re-read
    /// GetCapabilities when it becomes "connected".
    #[zbus(signal)]
    async fn device_connection_changed(
        emitter: &SignalEmitter<'_>,
        state: String,
        transport: String,
    ) -> zbus::Result<()>;

    /// The application class whose per-app hardware profile the daemon just
    /// applied on focus change, or "" when the focus left every profiled
    /// app. Broadcast by the focus-change consumer in main.rs; the overlay's
    /// tray shows it as the active profile.
    /// A physical button went down (CID); Settings lights its marker.
    #[zbus(signal)]
    async fn button_pressed(emitter: &SignalEmitter<'_>, cid: u16) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn active_profile_changed(emitter: &SignalEmitter<'_>, app: String) -> zbus::Result<()>;

    /// An application class (lowercased) focused for the first time since the
    /// daemon started. Broadcast by the focus-change consumer in main.rs; the
    /// settings app offers to create a profile for it once.
    #[zbus(signal)]
    async fn new_app_seen(emitter: &SignalEmitter<'_>, app: String) -> zbus::Result<()>;

    /// MX Keys S battery read right after the keyboard's radio linked up (a
    /// key press). Broadcast by keyboard::run_keyboard_link_watcher while
    /// keyboard.mx_keys.enabled is on.
    #[zbus(signal)]
    async fn keyboard_battery_changed(emitter: &SignalEmitter<'_>, percent: u8, charging: bool) -> zbus::Result<()>;

    // =========================================================================
    // HAPTIC / PROFILE / CONFIG METHODS
    // =========================================================================

    /// Notify that a slice is being hovered
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
    async fn trigger_haptic(&self, event: &str) -> fdo::Result<()> {
        // Hot path: fires on every radial slice change, so keep logging at debug.
        tracing::debug!(event, "TriggerHaptic D-Bus method called");
        let haptic_event = match event {
            "menu_appear" => HapticEvent::MenuAppear,
            "slice_change" => HapticEvent::SliceChange,
            "confirm" => HapticEvent::SelectionConfirm,
            "invalid" => HapticEvent::InvalidAction,
            "window_switch" => HapticEvent::WindowSwitch,
            "monitor_switch" => HapticEvent::MonitorSwitch,
            other => match HapticEvent::ALL.iter().find(|e| e.config_key() == other) {
                Some(e) => *e,
                None => {
                    tracing::warn!(event, "Unknown haptic event type");
                    return Ok(());
                }
            },
        };

        // try_lock, not lock: this runs on the single zbus executor thread
        // that also dispatches ShowMenuAtCursor, so blocking on a busy haptic
        // manager stalls the menu. A late haptic is worthless, drop it.
        match self.haptic_manager.try_lock() {
            Ok(mut manager) => {
                if haptic_event == HapticEvent::MonitorSwitch && !manager.is_monitor_switch_enabled() {
                    tracing::debug!("Monitor-switch haptic disabled, skipping emit");
                    return Ok(());
                }
                match manager.emit(haptic_event) {
                    Ok(()) => tracing::debug!("Haptic emit succeeded"),
                    Err(e) => tracing::warn!(error = %e, "Haptic emit failed"),
                }
            }
            Err(e) => {
                tracing::debug!(error = %e, "Haptic manager busy, dropping haptic event");
            }
        }

        Ok(())
    }

    /// Play a specific haptic waveform by name (settings "Test pulse").
    ///
    /// Unlike TriggerHaptic (which takes a UX event and plays its configured
    /// pattern), this plays the exact named MX4 waveform so the haptics page
    /// can audition a selected preset.
    /// Play one waveform (Settings' Test and hover preview). Answers
    /// (played, reason): reason is "off" (haptics off), "no_motor",
    /// "unreachable" (asleep, away) or "busy".
    async fn trigger_haptic_pattern(&self, name: &str) -> fdo::Result<(bool, String)> {
        tracing::info!(name, "TriggerHapticPattern D-Bus method called");
        let pattern = Mx4HapticPattern::from_name(name);
        // try_lock for the same reason as trigger_haptic: never stall the
        // zbus executor thread behind a busy haptic manager.
        match self.haptic_manager.try_lock() {
            Ok(mut manager) => {
                let outcome = manager.pulse_pattern(pattern);
                Ok((outcome == crate::hidpp::TestOutcome::Played, outcome.as_str().to_string()))
            }
            Err(e) => {
                tracing::debug!(error = %e, "Haptic manager busy, dropping test pattern");
                Ok((false, "busy".to_string()))
            }
        }
    }

    /// The motor strength as the mouse has it: (supported, enabled, percent).
    async fn get_haptic_level(&self) -> fdo::Result<(bool, bool, u8)> {
        match self.haptic_manager.lock() {
            Ok(mut m) => Ok(m.haptic_level().map_or((false, false, 0), |(on, pct)| (true, on, pct))),
            Err(_) => Ok((false, false, 0)),
        }
    }

    /// The Haptic Sense Panel press force: (supported, min, max, default,
    /// current), raw units, higher = firmer.
    async fn get_force_sense(&self) -> fdo::Result<(bool, u16, u16, u16, u16)> {
        match self.haptic_manager.lock() {
            Ok(mut m) => Ok(m
                .force_sense()
                .filter(|f| f.changeable)
                .map_or((false, 0, 0, 0, 0), |f| (true, f.min, f.max, f.default, f.current))),
            Err(_) => Ok((false, 0, 0, 0, 0)),
        }
    }

    /// Whether the focused-window tracker runs (per-app profiles, the App
    /// switch pulse); false on a desktop it cannot follow.
    async fn window_tracking_active(&self) -> fdo::Result<bool> {
        Ok(crate::window_tracker::is_tracking())
    }

    /// Set the active profile
    async fn set_profile(&self, name: &str) -> fdo::Result<()> {
        tracing::info!(name, "SetProfile called");
        Ok(())
    }

    /// Reload configuration from disk
    async fn reload_config(&self) -> fdo::Result<()> {
        tracing::info!("ReloadConfig called - reloading configuration from disk");

        match Config::load_default() {
            Ok(mut new_config) => {
                // Keep the connected mouse's per-device overrides on top of
                // the freshly loaded file.
                let (active_unit, active_app) = self
                    .config
                    .read()
                    .map(|c| (c.active_unit.clone(), c.active_app.clone()))
                    .unwrap_or_default();
                if let Some(unit) = active_unit.as_deref() {
                    if new_config.apply_device_overrides(unit) {
                        tracing::info!(unit, "Per-device overrides applied on reload");
                    }
                }
                // The focused app's button overrides, as profiles.json has
                // them now (a Settings save may have just changed them).
                let hardware = crate::profiles::load_hardware_profiles();
                if let Some(app) = active_app {
                    let (buttons, custom) = hardware
                        .get(&app)
                        .map(|p| (p.buttons.clone(), p.custom.clone()))
                        .unwrap_or_default();
                    new_config.set_app_overrides(Some(app), buttons, custom);
                }
                let haptic_config = new_config.haptics.clone();
                if let Ok(mut gm) = self.gaming_mode.write() {
                    gm.apply_config(&new_config.gaming);
                }
                let thumbwheel_config = new_config.thumbwheel.clone();
                let remapped_cids = new_config.remapped_button_cids();
                // Extra controls (buttons.controls) from both the new and the
                // outgoing config, so a key that was removed still gets its
                // divert cleared below.
                let mut extra_cids = new_config.extra_control_cids();

                match self.config.write() {
                    Ok(mut config) => {
                        extra_cids.extend(config.extra_control_cids());
                        *config = new_config;
                        crate::keypad::refresh();
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

                        // Re-apply volatile thumb-wheel divert from the new
                        // config. Diverted modes (Volume/Zoom) invert in
                        // software (hidraw reader); native Horizontal Scroll
                        // inverts in hardware, so the invert byte must be
                        // pushed here too or a reload wipes it (issue #127).
                        if manager.thumbwheel_supported() {
                            match manager.set_thumbwheel_reporting(
                                thumbwheel_config.is_diverted(),
                                thumbwheel_config.hardware_invert(),
                            ) {
                                Ok(()) => tracing::info!(
                                    diverted = thumbwheel_config.is_diverted(),
                                    invert = thumbwheel_config.hardware_invert(),
                                    "Thumb-wheel reporting re-applied on reload"
                                ),
                                Err(e) => tracing::warn!(error = %e, "Failed to re-apply thumb-wheel reporting"),
                            }
                        }

                        // Re-apply non-gesture button diverts so a newly
                        // reassigned button takes effect immediately, and a
                        // button returned to its native default has its divert
                        // cleared, without a reconnect. Done under the manager
                        // lock on the zbus executor (no Tokio runtime here, so
                        // spawn_blocking is unavailable). The HID++ calls are
                        // quick when connected and return immediately when not.
                        let remapped: std::collections::HashSet<u16> =
                            remapped_cids.into_iter().collect();
                        // A macro-bound button stays diverted too, or a
                        // Settings save silenced the macro until a reconnect.
                        let macro_cids = self.trigger_map.read().map(|m| m.cids()).unwrap_or_default();
                        let mut managed: Vec<u16> = Config::managed_button_cids().to_vec();
                        managed.extend(extra_cids);
                        managed.sort_unstable();
                        managed.dedup();
                        for cid in managed {
                            let divert = remapped.contains(&cid) || macro_cids.contains(&cid);
                            let _ = manager.set_button_divert(cid, divert);
                        }

                        // Also re-divert the gesture and haptic buttons. Their
                        // divert is volatile and the mouse clears it on
                        // power-off / radio sleep (issue #102), so a Settings
                        // save doubles as a manual recovery without waiting
                        // for the next reconnect.
                        match manager.divert_buttons() {
                            Ok(n) if n > 0 => tracing::info!(
                                count = n,
                                "Gesture buttons re-diverted on reload"
                            ),
                            Ok(_) => {}
                            Err(e) => tracing::warn!(
                                error = %e,
                                "Failed to re-divert gesture buttons on reload"
                            ),
                        }
                    }
                    Err(e) => {
                        tracing::error!(error = %e, "Failed to lock haptic manager for update");
                        return Err(fdo::Error::Failed(format!("Haptic manager lock error: {}", e)));
                    }
                }

                // Refresh the shared per-app hardware profile map from
                // profiles.json so a UI save takes effect without a daemon
                // restart. The focus-change consumer reads this map directly.
                match self.hardware_profiles.write() {
                    Ok(mut map) => {
                        tracing::info!(count = hardware.len(), "Per-app hardware profiles reloaded");
                        *map = hardware;
                    }
                    Err(e) => {
                        tracing::error!(error = %e, "Failed to lock hardware profiles for reload");
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

    /// Called by the persistent KWin active-window script to report the focused
    /// window's resource class. Forwarded to the per-app hardware-profile
    /// consumer. The send is synchronous and never blocks the zbus executor.
    /// App profiles "Try now": act as if `class` were in front for `seconds`
    /// (at most 300), so its profile can be tried from Settings.
    async fn try_app_profile(&self, class: String, seconds: u32) -> fdo::Result<bool> {
        tracing::info!(%class, seconds, "Trying an app profile");
        Ok(crate::focus_trial::start(&class, seconds))
    }

    /// End an app profile trial now.
    async fn stop_app_profile_trial(&self) -> fdo::Result<bool> {
        Ok(crate::focus_trial::stop())
    }

    async fn report_active_window(&self, class: String) -> fdo::Result<()> {
        let class = class.to_lowercase();
        tracing::debug!(class = %class, "ReportActiveWindow called");
        if self.active_window_tx.send(class).is_err() {
            tracing::trace!("Active-window channel closed; no profile consumer");
        }
        Ok(())
    }

    /// Called by KWin script to report cursor position and show menu
    async fn show_menu_at_cursor(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        x: i32,
        y: i32,
    ) -> fdo::Result<()> {
        if self.gaming_mode.read().is_ok_and(|gm| gm.should_suppress_overlay()) {
            tracing::debug!(x, y, "ShowMenuAtCursor suppressed - gaming mode active");
            return Ok(());
        }
        tracing::info!(x, y, "ShowMenuAtCursor called from KWin script");
        Self::menu_requested(&emitter, x, y).await?;
        Ok(())
    }

    /// Get battery status from the device
    async fn get_battery_status(&self) -> fdo::Result<(u8, bool)> {
        let state = self.battery_state.read().await;
        // Report the last-known value when available, and also when a live
        // notification has populated a non-zero percentage even though the
        // active poll later failed (it clears `available` but keeps the cache).
        if state.available || state.percentage > 0 {
            Ok((state.percentage, state.charging))
        } else {
            Ok((0, false))
        }
    }

    // =========================================================================
    // DPI METHODS
    // =========================================================================

    async fn get_dpi(&self) -> fdo::Result<u16> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(manager.get_dpi().unwrap_or(0)),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_dpi");
                Ok(0)
            }
        }
    }

    async fn set_dpi(&self, dpi: u16) -> fdo::Result<()> {
        tracing::info!(dpi, "SetDpi called");

        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.set_dpi(dpi) {
                    Ok(()) => {
                        tracing::info!(dpi, "DPI set successfully");
                        // Settings speaks for pointer.dpi again.
                        crate::replay::set_session_dpi(None);
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

    /// Mouse reachability: (connected|asleep|away|offline, bolt|unifying|bluetooth|usb|unknown).
    async fn get_device_connection(&self) -> fdo::Result<(String, String)> {
        let (state, transport) = crate::link_state::current();
        Ok((state.as_str().to_string(), transport.as_str().to_string()))
    }

    /// What the connected mouse can do, from its HID++ feature table.
    /// Never touches the device; empty until a mouse has been seen.
    async fn get_capabilities(&self) -> fdo::Result<std::collections::HashMap<String, bool>> {
        match self.haptic_manager.lock() {
            Ok(manager) => Ok(manager.capabilities()),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_capabilities");
                Ok(std::collections::HashMap::new())
            }
        }
    }

    /// The sensor's settable DPI (lowest, highest, step, factory default);
    /// step 0 means the device lists discrete values, default 0 that it
    /// reports none. All zero while unknown.
    async fn get_dpi_range(&self) -> fdo::Result<(u16, u16, u16, u16)> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(manager.dpi_caps().map_or((0, 0, 0, 0), |c| (c.min, c.max, c.step, c.default))),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_dpi_range");
                Ok((0, 0, 0, 0))
            }
        }
    }

    async fn dpi_supported(&self) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(manager.dpi_supported()),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for dpi_supported");
                Ok(false)
            }
        }
    }

    // =========================================================================
    // SMARTSHIFT METHODS
    // =========================================================================

    async fn get_smart_shift(&self) -> fdo::Result<(bool, u8)> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(manager.get_smart_shift().unwrap_or((false, 0))),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_smart_shift");
                Ok((false, 0))
            }
        }
    }

    async fn set_smart_shift(&self, enabled: bool, threshold: u8) -> fdo::Result<()> {
        tracing::info!(enabled, threshold, "SetSmartShift called");

        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.set_smart_shift(enabled, threshold) {
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

    /// Modifier keys held right now ("ctrl", "shift", "alt", "super").
    async fn modifiers_held(&self) -> fdo::Result<Vec<String>> {
        Ok(tokio::task::spawn_blocking(crate::keyboard::modifiers_held).await.unwrap_or_default())
    }

    /// Bolt and Unifying receivers with their paired devices:
    /// [(hidraw path, "bolt" | "unifying", [(slot, kind, wpid, name, role)])],
    /// role "mouse" / "keyboard" for the devices JuhRadial drives, else "".
    async fn list_receivers(&self) -> fdo::Result<Vec<(String, String, Vec<(u8, u8, u16, String, String)>)>> {
        let mouse = self
            .haptic_manager
            .lock()
            .ok()
            .and_then(|m| Some((m.device_path()?, m.device_index()?)));
        let rows = tokio::task::spawn_blocking(move || {
            let keyboard = crate::keyboard::manager().lock().ok().and_then(|mut k| k.receiver_slot());
            crate::hidpp::device::HidppDevice::list_receivers()
                .into_iter()
                .map(|(path, bolt, devices)| {
                    let slots = devices
                        .into_iter()
                        .map(|d| {
                            let here = |who: &Option<(std::path::PathBuf, u8)>| {
                                who.as_ref().is_some_and(|(p, i)| p == &path && *i == d.slot)
                            };
                            let role = if here(&mouse) { "mouse" } else if here(&keyboard) { "keyboard" } else { "" };
                            (d.slot, d.kind, d.wpid, d.name, role.to_string())
                        })
                        .collect();
                    (path.display().to_string(), if bolt { "bolt" } else { "unifying" }.to_string(), slots)
                })
                .collect::<Vec<_>>()
        })
        .await
        .unwrap_or_default();
        Ok(rows)
    }

    /// Scroll force (0x2111 tunable torque): (supported, current %, default %).
    async fn get_scroll_force(&self) -> fdo::Result<(bool, u8, u8)> {
        Ok(self.haptic_manager.lock().map(|mut m| m.get_scroll_force()).unwrap_or((false, 0, 0)))
    }

    /// Set the scroll force in % (1..100); false when the wheel refused.
    async fn set_scroll_force(&self, percent: u8) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut m) => match m.set_scroll_force(percent) {
                Ok(()) => Ok(true),
                Err(e) => {
                    tracing::warn!(error = %e, percent, "Scroll force not set");
                    Ok(false)
                }
            },
            Err(_) => Ok(false),
        }
    }

    async fn smart_shift_supported(&self) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(manager.smartshift_supported()),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for smart_shift_supported");
                Ok(false)
            }
        }
    }

    // =========================================================================
    // HIRESSCROLL METHODS
    // =========================================================================

    async fn get_hiresscroll_mode(&self) -> fdo::Result<(bool, bool, bool)> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.get_hiresscroll_mode() {
                    Some((hires, invert, target)) => Ok((hires, invert, target)),
                    None => Ok((true, false, false))
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for get_hiresscroll_mode");
                Ok((true, false, false))
            }
        }
    }

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
    // THUMB-WHEEL METHODS
    // =========================================================================

    /// Enable/disable thumb-wheel divert (HID++ ThumbWheel 0x2150).
    ///
    /// This runs on the zbus executor, NOT tokio, so it locks the haptic
    /// manager and issues the volatile HID++ command inline (mirroring SetDpi).
    /// `divert` routes rotation to HID++ notifications; `invert` requests the
    /// device to flip reported direction.
    async fn set_thumbwheel_reporting(&self, divert: bool, invert: bool) -> fdo::Result<()> {
        tracing::info!(divert, invert, "SetThumbwheelReporting called");

        match self.haptic_manager.lock() {
            Ok(mut manager) => match manager.set_thumbwheel_reporting(divert, invert) {
                Ok(()) => {
                    tracing::info!(divert, invert, "Thumb-wheel reporting set");
                    Ok(())
                }
                Err(e) => {
                    tracing::error!(error = %e, divert, invert, "Failed to set thumb-wheel reporting");
                    Err(fdo::Error::Failed(format!(
                        "Failed to set thumb-wheel reporting: {}",
                        e
                    )))
                }
            },
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for set_thumbwheel_reporting");
                Err(fdo::Error::Failed(format!("Lock error: {}", e)))
            }
        }
    }

    async fn thumbwheel_supported(&self) -> fdo::Result<bool> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(manager.thumbwheel_supported()),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for thumbwheel_supported");
                Ok(false)
            }
        }
    }

    // =========================================================================
    // EASY-SWITCH METHODS
    // =========================================================================

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

    /// Every Easy-Switch slot: (status 1 = paired, bus type, computer name).
    async fn get_host_slots(&self) -> fdo::Result<Vec<(u8, u8, String)>> {
        let (slots, current) = match self.haptic_manager.lock() {
            Ok(mut m) => (m.host_slots(), m.get_easy_switch_info().map(|(_, c)| c)),
            Err(_) => (Vec::new(), None),
        };
        crate::easy_switch::remember_mouse(slots.clone(), current);
        Ok(slots.into_iter().map(|s| (s.status, s.bus, s.name)).collect())
    }

    async fn set_host(&self, host_index: u8) -> fdo::Result<bool> {
        let together = self.config.read().map(|c| c.keyboard.mx_keys.move_together).unwrap_or(false);
        let keyboard_to = if together { crate::easy_switch::mouse_sent(host_index) } else { None };
        match self.haptic_manager.lock() {
            Ok(mut manager) => {
                match manager.set_current_host(host_index) {
                    Ok(()) => {
                        tracing::info!(host_index, "Switched to Easy-Switch host");
                        crate::link_state::report(crate::link_state::LinkState::Away, None);
                        if let Some(slot) = keyboard_to {
                            crate::easy_switch::move_keyboard(slot);
                        }
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
    // MACRO METHODS
    // =========================================================================

    async fn start_macro_recording(&self) -> fdo::Result<()> {
        tracing::info!("StartMacroRecording called");

        match self.macro_recorder.lock() {
            Ok(mut recorder) => {
                match recorder.start() {
                    Ok(()) => {
                        tracing::info!("Macro recording started");
                        Ok(())
                    }
                    Err(e) => {
                        tracing::error!(error = %e, "Failed to start recording");
                        Err(fdo::Error::Failed(format!("Recording failed: {}", e)))
                    }
                }
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock macro recorder");
                Err(fdo::Error::Failed(format!("Lock error: {}", e)))
            }
        }
    }

    async fn stop_macro_recording(&self) -> fdo::Result<String> {
        tracing::info!("StopMacroRecording called");

        match self.macro_recorder.lock() {
            Ok(mut recorder) => {
                let events = recorder.stop();
                let actions = events_to_actions(&events);

                tracing::info!(
                    event_count = events.len(),
                    action_count = actions.len(),
                    "Macro recording stopped"
                );

                let result = serde_json::json!({
                    "events": events,
                    "actions": actions,
                });

                serde_json::to_string(&result)
                    .map_err(|e| fdo::Error::Failed(format!("JSON serialization error: {}", e)))
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock macro recorder");
                Err(fdo::Error::Failed(format!("Lock error: {}", e)))
            }
        }
    }

    /// Live view of a recording: (recording, keyboards, captured events JSON).
    async fn get_recording_status(&self) -> fdo::Result<(bool, Vec<String>, String)> {
        let recorder = self
            .macro_recorder
            .lock()
            .map_err(|e| fdo::Error::Failed(format!("Lock error: {}", e)))?;
        let events = serde_json::to_string(&recorder.current_events())
            .map_err(|e| fdo::Error::Failed(format!("JSON error: {}", e)))?;
        Ok((recorder.is_recording(), recorder.devices().to_vec(), events))
    }

    async fn execute_macro(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        id: String,
    ) -> fdo::Result<()> {
        tracing::info!(id = %id, "ExecuteMacro called");

        let config = crate::macros::storage::load_macro(&id)
            .map_err(|e| fdo::Error::Failed(format!("Failed to load macro: {}", e)))?;

        let macro_id = config.id.clone();
        {
            let mut engine = self.macro_engine.lock()
                .map_err(|e| fdo::Error::Failed(format!("Lock error: {}", e)))?;
            engine.execute(config);
        }

        Self::macro_playback_started(&emitter, macro_id).await?;
        Ok(())
    }

    async fn execute_macro_inline(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        json: String,
    ) -> fdo::Result<()> {
        tracing::info!("ExecuteMacroInline called");

        let config: crate::macros::MacroConfig = serde_json::from_str(&json)
            .map_err(|e| fdo::Error::Failed(format!("Invalid macro JSON: {}", e)))?;

        let macro_id = config.id.clone();
        {
            let mut engine = self.macro_engine.lock()
                .map_err(|e| fdo::Error::Failed(format!("Lock error: {}", e)))?;
            engine.execute(config);
        }

        Self::macro_playback_started(&emitter, macro_id).await?;
        Ok(())
    }

    async fn stop_macro(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
    ) -> fdo::Result<()> {
        tracing::info!("StopMacro called");

        {
            let mut engine = self.macro_engine.lock()
                .map_err(|e| fdo::Error::Failed(format!("Lock error: {}", e)))?;
            engine.stop();
        }

        Self::macro_playback_stopped(&emitter, String::new()).await?;
        Ok(())
    }

    async fn save_macro(&self, json: String) -> fdo::Result<()> {
        tracing::info!("SaveMacro called");

        let config: crate::macros::MacroConfig = serde_json::from_str(&json)
            .map_err(|e| fdo::Error::Failed(format!("Invalid macro JSON: {}", e)))?;

        crate::macros::storage::save_macro(&config)
            .map_err(|e| fdo::Error::Failed(format!("Failed to save macro: {}", e)))?;

        tracing::info!(id = %config.id, name = %config.name, "Macro saved via D-Bus");
        Ok(())
    }

    async fn delete_macro(&self, id: String) -> fdo::Result<()> {
        tracing::info!(id = %id, "DeleteMacro called");

        crate::macros::storage::delete_macro(&id)
            .map_err(|e| fdo::Error::Failed(format!("Failed to delete macro: {}", e)))?;

        Ok(())
    }

    async fn list_macros(&self) -> fdo::Result<String> {
        let macros = crate::macros::storage::load_all_macros()
            .map_err(|e| fdo::Error::Failed(format!("Failed to load macros: {}", e)))?;

        let list: Vec<&crate::macros::MacroConfig> = macros.values().collect();
        serde_json::to_string(&list)
            .map_err(|e| fdo::Error::Failed(format!("JSON error: {}", e)))
    }

    async fn is_macro_running(&self) -> fdo::Result<bool> {
        match self.macro_engine.lock() {
            Ok(engine) => Ok(engine.is_running()),
            Err(_) => Ok(false),
        }
    }

    /// Reload macro trigger bindings from disk
    async fn reload_macro_triggers(&self) -> fdo::Result<()> {
        tracing::info!("ReloadMacroTriggers called");

        let (before, after) = match self.trigger_map.write() {
            Ok(mut map) => {
                let before = map.cids();
                map.reload();
                tracing::info!("Macro trigger map reloaded");
                (before, map.cids())
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock trigger map for reload");
                return Err(fdo::Error::Failed(format!("Lock error: {}", e)));
            }
        };
        // Divert a newly bound button now (it used to take a daemon restart,
        // and until then the button also did its own thing), and give an
        // unbound one back unless it is remapped.
        if before != after {
            let remapped: std::collections::HashSet<u16> = self
                .config
                .read()
                .map(|c| c.remapped_button_cids().into_iter().collect())
                .unwrap_or_default();
            if let Ok(mut manager) = self.haptic_manager.lock() {
                for cid in after.difference(&before) {
                    let _ = manager.set_button_divert(*cid, true);
                }
                for cid in before.difference(&after).filter(|c| !remapped.contains(c)) {
                    let _ = manager.set_button_divert(*cid, false);
                }
            }
        }
        Ok(())
    }

    // =========================================================================
    // MACRO SIGNALS
    // =========================================================================

    #[zbus(signal)]
    async fn macro_playback_started(emitter: &SignalEmitter<'_>, id: String) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn macro_playback_stopped(emitter: &SignalEmitter<'_>, id: String) -> zbus::Result<()>;

    // =========================================================================
    // GAMING MODE METHODS
    // =========================================================================

    async fn set_gaming_mode(
        &self,
        #[zbus(signal_emitter)] emitter: SignalEmitter<'_>,
        enabled: bool,
    ) -> fdo::Result<()> {
        tracing::info!(enabled, "SetGamingMode called");

        {
            let mut gm = self.gaming_mode.write()
                .map_err(|e| fdo::Error::Failed(format!("Lock error: {}", e)))?;
            if enabled {
                gm.enable();
            } else {
                gm.disable();
            }
        }

        Self::gaming_mode_changed(&emitter, enabled).await?;
        Ok(())
    }

    /// Gaming mode for Settings' status line: (on, turned on automatically,
    /// active preset 1-based, its DPI, Feral GameMode installed, a game
    /// registered with GameMode).
    async fn get_gaming_status(&self) -> fdo::Result<(bool, bool, u32, u16, bool, bool)> {
        match self.gaming_mode.read() {
            Ok(gm) => {
                let (gm_installed, gm_active) = gm.gamemode_state();
                Ok((
                    gm.is_enabled(),
                    gm.auto_engaged(),
                    gm.stage().0 as u32 + 1,
                    gm.active_dpi().unwrap_or(0),
                    gm_installed,
                    gm_active,
                ))
            }
            Err(_) => Ok((false, false, 0, 0, false, false)),
        }
    }

    async fn get_gaming_mode(&self) -> fdo::Result<bool> {
        match self.gaming_mode.read() {
            Ok(gm) => Ok(gm.is_enabled()),
            Err(_) => Ok(false),
        }
    }

    async fn cycle_gaming_dpi(&self) -> fdo::Result<String> {
        match self.gaming_mode.write() {
            Ok(mut gm) => Ok(gm.cycle_dpi().unwrap_or_default()),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock gaming mode for DPI cycle");
                Ok(String::new())
            }
        }
    }

    #[zbus(signal)]
    async fn gaming_mode_changed(emitter: &SignalEmitter<'_>, enabled: bool) -> zbus::Result<()>;

    // =========================================================================
    // DEVICE MODE METHODS
    // =========================================================================

    async fn get_device_mode(&self) -> fdo::Result<String> {
        Ok(self.device_mode.clone())
    }

    async fn get_device_name(&self) -> fdo::Result<String> {
        Ok(self.device_name.read().await.clone())
    }

    // =========================================================================
    // KEYBOARD METHODS (BETA, opt-in) - consumed by the Qt settings app
    //
    // All three are safe no-ops on a mouse-only system. The HID++ paths only
    // run when the user has enabled MX Keys S support; locking the std Mutex and
    // issuing the request inline mirrors the existing SetDpi / GetDpi handlers
    // (these run on the zbus executor, not Tokio).
    // =========================================================================

    /// Unit id of the connected mouse as the `devices` config key
    /// ("0x1234ABCD"), or "" when unknown.
    async fn get_unit_id(&self) -> fdo::Result<String> {
        match self.haptic_manager.lock() {
            Ok(manager) => Ok(manager.unit_id().map(Config::unit_key).unwrap_or_default()),
            Err(_) => Ok(String::new()),
        }
    }

    /// The connected mouse's REPROG_CONTROLS_V4 inventory as a JSON array:
    /// one object per control with `cid`, `hex`, `name` and the decoded
    /// capability bits (see `hidpp::controls`). `[]` without a device or the
    /// feature. Read-only on the device; the scan is cached per connection.
    async fn list_controls(&self) -> fdo::Result<String> {
        match self.haptic_manager.lock() {
            Ok(mut manager) => Ok(crate::hidpp::controls::controls_to_json(&manager.list_controls())),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock haptic manager for list_controls");
                Ok("[]".to_string())
            }
        }
    }

    /// Every plugin folder under ~/.config/juhradial/plugins as JSON: name,
    /// version, description, author, actions (`ref`, `id`, `label`, `icon`,
    /// `kind` and its parameters), and `error` for a folder that failed to
    /// load. Read from disk on each call, so new plugins need no restart.
    async fn list_plugins(&self) -> fdo::Result<String> {
        let plugins = crate::plugins::load_all(&crate::plugins::plugins_dir());
        serde_json::to_string(&plugins).map_err(|e| fdo::Error::Failed(format!("JSON error: {}", e)))
    }

    /// Run the plugin action `<folder>/<id>`. False when it does not exist or
    /// could not be started (the reason is in the journal).
    async fn run_plugin_action(&self, reference: String) -> fdo::Result<bool> {
        match crate::plugins::run(&crate::plugins::plugins_dir(), &reference).await {
            Ok(()) => Ok(true),
            Err(e) => {
                tracing::warn!(plugin_action = %reference, error = %e, "Plugin action failed");
                Ok(false)
            }
        }
    }

    /// Battery for an MX Keys S keyboard: `(percent, charging)`.
    ///
    /// Returns `(0, false)` unless `keyboard.mx_keys.enabled` is true and a
    /// keyboard is present. Never panics on a mouse-only system.
    async fn get_keyboard_battery(&self) -> fdo::Result<(u8, bool)> {
        let enabled = self
            .config
            .read()
            .map(|c| c.keyboard.mx_keys.enabled)
            .unwrap_or(false);
        if !enabled {
            return Ok((0, false));
        }
        match crate::keyboard::manager().lock() {
            Ok(mut mgr) => Ok(mgr.query_battery().unwrap_or((0, false))),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock keyboard manager for battery");
                Ok((0, false))
            }
        }
    }

    /// Whether a keyboard is paired to a connected receiver.
    ///
    /// Answered from the receiver's pairing table, so it stays `true` while
    /// the keyboard's radio deep-sleeps (when `GetKeyboardBattery` returns
    /// `(0, false)` because the keyboard ignores pings until a key wakes it).
    /// While `keyboard.mx_keys.enabled` is false only the passive register
    /// read runs (never fake-arrival), so Settings can offer to turn it on.
    async fn get_keyboard_paired(&self) -> fdo::Result<bool> {
        let enabled = self
            .config
            .read()
            .map(|c| c.keyboard.mx_keys.enabled)
            .unwrap_or(false);
        match crate::keyboard::manager().lock() {
            Ok(mut mgr) => Ok(if enabled { mgr.keyboard_paired() } else { mgr.keyboard_detected() }),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock keyboard manager for presence");
                Ok(false)
            }
        }
    }

    /// Set MX Keys S backlight brightness (0..=100). BETA.
    ///
    /// No-op returning `false` unless `keyboard.mx_keys.enabled` is true and a
    /// keyboard exposing BACKLIGHT2 is present. Verified on an MX Keys S over
    /// Bolt (see `HidppDevice::set_backlight`); it only runs on this explicit
    /// call.
    async fn set_keyboard_backlight(&self, brightness: u8) -> fdo::Result<bool> {
        let enabled = self
            .config
            .read()
            .map(|c| c.keyboard.mx_keys.enabled)
            .unwrap_or(false);
        if !enabled {
            tracing::info!("SetKeyboardBacklight ignored - MX Keys S support disabled");
            return Ok(false);
        }
        match crate::keyboard::manager().lock() {
            Ok(mut mgr) => Ok(mgr.set_backlight(brightness)),
            Err(e) => {
                tracing::error!(error = %e, "Failed to lock keyboard manager for backlight");
                Ok(false)
            }
        }
    }

    /// MX Keys S backlight: `(ok, enabled, mode, level, levels, status,
    /// automatic_supported, away_s, near_s, powered_s)`. `mode` 1 = Automatic,
    /// 2 = set by the keyboard's keys, 3 = Manual; `level` is what is lit now
    /// (0..levels-1); `status` 0xFF = unknown; durations in seconds. `ok` is
    /// false while support is off or the keyboard is absent or asleep.
    /// READ-ONLY.
    #[allow(clippy::type_complexity)]
    async fn get_keyboard_backlight(&self) -> fdo::Result<(bool, bool, u8, u8, u8, u8, bool, u16, u16, u16)> {
        let none = (false, false, 0, 0, 0, 0xFF, false, 0, 0, 0);
        if !self.keyboard_enabled() {
            return Ok(none);
        }
        let state = match crate::keyboard::manager().lock() {
            Ok(mut mgr) => mgr.backlight_state(),
            Err(_) => None,
        };
        Ok(state.map_or(none, |b| {
            (
                true,
                b.enabled,
                b.mode,
                b.level,
                b.levels,
                b.status.unwrap_or(0xFF),
                b.automatic_supported(),
                b.dho.saturating_mul(5),
                b.dhi.saturating_mul(5),
                b.dpow.saturating_mul(5),
            )
        }))
    }

    /// Automatic (`true`, the light sensor sets the level) or Manual backlight.
    /// A stored keyboard setting, written only on this explicit call. BETA.
    async fn set_keyboard_backlight_mode(&self, automatic: bool) -> fdo::Result<bool> {
        if !self.keyboard_enabled() {
            return Ok(false);
        }
        Ok(crate::keyboard::manager()
            .lock()
            .map(|mut mgr| mgr.set_backlight_mode(automatic))
            .unwrap_or(false))
    }

    /// How long the backlight stays on, in seconds (5..7200, 0 = unchanged):
    /// hands away from the keys, hands near them, on a cable. BETA.
    async fn set_keyboard_backlight_durations(&self, away_s: u16, near_s: u16, powered_s: u16) -> fdo::Result<bool> {
        if !self.keyboard_enabled() {
            return Ok(false);
        }
        Ok(crate::keyboard::manager()
            .lock()
            .map(|mut mgr| mgr.set_backlight_durations(away_s, near_s, powered_s))
            .unwrap_or(false))
    }

    /// The connected mouse's main firmware versions ("RBM 27.00.B0015"),
    /// empty without a device. READ-ONLY, cached per connection.
    async fn get_firmware(&self) -> fdo::Result<Vec<String>> {
        Ok(self
            .haptic_manager
            .lock()
            .map(|mut m| m.firmware())
            .unwrap_or_default())
    }

    /// List the evdev key codes (decimal strings) of the first physical
    /// keyboard, for the settings UI to populate a remap picker. READ-ONLY: it
    /// never grabs the keyboard. Empty when none is found.
    async fn list_keyboard_keys(&self) -> fdo::Result<Vec<String>> {
        Ok(crate::keyboard::list_keyboard_key_codes())
    }

    // =========================================================================
    // PROPERTIES
    // =========================================================================

    #[zbus(property)]
    async fn current_profile(&self) -> &str {
        &self.current_profile
    }

    #[zbus(property)]
    async fn haptics_enabled(&self) -> bool {
        self.config
            .read()
            .map(|c| c.haptics.enabled)
            .unwrap_or(true)
    }

    #[zbus(property)]
    async fn daemon_version(&self) -> &str {
        &self.version
    }

    #[zbus(property)]
    async fn device_mode(&self) -> &str {
        &self.device_mode
    }

    #[zbus(property)]
    async fn device_name(&self) -> String {
        self.device_name.read().await.clone()
    }

    #[zbus(property)]
    async fn gaming_mode_enabled(&self) -> bool {
        self.gaming_mode
            .read()
            .map(|gm| gm.is_enabled())
            .unwrap_or(false)
    }
}
