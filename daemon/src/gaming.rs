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

use crate::hidpp::SharedHapticManager;
use crate::macros::dpi::DpiManager;

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
}

impl GamingMode {
    /// Create a new gaming mode instance
    pub fn new(haptic_manager: SharedHapticManager) -> Self {
        Self {
            enabled: false,
            suppress_overlay: true,
            dpi_manager: DpiManager::new(),
            haptic_manager,
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

        tracing::info!("Enabling gaming mode");

        // Save current DPI before switching
        self.dpi_manager.save_current_dpi(&self.haptic_manager);

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

        tracing::info!("Disabling gaming mode");

        // Restore saved DPI
        if let Err(e) = self.dpi_manager.restore_saved_dpi(&self.haptic_manager) {
            tracing::warn!(error = %e, "Failed to restore saved DPI");
        }

        self.enabled = false;

        tracing::info!("Gaming mode disabled - overlay resumed");
    }

    /// Check if gaming mode is enabled
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
}
