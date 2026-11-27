//! HID++ protocol implementation for haptic feedback
//!
//! Sends runtime-only haptic commands to MX Master 4 without writing
//! to onboard memory. This preserves cross-platform mouse compatibility.
//!
//! # CRITICAL SAFETY CONSTRAINT
//!
//! This module MUST NEVER write to the mouse's onboard memory.
//! Only volatile/runtime HID++ commands are permitted. The mouse
//! must remain 100% compatible with Windows/macOS after use.
//!
//! # HID++ Communication
//!
//! Uses direct hidraw device access (same approach as battery module).
//! This is more reliable than hidapi library for Logitech devices.

pub mod capabilities;
pub mod constants;
pub mod controls;
pub mod device;
pub mod error;
pub mod manager;
pub mod messages;
pub mod notifications;
pub mod patterns;
pub mod safety;

#[cfg(test)]
mod tests;

use std::sync::{Arc, Mutex};

// Re-export all public types at the module level for backwards compatibility
pub use constants::{
    allowed_features, blocklisted_features, features, product_ids, report_type,
    LOGITECH_VENDOR_ID,
};
pub use error::HapticError;
pub use manager::{ConnectionState, HapticManager, TestOutcome};
pub use messages::{ConnectionType, HidppLongMessage, HidppShortMessage};
pub use patterns::{
    haptic_profiles, HapticEvent, HapticPattern, HapticPulse, Mx4HapticPattern, PerEventPattern,
};
pub use safety::verify_feature_safety;

/// Shared haptic manager for thread-safe access from D-Bus handlers
pub type SharedHapticManager = Arc<Mutex<HapticManager>>;

/// Where the kernel lists hidraw nodes. Every device scan goes through here.
///
/// Unit tests get a directory that does not exist, so no test opens a real
/// device. Tests that build a manager used to connect to the mouse on the
/// developer's desk and send it hundreds of requests; hidraw hands every
/// reply to every open handle, so a daemon reading its feature table at that
/// moment took the test's replies for its own and came out with the wrong
/// feature indexes (no diverted buttons until a restart).
pub fn hidraw_class_dir() -> std::path::PathBuf {
    if cfg!(test) {
        std::path::PathBuf::from("/nonexistent/juhradial-unit-tests/hidraw")
    } else {
        std::path::PathBuf::from("/sys/class/hidraw")
    }
}

/// Create a new shared haptic manager from config
pub fn new_shared_haptic_manager(config: &crate::config::HapticConfig) -> SharedHapticManager {
    Arc::new(Mutex::new(HapticManager::from_config(config)))
}
