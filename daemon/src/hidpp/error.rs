//! HID++ error types

use std::fmt;

/// Haptic error type
#[derive(Debug)]
pub enum HapticError {
    /// No compatible device found
    DeviceNotFound,
    /// Permission denied accessing device
    PermissionDenied,
    /// Device does not support haptics
    UnsupportedDevice,
    /// Feature not supported on this device
    NotSupported,
    /// Communication error with device
    CommunicationError,
    /// I/O error during communication
    IoError(std::io::Error),
    /// HID++ protocol error
    ProtocolError(String),
    /// CRITICAL: Attempted to use blocklisted feature that writes to memory
    ///
    /// This error indicates a programming bug - we should NEVER
    /// attempt to use persistent/memory-writing HID++ features.
    SafetyViolation {
        feature_id: u16,
        reason: &'static str,
    },
}

impl fmt::Display for HapticError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HapticError::DeviceNotFound => write!(f, "MX Master 4 device not found"),
            HapticError::PermissionDenied => {
                write!(f, "Permission denied accessing HID device")
            }
            HapticError::UnsupportedDevice => {
                write!(f, "Device does not support haptic feedback")
            }
            HapticError::NotSupported => {
                write!(f, "Feature not supported on this device")
            }
            HapticError::CommunicationError => {
                write!(f, "Communication error with device")
            }
            HapticError::IoError(e) => write!(f, "I/O error: {}", e),
            HapticError::ProtocolError(msg) => write!(f, "HID++ protocol error: {}", msg),
            HapticError::SafetyViolation { feature_id, reason } => {
                write!(
                    f,
                    "SAFETY VIOLATION: Blocked feature 0x{:04X} - {}",
                    feature_id, reason
                )
            }
        }
    }
}

impl std::error::Error for HapticError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            HapticError::IoError(e) => Some(e),
            _ => None,
        }
    }
}

impl From<std::io::Error> for HapticError {
    fn from(err: std::io::Error) -> Self {
        HapticError::IoError(err)
    }
}
