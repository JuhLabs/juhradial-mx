//! What the connected mouse can do, from its HID++ feature table.
//!
//! Pure: built from the table the connect-time enumeration already filled, so
//! answering never touches the device.

use std::collections::HashMap;

use super::constants::features;

/// Feature ids that are only reported, never driven.
const EXTENDED_ADJUSTABLE_DPI: u16 = 0x2202;
const FORCE_SENSE: u16 = 0x19C0;

/// Capability flags keyed by the names the settings app reads.
pub fn capability_map(has: impl Fn(u16) -> bool, gesture_button: bool) -> HashMap<String, bool> {
    let entries = [
        ("dpi", has(features::ADJUSTABLE_DPI)),
        ("dpi_extended", has(EXTENDED_ADJUSTABLE_DPI)),
        (
            "smartshift",
            has(features::HIRES_SCROLL) || has(features::SMARTSHIFT_LEGACY),
        ),
        ("hires_wheel", has(features::HIRES_WHEEL)),
        ("thumbwheel", has(features::THUMB_WHEEL)),
        (
            "haptics",
            has(features::MX_MASTER_4_HAPTIC) || has(features::FORCE_FEEDBACK),
        ),
        ("haptic_levels", has(features::MX_MASTER_4_HAPTIC)),
        ("force_sense", has(FORCE_SENSE)),
        ("easy_switch", has(features::CHANGE_HOST)),
        (
            "battery",
            has(features::UNIFIED_BATTERY) || has(features::BATTERY_STATUS),
        ),
        ("button_divert", has(features::REPROG_CONTROLS_V4)),
        ("gesture_button", gesture_button),
    ];
    entries
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mx_master_4_feature_set() {
        let table = [
            0x2201u16, 0x2111, 0x2121, 0x2150, 0x19B0, 0x19C0, 0x1814, 0x1004, 0x1B04,
        ];
        let caps = capability_map(|id| table.contains(&id), true);
        for key in [
            "dpi", "smartshift", "hires_wheel", "thumbwheel", "haptics", "haptic_levels",
            "force_sense", "easy_switch", "battery", "button_divert", "gesture_button",
        ] {
            assert!(caps[key], "{key}");
        }
        assert!(!caps["dpi_extended"]);
    }

    #[test]
    fn mouse_without_a_motor_reports_no_haptics() {
        // MX Master 3S: DPI, SmartShift, hi-res, thumb wheel, no 0x19B0/0x19C0.
        let table = [0x2201u16, 0x2111, 0x2121, 0x2150, 0x1814, 0x1004, 0x1B04];
        let caps = capability_map(|id| table.contains(&id), true);
        assert!(!caps["haptics"]);
        assert!(!caps["haptic_levels"]);
        assert!(!caps["force_sense"]);
        assert!(caps["dpi"]);
    }

    #[test]
    fn empty_table_reports_every_key_false() {
        let caps = capability_map(|_| false, false);
        assert_eq!(caps.len(), 12);
        assert!(caps.values().all(|v| !v));
    }
}
