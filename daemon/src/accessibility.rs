//! Accessibility settings detection
//!
//! Story 4.6: Reduced Motion Support
//!
//! Detects system accessibility preferences including:
//! - Reduced motion / animation preferences
//! - High contrast mode (for Story 4.5)

use std::env;

/// Accessibility settings for the application
#[derive(Debug, Clone, Default)]
pub struct AccessibilitySettings {
    /// User override for reduced motion (None = follow system)
    pub reduced_motion_override: Option<bool>,

    /// Detected system preference for reduced motion
    system_prefers_reduced_motion: bool,

    /// User override for high contrast (None = follow system)
    pub high_contrast_override: Option<bool>,

    /// Detected system preference for high contrast
    system_prefers_high_contrast: bool,
}

impl AccessibilitySettings {
    /// Create new accessibility settings with system detection
    pub fn new() -> Self {
        let mut settings = Self::default();
        settings.detect_system_preferences();
        settings
    }

    /// Detect system accessibility preferences
    pub fn detect_system_preferences(&mut self) {
        // Check GTK_ENABLE_ANIMATIONS environment variable (Task 1.3)
        if let Ok(val) = env::var("GTK_ENABLE_ANIMATIONS") {
            if val == "0" || val.to_lowercase() == "false" {
                self.system_prefers_reduced_motion = true;
                tracing::info!("Detected reduced motion from GTK_ENABLE_ANIMATIONS=0");
            }
        }

        // Check NO_ANIMATIONS environment variable
        if env::var("NO_ANIMATIONS").is_ok() {
            self.system_prefers_reduced_motion = true;
            tracing::info!("Detected reduced motion from NO_ANIMATIONS env var");
        }

        // Check REDUCE_MOTION environment variable
        if let Ok(val) = env::var("REDUCE_MOTION") {
            if val == "1" || val.to_lowercase() == "true" {
                self.system_prefers_reduced_motion = true;
                tracing::info!("Detected reduced motion from REDUCE_MOTION env var");
            }
        }

        // Note: D-Bus detection (Task 1.2, 1.4) requires async runtime
        // This is handled in detect_system_preferences_async()

        tracing::debug!(
            reduced_motion = self.system_prefers_reduced_motion,
            high_contrast = self.system_prefers_high_contrast,
            "System accessibility preferences detected"
        );
    }

    /// Check if reduced motion should be active (Task 3.1)
    ///
    /// Returns true if:
    /// - User has explicitly enabled reduced motion, OR
    /// - System prefers reduced motion AND user hasn't explicitly disabled it
    pub fn should_reduce_motion(&self) -> bool {
        match self.reduced_motion_override {
            Some(true) => true,   // User explicitly wants reduced motion
            Some(false) => false, // User explicitly disabled reduced motion
            None => self.system_prefers_reduced_motion, // Follow system
        }
    }

    /// Check if high contrast should be active
    pub fn should_use_high_contrast(&self) -> bool {
        match self.high_contrast_override {
            Some(true) => true,
            Some(false) => false,
            None => self.system_prefers_high_contrast,
        }
    }

    /// Set user override for reduced motion (Task 2.1, 2.2)
    pub fn set_reduced_motion(&mut self, value: Option<bool>) {
        self.reduced_motion_override = value;
        tracing::info!(
            override_value = ?value,
            effective = self.should_reduce_motion(),
            "Reduced motion override updated"
        );
    }

    /// Set user override for high contrast
    pub fn set_high_contrast(&mut self, value: Option<bool>) {
        self.high_contrast_override = value;
        tracing::info!(
            override_value = ?value,
            effective = self.should_use_high_contrast(),
            "High contrast override updated"
        );
    }

    /// Get the system's detected reduced motion preference
    pub fn system_prefers_reduced_motion(&self) -> bool {
        self.system_prefers_reduced_motion
    }

    /// Get the system's detected high contrast preference
    pub fn system_prefers_high_contrast(&self) -> bool {
        self.system_prefers_high_contrast
    }

    /// Manually set system reduced motion (for testing or D-Bus callback)
    pub fn set_system_reduced_motion(&mut self, value: bool) {
        self.system_prefers_reduced_motion = value;
    }

    /// Manually set system high contrast (for testing or D-Bus callback)
    pub fn set_system_high_contrast(&mut self, value: bool) {
        self.system_prefers_high_contrast = value;
    }
}

/// Animation timings with reduced motion support (Task 3.2)
#[derive(Debug, Clone, Copy)]
pub struct EffectiveAnimationTimings {
    /// Menu appear duration (ms)
    pub appear_ms: u16,
    /// Menu dismiss duration (ms)
    pub dismiss_ms: u16,
    /// Slice highlight in duration (ms)
    pub highlight_in_ms: u16,
    /// Slice highlight out duration (ms)
    pub highlight_out_ms: u16,
    /// Icon scale animation enabled
    pub icon_scale_enabled: bool,
    /// Idle effects enabled (matrix rain, particles)
    pub idle_effects_enabled: bool,
}

impl EffectiveAnimationTimings {
    /// Create timings for reduced motion mode (all 0ms, effects disabled)
    pub fn reduced_motion() -> Self {
        Self {
            appear_ms: 0,
            dismiss_ms: 0,
            highlight_in_ms: 0,
            highlight_out_ms: 0,
            icon_scale_enabled: false,
            idle_effects_enabled: false,
        }
    }

    /// Create default timings from UX spec
    pub fn default_timings() -> Self {
        Self {
            appear_ms: 30,
            dismiss_ms: 50,
            highlight_in_ms: 80,
            highlight_out_ms: 60,
            icon_scale_enabled: true,
            idle_effects_enabled: true,
        }
    }
}

impl Default for EffectiveAnimationTimings {
    fn default() -> Self {
        Self::default_timings()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Task 4.1: Test animation timing override
    #[test]
    fn test_reduced_motion_timings() {
        let timings = EffectiveAnimationTimings::reduced_motion();

        assert_eq!(timings.appear_ms, 0);
        assert_eq!(timings.dismiss_ms, 0);
        assert_eq!(timings.highlight_in_ms, 0);
        assert_eq!(timings.highlight_out_ms, 0);
        assert!(!timings.icon_scale_enabled);
        assert!(!timings.idle_effects_enabled);
    }

    #[test]
    fn test_default_timings() {
        let timings = EffectiveAnimationTimings::default_timings();

        assert_eq!(timings.appear_ms, 30);
        assert_eq!(timings.dismiss_ms, 50);
        assert_eq!(timings.highlight_in_ms, 80);
        assert_eq!(timings.highlight_out_ms, 60);
        assert!(timings.icon_scale_enabled);
        assert!(timings.idle_effects_enabled);
    }

    // Task 4.2: Test user setting overrides system
    #[test]
    fn test_user_override_reduced_motion() {
        let mut settings = AccessibilitySettings::default();

        // System says no reduced motion
        settings.set_system_reduced_motion(false);
        assert!(!settings.should_reduce_motion());

        // User forces reduced motion ON
        settings.set_reduced_motion(Some(true));
        assert!(settings.should_reduce_motion());

        // User forces reduced motion OFF
        settings.set_reduced_motion(Some(false));
        assert!(!settings.should_reduce_motion());

        // System says reduced motion, but user forces OFF
        settings.set_system_reduced_motion(true);
        settings.set_reduced_motion(Some(false));
        assert!(!settings.should_reduce_motion());
    }

    // Task 4.3: Test None follows system default
    #[test]
    fn test_none_follows_system() {
        let mut settings = AccessibilitySettings::default();

        // No override, system false
        settings.set_reduced_motion(None);
        settings.set_system_reduced_motion(false);
        assert!(!settings.should_reduce_motion());

        // No override, system true
        settings.set_system_reduced_motion(true);
        assert!(settings.should_reduce_motion());
    }

    #[test]
    fn test_high_contrast_override() {
        let mut settings = AccessibilitySettings::default();

        settings.set_system_high_contrast(false);
        assert!(!settings.should_use_high_contrast());

        settings.set_high_contrast(Some(true));
        assert!(settings.should_use_high_contrast());

        settings.set_high_contrast(None);
        settings.set_system_high_contrast(true);
        assert!(settings.should_use_high_contrast());
    }

    #[test]
    fn test_default_settings() {
        let settings = AccessibilitySettings::default();

        assert!(settings.reduced_motion_override.is_none());
        assert!(settings.high_contrast_override.is_none());
        assert!(!settings.system_prefers_reduced_motion);
        assert!(!settings.system_prefers_high_contrast);
    }
}
