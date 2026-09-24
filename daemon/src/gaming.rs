//! Gaming mode for JuhRadial MX
//!
//! When gaming mode is enabled:
//! - The overlay (radial menu) is suppressed (no MenuRequested signals)
//! - A gaming DPI profile is applied
//! - Macro bindings can be used instead of radial menu actions
//!
//! When gaming mode is disabled:
//! - Normal overlay behavior resumes
//! - Original DPI is restored
//!
//! Gaming mode state is managed here and queried by the D-Bus service
//! to decide whether to emit MenuRequested signals.

use std::sync::{Arc, RwLock};

use crate::config::{ButtonAction, GamingConfig};
use crate::hidpp::SharedHapticManager;
use crate::macros::dpi::{DpiManager, DpiProfile};

/// What can turn gaming mode on by itself.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AutoSource {
    /// Feral GameMode has a registered game.
    GameMode,
    /// An app on `gaming.auto_apps` is in front.
    App,
}

// ============================================================================
// Gaming Mode
// ============================================================================

/// Gaming mode state
pub struct GamingMode {
    /// Whether gaming mode is currently enabled
    enabled: bool,

    /// Whether to suppress overlay (MenuRequested signals)
    suppress_overlay: bool,

    /// DPI manager for gaming DPI profiles
    dpi_manager: DpiManager,

    /// Reference to the HID++ device manager
    haptic_manager: SharedHapticManager,

    /// Settings > Gaming (presets, ring button, wheel lock, automatic mode)
    config: GamingConfig,

    /// Wheel state to put back when gaming mode ends (wheel lock).
    saved_wheel: Option<(bool, u8)>,

    /// Automatic sources that are active right now, and whether they (not
    /// the user) turned gaming mode on.
    gamemode_active: bool,
    gamemode_installed: bool,
    auto_app_active: bool,
    auto_engaged: bool,
}

impl GamingMode {
    /// Create a new gaming mode instance
    pub fn new(haptic_manager: SharedHapticManager) -> Self {
        Self {
            enabled: false,
            suppress_overlay: true,
            dpi_manager: DpiManager::new(),
            haptic_manager,
            config: GamingConfig::default(),
            saved_wheel: None,
            gamemode_active: false,
            gamemode_installed: false,
            auto_app_active: false,
            auto_engaged: false,
        }
    }

    /// Take Settings > Gaming: presets, active preset, ring, wheel, automatic
    /// mode. While gaming mode is on, a new active DPI is written at once.
    pub fn apply_config(&mut self, config: &GamingConfig) {
        let before = self.active_dpi();
        self.suppress_overlay = config.suppress_overlay;
        let presets: Vec<DpiProfile> = config
            .dpi_profiles
            .iter()
            .filter(|p| p.dpi > 0)
            .take(5)
            .map(|p| DpiProfile::new(p.name.clone(), p.dpi))
            .collect();
        if !presets.is_empty() {
            let last = presets.len() - 1;
            self.dpi_manager.set_profiles(presets);
            self.dpi_manager.set_active_index(config.active_dpi_profile.min(last));
        }
        self.config = config.clone();
        if self.enabled && self.active_dpi() != before {
            if let Err(e) = self.dpi_manager.apply_active(&self.haptic_manager) {
                tracing::warn!(error = %e, "Failed to apply the new gaming DPI preset");
            }
        }
    }

    /// What the ring button does while gaming mode is on (None = its
    /// normal job, or nothing when the ring is hidden).
    pub fn ring_action(&self) -> Option<ButtonAction> {
        if self.enabled {
            self.config.ring_action()
        } else {
            None
        }
    }

    /// Whether automatic mode (not the user) turned gaming mode on.
    pub fn auto_engaged(&self) -> bool {
        self.auto_engaged
    }

    /// (Feral GameMode installed, a game registered with it).
    pub fn gamemode_state(&self) -> (bool, bool) {
        (self.gamemode_installed, self.gamemode_active)
    }

    /// The GameMode watcher saw gamemoded installed (activatable) or not.
    pub fn set_gamemode_installed(&mut self, installed: bool) {
        self.gamemode_installed = installed;
    }

    /// Whether preset changes pulse once per stage.
    pub fn dpi_pulse(&self) -> bool {
        self.config.dpi_pulse
    }

    /// The active preset's position (0-based) and the number of presets.
    pub fn stage(&self) -> (usize, usize) {
        self.dpi_manager.stage()
    }

    /// An automatic source changed. Turns gaming mode on when a source
    /// becomes active and off again only if a source turned it on. Returns
    /// the new state when it flipped.
    pub fn set_auto(&mut self, source: AutoSource, active: bool) -> Option<bool> {
        match source {
            AutoSource::GameMode => self.gamemode_active = active,
            AutoSource::App => self.auto_app_active = active,
        }
        let want = (self.config.auto_gamemode && self.gamemode_active) || self.auto_app_active;
        if want && !self.enabled {
            self.enable();
            self.auto_engaged = true;
            return Some(true);
        }
        if !want && self.enabled && self.auto_engaged {
            self.disable();
            return Some(false);
        }
        None
    }

    /// Hold the wheel in one mode while gaming (weapon switching wants
    /// notches); `restore` puts back what it was.
    fn lock_wheel(&mut self, restore: bool) {
        let Ok(mut m) = self.haptic_manager.lock() else { return };
        if restore {
            if let Some((on, thr)) = self.saved_wheel.take() {
                let _ = m.set_smart_shift(on, thr);
            }
            return;
        }
        let want = match self.config.wheel.as_str() {
            "ratchet" => (false, 0),
            "freespin" => (true, 0),
            _ => return,
        };
        self.saved_wheel = m.get_smart_shift();
        if let Err(e) = m.set_smart_shift(want.0, want.1) {
            tracing::warn!(error = %e, "Gaming wheel lock failed");
        }
    }

    /// Enable gaming mode
    ///
    /// Saves current DPI, applies gaming DPI profile, and sets the
    /// suppress_overlay flag so MenuRequested signals are not emitted.
    pub fn enable(&mut self) {
        if self.enabled {
            tracing::debug!("Gaming mode already enabled");
            return;
        }
        // Haptics stay quiet in games unless haptics.mute_in_games is off.
        if let Ok(mut m) = self.haptic_manager.lock() {
            m.set_gaming_active(true);
        }

        tracing::info!("Enabling gaming mode");

        // Save current DPI before switching
        self.dpi_manager.save_current_dpi(&self.haptic_manager);

        self.lock_wheel(false);
        // Apply gaming DPI profile
        if let Err(e) = self.dpi_manager.apply_active(&self.haptic_manager) {
            tracing::warn!(error = %e, "Failed to apply gaming DPI profile");
        }

        self.enabled = true;

        tracing::info!(
            dpi_profile = ?self.dpi_manager.active_profile().map(|p| &p.name),
            "Gaming mode enabled"
        );
    }

    /// Disable gaming mode
    ///
    /// Restores the saved DPI and re-enables overlay signals.
    pub fn disable(&mut self) {
        if !self.enabled {
            tracing::debug!("Gaming mode already disabled");
            return;
        }
        if let Ok(mut m) = self.haptic_manager.lock() {
            m.set_gaming_active(false);
        }

        tracing::info!("Disabling gaming mode");

        self.auto_engaged = false;
        self.lock_wheel(true);
        // Restore saved DPI
        if let Err(e) = self.dpi_manager.restore_saved_dpi(&self.haptic_manager) {
            tracing::warn!(error = %e, "Failed to restore saved DPI");
        }

        self.enabled = false;

        tracing::info!("Gaming mode disabled - overlay resumed");
    }

    /// Check if gaming mode is enabled
    /// DPI of the active gaming preset while gaming mode is on.
    pub fn active_dpi(&self) -> Option<u16> {
        if !self.enabled {
            return None;
        }
        self.dpi_manager.active_profile().map(|p| p.dpi)
    }

    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Check if overlay should be suppressed
    ///
    /// When true, the D-Bus service should NOT emit MenuRequested signals.
    pub fn should_suppress_overlay(&self) -> bool {
        self.enabled && self.suppress_overlay
    }

    /// Set whether overlay is suppressed in gaming mode
    pub fn set_suppress_overlay(&mut self, suppress: bool) {
        self.suppress_overlay = suppress;
    }

    /// Get a reference to the DPI manager
    pub fn dpi_manager(&self) -> &DpiManager {
        &self.dpi_manager
    }

    /// Get a mutable reference to the DPI manager
    pub fn dpi_manager_mut(&mut self) -> &mut DpiManager {
        &mut self.dpi_manager
    }

    /// Cycle to the next DPI profile (used for DPI cycling hotkey)
    pub fn cycle_dpi(&mut self) -> Option<String> {
        match self.dpi_manager.cycle_next(&self.haptic_manager) {
            Ok(profile) => {
                let name = profile.name.clone();
                tracing::info!(profile = %name, dpi = profile.dpi, "DPI cycled");
                Some(name)
            }
            Err(e) => {
                tracing::warn!(error = %e, "Failed to cycle DPI");
                None
            }
        }
    }
}

// ============================================================================
// Shared Gaming Mode
// ============================================================================

/// Thread-safe shared gaming mode state
pub type SharedGamingMode = Arc<RwLock<GamingMode>>;

/// Whether a gesture press belongs to the game's ring job (run by the main
/// loop's Pressed branch) rather than the menu. The KWin cursor script opens
/// the menu directly, so the input handlers skip it while this holds.
pub fn ring_job_active(gaming: Option<&SharedGamingMode>) -> bool {
    gaming.is_some_and(|g| g.read().is_ok_and(|g| g.ring_action().is_some()))
}

/// Create a new shared gaming mode instance
pub fn new_shared_gaming_mode(haptic_manager: SharedHapticManager) -> SharedGamingMode {
    Arc::new(RwLock::new(GamingMode::new(haptic_manager)))
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::HapticConfig;
    use crate::hidpp::new_shared_haptic_manager;

    fn test_haptic_manager() -> SharedHapticManager {
        let config = HapticConfig::default();
        new_shared_haptic_manager(&config)
    }

    #[test]
    fn ring_job_takes_the_press_only_in_a_game_with_a_ring_job() {
        let gm = new_shared_gaming_mode(test_haptic_manager());
        assert!(!ring_job_active(None));
        assert!(!ring_job_active(Some(&gm)));
        let cfg = crate::config::GamingConfig { ring_button: "dpi_shift".into(), ..Default::default() };
        gm.write().unwrap().apply_config(&cfg);
        assert!(!ring_job_active(Some(&gm)), "not in a game yet");
        gm.write().unwrap().enable();
        assert!(ring_job_active(Some(&gm)));
    }

    #[test]
    fn test_gaming_mode_creation() {
        let hm = test_haptic_manager();
        let gm = GamingMode::new(hm);
        assert!(!gm.is_enabled());
        assert!(!gm.should_suppress_overlay()); // Not enabled, so no suppression
    }

    #[test]
    fn test_gaming_mode_enable_disable() {
        let hm = test_haptic_manager();
        let mut gm = GamingMode::new(hm);

        gm.enable();
        assert!(gm.is_enabled());
        assert!(gm.should_suppress_overlay());

        gm.disable();
        assert!(!gm.is_enabled());
        assert!(!gm.should_suppress_overlay());
    }

    #[test]
    fn test_gaming_mode_double_enable() {
        let hm = test_haptic_manager();
        let mut gm = GamingMode::new(hm);

        gm.enable();
        gm.enable(); // Should be a no-op
        assert!(gm.is_enabled());
    }

    #[test]
    fn test_gaming_mode_double_disable() {
        let hm = test_haptic_manager();
        let mut gm = GamingMode::new(hm);

        gm.disable(); // Already disabled, should be a no-op
        assert!(!gm.is_enabled());
    }

    #[test]
    fn test_suppress_overlay_toggle() {
        let hm = test_haptic_manager();
        let mut gm = GamingMode::new(hm);

        gm.enable();
        assert!(gm.should_suppress_overlay());

        gm.set_suppress_overlay(false);
        assert!(!gm.should_suppress_overlay());

        gm.set_suppress_overlay(true);
        assert!(gm.should_suppress_overlay());
    }

    #[test]
    fn test_dpi_manager_access() {
        let hm = test_haptic_manager();
        let gm = GamingMode::new(hm);
        assert!(!gm.dpi_manager().profiles().is_empty());
    }

    #[test]
    fn test_shared_gaming_mode() {
        let hm = test_haptic_manager();
        let sgm = new_shared_gaming_mode(hm);

        {
            let gm = sgm.read().unwrap();
            assert!(!gm.is_enabled());
        }

        {
            let mut gm = sgm.write().unwrap();
            gm.enable();
        }

        {
            let gm = sgm.read().unwrap();
            assert!(gm.is_enabled());
        }
    }

    #[test]
    fn settings_reach_gaming_mode() {
        let hm = test_haptic_manager();
        let mut gm = GamingMode::new(hm);
        let json = r#"{"suppress_overlay": false, "active_dpi_profile": 2, "ring_button": "dpi_cycle",
            "dpi_profiles": [{"name": "A", "dpi": 500}, {"name": "B", "dpi": 900}, {"name": "C", "dpi": 2000}]}"#;
        let cfg: GamingConfig = serde_json::from_str(json).unwrap();
        gm.apply_config(&cfg);
        assert_eq!(gm.stage(), (2, 3));
        assert_eq!(gm.ring_action(), None); // off: the ring does its normal job
        gm.enable();
        assert!(!gm.should_suppress_overlay()); // "Show the radial menu in games" on
        assert_eq!(gm.active_dpi(), Some(2000));
        assert_eq!(gm.ring_action(), Some(ButtonAction::DpiCycle));
        // an out-of-range preset index lands on the last preset
        let cfg = GamingConfig { active_dpi_profile: 9, ..cfg };
        gm.apply_config(&cfg);
        assert_eq!(gm.stage().0, 2);
    }

    #[test]
    fn automatic_mode_only_undoes_what_it_did() {
        let hm = test_haptic_manager();
        let mut gm = GamingMode::new(hm);
        gm.apply_config(&GamingConfig { auto_gamemode: true, ..GamingConfig::default() });
        assert_eq!(gm.set_auto(AutoSource::GameMode, true), Some(true));
        assert!(gm.is_enabled() && gm.auto_engaged());
        assert_eq!(gm.set_auto(AutoSource::GameMode, false), Some(false));
        assert!(!gm.is_enabled());
        // the user turned it on by hand: a game ending does not turn it off
        gm.enable();
        assert_eq!(gm.set_auto(AutoSource::GameMode, true), None);
        assert_eq!(gm.set_auto(AutoSource::GameMode, false), None);
        assert!(gm.is_enabled());
        gm.disable();
        // GameMode is ignored unless its switch is on; listed apps always count
        gm.apply_config(&GamingConfig::default());
        assert_eq!(gm.set_auto(AutoSource::GameMode, true), None);
        assert_eq!(gm.set_auto(AutoSource::App, true), Some(true));
        assert_eq!(gm.set_auto(AutoSource::App, false), Some(false));
    }
}
