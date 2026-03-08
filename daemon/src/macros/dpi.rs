//! DPI switching for gaming mode
//!
//! Provides DPI profile management on top of the existing HID++ DPI commands
//! exposed through the HapticManager. This module adds profile-level
//! abstractions for quick switching between DPI presets.

use serde::{Deserialize, Serialize};

use crate::hidpp::SharedHapticManager;

// ============================================================================
// DPI Profile
// ============================================================================

/// A named DPI preset
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DpiProfile {
    /// Profile name (e.g. "Desktop", "FPS", "Sniper")
    pub name: String,

    /// DPI value (typically 400-8000)
    pub dpi: u16,
}

impl DpiProfile {
    /// Create a new DPI profile
    pub fn new(name: impl Into<String>, dpi: u16) -> Self {
        Self {
            name: name.into(),
            dpi,
        }
    }
}

/// Default DPI profiles for gaming mode
pub fn default_dpi_profiles() -> Vec<DpiProfile> {
    vec![
        DpiProfile::new("Desktop", 1000),
        DpiProfile::new("FPS", 800),
        DpiProfile::new("Precision", 400),
        DpiProfile::new("Fast", 1600),
    ]
}

// ============================================================================
// DPI Manager
// ============================================================================

/// Manages DPI profiles and switching
pub struct DpiManager {
    /// Available DPI profiles
    profiles: Vec<DpiProfile>,

    /// Index of the active profile
    active_index: usize,

    /// DPI value before gaming mode was enabled (for restore)
    saved_dpi: Option<u16>,
}

impl DpiManager {
    /// Create a new DPI manager with default profiles
    pub fn new() -> Self {
        Self {
            profiles: default_dpi_profiles(),
            active_index: 0,
            saved_dpi: None,
        }
    }

    /// Create a DPI manager with custom profiles
    pub fn with_profiles(profiles: Vec<DpiProfile>) -> Self {
        Self {
            profiles,
            active_index: 0,
            saved_dpi: None,
        }
    }

    /// Get the current active profile
    pub fn active_profile(&self) -> Option<&DpiProfile> {
        self.profiles.get(self.active_index)
    }

    /// Get all profiles
    pub fn profiles(&self) -> &[DpiProfile] {
        &self.profiles
    }

    /// Set active profile by index
    pub fn set_active_index(&mut self, index: usize) -> bool {
        if index < self.profiles.len() {
            self.active_index = index;
            true
        } else {
            false
        }
    }

    /// Apply the active profile's DPI to the device
    pub fn apply_active(&self, haptic_manager: &SharedHapticManager) -> Result<(), DpiError> {
        let profile = self.active_profile().ok_or(DpiError::NoProfile)?;
        set_dpi(haptic_manager, profile.dpi)
    }

    /// Save the current device DPI (call before entering gaming mode)
    pub fn save_current_dpi(&mut self, haptic_manager: &SharedHapticManager) {
        self.saved_dpi = get_dpi(haptic_manager);
        if let Some(dpi) = self.saved_dpi {
            tracing::info!(dpi, "Saved current DPI for restore");
        }
    }

    /// Restore the saved DPI (call when leaving gaming mode)
    pub fn restore_saved_dpi(&mut self, haptic_manager: &SharedHapticManager) -> Result<(), DpiError> {
        if let Some(dpi) = self.saved_dpi.take() {
            tracing::info!(dpi, "Restoring saved DPI");
            set_dpi(haptic_manager, dpi)
        } else {
            tracing::debug!("No saved DPI to restore");
            Ok(())
        }
    }

    /// Cycle to the next DPI profile and apply it
    pub fn cycle_next(&mut self, haptic_manager: &SharedHapticManager) -> Result<&DpiProfile, DpiError> {
        if self.profiles.is_empty() {
            return Err(DpiError::NoProfile);
        }

        self.active_index = (self.active_index + 1) % self.profiles.len();
        self.apply_active(haptic_manager)?;

        Ok(&self.profiles[self.active_index])
    }
}

impl Default for DpiManager {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// Device DPI Functions
// ============================================================================

/// Set DPI on the device via HID++ (through HapticManager)
pub fn set_dpi(haptic_manager: &SharedHapticManager, dpi: u16) -> Result<(), DpiError> {
    match haptic_manager.lock() {
        Ok(mut manager) => {
            manager.set_dpi(dpi).map_err(|e| DpiError::DeviceError(format!("{}", e)))?;
            tracing::info!(dpi, "DPI set on device");
            Ok(())
        }
        Err(e) => {
            tracing::error!(error = %e, "Failed to lock haptic manager for DPI");
            Err(DpiError::LockError)
        }
    }
}

/// Get current DPI from the device
pub fn get_dpi(haptic_manager: &SharedHapticManager) -> Option<u16> {
    match haptic_manager.lock() {
        Ok(mut manager) => manager.get_dpi(),
        Err(e) => {
            tracing::error!(error = %e, "Failed to lock haptic manager for get_dpi");
            None
        }
    }
}

// ============================================================================
// Error Type
// ============================================================================

/// DPI error type
#[derive(Debug)]
pub enum DpiError {
    /// No profile available
    NoProfile,
    /// Device communication error
    DeviceError(String),
    /// Failed to acquire lock
    LockError,
}

impl std::fmt::Display for DpiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DpiError::NoProfile => write!(f, "No DPI profile available"),
            DpiError::DeviceError(msg) => write!(f, "DPI device error: {}", msg),
            DpiError::LockError => write!(f, "Failed to lock haptic manager"),
        }
    }
}

impl std::error::Error for DpiError {}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dpi_profile_creation() {
        let profile = DpiProfile::new("Test", 800);
        assert_eq!(profile.name, "Test");
        assert_eq!(profile.dpi, 800);
    }

    #[test]
    fn test_default_profiles() {
        let profiles = default_dpi_profiles();
        assert_eq!(profiles.len(), 4);
        assert_eq!(profiles[0].name, "Desktop");
        assert_eq!(profiles[0].dpi, 1000);
        assert_eq!(profiles[1].name, "FPS");
        assert_eq!(profiles[1].dpi, 800);
    }

    #[test]
    fn test_dpi_manager_creation() {
        let manager = DpiManager::new();
        assert_eq!(manager.profiles().len(), 4);
        assert_eq!(manager.active_profile().unwrap().name, "Desktop");
    }

    #[test]
    fn test_dpi_manager_set_active() {
        let mut manager = DpiManager::new();
        assert!(manager.set_active_index(1));
        assert_eq!(manager.active_profile().unwrap().name, "FPS");

        // Out of range
        assert!(!manager.set_active_index(99));
        // Should still be at index 1
        assert_eq!(manager.active_profile().unwrap().name, "FPS");
    }

    #[test]
    fn test_dpi_manager_custom_profiles() {
        let profiles = vec![
            DpiProfile::new("Low", 400),
            DpiProfile::new("High", 3200),
        ];
        let manager = DpiManager::with_profiles(profiles);
        assert_eq!(manager.profiles().len(), 2);
        assert_eq!(manager.active_profile().unwrap().dpi, 400);
    }

    #[test]
    fn test_dpi_error_display() {
        let err = DpiError::NoProfile;
        assert!(format!("{}", err).contains("No DPI profile"));

        let err = DpiError::DeviceError("timeout".to_string());
        assert!(format!("{}", err).contains("timeout"));

        let err = DpiError::LockError;
        assert!(format!("{}", err).contains("lock"));
    }

    #[test]
    fn test_dpi_profile_serialization() {
        let profile = DpiProfile::new("FPS", 800);
        let json = serde_json::to_string(&profile).unwrap();
        assert!(json.contains("FPS"));
        assert!(json.contains("800"));

        let deserialized: DpiProfile = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.name, "FPS");
        assert_eq!(deserialized.dpi, 800);
    }
}
