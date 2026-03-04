//! Haptic patterns and event types
//!
//! MX Master 4 waveform patterns, legacy haptic profiles,
//! and UX haptic event definitions.

use std::fmt;

/// HID++ haptic intensity levels
#[derive(Debug, Clone, Copy)]
pub struct HapticPulse {
    /// Intensity (0-100)
    pub intensity: u8,
    /// Duration in milliseconds
    pub duration_ms: u16,
}

/// Predefined haptic profiles from UX spec
pub mod haptic_profiles {
    use super::HapticPulse;

    /// Menu appearance haptic (20% intensity, 10ms)
    pub const MENU_APPEAR: HapticPulse = HapticPulse {
        intensity: 20,
        duration_ms: 10,
    };

    /// Slice change haptic (40% intensity, 15ms)
    pub const SLICE_CHANGE: HapticPulse = HapticPulse {
        intensity: 40,
        duration_ms: 15,
    };

    /// Selection confirm haptic (80% intensity, 25ms)
    pub const CONFIRM: HapticPulse = HapticPulse {
        intensity: 80,
        duration_ms: 25,
    };

    /// Invalid action haptic (30% intensity, 50ms)
    pub const INVALID: HapticPulse = HapticPulse {
        intensity: 30,
        duration_ms: 50,
    };
}

/// Haptic pulse pattern type
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HapticPattern {
    /// Single pulse
    Single,
    /// Double pulse with 30ms gap
    Double,
    /// Triple short pulse with 20ms gaps
    Triple,
}

impl HapticPattern {
    /// Get the number of pulses for this pattern
    pub fn pulse_count(&self) -> u8 {
        match self {
            HapticPattern::Single => 1,
            HapticPattern::Double => 2,
            HapticPattern::Triple => 3,
        }
    }

    /// Get the gap between pulses in milliseconds
    pub fn gap_ms(&self) -> u64 {
        match self {
            HapticPattern::Single => 0,
            HapticPattern::Double => 30,
            HapticPattern::Triple => 20,
        }
    }
}

/// MX Master 4 haptic waveforms
///
/// The MX Master 4 uses predefined haptic waveforms. The actual haptic
/// commands are sent via feature index 0x0B with function 0x04
/// (based on mx4notifications project implementation).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Mx4HapticPattern {
    /// Sharp state change - crisp feedback for state transitions (ID: 0x00)
    SharpStateChange = 0x00,
    /// Damp state change - softer feedback for state transitions (ID: 0x01)
    DampStateChange = 0x01,
    /// Sharp collision - strong feedback for collisions (ID: 0x02)
    SharpCollision = 0x02,
    /// Damp collision - soft feedback for collisions (ID: 0x03)
    DampCollision = 0x03,
    /// Subtle collision - very light feedback (ID: 0x04)
    SubtleCollision = 0x04,
    /// Happy alert - positive notification (ID: 0x05)
    HappyAlert = 0x05,
    /// Angry alert - error/warning notification (ID: 0x06)
    AngryAlert = 0x06,
    /// Completed - success/completion feedback (ID: 0x07)
    Completed = 0x07,
    /// Square wave pattern (ID: 0x08)
    Square = 0x08,
    /// Wave pattern (ID: 0x09)
    Wave = 0x09,
    /// Firework pattern (ID: 0x0A)
    Firework = 0x0A,
    /// Mad pattern - strong error (ID: 0x0B)
    Mad = 0x0B,
    /// Knock pattern (ID: 0x0C)
    Knock = 0x0C,
    /// Jingle pattern (ID: 0x0D)
    Jingle = 0x0D,
    /// Ringing pattern (ID: 0x0E)
    Ringing = 0x0E,
    /// Whisper collision - very subtle (ID: 0x1B)
    WhisperCollision = 0x1B,
}

impl Mx4HapticPattern {
    /// Convert pattern to raw ID for HID++ command
    pub fn to_id(self) -> u8 {
        self as u8
    }

    /// Create from raw waveform ID
    pub fn from_id(id: u8) -> Option<Self> {
        match id {
            0x00 => Some(Self::SharpStateChange),
            0x01 => Some(Self::DampStateChange),
            0x02 => Some(Self::SharpCollision),
            0x03 => Some(Self::DampCollision),
            0x04 => Some(Self::SubtleCollision),
            0x05 => Some(Self::HappyAlert),
            0x06 => Some(Self::AngryAlert),
            0x07 => Some(Self::Completed),
            0x08 => Some(Self::Square),
            0x09 => Some(Self::Wave),
            0x0A => Some(Self::Firework),
            0x0B => Some(Self::Mad),
            0x0C => Some(Self::Knock),
            0x0D => Some(Self::Jingle),
            0x0E => Some(Self::Ringing),
            0x1B => Some(Self::WhisperCollision),
            _ => None,
        }
    }

    /// Get human-readable name for the waveform
    pub fn name(&self) -> &'static str {
        match self {
            Self::SharpStateChange => "Sharp State Change",
            Self::DampStateChange => "Damp State Change",
            Self::SharpCollision => "Sharp Collision",
            Self::DampCollision => "Damp Collision",
            Self::SubtleCollision => "Subtle Collision",
            Self::HappyAlert => "Happy Alert",
            Self::AngryAlert => "Angry Alert",
            Self::Completed => "Completed",
            Self::Square => "Square",
            Self::Wave => "Wave",
            Self::Firework => "Firework",
            Self::Mad => "Mad",
            Self::Knock => "Knock",
            Self::Jingle => "Jingle",
            Self::Ringing => "Ringing",
            Self::WhisperCollision => "Whisper Collision",
        }
    }

    /// Create from config name string (snake_case)
    /// Returns SubtleCollision as default if name is not recognized
    pub fn from_name(name: &str) -> Self {
        match name {
            "sharp_state_change" => Self::SharpStateChange,
            "damp_state_change" => Self::DampStateChange,
            "sharp_collision" => Self::SharpCollision,
            "damp_collision" => Self::DampCollision,
            "subtle_collision" => Self::SubtleCollision,
            "whisper_collision" => Self::WhisperCollision,
            "happy_alert" => Self::HappyAlert,
            "angry_alert" => Self::AngryAlert,
            "completed" => Self::Completed,
            "square" => Self::Square,
            "wave" => Self::Wave,
            "firework" => Self::Firework,
            "mad" => Self::Mad,
            "knock" => Self::Knock,
            "jingle" => Self::Jingle,
            "ringing" => Self::Ringing,
            _ => {
                tracing::warn!(name, "Unknown haptic pattern name, using default");
                Self::SubtleCollision
            }
        }
    }
}

impl fmt::Display for Mx4HapticPattern {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} ({})", self.name(), self.to_id())
    }
}

/// UX haptic events triggered during menu interaction
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HapticEvent {
    /// Radial menu appears on screen
    MenuAppear,
    /// Cursor moves to highlight a different slice
    SliceChange,
    /// User confirms selection (gesture button released on valid slice)
    SelectionConfirm,
    /// User selects an empty or invalid slice
    InvalidAction,
}

impl HapticEvent {
    /// Get the base UX profile for this event
    pub fn base_profile(&self) -> HapticPulse {
        match self {
            HapticEvent::MenuAppear => haptic_profiles::MENU_APPEAR,
            HapticEvent::SliceChange => haptic_profiles::SLICE_CHANGE,
            HapticEvent::SelectionConfirm => haptic_profiles::CONFIRM,
            HapticEvent::InvalidAction => haptic_profiles::INVALID,
        }
    }

    /// Get the pulse pattern for this event
    pub fn pattern(&self) -> HapticPattern {
        match self {
            HapticEvent::MenuAppear => HapticPattern::Single,
            HapticEvent::SliceChange => HapticPattern::Single,
            HapticEvent::SelectionConfirm => HapticPattern::Double,
            HapticEvent::InvalidAction => HapticPattern::Triple,
        }
    }

    /// Get the default intensity for this event (0-100)
    pub fn default_intensity(&self) -> u8 {
        self.base_profile().intensity
    }

    /// Get the duration for this event in milliseconds
    pub fn duration_ms(&self) -> u16 {
        self.base_profile().duration_ms
    }

    /// Get the MX Master 4 haptic waveform for this event
    ///
    /// Maps UX haptic events to appropriate MX4 waveform IDs.
    /// Waveform selection is based on the feel that best matches
    /// the intended UX feedback.
    pub fn mx4_pattern(&self) -> Mx4HapticPattern {
        match self {
            // Menu appear: subtle feedback to indicate menu opened
            HapticEvent::MenuAppear => Mx4HapticPattern::SubtleCollision,
            // Slice change: distinct click for each slice transition
            HapticEvent::SliceChange => Mx4HapticPattern::SharpStateChange,
            // Selection confirm: success/completion feel
            HapticEvent::SelectionConfirm => Mx4HapticPattern::Completed,
            // Invalid action: error/warning feel
            HapticEvent::InvalidAction => Mx4HapticPattern::AngryAlert,
        }
    }
}

impl fmt::Display for HapticEvent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HapticEvent::MenuAppear => write!(f, "menu_appear"),
            HapticEvent::SliceChange => write!(f, "slice_change"),
            HapticEvent::SelectionConfirm => write!(f, "selection_confirm"),
            HapticEvent::InvalidAction => write!(f, "invalid_action"),
        }
    }
}

/// Per-event haptic pattern configuration
#[derive(Debug, Clone, Copy)]
pub struct PerEventPattern {
    /// Pattern for menu appearance
    pub menu_appear: Mx4HapticPattern,
    /// Pattern for slice change (hover)
    pub slice_change: Mx4HapticPattern,
    /// Pattern for selection confirmation
    pub confirm: Mx4HapticPattern,
    /// Pattern for invalid action
    pub invalid: Mx4HapticPattern,
}

impl Default for PerEventPattern {
    fn default() -> Self {
        Self {
            menu_appear: Mx4HapticPattern::DampStateChange,
            slice_change: Mx4HapticPattern::SubtleCollision,
            confirm: Mx4HapticPattern::SharpStateChange,
            invalid: Mx4HapticPattern::AngryAlert,
        }
    }
}

impl PerEventPattern {
    /// Get pattern for a specific event
    pub fn get(&self, event: &HapticEvent) -> Mx4HapticPattern {
        match event {
            HapticEvent::MenuAppear => self.menu_appear,
            HapticEvent::SliceChange => self.slice_change,
            HapticEvent::SelectionConfirm => self.confirm,
            HapticEvent::InvalidAction => self.invalid,
        }
    }
}

