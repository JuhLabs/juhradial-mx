//! HID++ protocol constants
//!
//! Feature IDs, report types, product IDs, and safety lists.

/// Logitech vendor ID
pub const LOGITECH_VENDOR_ID: u16 = 0x046D;

/// Known MX Master 4 product IDs
pub mod product_ids {
    /// MX Master 4 via USB
    pub const MX_MASTER_4_USB: u16 = 0xB034;
    /// MX Master 4 via Bolt receiver
    pub const MX_MASTER_4_BOLT: u16 = 0xC548;
    /// Bolt receiver itself
    pub const BOLT_RECEIVER: u16 = 0xC548;
    /// Generic Logitech receiver (may host MX Master 4)
    pub const UNIFYING_RECEIVER: u16 = 0xC52B;
}

/// HID++ report types
pub mod report_type {
    /// Short HID++ report (7 bytes)
    pub const SHORT: u8 = 0x10;
    /// Long HID++ report (20 bytes)
    pub const LONG: u8 = 0x11;
    /// Very long HID++ report (64 bytes)
    pub const VERY_LONG: u8 = 0x12;
}

/// HID++ 2.0 feature IDs - SAFE for runtime use (read-only or volatile)
pub mod features {
    /// IRoot - Protocol version, ping (READ-ONLY)
    pub const I_ROOT: u16 = 0x0000;
    /// IFeatureSet - Enumerate device features (READ-ONLY)
    pub const I_FEATURE_SET: u16 = 0x0001;
    /// Device name and type (READ-ONLY)
    pub const DEVICE_NAME: u16 = 0x0005;
    /// Battery status (READ-ONLY) - older devices
    pub const BATTERY_STATUS: u16 = 0x1000;
    /// Unified Battery (READ-ONLY) - newer devices like MX Master 4
    pub const UNIFIED_BATTERY: u16 = 0x1004;
    /// LED control - some devices include haptic here (RUNTIME-ONLY)
    pub const LED_CONTROL: u16 = 0x1300;
    /// Force feedback for racing wheels like G920/G923 (RUNTIME-ONLY - does NOT persist)
    pub const FORCE_FEEDBACK: u16 = 0x8123;
    /// MX Master 4 haptic motor (RUNTIME-ONLY - does NOT persist)
    /// Uses waveform IDs (0x00-0x1B) for predefined haptic patterns.
    pub const MX_MASTER_4_HAPTIC: u16 = 0x19B0;
    /// Alternative haptic feature used by mx4notifications project
    /// Some MX Master 4 devices may report this instead of 0x19B0
    pub const MX4_HAPTIC_ALT: u16 = 0x0B4E;
    /// Adjustable DPI - Mouse pointer speed/sensitivity (PERSISTS to device)
    /// Note: DPI settings persist on the device but this is expected user behavior.
    /// Users want their DPI setting to be remembered across reboots.
    /// Functions: [0] getSensorCount, [1] getSensorDpiList, [2] getSensorDpi, [3] setSensorDpi
    pub const ADJUSTABLE_DPI: u16 = 0x2201;
    /// HiResScroll - High-resolution scroll with SmartShift (MX Master 3/4)
    /// This is used by newer mice (MX Master 3, 3S, 4) for ratchet/free-spin control.
    /// Functions: [0] getMode, [1] setMode (contains ratchet mode control)
    pub const HIRES_SCROLL: u16 = 0x2111;

    /// SmartShift Legacy - For older mice (MX Master 2S and earlier)
    /// Functions: [0] getRatchetControlMode, [1] setRatchetControlMode
    pub const SMARTSHIFT_LEGACY: u16 = 0x2110;

    /// Change Host - Easy-Switch device slot switching (READ-ONLY safe)
    /// Functions: [0] getHostInfo (returns numHosts, currentHost), [1] setHost(slot)
    /// Used for reading current Easy-Switch status - we only use function 0
    pub const CHANGE_HOST: u16 = 0x1814;

    /// Host Info - READ-ONLY access to paired host names (0x1815)
    /// Functions: [0] getHostInfo, [1] getHostDescriptor, [3] getHostFriendlyName
    /// NOTE: This is blocklisted for WRITE but READ is safe for getting host names
    pub const HOSTS_INFO: u16 = 0x1815;

    /// REPROG_CONTROLS_V4 - Special Keys & Mouse Buttons (0x1B04)
    ///
    /// Used ONLY for runtime button divert (setCidReporting with divert=true).
    /// Divert is VOLATILE - it resets on mouse disconnect/host switch.
    /// We NEVER use persistent remapping functions.
    ///
    /// Functions we use:
    /// - [0] getCount() - number of remappable controls (READ-ONLY)
    /// - [1] getCidInfo(index) - get control info for an index (READ-ONLY)
    /// - [3] setCidReporting(CID, flags) - set divert flag (RUNTIME-ONLY, volatile)
    pub const REPROG_CONTROLS_V4: u16 = 0x1B04;
}

/// BLOCKLISTED HID++ feature IDs - NEVER use these!
///
/// # CRITICAL SAFETY
///
/// These features write to onboard mouse memory and would break
/// cross-platform compatibility. Using these is FORBIDDEN.
///
/// NOTE: 0x1B04 (REPROG_CONTROLS_V4) was removed from this list.
/// We use it ONLY for volatile runtime divert (setCidReporting),
/// which resets on disconnect. See features::REPROG_CONTROLS_V4.
pub mod blocklisted_features {
    /// Report Rate - MAY persist on some devices
    pub const REPORT_RATE: u16 = 0x8060;
    /// Onboard Profiles - PERSISTENT profile storage
    pub const ONBOARD_PROFILES: u16 = 0x8100;
    /// Mode Status - Profile switching that may persist
    pub const MODE_STATUS: u16 = 0x8090;
    /// Mouse Button Spy - Profile modification
    pub const MOUSE_BUTTON_SPY: u16 = 0x8110;
    /// Persistent Remappable Action - PERSISTENT key remapping
    pub const PERSISTENT_REMAPPABLE_ACTION: u16 = 0x1BC0;
    /// Host Info - Device pairing that persists
    pub const HOST_INFO: u16 = 0x1815;

    /// Check if a feature ID is blocklisted (would write to memory)
    pub fn is_blocklisted(feature_id: u16) -> bool {
        matches!(
            feature_id,
            REPORT_RATE
                | ONBOARD_PROFILES
                | MODE_STATUS
                | MOUSE_BUTTON_SPY
                | PERSISTENT_REMAPPABLE_ACTION
                | HOST_INFO
        )
    }

    /// Get human-readable name for blocklisted feature
    pub fn blocklist_reason(feature_id: u16) -> Option<&'static str> {
        match feature_id {
            REPORT_RATE => Some("May persist report rate settings"),
            ONBOARD_PROFILES => Some("Persistent profile storage"),
            MODE_STATUS => Some("Profile switching may persist"),
            MOUSE_BUTTON_SPY => Some("Profile modification"),
            PERSISTENT_REMAPPABLE_ACTION => Some("Persistent key remapping"),
            HOST_INFO => Some("Device pairing persistence"),
            _ => None,
        }
    }
}

/// Allowed HID++ feature IDs - explicitly safe for use
pub mod allowed_features {
    use super::features;

    /// List of all features that are safe to use
    pub const SAFELIST: &[u16] = &[
        features::I_ROOT,
        features::I_FEATURE_SET,
        features::DEVICE_NAME,
        features::BATTERY_STATUS,
        features::LED_CONTROL,
        features::FORCE_FEEDBACK,
        features::MX_MASTER_4_HAPTIC,
        features::MX4_HAPTIC_ALT,
        features::ADJUSTABLE_DPI,
        features::REPROG_CONTROLS_V4,
    ];

    /// Check if a feature ID is explicitly allowed
    pub fn is_allowed(feature_id: u16) -> bool {
        SAFELIST.contains(&feature_id)
    }
}
