//! Core types for the macro system
//!
//! Defines all the data structures for macro recording, playback, and storage.
//! All types implement serde Serialize/Deserialize for JSON persistence.
//!
//! **Important:** The JSON format is defined by the Python settings UI.
//! Rust types are designed to deserialize from that format.

use serde::{Deserialize, Deserializer, Serialize, Serializer};

// ============================================================================
// Macro Actions
// ============================================================================

/// A single action within a macro sequence.
///
/// JSON format (produced by Python settings_macro_storage.py):
/// ```json
/// {"type": "key_down", "key": "ctrl", "id": "...", "delay_after_ms": 0}
/// {"type": "delay", "ms": 50, "id": "...", "delay_after_ms": 0}
/// {"type": "mouse_down", "button": "left", "id": "...", "delay_after_ms": 0}
/// {"type": "text", "text": "hello", "id": "...", "delay_after_ms": 0}
/// {"type": "scroll", "direction": "up", "amount": 3, "id": "...", "delay_after_ms": 0}
/// ```
#[derive(Debug, Clone, PartialEq)]
pub enum MacroAction {
    KeyDown(String),
    KeyUp(String),
    MouseDown(String),
    MouseUp(String),
    MouseClick(String),
    Delay(u64),
    Text(String),
    Scroll { direction: String, amount: i32 },
}

/// Raw JSON representation of a macro action (flat struct for serde)
#[derive(Debug, Serialize, Deserialize)]
struct RawAction {
    #[serde(rename = "type")]
    action_type: String,

    // Key actions
    #[serde(skip_serializing_if = "Option::is_none")]
    key: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    keycode: Option<u32>,

    // Mouse actions
    #[serde(skip_serializing_if = "Option::is_none")]
    button: Option<String>,

    // Delay actions
    #[serde(skip_serializing_if = "Option::is_none")]
    ms: Option<u64>,

    // Text actions
    #[serde(skip_serializing_if = "Option::is_none")]
    text: Option<String>,

    // Scroll actions
    #[serde(skip_serializing_if = "Option::is_none")]
    direction: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    amount: Option<i32>,

    // Common fields (preserved on round-trip)
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<String>,
    #[serde(default)]
    delay_after_ms: u64,
}

impl Serialize for MacroAction {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let raw = match self {
            MacroAction::KeyDown(key) => RawAction {
                action_type: "key_down".into(),
                key: Some(key.clone()),
                keycode: None,
                button: None,
                ms: None,
                text: None,
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::KeyUp(key) => RawAction {
                action_type: "key_up".into(),
                key: Some(key.clone()),
                keycode: None,
                button: None,
                ms: None,
                text: None,
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::MouseDown(btn) => RawAction {
                action_type: "mouse_down".into(),
                key: None,
                keycode: None,
                button: Some(btn.clone()),
                ms: None,
                text: None,
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::MouseUp(btn) => RawAction {
                action_type: "mouse_up".into(),
                key: None,
                keycode: None,
                button: Some(btn.clone()),
                ms: None,
                text: None,
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::MouseClick(btn) => RawAction {
                action_type: "mouse_click".into(),
                key: None,
                keycode: None,
                button: Some(btn.clone()),
                ms: None,
                text: None,
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::Delay(ms) => RawAction {
                action_type: "delay".into(),
                key: None,
                keycode: None,
                button: None,
                ms: Some(*ms),
                text: None,
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::Text(text) => RawAction {
                action_type: "text".into(),
                key: None,
                keycode: None,
                button: None,
                ms: None,
                text: Some(text.clone()),
                direction: None,
                amount: None,
                id: None,
                delay_after_ms: 0,
            },
            MacroAction::Scroll { direction, amount } => RawAction {
                action_type: "scroll".into(),
                key: None,
                keycode: None,
                button: None,
                ms: None,
                text: None,
                direction: Some(direction.clone()),
                amount: Some(*amount),
                id: None,
                delay_after_ms: 0,
            },
        };
        raw.serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for MacroAction {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = RawAction::deserialize(deserializer)?;
        match raw.action_type.as_str() {
            "key_down" => Ok(MacroAction::KeyDown(raw.key.unwrap_or_default())),
            "key_up" => Ok(MacroAction::KeyUp(raw.key.unwrap_or_default())),
            "mouse_down" => Ok(MacroAction::MouseDown(
                raw.button.unwrap_or_else(|| "left".into()),
            )),
            "mouse_up" => Ok(MacroAction::MouseUp(
                raw.button.unwrap_or_else(|| "left".into()),
            )),
            "mouse_click" => Ok(MacroAction::MouseClick(
                raw.button.unwrap_or_else(|| "left".into()),
            )),
            "delay" => Ok(MacroAction::Delay(raw.ms.unwrap_or(0))),
            "text" => Ok(MacroAction::Text(raw.text.unwrap_or_default())),
            "scroll" => Ok(MacroAction::Scroll {
                direction: raw.direction.unwrap_or_else(|| "up".into()),
                amount: raw.amount.unwrap_or(1),
            }),
            other => Err(serde::de::Error::unknown_variant(
                other,
                &[
                    "key_down",
                    "key_up",
                    "mouse_down",
                    "mouse_up",
                    "mouse_click",
                    "delay",
                    "text",
                    "scroll",
                ],
            )),
        }
    }
}

// ============================================================================
// Repeat Modes
// ============================================================================

/// How a macro should repeat during playback.
///
/// Serialized as a flat string to match Python format:
/// `"once"`, `"while_holding"`, `"toggle"`, `"repeat_n"`, `"sequence"`
#[derive(Debug, Clone, PartialEq, Default)]
pub enum RepeatMode {
    #[default]
    Once,
    WhileHolding,
    Toggle,
    RepeatN,
    Sequence,
}

impl Serialize for RepeatMode {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let s = match self {
            RepeatMode::Once => "once",
            RepeatMode::WhileHolding => "while_holding",
            RepeatMode::Toggle => "toggle",
            RepeatMode::RepeatN => "repeat_n",
            RepeatMode::Sequence => "sequence",
        };
        serializer.serialize_str(s)
    }
}

impl<'de> Deserialize<'de> for RepeatMode {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let s = String::deserialize(deserializer)?;
        match s.as_str() {
            "once" => Ok(RepeatMode::Once),
            "while_holding" => Ok(RepeatMode::WhileHolding),
            "toggle" => Ok(RepeatMode::Toggle),
            "repeat_n" => Ok(RepeatMode::RepeatN),
            "sequence" => Ok(RepeatMode::Sequence),
            other => Err(serde::de::Error::unknown_variant(
                other,
                &["once", "while_holding", "toggle", "repeat_n", "sequence"],
            )),
        }
    }
}

// ============================================================================
// Sequence Phase Actions (for RepeatMode::Sequence)
// ============================================================================

/// Separate action lists for the three phases of a button interaction.
///
/// JSON format (from Python):
/// ```json
/// "sequence_actions": {"press": [...], "hold": [...], "release": [...]}
/// ```
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct SequenceActions {
    #[serde(default)]
    pub press: Vec<MacroAction>,

    #[serde(default)]
    pub hold: Vec<MacroAction>,

    #[serde(default)]
    pub release: Vec<MacroAction>,
}

// ============================================================================
// Macro Configuration
// ============================================================================

/// Complete macro configuration for storage and playback.
///
/// Matches the JSON format from Python's settings_macro_storage.py.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MacroConfig {
    pub id: String,
    pub name: String,

    #[serde(default)]
    pub description: String,

    #[serde(default)]
    pub repeat_mode: RepeatMode,

    /// Repeat count - only used when repeat_mode == "repeat_n"
    #[serde(default = "default_repeat_count")]
    pub repeat_count: u32,

    /// Primary action list (used for non-sequence modes)
    #[serde(default)]
    pub actions: Vec<MacroAction>,

    /// Sequence phase actions (used when repeat_mode == "sequence")
    #[serde(default)]
    pub sequence_actions: Option<SequenceActions>,

    /// Default delay between actions in ms (0 = no delay / fastest)
    #[serde(default = "default_standard_delay")]
    pub standard_delay_ms: u64,

    /// When true, override recorded delays with standard_delay_ms
    #[serde(default = "default_use_standard_delay")]
    pub use_standard_delay: bool,

    /// Which trigger this macro is assigned to (if any)
    #[serde(default)]
    pub assigned_trigger: Option<String>,
}

fn default_standard_delay() -> u64 {
    50
}

fn default_repeat_count() -> u32 {
    3
}

fn default_use_standard_delay() -> bool {
    true
}

// ============================================================================
// Recording Events
// ============================================================================

/// Raw event captured during macro recording
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MacroEvent {
    pub timestamp_ms: u64,
    pub event_type: RecordedEventType,
    pub key: String,
}

/// Type of event captured during recording
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum RecordedEventType {
    KeyDown,
    KeyUp,
}

// ============================================================================
// Playback State
// ============================================================================

/// Current state of macro playback
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub enum PlaybackState {
    #[default]
    Idle,
    Playing,
    ToggledOn,
}

// ============================================================================
// Helpers
// ============================================================================

impl MacroConfig {
    pub fn new(id: String, name: String) -> Self {
        Self {
            id,
            name,
            description: String::new(),
            repeat_mode: RepeatMode::Once,
            repeat_count: default_repeat_count(),
            actions: Vec::new(),
            sequence_actions: None,
            standard_delay_ms: default_standard_delay(),
            use_standard_delay: default_use_standard_delay(),
            assigned_trigger: None,
        }
    }
}

/// Convert recorded events into a MacroAction list with delays
pub fn events_to_actions(events: &[MacroEvent]) -> Vec<MacroAction> {
    let mut actions = Vec::new();
    let mut last_timestamp = 0u64;

    for event in events {
        if event.timestamp_ms > last_timestamp && !actions.is_empty() {
            let delay = event.timestamp_ms - last_timestamp;
            if delay > 0 {
                actions.push(MacroAction::Delay(delay));
            }
        }
        last_timestamp = event.timestamp_ms;

        match event.event_type {
            RecordedEventType::KeyDown => {
                actions.push(MacroAction::KeyDown(event.key.clone()));
            }
            RecordedEventType::KeyUp => {
                actions.push(MacroAction::KeyUp(event.key.clone()));
            }
        }
    }

    actions
}

/// Map mouse button name (from Python) to xdotool button number
pub fn mouse_button_to_number(button: &str) -> u8 {
    match button {
        "left" => 1,
        "middle" => 2,
        "right" => 3,
        _ => 1,
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_action_python_format_roundtrip() {
        // Test that we can deserialize the exact JSON Python produces
        let json = r#"{"type": "key_down", "key": "ctrl", "id": "abc-123", "delay_after_ms": 0}"#;
        let action: MacroAction = serde_json::from_str(json).unwrap();
        assert_eq!(action, MacroAction::KeyDown("ctrl".into()));
    }

    #[test]
    fn test_delay_python_format() {
        let json = r#"{"type": "delay", "ms": 50, "id": "def-456", "delay_after_ms": 0}"#;
        let action: MacroAction = serde_json::from_str(json).unwrap();
        assert_eq!(action, MacroAction::Delay(50));
    }

    #[test]
    fn test_mouse_python_format() {
        let json =
            r#"{"type": "mouse_down", "button": "left", "id": "ghi-789", "delay_after_ms": 0}"#;
        let action: MacroAction = serde_json::from_str(json).unwrap();
        assert_eq!(action, MacroAction::MouseDown("left".into()));
    }

    #[test]
    fn test_text_python_format() {
        let json = r#"{"type": "text", "text": "hello world", "id": "jkl", "delay_after_ms": 0}"#;
        let action: MacroAction = serde_json::from_str(json).unwrap();
        assert_eq!(action, MacroAction::Text("hello world".into()));
    }

    #[test]
    fn test_scroll_python_format() {
        let json = r#"{"type": "scroll", "direction": "up", "amount": 3, "id": "mno", "delay_after_ms": 0}"#;
        let action: MacroAction = serde_json::from_str(json).unwrap();
        assert_eq!(
            action,
            MacroAction::Scroll {
                direction: "up".into(),
                amount: 3
            }
        );
    }

    #[test]
    fn test_repeat_mode_flat_string() {
        let json = r#""once""#;
        let mode: RepeatMode = serde_json::from_str(json).unwrap();
        assert_eq!(mode, RepeatMode::Once);

        let json = r#""repeat_n""#;
        let mode: RepeatMode = serde_json::from_str(json).unwrap();
        assert_eq!(mode, RepeatMode::RepeatN);
    }

    #[test]
    fn test_full_macro_config_python_format() {
        let json = r#"{
            "id": "test-123",
            "name": "Quick Copy",
            "description": "Ctrl+C",
            "repeat_mode": "once",
            "repeat_count": 3,
            "use_standard_delay": true,
            "standard_delay_ms": 50,
            "actions": [
                {"type": "key_down", "key": "ctrl", "id": "a1", "delay_after_ms": 0},
                {"type": "key_down", "key": "c", "id": "a2", "delay_after_ms": 0},
                {"type": "delay", "ms": 50, "id": "a3", "delay_after_ms": 0},
                {"type": "key_up", "key": "c", "id": "a4", "delay_after_ms": 0},
                {"type": "key_up", "key": "ctrl", "id": "a5", "delay_after_ms": 0}
            ],
            "assigned_trigger": null
        }"#;
        let config: MacroConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.id, "test-123");
        assert_eq!(config.repeat_mode, RepeatMode::Once);
        assert_eq!(config.actions.len(), 5);
        assert!(config.use_standard_delay);
        assert_eq!(config.standard_delay_ms, 50);
    }

    #[test]
    fn test_sequence_mode_python_format() {
        let json = r#"{
            "id": "seq-1",
            "name": "Press Hold Release",
            "repeat_mode": "sequence",
            "repeat_count": 1,
            "use_standard_delay": false,
            "standard_delay_ms": 50,
            "actions": [],
            "sequence_actions": {
                "press": [{"type": "key_down", "key": "shift", "id": "s1", "delay_after_ms": 0}],
                "hold": [{"type": "delay", "ms": 100, "id": "s2", "delay_after_ms": 0}],
                "release": [{"type": "key_up", "key": "shift", "id": "s3", "delay_after_ms": 0}]
            }
        }"#;
        let config: MacroConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.repeat_mode, RepeatMode::Sequence);
        let seq = config.sequence_actions.unwrap();
        assert_eq!(seq.press.len(), 1);
        assert_eq!(seq.hold.len(), 1);
        assert_eq!(seq.release.len(), 1);
    }

    #[test]
    fn test_events_to_actions() {
        let events = vec![
            MacroEvent {
                timestamp_ms: 0,
                event_type: RecordedEventType::KeyDown,
                key: "a".to_string(),
            },
            MacroEvent {
                timestamp_ms: 100,
                event_type: RecordedEventType::KeyUp,
                key: "a".to_string(),
            },
        ];

        let actions = events_to_actions(&events);
        assert_eq!(actions.len(), 3);
        assert_eq!(actions[0], MacroAction::KeyDown("a".into()));
        assert_eq!(actions[1], MacroAction::Delay(100));
        assert_eq!(actions[2], MacroAction::KeyUp("a".into()));
    }

    #[test]
    fn test_mouse_button_to_number() {
        assert_eq!(mouse_button_to_number("left"), 1);
        assert_eq!(mouse_button_to_number("middle"), 2);
        assert_eq!(mouse_button_to_number("right"), 3);
        assert_eq!(mouse_button_to_number("unknown"), 1);
    }
}
