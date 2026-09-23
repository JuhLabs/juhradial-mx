//! Configuration management for JuhRadial MX
//!
//! Handles loading, validation, and hot-reload of JSON configuration files.
//! Configuration is stored at `~/.config/juhradial/config.json`.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

// ============================================================================
// Constants
// ============================================================================

/// Default config directory name
const CONFIG_DIR: &str = "juhradial";

/// Default config file name
const CONFIG_FILE: &str = "config.json";

// ============================================================================
// Haptic Configuration
// ============================================================================

/// Per-event haptic pattern overrides
/// Pattern names match MX Master 4 waveform IDs from the HID++ spec
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HapticEventConfig {
    /// Pattern when menu appears (default: damp_state_change)
    #[serde(default = "default_menu_appear")]
    pub menu_appear: String,

    /// Pattern when hovering over different slices (default: subtle_collision)
    #[serde(default = "default_slice_change")]
    pub slice_change: String,

    /// Pattern when selecting an action (default: sharp_state_change)
    #[serde(default = "default_confirm")]
    pub confirm: String,

    /// Pattern for invalid/blocked actions (default: angry_alert)
    #[serde(default = "default_invalid")]
    pub invalid: String,

    /// Pattern when the focused application window changes (default: subtle_collision)
    #[serde(default = "default_window_switch")]
    pub window_switch: String,

    /// Pattern when the cursor moves to a different physical monitor (default: subtle_collision)
    #[serde(default = "default_monitor_switch")]
    pub monitor_switch: String,
}

fn default_menu_appear() -> String { "damp_state_change".to_string() }
fn default_slice_change() -> String { "subtle_collision".to_string() }
fn default_confirm() -> String { "sharp_state_change".to_string() }
fn default_invalid() -> String { "angry_alert".to_string() }
fn default_window_switch() -> String { "subtle_collision".to_string() }
fn default_monitor_switch() -> String { "subtle_collision".to_string() }

impl Default for HapticEventConfig {
    fn default() -> Self {
        Self {
            menu_appear: default_menu_appear(),
            slice_change: default_slice_change(),
            confirm: default_confirm(),
            invalid: default_invalid(),
            window_switch: default_window_switch(),
            monitor_switch: default_monitor_switch(),
        }
    }
}

impl HapticEventConfig {
    /// Validate pattern names (no-op for now, could check against valid patterns)
    pub fn validate(&mut self) {
        // Pattern validation could be added here if needed
    }
}

/// Haptic feedback configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HapticConfig {
    /// Enable haptic feedback
    #[serde(default = "default_true")]
    pub enabled: bool,

    /// Master haptic strength, 0-100 (default 70).
    ///
    /// HARDWARE NOTE: the MX Master 4 plays fixed firmware waveforms selected
    /// by ID; its HID++ play command (`send_haptic_pattern`) carries no
    /// amplitude byte, so per-call strength scaling is impossible on that
    /// device. There `intensity` acts as a master gate: 0 silences haptics,
    /// any non-zero value plays the waveform at its native firmware amplitude.
    /// On legacy force-feedback devices (0x8123, `send_haptic_pulse`) the pulse
    /// DOES take an intensity byte, so there `intensity` scales amplitude for
    /// real. Clamped to 0..=100 on load.
    #[serde(default = "default_intensity")]
    pub intensity: u8,

    /// Default haptic pattern (fallback when event-specific not set)
    #[serde(default = "default_pattern")]
    pub default_pattern: String,

    /// Per-event pattern overrides
    #[serde(default)]
    pub per_event: HapticEventConfig,

    /// Minimum time between pulses in milliseconds (general debounce)
    #[serde(default = "default_debounce")]
    pub debounce_ms: u64,

    /// Minimum time between slice change haptics in milliseconds
    /// Used to prevent rapid-fire feedback during fast cursor movement
    #[serde(default = "default_slice_debounce")]
    pub slice_debounce_ms: u64,

    /// Time window for re-entry detection in milliseconds
    /// Prevents duplicate haptic when cursor re-enters the same slice quickly
    #[serde(default = "default_reentry_debounce")]
    pub reentry_debounce_ms: u64,

    /// Enable a haptic pulse when the focused application window changes,
    /// independent of the radial menu
    #[serde(default = "default_true")]
    pub window_switch_enabled: bool,

    /// Enable a haptic pulse when the cursor moves to a different physical
    /// monitor, independent of the radial menu
    #[serde(default = "default_true")]
    pub monitor_switch_enabled: bool,
}

fn default_true() -> bool { true }
fn default_intensity() -> u8 { 70 }
fn default_pattern() -> String { "subtle_collision".to_string() }
fn default_debounce() -> u64 { 20 }
fn default_slice_debounce() -> u64 { 20 }
fn default_reentry_debounce() -> u64 { 50 }

impl Default for HapticConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            intensity: default_intensity(),
            default_pattern: default_pattern(),
            per_event: HapticEventConfig::default(),
            debounce_ms: 20,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
            window_switch_enabled: true,
            monitor_switch_enabled: true,
        }
    }
}

impl HapticConfig {
    /// Validate all values
    pub fn validate(&mut self) {
        self.intensity = self.intensity.clamp(0, 100);
        self.per_event.validate();
    }

    /// Check if haptics are effectively disabled
    pub fn is_disabled(&self) -> bool {
        !self.enabled
    }
}

// ============================================================================
// Button Action Configuration
// ============================================================================

/// Actions that can be assigned to mouse buttons.
/// These match the action IDs written by the Python Settings UI.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ButtonAction {
    RadialMenu,
    VirtualDesktops,
    MiddleClick,
    Back,
    Forward,
    Copy,
    Paste,
    Undo,
    Redo,
    Screenshot,
    Smartshift,
    ScrollLeftRight,
    VolumeUp,
    VolumeDown,
    PlayPause,
    Mute,
    ZoomIn,
    ZoomOut,
    ShowDesktop,
    SwitchDesktopLeft,
    SwitchDesktopRight,
    TaskSwitcher,
    CloseWindow,
    LockScreen,
    Calculator,
    None,
    Custom,
}

impl std::fmt::Display for ButtonAction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ButtonAction::RadialMenu => write!(f, "radial_menu"),
            ButtonAction::VirtualDesktops => write!(f, "virtual_desktops"),
            ButtonAction::MiddleClick => write!(f, "middle_click"),
            ButtonAction::Back => write!(f, "back"),
            ButtonAction::Forward => write!(f, "forward"),
            ButtonAction::Copy => write!(f, "copy"),
            ButtonAction::Paste => write!(f, "paste"),
            ButtonAction::Undo => write!(f, "undo"),
            ButtonAction::Redo => write!(f, "redo"),
            ButtonAction::Screenshot => write!(f, "screenshot"),
            ButtonAction::Smartshift => write!(f, "smartshift"),
            ButtonAction::ScrollLeftRight => write!(f, "scroll_left_right"),
            ButtonAction::VolumeUp => write!(f, "volume_up"),
            ButtonAction::VolumeDown => write!(f, "volume_down"),
            ButtonAction::PlayPause => write!(f, "play_pause"),
            ButtonAction::Mute => write!(f, "mute"),
            ButtonAction::ZoomIn => write!(f, "zoom_in"),
            ButtonAction::ZoomOut => write!(f, "zoom_out"),
            ButtonAction::ShowDesktop => write!(f, "show_desktop"),
            ButtonAction::SwitchDesktopLeft => write!(f, "switch_desktop_left"),
            ButtonAction::SwitchDesktopRight => write!(f, "switch_desktop_right"),
            ButtonAction::TaskSwitcher => write!(f, "task_switcher"),
            ButtonAction::CloseWindow => write!(f, "close_window"),
            ButtonAction::LockScreen => write!(f, "lock_screen"),
            ButtonAction::Calculator => write!(f, "calculator"),
            ButtonAction::None => write!(f, "none"),
            ButtonAction::Custom => write!(f, "custom"),
        }
    }
}

fn default_gesture_action() -> ButtonAction { ButtonAction::VirtualDesktops }
fn default_thumb_action() -> ButtonAction { ButtonAction::RadialMenu }
fn default_middle_action() -> ButtonAction { ButtonAction::MiddleClick }
fn default_shift_wheel_action() -> ButtonAction { ButtonAction::Smartshift }
fn default_forward_action() -> ButtonAction { ButtonAction::Forward }
fn default_back_action() -> ButtonAction { ButtonAction::Back }
fn default_horizontal_scroll_action() -> ButtonAction { ButtonAction::ScrollLeftRight }
fn default_direction_action() -> ButtonAction { ButtonAction::None }
fn default_gesture_threshold_px() -> u32 { 40 }

/// Directional gestures on the gesture button: hold, drag, and a different
/// action fires per direction. Matches `buttons.gesture_directions` written by
/// Settings. Absent or `enabled: false` keeps the single-action behaviour of
/// `buttons.gesture` exactly as before, so existing configs are unaffected.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GestureDirectionsConfig {
    #[serde(default)]
    pub enabled: bool,

    #[serde(default = "default_direction_action")]
    pub up: ButtonAction,

    #[serde(default = "default_direction_action")]
    pub down: ButtonAction,

    #[serde(default = "default_direction_action")]
    pub left: ButtonAction,

    #[serde(default = "default_direction_action")]
    pub right: ButtonAction,

    /// Action for a press with no drag. `None` falls back to `buttons.gesture`,
    /// so the plain click keeps whatever the user already had assigned.
    #[serde(default)]
    pub click: Option<ButtonAction>,

    /// Movement below this many pixels counts as a click.
    #[serde(default = "default_gesture_threshold_px")]
    pub threshold_px: u32,
}

impl Default for GestureDirectionsConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            up: default_direction_action(),
            down: default_direction_action(),
            left: default_direction_action(),
            right: default_direction_action(),
            click: None,
            threshold_px: default_gesture_threshold_px(),
        }
    }
}

/// Per-button action assignments.
/// Matches the "buttons" section in config.json written by Settings UI.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ButtonsConfig {
    #[serde(default = "default_gesture_action")]
    pub gesture: ButtonAction,

    #[serde(default)]
    pub gesture_directions: GestureDirectionsConfig,

    #[serde(default = "default_thumb_action")]
    pub thumb: ButtonAction,

    #[serde(default = "default_middle_action")]
    pub middle: ButtonAction,

    #[serde(default = "default_shift_wheel_action")]
    pub shift_wheel: ButtonAction,

    #[serde(default = "default_forward_action")]
    pub forward: ButtonAction,

    #[serde(default = "default_back_action")]
    pub back: ButtonAction,

    #[serde(default = "default_horizontal_scroll_action")]
    pub horizontal_scroll: ButtonAction,

    /// Actions for controls beyond the named slots, keyed by HID++ control id
    /// as reported by `ListControls` ("0x00D7", decimal accepted). Lets any
    /// divertable control the mouse exposes (MX Anywhere side buttons, the
    /// MX Vertical DPI switch) carry an action; a `none` entry keeps the
    /// control at its native behaviour and clears its divert on reload.
    #[serde(default)]
    pub controls: std::collections::HashMap<String, ButtonAction>,
}

impl Default for ButtonsConfig {
    fn default() -> Self {
        Self {
            gesture: default_gesture_action(),
            gesture_directions: GestureDirectionsConfig::default(),
            thumb: default_thumb_action(),
            middle: default_middle_action(),
            shift_wheel: default_shift_wheel_action(),
            forward: default_forward_action(),
            back: default_back_action(),
            horizontal_scroll: default_horizontal_scroll_action(),
            controls: std::collections::HashMap::new(),
        }
    }
}

/// Parse a `buttons.controls` key: "0x00D7", "00D7"-style hex, or decimal.
pub fn parse_control_cid(key: &str) -> Option<u16> {
    let key = key.trim();
    if let Some(hex) = key.strip_prefix("0x").or_else(|| key.strip_prefix("0X")) {
        return u16::from_str_radix(hex, 16).ok();
    }
    key.parse::<u16>().ok()
}

// ============================================================================
// Thumb-Wheel Configuration
// ============================================================================

/// What a thumb-wheel rotation should do.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ThumbwheelMode {
    /// Thumb wheel keeps its native behaviour (not diverted).
    #[default]
    Off,
    /// Rotation adjusts system volume.
    Volume,
    /// Rotation scrolls horizontally.
    Scroll,
    /// Rotation zooms in/out (Ctrl +/-).
    Zoom,
}

/// Resolved output of a thumb-wheel rotation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ThumbwheelOutput {
    /// Dispatch a button action (volume/zoom) `repeats` times.
    Button(ButtonAction),
    /// Inject `clicks` horizontal scroll clicks (sign = direction).
    HorizontalScroll(i32),
}

/// Thumb-wheel configuration (HID++ ThumbWheel feature 0x2150).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThumbwheelConfig {
    /// What rotation does.
    #[serde(default)]
    pub mode: ThumbwheelMode,

    /// Invert rotation direction.
    #[serde(default)]
    pub invert: bool,

    /// Repeats per rotation notification (1..=8). Higher = faster response.
    #[serde(default = "default_thumbwheel_speed")]
    pub speed: u8,
}

fn default_thumbwheel_speed() -> u8 { 1 }

impl Default for ThumbwheelConfig {
    fn default() -> Self {
        Self {
            mode: ThumbwheelMode::default(),
            invert: false,
            speed: default_thumbwheel_speed(),
        }
    }
}

impl ThumbwheelConfig {
    /// Whether rotation should be diverted to HID++ notifications.
    ///
    /// Only Volume and Zoom need diverting (their rotations are re-injected as
    /// actions). Horizontal Scroll is the thumb-wheel's native hardware
    /// behaviour, so it is left un-diverted to scroll reliably on every
    /// compositor; Off is native too.
    pub fn is_diverted(&self) -> bool {
        matches!(self.mode, ThumbwheelMode::Volume | ThumbwheelMode::Zoom)
    }

    /// Hardware invert byte for `setThumbwheelReporting` (issue #127).
    ///
    /// Diverted modes (Volume/Zoom) invert in software via `resolve()`, so
    /// their hardware byte stays 0 to avoid inverting twice. Horizontal
    /// Scroll stays un-diverted (native REL_HWHEEL never reaches
    /// `resolve()`), so its inversion must happen in hardware. Off leaves the
    /// device at its native default.
    pub fn hardware_invert(&self) -> bool {
        self.invert && self.mode == ThumbwheelMode::Scroll
    }

    /// Number of times to repeat the action per rotation notification.
    pub fn repeats(&self) -> u8 {
        self.speed.clamp(1, 8)
    }

    /// Resolve a raw signed thumb-wheel delta into a directional output.
    ///
    /// Returns `None` when the wheel is off or the delta is zero. `invert` is
    /// applied here (software direction), so the device divert is enabled with
    /// no hardware inversion.
    pub fn resolve(&self, delta: i16) -> Option<ThumbwheelOutput> {
        if delta == 0 || self.mode == ThumbwheelMode::Off {
            return None;
        }
        let forward = if self.invert { delta < 0 } else { delta > 0 };
        Some(match (self.mode, forward) {
            (ThumbwheelMode::Volume, true) => ThumbwheelOutput::Button(ButtonAction::VolumeUp),
            (ThumbwheelMode::Volume, false) => ThumbwheelOutput::Button(ButtonAction::VolumeDown),
            (ThumbwheelMode::Zoom, true) => ThumbwheelOutput::Button(ButtonAction::ZoomIn),
            (ThumbwheelMode::Zoom, false) => ThumbwheelOutput::Button(ButtonAction::ZoomOut),
            (ThumbwheelMode::Scroll, true) => ThumbwheelOutput::HorizontalScroll(1),
            (ThumbwheelMode::Scroll, false) => ThumbwheelOutput::HorizontalScroll(-1),
            (ThumbwheelMode::Off, _) => unreachable!("guarded above"),
        })
    }
}

// ============================================================================
// Keyboard Configuration (BETA, opt-in)
// ============================================================================

/// MX Keys S HID++ options (battery readback + backlight). BETA.
///
/// Off by default. While disabled the daemon never opens or talks HID++ to any
/// keyboard, so a normal mouse-only setup is completely unaffected. Even when
/// enabled, the HID++ paths only run in response to an explicit D-Bus call.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MxKeysConfig {
    /// Allow the daemon to talk HID++ to an MX Keys S keyboard for battery
    /// readback and backlight control. Volatile reads are safe; the backlight
    /// SET is UNVERIFIED on hardware (see `hidpp::device::HidppDevice::set_backlight`).
    #[serde(default)]
    pub enabled: bool,
}

/// Generic keyboard remap + MX Keys S support. BETA, opt-in.
///
/// The whole section is inert unless `enabled` is true:
/// - `enabled` false (default): no keyboard is ever grabbed, opened, or remapped.
/// - `enabled` true + non-empty `remap`: the first physical keyboard is grabbed
///   (EVIOCGRAB) and its events forwarded through a virtual keyboard with the
///   listed source evdev key codes rewritten to their targets.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct KeyboardConfig {
    /// Master switch for the generic remap path. Off by default.
    #[serde(default)]
    pub enabled: bool,

    /// Generic remap table: source evdev key code -> target evdev key code.
    /// JSON object with stringified integer keys, e.g. `{"58": 29}`
    /// (CapsLock -> LeftCtrl). Empty by default; an empty table never triggers
    /// a device grab.
    #[serde(default)]
    pub remap: std::collections::HashMap<u16, u16>,

    /// MX Keys S HID++ options (battery + backlight). Independent of the
    /// generic remap switch above.
    #[serde(default)]
    pub mx_keys: MxKeysConfig,
}

impl KeyboardConfig {
    /// Whether the generic remap path should grab a keyboard: only when enabled
    /// AND at least one remap entry exists. Prevents a misconfigured-but-enabled
    /// section from grabbing the keyboard with an empty (identity) table.
    pub fn remap_active(&self) -> bool {
        self.enabled && !self.remap.is_empty()
    }
}

// ============================================================================
// Main Configuration
// ============================================================================

/// Main configuration structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    /// Haptic feedback settings
    #[serde(default)]
    pub haptics: HapticConfig,

    /// Current theme name
    #[serde(default = "default_theme")]
    pub theme: String,

    /// Enable blur effects (may be auto-disabled on slow GPUs)
    #[serde(default = "default_true")]
    pub blur_enabled: bool,

    /// Button action assignments
    #[serde(default)]
    pub buttons: ButtonsConfig,

    /// Thumb-wheel behaviour (HID++ ThumbWheel 0x2150)
    #[serde(default)]
    pub thumbwheel: ThumbwheelConfig,

    /// Keyboard support (generic remap + MX Keys S). BETA, opt-in, off by default.
    #[serde(default)]
    pub keyboard: KeyboardConfig,

    /// Configuration file path (not serialized)
    #[serde(skip)]
    pub config_path: Option<PathBuf>,
}

fn default_theme() -> String {
    "catppuccin-mocha".to_string()
}

impl Default for Config {
    fn default() -> Self {
        Self {
            haptics: HapticConfig::default(),
            theme: default_theme(),
            blur_enabled: true,
            buttons: ButtonsConfig::default(),
            thumbwheel: ThumbwheelConfig::default(),
            keyboard: KeyboardConfig::default(),
            config_path: None,
        }
    }
}

impl Config {
    /// Get the default config directory path
    pub fn default_config_dir() -> Option<PathBuf> {
        dirs::config_dir().map(|p| p.join(CONFIG_DIR))
    }

    /// Get the default config file path
    pub fn default_config_path() -> Option<PathBuf> {
        Self::default_config_dir().map(|p| p.join(CONFIG_FILE))
    }

    /// Load configuration from the default location
    ///
    /// Returns default config if file doesn't exist.
    pub fn load_default() -> Result<Self, ConfigError> {
        match Self::default_config_path() {
            Some(path) => Self::load(&path),
            None => {
                tracing::warn!("Could not determine config directory, using defaults");
                Ok(Self::default())
            }
        }
    }

    /// Load configuration from file path
    ///
    /// Returns default config if file doesn't exist.
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self, ConfigError> {
        let path = path.as_ref();

        // If file doesn't exist, return defaults
        if !path.exists() {
            tracing::info!(path = %path.display(), "Config file not found, using defaults");
            return Ok(Self { config_path: Some(path.to_path_buf()), ..Self::default() });
        }

        // Read and parse the file
        let contents = fs::read_to_string(path).map_err(ConfigError::IoError)?;
        let mut config: Config =
            serde_json::from_str(&contents).map_err(ConfigError::ParseError)?;

        // Validate and clamp values
        config.haptics.validate();
        config.config_path = Some(path.to_path_buf());

        tracing::info!(
            path = %path.display(),
            default_pattern = %config.haptics.default_pattern,
            haptics_enabled = config.haptics.enabled,
            theme = %config.theme,
            gesture_button = %config.buttons.gesture,
            thumb_button = %config.buttons.thumb,
            "Configuration loaded"
        );

        Ok(config)
    }

    /// Save configuration to file
    pub fn save(&self) -> Result<(), ConfigError> {
        let path = match &self.config_path {
            Some(p) => p.clone(),
            None => Self::default_config_path()
                .ok_or_else(|| ConfigError::ValidationError("No config path".to_string()))?,
        };

        // Ensure directory exists
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(ConfigError::IoError)?;
        }

        // Serialize and write
        let contents = serde_json::to_string_pretty(self).map_err(ConfigError::ParseError)?;
        fs::write(&path, contents).map_err(ConfigError::IoError)?;

        tracing::info!(path = %path.display(), "Configuration saved");
        Ok(())
    }

    /// Create default config file if it doesn't exist
    pub fn create_default_if_missing() -> Result<Self, ConfigError> {
        let config = Self::load_default()?;

        // Save defaults if file didn't exist
        if let Some(path) = &config.config_path {
            if !path.exists() {
                config.save()?;
                tracing::info!(path = %path.display(), "Created default configuration file");
            }
        }

        Ok(config)
    }

    /// Check if haptics are enabled
    pub fn haptics_enabled(&self) -> bool {
        self.haptics.enabled
    }

    /// Get default haptic pattern name
    pub fn default_haptic_pattern(&self) -> &str {
        &self.haptics.default_pattern
    }

    /// Whether the gesture button resolves to per-direction actions.
    pub fn directional_gestures_enabled(&self) -> bool {
        self.buttons.gesture_directions.enabled
    }

    /// Action for a classified gesture. A click falls back to the plain
    /// `buttons.gesture` assignment when no explicit click action is set.
    pub fn gesture_direction_action(&self, direction: crate::gesture::GestureDirection) -> ButtonAction {
        use crate::gesture::GestureDirection;
        let d = &self.buttons.gesture_directions;
        match direction {
            GestureDirection::Up => d.up,
            GestureDirection::Down => d.down,
            GestureDirection::Left => d.left,
            GestureDirection::Right => d.right,
            GestureDirection::Click => d.click.unwrap_or(self.buttons.gesture),
        }
    }

    /// Get the configured action for a HID++ CID (Control ID)
    pub fn action_for_cid(&self, cid: u16) -> ButtonAction {
        use crate::hidraw::button_cid;
        match cid {
            button_cid::GESTURE_BUTTON => self.buttons.gesture,
            button_cid::HAPTIC => self.buttons.thumb,
            button_cid::MIDDLE_BUTTON => self.buttons.middle,
            button_cid::BACK_BUTTON => self.buttons.back,
            button_cid::FORWARD_BUTTON => self.buttons.forward,
            button_cid::SMART_SHIFT => self.buttons.shift_wheel,
            _ => self.extra_control_action(cid).unwrap_or(ButtonAction::None),
        }
    }

    /// Action configured under `buttons.controls` for a CID, if any.
    fn extra_control_action(&self, cid: u16) -> Option<ButtonAction> {
        self.buttons
            .controls
            .iter()
            .find(|(key, _)| parse_control_cid(key) == Some(cid))
            .map(|(_, action)| *action)
    }

    /// Every CID named under `buttons.controls` (any action, including `none`),
    /// so a reload can clear the divert of a control returned to native.
    pub fn extra_control_cids(&self) -> Vec<u16> {
        let mut cids: Vec<u16> = self.buttons.controls.keys().filter_map(|k| parse_control_cid(k)).collect();
        cids.sort_unstable();
        cids.dedup();
        cids
    }

    /// CIDs of the non-gesture buttons (back, forward, middle, shift-wheel) the
    /// user has reassigned away from their native default. Only these are
    /// HID++-diverted so the daemon can apply the chosen action; buttons left at
    /// their native default are not diverted and keep hardware behaviour intact.
    pub fn remapped_button_cids(&self) -> Vec<u16> {
        use crate::hidraw::button_cid;
        let mut cids = Vec::new();
        if self.buttons.back != ButtonAction::Back {
            cids.push(button_cid::BACK_BUTTON);
        }
        if self.buttons.forward != ButtonAction::Forward {
            cids.push(button_cid::FORWARD_BUTTON);
        }
        if self.buttons.middle != ButtonAction::MiddleClick {
            cids.push(button_cid::MIDDLE_BUTTON);
        }
        if self.buttons.shift_wheel != ButtonAction::Smartshift {
            cids.push(button_cid::SMART_SHIFT);
        }
        // Extra controls carry an action only when one is configured; the
        // named slots above stay authoritative for their own CIDs.
        for cid in self.extra_control_cids() {
            if Self::managed_button_cids().contains(&cid)
                || cid == button_cid::GESTURE_BUTTON
                || cid == button_cid::HAPTIC
            {
                continue;
            }
            if self.extra_control_action(cid).is_some_and(|a| a != ButtonAction::None) {
                cids.push(cid);
            }
        }
        cids
    }

    /// The full set of non-gesture button CIDs the daemon may divert. Used on
    /// config reload to clear the divert for any button returned to its native
    /// default so its hardware behaviour comes back without a reconnect.
    pub fn managed_button_cids() -> [u16; 4] {
        use crate::hidraw::button_cid;
        [
            button_cid::BACK_BUTTON,
            button_cid::FORWARD_BUTTON,
            button_cid::MIDDLE_BUTTON,
            button_cid::SMART_SHIFT,
        ]
    }
}

// ============================================================================
// Shared Config (for hot-reload)
// ============================================================================

use std::sync::{Arc, RwLock};

/// Thread-safe shared configuration for hot-reload support
pub type SharedConfig = Arc<RwLock<Config>>;

/// Create a new shared config with defaults
pub fn new_shared_config() -> SharedConfig {
    Arc::new(RwLock::new(Config::default()))
}

/// Create a new shared config from file (or defaults if file doesn't exist)
pub fn load_shared_config() -> Result<SharedConfig, ConfigError> {
    let config = Config::load_default()?;
    Ok(Arc::new(RwLock::new(config)))
}

// ============================================================================
// Error Types
// ============================================================================

/// Configuration error type
#[derive(Debug)]
pub enum ConfigError {
    /// I/O error reading/writing file
    IoError(std::io::Error),
    /// JSON parsing error
    ParseError(serde_json::Error),
    /// Validation error
    ValidationError(String),
}

impl std::fmt::Display for ConfigError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ConfigError::IoError(e) => write!(f, "I/O error: {}", e),
            ConfigError::ParseError(e) => write!(f, "Parse error: {}", e),
            ConfigError::ValidationError(msg) => write!(f, "Validation error: {}", msg),
        }
    }
}

impl std::error::Error for ConfigError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ConfigError::IoError(e) => Some(e),
            ConfigError::ParseError(e) => Some(e),
            ConfigError::ValidationError(_) => None,
        }
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_gesture_config_keeps_directional_gestures_off() {
        let json = r#"{ "buttons": { "gesture": "copy" } }"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert!(!config.directional_gestures_enabled());
        assert_eq!(config.buttons.gesture, ButtonAction::Copy);
        assert_eq!(config.buttons.gesture_directions, GestureDirectionsConfig::default());
        assert_eq!(config.buttons.gesture_directions.threshold_px, 40);
    }

    #[test]
    fn gesture_directions_parse_partial_section_and_fall_back_for_click() {
        use crate::gesture::GestureDirection;
        let json = r#"{
            "buttons": {
                "gesture": "virtual_desktops",
                "gesture_directions": {
                    "enabled": true,
                    "up": "show_desktop",
                    "left": "switch_desktop_left",
                    "threshold_px": 64
                }
            }
        }"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert!(config.directional_gestures_enabled());
        assert_eq!(config.gesture_direction_action(GestureDirection::Up), ButtonAction::ShowDesktop);
        assert_eq!(config.gesture_direction_action(GestureDirection::Down), ButtonAction::None);
        assert_eq!(config.gesture_direction_action(GestureDirection::Left), ButtonAction::SwitchDesktopLeft);
        assert_eq!(config.gesture_direction_action(GestureDirection::Right), ButtonAction::None);
        assert_eq!(config.gesture_direction_action(GestureDirection::Click), ButtonAction::VirtualDesktops);
        assert_eq!(config.buttons.gesture_directions.threshold_px, 64);
    }

    #[test]
    fn gesture_directions_explicit_click_overrides_gesture_action() {
        use crate::gesture::GestureDirection;
        let json = r#"{
            "buttons": {
                "gesture": "virtual_desktops",
                "gesture_directions": { "enabled": true, "click": "task_switcher" }
            }
        }"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.gesture_direction_action(GestureDirection::Click), ButtonAction::TaskSwitcher);
    }

    #[test]
    fn gesture_directions_disabled_section_is_inert() {
        let json = r#"{
            "buttons": {
                "gesture_directions": { "enabled": false, "up": "copy" }
            }
        }"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert!(!config.directional_gestures_enabled());
        assert_eq!(config.action_for_cid(crate::hidraw::button_cid::GESTURE_BUTTON), ButtonAction::VirtualDesktops);
    }

    #[test]
    fn test_default_config() {
        let config = Config::default();
        assert_eq!(config.haptics.default_pattern, "subtle_collision");
        assert!(config.haptics.enabled);
        assert_eq!(config.theme, "catppuccin-mocha");
    }

    #[test]
    fn test_haptic_config_defaults() {
        let haptic = HapticConfig::default();
        assert!(haptic.enabled);
        assert_eq!(haptic.default_pattern, "subtle_collision");
        assert_eq!(haptic.per_event.menu_appear, "damp_state_change");
        assert_eq!(haptic.per_event.slice_change, "subtle_collision");
        assert_eq!(haptic.per_event.confirm, "sharp_state_change");
        assert_eq!(haptic.per_event.invalid, "angry_alert");
        assert_eq!(haptic.per_event.window_switch, "subtle_collision");
        assert!(haptic.window_switch_enabled);
        assert_eq!(haptic.per_event.monitor_switch, "subtle_collision");
        assert!(haptic.monitor_switch_enabled);
    }

    #[test]
    fn test_haptic_intensity_default() {
        // Field default must match the Settings UI default (70).
        assert_eq!(HapticConfig::default().intensity, 70);
        assert_eq!(default_intensity(), 70);
    }

    #[test]
    fn test_haptic_intensity_serde_roundtrip() {
        // Explicit value survives a serialize/deserialize round-trip.
        let mut cfg = HapticConfig::default();
        cfg.intensity = 42;
        let json = serde_json::to_string(&cfg).unwrap();
        assert!(json.contains("\"intensity\":42"), "serialized: {json}");
        let back: HapticConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(back.intensity, 42);
    }

    #[test]
    fn test_haptic_intensity_from_partial_json() {
        // The Settings UI writes intensity as part of the haptics block.
        let json = r#"{"haptics": {"intensity": 30}}"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.haptics.intensity, 30);
    }

    #[test]
    fn test_haptic_intensity_missing_uses_default() {
        // Older configs without the field fall back to the default (no drop).
        let json = r#"{"haptics": {"enabled": true}}"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.haptics.intensity, 70);
    }

    #[test]
    fn test_haptic_intensity_clamped_on_validate() {
        // Out-of-range values are clamped to 0..=100 on load.
        let mut high: HapticConfig = serde_json::from_str(r#"{"intensity": 250}"#).unwrap();
        high.validate();
        assert_eq!(high.intensity, 100);

        let mut ok: HapticConfig = serde_json::from_str(r#"{"intensity": 55}"#).unwrap();
        ok.validate();
        assert_eq!(ok.intensity, 55);
    }

    #[test]
    fn test_haptic_config_slice_debounce_defaults() {
        let haptic = HapticConfig::default();
        assert_eq!(haptic.slice_debounce_ms, 20);
        assert_eq!(haptic.reentry_debounce_ms, 50);
    }

    #[test]
    fn test_haptic_disabled_check() {
        let mut config = HapticConfig::default();
        assert!(!config.is_disabled());

        config.enabled = false;
        assert!(config.is_disabled());
    }

    #[test]
    fn test_config_json_parsing() {
        let json = r#"{
            "haptics": {
                "enabled": true,
                "default_pattern": "sharp_collision",
                "per_event": {
                    "menu_appear": "happy_alert",
                    "slice_change": "whisper_collision"
                }
            },
            "theme": "vaporwave"
        }"#;

        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.haptics.default_pattern, "sharp_collision");
        assert_eq!(config.haptics.per_event.menu_appear, "happy_alert");
        assert_eq!(config.haptics.per_event.slice_change, "whisper_collision");
        // Defaults should fill in missing fields
        assert_eq!(config.haptics.per_event.confirm, "sharp_state_change");
        assert_eq!(config.theme, "vaporwave");
    }

    #[test]
    fn test_config_json_minimal() {
        // Minimal config should use all defaults
        let json = r#"{}"#;
        let config: Config = serde_json::from_str(json).unwrap();

        assert!(config.haptics.enabled);
        assert_eq!(config.haptics.default_pattern, "subtle_collision");
        assert_eq!(config.theme, "catppuccin-mocha");
    }

    #[test]
    fn test_disabled_haptics_via_enabled_field() {
        let json = r#"{"haptics": {"enabled": false}}"#;
        let config: Config = serde_json::from_str(json).unwrap();

        assert!(!config.haptics_enabled());
        assert!(config.haptics.is_disabled());
    }

    #[test]
    fn test_haptics_enabled_getter() {
        let config = Config::default();
        assert!(config.haptics_enabled());
        assert_eq!(config.default_haptic_pattern(), "subtle_collision");
    }

    #[test]
    fn test_config_serialization() {
        let config = Config::default();
        let json = serde_json::to_string_pretty(&config).unwrap();

        // Should contain expected fields
        assert!(json.contains("haptics"));
        assert!(json.contains("default_pattern"));
        assert!(json.contains("catppuccin-mocha"));
        assert!(json.contains("buttons"));
        assert!(json.contains("virtual_desktops"));
        assert!(json.contains("radial_menu"));
    }

    // ========================================================================
    // Button Action Config Tests
    // ========================================================================

    #[test]
    fn test_button_action_serde_all_variants() {
        // Test that all action IDs from Settings UI deserialize correctly
        let actions = vec![
            ("\"radial_menu\"", ButtonAction::RadialMenu),
            ("\"virtual_desktops\"", ButtonAction::VirtualDesktops),
            ("\"middle_click\"", ButtonAction::MiddleClick),
            ("\"back\"", ButtonAction::Back),
            ("\"forward\"", ButtonAction::Forward),
            ("\"copy\"", ButtonAction::Copy),
            ("\"paste\"", ButtonAction::Paste),
            ("\"undo\"", ButtonAction::Undo),
            ("\"redo\"", ButtonAction::Redo),
            ("\"screenshot\"", ButtonAction::Screenshot),
            ("\"smartshift\"", ButtonAction::Smartshift),
            ("\"scroll_left_right\"", ButtonAction::ScrollLeftRight),
            ("\"volume_up\"", ButtonAction::VolumeUp),
            ("\"volume_down\"", ButtonAction::VolumeDown),
            ("\"play_pause\"", ButtonAction::PlayPause),
            ("\"mute\"", ButtonAction::Mute),
            ("\"zoom_in\"", ButtonAction::ZoomIn),
            ("\"zoom_out\"", ButtonAction::ZoomOut),
            ("\"none\"", ButtonAction::None),
            ("\"custom\"", ButtonAction::Custom),
        ];

        for (json, expected) in actions {
            let result: ButtonAction = serde_json::from_str(json).unwrap();
            assert_eq!(result, expected, "Failed for JSON: {}", json);
        }
    }

    #[test]
    fn test_button_action_serialize_roundtrip() {
        let action = ButtonAction::VirtualDesktops;
        let json = serde_json::to_string(&action).unwrap();
        assert_eq!(json, "\"virtual_desktops\"");

        let back: ButtonAction = serde_json::from_str(&json).unwrap();
        assert_eq!(back, ButtonAction::VirtualDesktops);
    }

    #[test]
    fn test_buttons_config_defaults_match_settings_ui() {
        // Default button assignments must match Python Settings UI defaults
        // from settings_constants.py _BASE_DEFAULT_BUTTON_ACTIONS
        let config = ButtonsConfig::default();
        assert_eq!(config.gesture, ButtonAction::VirtualDesktops);
        assert_eq!(config.thumb, ButtonAction::RadialMenu);
        assert_eq!(config.middle, ButtonAction::MiddleClick);
        assert_eq!(config.shift_wheel, ButtonAction::Smartshift);
        assert_eq!(config.forward, ButtonAction::Forward);
        assert_eq!(config.back, ButtonAction::Back);
        assert_eq!(config.horizontal_scroll, ButtonAction::ScrollLeftRight);
    }

    #[test]
    fn test_config_with_buttons_section() {
        // Simulate the JSON that Settings UI writes
        let json = r#"{
            "buttons": {
                "gesture": "virtual_desktops",
                "middle": "middle_click",
                "shift_wheel": "smartshift",
                "thumb": "radial_menu"
            }
        }"#;

        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.buttons.gesture, ButtonAction::VirtualDesktops);
        assert_eq!(config.buttons.thumb, ButtonAction::RadialMenu);
        assert_eq!(config.buttons.middle, ButtonAction::MiddleClick);
        assert_eq!(config.buttons.shift_wheel, ButtonAction::Smartshift);
        // Unspecified buttons use defaults
        assert_eq!(config.buttons.forward, ButtonAction::Forward);
        assert_eq!(config.buttons.back, ButtonAction::Back);
    }

    #[test]
    fn test_config_without_buttons_section_backward_compat() {
        // Existing config files without a "buttons" section should still work
        let json = r#"{
            "haptics": {"enabled": true},
            "theme": "catppuccin-mocha"
        }"#;

        let config: Config = serde_json::from_str(json).unwrap();
        // Buttons should have sane defaults
        assert_eq!(config.buttons.gesture, ButtonAction::VirtualDesktops);
        assert_eq!(config.buttons.thumb, ButtonAction::RadialMenu);
    }

    #[test]
    fn test_config_swapped_buttons() {
        // User swaps gesture=radial_menu, thumb=virtual_desktops
        let json = r#"{
            "buttons": {
                "gesture": "radial_menu",
                "thumb": "virtual_desktops"
            }
        }"#;

        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.buttons.gesture, ButtonAction::RadialMenu);
        assert_eq!(config.buttons.thumb, ButtonAction::VirtualDesktops);
    }

    #[test]
    fn test_button_action_display() {
        assert_eq!(format!("{}", ButtonAction::RadialMenu), "radial_menu");
        assert_eq!(format!("{}", ButtonAction::VirtualDesktops), "virtual_desktops");
        assert_eq!(format!("{}", ButtonAction::MiddleClick), "middle_click");
        assert_eq!(format!("{}", ButtonAction::None), "none");
    }

    // ========================================================================
    // Thumb-Wheel Config Tests
    // ========================================================================

    #[test]
    fn test_thumbwheel_defaults() {
        let tw = ThumbwheelConfig::default();
        assert_eq!(tw.mode, ThumbwheelMode::Off);
        assert!(!tw.invert);
        assert_eq!(tw.speed, 1);
        assert!(!tw.is_diverted());
    }

    #[test]
    fn test_thumbwheel_off_resolves_none() {
        let tw = ThumbwheelConfig::default();
        assert_eq!(tw.resolve(100), None);
        assert_eq!(tw.resolve(-100), None);
    }

    #[test]
    fn test_thumbwheel_zero_delta_resolves_none() {
        let tw = ThumbwheelConfig { mode: ThumbwheelMode::Volume, ..Default::default() };
        assert_eq!(tw.resolve(0), None);
    }

    #[test]
    fn test_thumbwheel_volume_direction() {
        let tw = ThumbwheelConfig { mode: ThumbwheelMode::Volume, ..Default::default() };
        assert_eq!(tw.resolve(5), Some(ThumbwheelOutput::Button(ButtonAction::VolumeUp)));
        assert_eq!(tw.resolve(-5), Some(ThumbwheelOutput::Button(ButtonAction::VolumeDown)));
        assert!(tw.is_diverted());
    }

    #[test]
    fn test_thumbwheel_invert_flips_direction() {
        let tw = ThumbwheelConfig { mode: ThumbwheelMode::Volume, invert: true, speed: 1 };
        assert_eq!(tw.resolve(5), Some(ThumbwheelOutput::Button(ButtonAction::VolumeDown)));
        assert_eq!(tw.resolve(-5), Some(ThumbwheelOutput::Button(ButtonAction::VolumeUp)));
    }

    #[test]
    fn test_thumbwheel_hardware_invert_only_for_native_scroll() {
        // Issue #127: Scroll is never diverted, so its inversion must be the
        // hardware byte; diverted modes invert in software (resolve()) and
        // must keep the hardware byte 0, or direction would flip twice.
        let scroll = ThumbwheelConfig { mode: ThumbwheelMode::Scroll, invert: true, speed: 1 };
        assert!(scroll.hardware_invert());
        assert!(!scroll.is_diverted());

        let volume = ThumbwheelConfig { mode: ThumbwheelMode::Volume, invert: true, speed: 1 };
        assert!(!volume.hardware_invert());
        let zoom = ThumbwheelConfig { mode: ThumbwheelMode::Zoom, invert: true, speed: 1 };
        assert!(!zoom.hardware_invert());
        let off = ThumbwheelConfig { mode: ThumbwheelMode::Off, invert: true, speed: 1 };
        assert!(!off.hardware_invert());

        let not_inverted = ThumbwheelConfig { mode: ThumbwheelMode::Scroll, invert: false, speed: 1 };
        assert!(!not_inverted.hardware_invert());
    }

    #[test]
    fn test_thumbwheel_zoom_and_scroll() {
        let zoom = ThumbwheelConfig { mode: ThumbwheelMode::Zoom, ..Default::default() };
        assert_eq!(zoom.resolve(1), Some(ThumbwheelOutput::Button(ButtonAction::ZoomIn)));
        assert_eq!(zoom.resolve(-1), Some(ThumbwheelOutput::Button(ButtonAction::ZoomOut)));

        let scroll = ThumbwheelConfig { mode: ThumbwheelMode::Scroll, ..Default::default() };
        assert_eq!(scroll.resolve(1), Some(ThumbwheelOutput::HorizontalScroll(1)));
        assert_eq!(scroll.resolve(-1), Some(ThumbwheelOutput::HorizontalScroll(-1)));
    }

    #[test]
    fn test_thumbwheel_repeats_clamped() {
        assert_eq!(ThumbwheelConfig { speed: 0, ..Default::default() }.repeats(), 1);
        assert_eq!(ThumbwheelConfig { speed: 3, ..Default::default() }.repeats(), 3);
        assert_eq!(ThumbwheelConfig { speed: 99, ..Default::default() }.repeats(), 8);
    }

    #[test]
    fn test_config_thumbwheel_json_roundtrip() {
        let json = r#"{"thumbwheel": {"mode": "volume", "invert": true, "speed": 4}}"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.thumbwheel.mode, ThumbwheelMode::Volume);
        assert!(config.thumbwheel.invert);
        assert_eq!(config.thumbwheel.speed, 4);
    }

    #[test]
    fn test_config_without_thumbwheel_backward_compat() {
        let json = r#"{"theme": "catppuccin-mocha"}"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.thumbwheel.mode, ThumbwheelMode::Off);
    }

    #[test]
    fn test_action_for_cid() {
        let config = Config::default();
        use crate::hidraw::button_cid;

        assert_eq!(config.action_for_cid(button_cid::GESTURE_BUTTON), ButtonAction::VirtualDesktops);
        assert_eq!(config.action_for_cid(button_cid::HAPTIC), ButtonAction::RadialMenu);
        assert_eq!(config.action_for_cid(button_cid::MIDDLE_BUTTON), ButtonAction::MiddleClick);
        assert_eq!(config.action_for_cid(button_cid::BACK_BUTTON), ButtonAction::Back);
        assert_eq!(config.action_for_cid(button_cid::FORWARD_BUTTON), ButtonAction::Forward);
        assert_eq!(config.action_for_cid(button_cid::SMART_SHIFT), ButtonAction::Smartshift);
        assert_eq!(config.action_for_cid(9999), ButtonAction::None); // Unknown CID
    }

    #[test]
    fn extra_controls_carry_actions_and_diverts() {
        use crate::hidraw::button_cid;
        let json = r#"{"buttons": {"controls": {"0x00D7": "copy", "253": "zoom_in", "0x00FE": "none", "junk": "paste", "0x0053": "undo"}}}"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert_eq!(config.action_for_cid(0x00D7), ButtonAction::Copy);
        assert_eq!(config.action_for_cid(253), ButtonAction::ZoomIn);
        assert_eq!(config.action_for_cid(0x00FE), ButtonAction::None);
        // the named back slot wins over a controls entry for the same CID
        assert_eq!(config.action_for_cid(button_cid::BACK_BUTTON), ButtonAction::Back);
        let remapped = config.remapped_button_cids();
        assert!(remapped.contains(&0x00D7) && remapped.contains(&253));
        assert!(!remapped.contains(&0x00FE), "a none entry is not diverted");
        assert!(!remapped.contains(&button_cid::BACK_BUTTON));
        assert_eq!(config.extra_control_cids(), vec![0x0053, 0x00D7, 0x00FD, 0x00FE]);
        assert_eq!(parse_control_cid(" 0X1a0 "), Some(0x01A0));
        assert_eq!(parse_control_cid("junk"), None);
    }

    #[test]
    fn test_remapped_button_cids() {
        use crate::hidraw::button_cid;

        // Defaults are all native, so nothing is diverted.
        assert!(Config::default().remapped_button_cids().is_empty());

        // Reassigning non-gesture buttons away from their default marks them.
        let mut config = Config::default();
        config.buttons.back = ButtonAction::PlayPause;
        config.buttons.middle = ButtonAction::None;
        let cids = config.remapped_button_cids();
        assert!(cids.contains(&button_cid::BACK_BUTTON));
        assert!(cids.contains(&button_cid::MIDDLE_BUTTON));
        assert!(!cids.contains(&button_cid::FORWARD_BUTTON));
        assert!(!cids.contains(&button_cid::SMART_SHIFT));

        // Returning a button to its native default clears it.
        config.buttons.back = ButtonAction::Back;
        assert!(
            !config
                .remapped_button_cids()
                .contains(&button_cid::BACK_BUTTON)
        );
    }

    // ========================================================================
    // Keyboard Config Tests (BETA)
    // ========================================================================

    #[test]
    fn test_keyboard_defaults_disabled() {
        let kb = KeyboardConfig::default();
        assert!(!kb.enabled);
        assert!(kb.remap.is_empty());
        assert!(!kb.mx_keys.enabled);
        // Nothing should grab the keyboard with defaults.
        assert!(!kb.remap_active());
    }

    #[test]
    fn test_keyboard_remap_active_requires_enabled_and_entries() {
        let mut kb = KeyboardConfig::default();
        kb.remap.insert(58, 29); // CapsLock -> LeftCtrl, but still disabled
        assert!(!kb.remap_active());

        kb.enabled = true;
        assert!(kb.remap_active());

        kb.remap.clear();
        // Enabled but empty table must NOT grab.
        assert!(!kb.remap_active());
    }

    #[test]
    fn test_config_without_keyboard_section_backward_compat() {
        // Existing configs with no "keyboard" section must still parse.
        let json = r#"{"theme": "catppuccin-mocha"}"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert!(!config.keyboard.enabled);
        assert!(config.keyboard.remap.is_empty());
        assert!(!config.keyboard.mx_keys.enabled);
    }

    #[test]
    fn test_config_keyboard_json_roundtrip() {
        let json = r#"{
            "keyboard": {
                "enabled": true,
                "remap": {"58": 29, "1": 14},
                "mx_keys": {"enabled": true}
            }
        }"#;
        let config: Config = serde_json::from_str(json).unwrap();
        assert!(config.keyboard.enabled);
        assert_eq!(config.keyboard.remap.get(&58), Some(&29));
        assert_eq!(config.keyboard.remap.get(&1), Some(&14));
        assert!(config.keyboard.mx_keys.enabled);
        assert!(config.keyboard.remap_active());

        // Round-trips back through serialization (string keys in JSON).
        let out = serde_json::to_string(&config).unwrap();
        let reparsed: Config = serde_json::from_str(&out).unwrap();
        assert_eq!(reparsed.keyboard.remap.get(&58), Some(&29));
    }
}
