//! Macro trigger mapping
//!
//! Maps evdev button codes to macro IDs for automatic trigger detection.
//! Handles both Wayland and X11 GDK button numbering.

use std::collections::HashMap;
use std::sync::{Arc, RwLock};

use super::types::MacroConfig;

/// Shared trigger map, thread-safe for use across daemon tasks
pub type SharedTriggerMap = Arc<RwLock<TriggerMap>>;

/// Maps evdev button codes to macro IDs
pub struct TriggerMap {
    /// evdev_code -> macro_id
    bindings: HashMap<u16, String>,
}

impl TriggerMap {
    /// Build a trigger map from loaded macros
    pub fn from_macros(macros: &HashMap<String, MacroConfig>) -> Self {
        let mut bindings = HashMap::new();

        for config in macros.values() {
            if let Some(ref trigger) = config.assigned_trigger {
                if let Some(evdev_code) = parse_trigger(trigger) {
                    tracing::info!(
                        trigger = %trigger,
                        evdev_code = format!("0x{:03x}", evdev_code),
                        macro_id = %config.id,
                        macro_name = %config.name,
                        mode = ?config.repeat_mode,
                        "Registered macro trigger"
                    );
                    bindings.insert(evdev_code, config.id.clone());
                }
            }
        }

        Self { bindings }
    }

    /// Look up a macro ID by evdev button code
    pub fn get(&self, evdev_code: u16) -> Option<&str> {
        self.bindings.get(&evdev_code).map(|s| s.as_str())
    }

    /// Reload the trigger map from disk
    pub fn reload(&mut self) {
        match super::storage::load_all_macros() {
            Ok(macros) => {
                let new_map = Self::from_macros(&macros);
                self.bindings = new_map.bindings;
                tracing::info!(count = self.bindings.len(), "Macro triggers reloaded");
            }
            Err(e) => {
                tracing::warn!("Failed to reload macro triggers: {}", e);
            }
        }
    }

    /// Number of registered triggers
    pub fn len(&self) -> usize {
        self.bindings.len()
    }

    /// Check if any triggers are registered
    pub fn is_empty(&self) -> bool {
        self.bindings.is_empty()
    }

    /// Get all registered evdev key codes (for HID++ button divert)
    pub fn evdev_codes(&self) -> Vec<u16> {
        self.bindings.keys().copied().collect()
    }
}

impl Default for TriggerMap {
    fn default() -> Self {
        Self {
            bindings: HashMap::new(),
        }
    }
}

/// Parse a trigger string into an evdev button code
///
/// Trigger formats from the Python settings UI:
/// - `"mouse:N"` where N is the GDK button number
/// - `"key:name"` where name is the GDK keyval name (not yet supported)
pub fn parse_trigger(trigger: &str) -> Option<u16> {
    if let Some(num_str) = trigger.strip_prefix("mouse:") {
        let button: u32 = num_str.parse().ok()?;
        gdk_button_to_evdev(button)
    } else {
        // "key:..." triggers not yet supported in evdev layer
        None
    }
}

/// Map GDK/X button number to evdev key code
///
/// Handles both Wayland and X11 numbering:
/// - Wayland: 4 = BTN_SIDE, 5 = BTN_EXTRA (direct mapping)
/// - X11: 8 = BTN_SIDE, 9 = BTN_EXTRA (skips scroll buttons 4-7)
///
/// Gaming mice (SteelSeries, Razer, etc.) may have many extra buttons
/// that map to higher GDK numbers. This handles all of them.
fn gdk_button_to_evdev(button: u32) -> Option<u16> {
    match button {
        1 => Some(0x110), // BTN_LEFT
        2 => Some(0x112), // BTN_MIDDLE
        3 => Some(0x111), // BTN_RIGHT
        // Wayland direct mapping: button 4+ -> BTN_SIDE (0x113) + offset
        // Covers BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK, BTN_TASK, etc.
        4..=7 => Some(0x113 + (button - 4) as u16),
        // X11 mapping: button 8+ -> BTN_SIDE (0x113) + offset
        // (scroll buttons 4-7 are consumed by GDK, never reach GestureClick)
        8.. => Some(0x113 + (button - 8) as u16),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::macros::types::{MacroConfig, RepeatMode};

    #[test]
    fn test_parse_mouse_trigger_wayland() {
        assert_eq!(parse_trigger("mouse:4"), Some(0x113)); // BTN_SIDE
        assert_eq!(parse_trigger("mouse:5"), Some(0x114)); // BTN_EXTRA
        assert_eq!(parse_trigger("mouse:6"), Some(0x115)); // BTN_FORWARD
        assert_eq!(parse_trigger("mouse:7"), Some(0x116)); // BTN_BACK
    }

    #[test]
    fn test_parse_mouse_trigger_x11() {
        assert_eq!(parse_trigger("mouse:8"), Some(0x113)); // BTN_SIDE
        assert_eq!(parse_trigger("mouse:9"), Some(0x114)); // BTN_EXTRA
        assert_eq!(parse_trigger("mouse:10"), Some(0x115)); // BTN_FORWARD
        assert_eq!(parse_trigger("mouse:11"), Some(0x116)); // BTN_BACK
    }

    #[test]
    fn test_parse_mouse_trigger_gaming_extra() {
        // Gaming mice (SteelSeries, Razer) with extra buttons
        assert_eq!(parse_trigger("mouse:12"), Some(0x117)); // BTN_TASK (X11)
        assert_eq!(parse_trigger("mouse:13"), Some(0x118)); // Extra gaming button
    }

    #[test]
    fn test_parse_primary_buttons() {
        assert_eq!(parse_trigger("mouse:1"), Some(0x110));
        assert_eq!(parse_trigger("mouse:2"), Some(0x112));
        assert_eq!(parse_trigger("mouse:3"), Some(0x111));
    }

    #[test]
    fn test_parse_key_trigger_unsupported() {
        assert_eq!(parse_trigger("key:a"), None);
    }

    #[test]
    fn test_parse_invalid() {
        assert_eq!(parse_trigger("invalid"), None);
        assert_eq!(parse_trigger("mouse:abc"), None);
    }

    #[test]
    fn test_trigger_map_from_macros() {
        let mut macros = HashMap::new();
        macros.insert(
            "test1".to_string(),
            MacroConfig {
                id: "test1".to_string(),
                name: "Test".to_string(),
                description: String::new(),
                repeat_mode: RepeatMode::WhileHolding,
                repeat_count: 1,
                actions: vec![],
                sequence_actions: None,
                standard_delay_ms: 50,
                use_standard_delay: true,
                assigned_trigger: Some("mouse:8".to_string()),
            },
        );

        let map = TriggerMap::from_macros(&macros);
        assert_eq!(map.get(0x113), Some("test1"));
        assert_eq!(map.get(0x110), None);
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn test_trigger_map_empty() {
        let macros = HashMap::new();
        let map = TriggerMap::from_macros(&macros);
        assert!(map.is_empty());
    }
}
