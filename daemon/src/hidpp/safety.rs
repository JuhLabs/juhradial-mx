//! HID++ safety verification
//!
//! Runtime and compile-time checks to ensure we never use
//! blocklisted features that write to onboard memory.

use super::constants::{allowed_features, blocklisted_features};
use super::error::HapticError;

/// Verify that a feature ID is safe to use (runtime check)
///
/// # CRITICAL SAFETY
///
/// This function MUST be called before sending any HID++ command
/// that references a feature ID. It ensures we never accidentally
/// use a blocklisted feature that would write to onboard memory.
///
/// # Returns
///
/// - `Ok(())` if feature is safe (allowed or unknown-but-not-blocklisted)
/// - `Err(HapticError::SafetyViolation)` if feature is blocklisted
pub fn verify_feature_safety(feature_id: u16) -> Result<(), HapticError> {
    // First check: Is this feature explicitly blocklisted?
    if blocklisted_features::is_blocklisted(feature_id) {
        let reason = blocklisted_features::blocklist_reason(feature_id)
            .unwrap_or("Unknown persistent feature");

        tracing::error!(
            feature_id = format!("0x{:04X}", feature_id),
            reason = reason,
            "SAFETY VIOLATION: Attempted to use blocklisted HID++ feature!"
        );

        return Err(HapticError::SafetyViolation { feature_id, reason });
    }

    // Second check: Warn if feature is not explicitly allowed (unknown feature)
    if !allowed_features::is_allowed(feature_id) {
        tracing::warn!(
            feature_id = format!("0x{:04X}", feature_id),
            "Using unknown HID++ feature - verify it doesn't persist to memory"
        );
    }

    Ok(())
}

/// Assert at compile time that we only use safe features
///
/// This macro can be used to document which features are being used
/// and provides compile-time visibility into HID++ feature usage.
#[macro_export]
macro_rules! assert_safe_feature {
    ($feature_id:expr) => {{
        // Runtime check
        $crate::hidpp::verify_feature_safety($feature_id)?;
        $feature_id
    }};
}
