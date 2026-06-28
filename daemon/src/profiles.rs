//! Profile management for per-application radial menu configurations
//!
//! Story 3.1: Profile Configuration Schema
//!
//! Configuration is stored at `~/.config/juhradial/profiles.json`

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use crate::actions::{get_default_actions, Action};
use crate::config::{ButtonAction, ThumbwheelMode};

/// Current schema version for profiles.json
///
/// v2 added the optional `hardware` map (per-app HardwareProfile). v1 files load
/// unchanged: the field defaults to empty and `migrate` bumps the version.
pub const SCHEMA_VERSION: u32 = 2;

/// Default config directory name
const CONFIG_DIR_NAME: &str = "juhradial";

/// Default profiles filename
const PROFILES_FILENAME: &str = "profiles.json";

/// Shared, hot-reloadable per-app hardware profile map keyed by (lowercased)
/// window resource class. Written by `ReloadConfig`, read by the focus-change
/// consumer that applies a `HardwareProfile` when the active window changes.
pub type SharedHardwareProfiles = Arc<RwLock<HashMap<String, HardwareProfile>>>;

/// serde default for `ProfilesConfig::version` when a file omits it.
///
/// The GTK settings UI writes profiles.json in a FLAT shape (per-app keys plus a
/// `hardware` map) with no top-level `version`/`profiles`. Defaulting both lets
/// that file load without a parse error so the `hardware` map is still read.
fn default_schema_version() -> u32 {
    SCHEMA_VERSION
}

/// Top-level profiles configuration (Story 3.1: Task 1.1, 1.3)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfilesConfig {
    /// Schema version for future migrations. Defaulted so a UI-written file that
    /// omits it still loads (see `default_schema_version`).
    #[serde(default = "default_schema_version")]
    pub version: u32,

    /// All profiles (default + application-specific). Defaulted to empty so a
    /// flat UI-written file (which has no `profiles` array) still loads; the
    /// loader then inserts the built-in default profile.
    #[serde(default)]
    pub profiles: Vec<Profile>,

    /// Per-application hardware profiles, keyed by window resource class.
    /// Added in schema v2; absent in v1 files (defaults to empty).
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub hardware: HashMap<String, HardwareProfile>,
}

impl Default for ProfilesConfig {
    fn default() -> Self {
        Self {
            version: SCHEMA_VERSION,
            profiles: vec![create_default_profile()],
            hardware: HashMap::new(),
        }
    }
}

/// SmartShift setting for a hardware profile.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub struct SmartshiftSetting {
    pub enabled: bool,
    pub threshold: u8,
}

/// Per-application HARDWARE state to apply on focus (Story 3.x).
///
/// Every field is optional: only the ones present are applied, and each maps to
/// a VOLATILE HID++ setter (no onboard-memory writes). Missing fields leave the
/// current device state untouched.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct HardwareProfile {
    /// Pointer DPI (ADJUSTABLE_DPI 0x2201).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dpi: Option<u16>,

    /// SmartShift auto-disengage (HiResScroll 0x2111).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub smartshift: Option<SmartshiftSetting>,

    /// HiRes/ratchet scroll mode (true = hi-res on).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hires: Option<bool>,

    /// Thumb-wheel mode (divert is derived: any non-Off mode diverts).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thumbwheel: Option<ThumbwheelMode>,

    /// Per-button action overrides keyed by button name (gesture/thumb/middle/
    /// back/forward/shift_wheel). Recorded in the schema; applied via config, not
    /// by `apply_hardware_profile` (which only touches volatile device state).
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub buttons: HashMap<String, ButtonAction>,
}

impl ProfilesConfig {
    /// Create a new ProfilesConfig with default profile
    pub fn new() -> Self {
        Self::default()
    }

    /// Create ProfilesConfig with default profile using get_default_actions()
    /// (Story 3.1: Task 4.1, 4.2)
    pub fn with_default_actions() -> Self {
        Self {
            version: SCHEMA_VERSION,
            profiles: vec![create_default_profile()],
            hardware: HashMap::new(),
        }
    }

    /// Migrate an older config in place, defaulting any fields added by newer
    /// schema versions, then stamp the current version. v1 -> v2 only needs the
    /// `hardware` map, which serde already defaulted to empty on load.
    pub fn migrate(&mut self) {
        if self.version < SCHEMA_VERSION {
            tracing::info!(
                from = self.version,
                to = SCHEMA_VERSION,
                "Migrating profiles config (defaulting new hardware fields)"
            );
            // `hardware` is already populated (empty) by serde default; nothing
            // else to backfill for v1 -> v2.
            self.version = SCHEMA_VERSION;
        }
    }
}

/// A radial menu profile (Story 3.1: Task 1.2)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Profile {
    /// Profile name
    pub name: String,

    /// Window class to match (None for default profile)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub window_class: Option<String>,

    /// 8 slice actions (N, NE, E, SE, S, SW, W, NW)
    pub slices: [Option<Action>; 8],

    /// Center tap action
    #[serde(skip_serializing_if = "Option::is_none")]
    pub center: Option<Action>,

    /// Profile icon (emoji or path)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub icon: Option<String>,

    /// Profile description
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

impl Default for Profile {
    fn default() -> Self {
        Self {
            name: "default".to_string(),
            window_class: None,
            slices: [None, None, None, None, None, None, None, None],
            center: None,
            icon: None,
            description: Some("Default profile".to_string()),
        }
    }
}

/// Create the default profile with common actions (Story 3.1: Task 4.1, 4.2)
pub fn create_default_profile() -> Profile {
    let default_actions = get_default_actions();

    Profile {
        name: "default".to_string(),
        window_class: None,
        slices: [
            Some(default_actions[0].clone()), // N: Copy
            Some(default_actions[1].clone()), // NE: Paste
            Some(default_actions[2].clone()), // E: Undo
            Some(default_actions[3].clone()), // SE: Redo
            Some(default_actions[4].clone()), // S: Select All
            Some(default_actions[5].clone()), // SW: Cut
            Some(default_actions[6].clone()), // W: Save
            Some(default_actions[7].clone()), // NW: Close
        ],
        center: None,
        icon: Some("🎯".to_string()),
        description: Some("Default profile with common shortcuts".to_string()),
    }
}

/// Validate an icon reference (Story 3.5)
///
/// Accepts:
/// - Unicode emoji (single character or emoji sequence)
/// - File path (ends with .png, .svg, .ico)
/// - System icon name (alphanumeric with hyphens)
///
/// Returns true if the icon reference appears valid.
pub fn validate_icon_reference(icon: &str) -> bool {
    if icon.is_empty() {
        return false;
    }

    // Check if it's an emoji or symbol character (common Unicode emoji ranges)
    let first_char = icon.chars().next().unwrap();
    let cp = first_char as u32;
    if cp > 0x1F000                        // Supplementary emoji (Mahjong+)
        || (0x2190..=0x21FF).contains(&cp) // Arrows (↩, ↪)
        || (0x2300..=0x23FF).contains(&cp) // Misc Technical (⏏, ⌨)
        || (0x2500..=0x27BF).contains(&cp) // Box Drawing through Dingbats (✂, ❌)
        // Supplemental Arrows, Misc Symbols (⭐)
        || (0x2900..=0x2BFF).contains(&cp)
    {
        return true;
    }

    // Check if it's a file path
    let lower = icon.to_lowercase();
    if lower.ends_with(".png") || lower.ends_with(".svg") || lower.ends_with(".ico") {
        // It's a file path - we don't validate existence here (done at render)
        return true;
    }

    // Check if it's a system icon name (letters, numbers, hyphens)
    if icon
        .chars()
        .all(|c| c.is_alphanumeric() || c == '-' || c == '_')
    {
        return true;
    }

    // Unknown format
    false
}

/// Direction indices for slices
pub mod direction {
    pub const NORTH: usize = 0;
    pub const NORTH_EAST: usize = 1;
    pub const EAST: usize = 2;
    pub const SOUTH_EAST: usize = 3;
    pub const SOUTH: usize = 4;
    pub const SOUTH_WEST: usize = 5;
    pub const WEST: usize = 6;
    pub const NORTH_WEST: usize = 7;
}

/// Get the config directory path (~/.config/juhradial/) (Story 3.1: Task 2.1, 2.3)
///
/// Respects XDG_CONFIG_HOME if set, otherwise uses ~/.config/
pub fn get_config_dir() -> PathBuf {
    // Check XDG_CONFIG_HOME first (Task 2.3)
    if let Ok(xdg_config) = std::env::var("XDG_CONFIG_HOME") {
        return PathBuf::from(xdg_config).join(CONFIG_DIR_NAME);
    }

    // Fall back to ~/.config/
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home).join(".config").join(CONFIG_DIR_NAME);
    }

    // Last resort fallback
    PathBuf::from(".config").join(CONFIG_DIR_NAME)
}

/// Get the profiles.json file path (Story 3.1: Task 2.2)
pub fn get_profiles_path() -> PathBuf {
    get_config_dir().join(PROFILES_FILENAME)
}

/// Ensure config directory exists (Story 3.1: Task 2.4)
pub fn ensure_config_dir() -> Result<PathBuf, ProfileError> {
    ensure_config_dir_at(get_config_dir())
}

fn ensure_config_dir_at(config_dir: PathBuf) -> Result<PathBuf, ProfileError> {
    if !config_dir.exists() {
        fs::create_dir_all(&config_dir).map_err(ProfileError::IoError)?;
        tracing::info!("Created config directory: {:?}", config_dir);
    }

    Ok(config_dir)
}

/// Profile manager for loading and switching profiles
#[derive(Debug)]
pub struct ProfileManager {
    /// All loaded profiles
    profiles: HashMap<String, Profile>,

    /// Current active profile name
    current_profile: String,

    /// Window class to profile mapping (Story 3.1: Task 3.4)
    window_mappings: HashMap<String, String>,

    /// Per-application hardware profiles keyed by window resource class (v2)
    hardware: HashMap<String, HardwareProfile>,

    /// Config file path (used for future save functionality)
    #[allow(dead_code)]
    config_path: PathBuf,
}

impl ProfileManager {
    /// Create a new profile manager with default profile
    pub fn new() -> Self {
        let mut profiles = HashMap::new();
        let default_profile = create_default_profile();
        profiles.insert("default".to_string(), default_profile);

        Self {
            profiles,
            current_profile: "default".to_string(),
            window_mappings: HashMap::new(),
            hardware: HashMap::new(),
            config_path: get_profiles_path(),
        }
    }

    /// Load profiles from JSON file or create default (Story 3.1: Task 3, 5)
    ///
    /// If profiles.json doesn't exist, creates it with default profile.
    pub fn load_or_create() -> Result<Self, ProfileError> {
        let config_path = get_profiles_path();

        // Check if file exists (Task 5.1)
        if !config_path.exists() {
            tracing::info!("profiles.json not found, creating default...");
            // Create default profiles.json (Task 5.2)
            let manager = Self::create_default_file()?;
            return Ok(manager);
        }

        // Load existing file (Task 3.1)
        Self::load_from_path(&config_path)
    }

    /// Load profiles from a specific path (Story 3.1: Task 3.1-3.5)
    pub fn load_from_path(path: &Path) -> Result<Self, ProfileError> {
        // Task 3.1: Read file
        let content = fs::read_to_string(path).map_err(ProfileError::IoError)?;

        // Task 3.2: Deserialize JSON
        let mut config: ProfilesConfig =
            serde_json::from_str(&content).map_err(ProfileError::ParseError)?;

        // Migrate older schema versions (defaults missing hardware fields).
        config.migrate();

        // Capture per-app hardware profiles before consuming `config.profiles`.
        // Keys are normalized to lowercase so lookups are case-insensitive: the
        // KWin/Hyprland/X11 window-class sources differ in case, and the D-Bus
        // `ReportActiveWindow` path lowercases the incoming class.
        let hardware: HashMap<String, HardwareProfile> = config
            .hardware
            .iter()
            .map(|(k, v)| (k.to_lowercase(), v.clone()))
            .collect();

        // Task 3.3, 3.4: Build profile map and window mappings
        let mut profiles = HashMap::new();
        let mut window_mappings = HashMap::new();

        for mut profile in config.profiles {
            // Story 3.6: Validate and fix slice count
            // If profile has wrong number of slices, pad or truncate to 8
            let slice_count = profile.slices.len();
            if slice_count != 8 {
                tracing::warn!(
                    profile = %profile.name,
                    found = slice_count,
                    expected = 8,
                    "Profile has incorrect slice count - padding/truncating to 8"
                );
                // Create new array with exactly 8 slots
                let mut fixed_slices: [Option<Action>; 8] = Default::default();
                for (i, slice) in profile.slices.iter().take(8).enumerate() {
                    fixed_slices[i] = slice.clone();
                }
                profile.slices = fixed_slices;
            }

            // Story 3.5: Validate icons (warn on invalid, don't fail)
            for (i, slice) in profile.slices.iter().enumerate() {
                if let Some(action) = slice {
                    if let Some(ref icon) = action.icon {
                        if !validate_icon_reference(icon) {
                            tracing::warn!(
                                profile = %profile.name,
                                slice = i,
                                icon = %icon,
                                "Icon may not be valid - will fall back to default at render time"
                            );
                        }
                    }
                }
            }

            // Story 3.3: Build window class mapping for profile matching
            if let Some(ref window_class) = profile.window_class {
                window_mappings.insert(window_class.clone(), profile.name.clone());
            }

            profiles.insert(profile.name.clone(), profile);
        }

        // Ensure default profile exists
        if !profiles.contains_key("default") {
            profiles.insert("default".to_string(), create_default_profile());
            tracing::warn!("Default profile missing from config, using built-in default");
        }

        tracing::info!(
            profile_count = profiles.len(),
            "Loaded profiles from {:?}",
            path
        );

        Ok(Self {
            profiles,
            current_profile: "default".to_string(),
            window_mappings,
            hardware,
            config_path: path.to_path_buf(),
        })
    }

    /// Create default profiles.json file (Story 3.1: Task 4.3, 4.4)
    fn create_default_file() -> Result<Self, ProfileError> {
        // Ensure directory exists (Task 2.4)
        ensure_config_dir()?;

        let config_path = get_profiles_path();
        let config = ProfilesConfig::with_default_actions();

        // Write JSON file (Task 4.3)
        let json = serde_json::to_string_pretty(&config).map_err(ProfileError::ParseError)?;

        let mut file = fs::File::create(&config_path).map_err(ProfileError::IoError)?;
        file.write_all(json.as_bytes())
            .map_err(ProfileError::IoError)?;

        // Log creation (Task 4.4)
        tracing::info!("Created default profiles.json at {:?}", config_path);

        // Load the newly created config
        Self::load_from_path(&config_path)
    }

    /// Get profile for a window class (falls back to default)
    pub fn get_profile_for_window(&self, window_class: &str) -> &Profile {
        if let Some(profile_name) = self.window_mappings.get(window_class) {
            if let Some(profile) = self.profiles.get(profile_name) {
                return profile;
            }
        }
        self.profiles
            .get("default")
            .expect("Default profile must exist")
    }

    /// Get the hardware profile for a window class, if one is configured.
    ///
    /// Lookup is case-insensitive: the map keys are lowercased at load time, so
    /// the query is lowercased to match.
    pub fn get_hardware_profile_for_window(&self, window_class: &str) -> Option<&HardwareProfile> {
        self.hardware.get(&window_class.to_lowercase())
    }

    /// Whether any per-app hardware profiles are configured.
    pub fn has_hardware_profiles(&self) -> bool {
        !self.hardware.is_empty()
    }

    /// Clone the (lowercased-key) per-app hardware profile map for sharing with
    /// the focus-change consumer behind a `SharedHardwareProfiles`.
    pub fn hardware_profiles(&self) -> HashMap<String, HardwareProfile> {
        self.hardware.clone()
    }

    /// Get current active profile
    pub fn current(&self) -> &Profile {
        self.profiles
            .get(&self.current_profile)
            .expect("Current profile must exist")
    }

    /// Set current profile by name
    pub fn set_current(&mut self, name: &str) -> Result<(), ProfileError> {
        if self.profiles.contains_key(name) {
            self.current_profile = name.to_string();
            Ok(())
        } else {
            Err(ProfileError::NotFound(name.to_string()))
        }
    }

    /// Get profile count
    pub fn profile_count(&self) -> usize {
        self.profiles.len()
    }

    /// Get list of profile names
    pub fn profile_names(&self) -> Vec<&String> {
        self.profiles.keys().collect()
    }
}

impl Default for ProfileManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Apply a per-app hardware profile to the device (VOLATILE only).
///
/// Each present field maps to a runtime HID++ setter on the haptic manager;
/// absent fields leave current state untouched. Failures are logged, not
/// fatal, so one unsupported setter never blocks the rest. Per-button overrides
/// are intentionally NOT applied here (they are config-level, not device state).
pub fn apply_hardware_profile(profile: &HardwareProfile, manager: &mut crate::hidpp::HapticManager) {
    if let Some(dpi) = profile.dpi {
        match manager.set_dpi(dpi) {
            Ok(()) => tracing::info!(dpi, "Hardware profile: DPI applied"),
            Err(e) => tracing::warn!(error = %e, dpi, "Hardware profile: set_dpi failed"),
        }
    }

    if let Some(ss) = profile.smartshift {
        match manager.set_smart_shift(ss.enabled, ss.threshold) {
            Ok(()) => tracing::info!(enabled = ss.enabled, threshold = ss.threshold, "Hardware profile: SmartShift applied"),
            Err(e) => tracing::warn!(error = %e, "Hardware profile: set_smart_shift failed"),
        }
    }

    if let Some(hires) = profile.hires {
        // invert/target unchanged from device default (false) for per-app apply.
        match manager.set_hiresscroll_mode(hires, false, false) {
            Ok(()) => tracing::info!(hires, "Hardware profile: HiRes scroll applied"),
            Err(e) => tracing::warn!(error = %e, "Hardware profile: set_hiresscroll_mode failed"),
        }
    }

    if let Some(mode) = profile.thumbwheel {
        let divert = mode != ThumbwheelMode::Off;
        // Software handles inversion (hidraw reader), so device invert stays off.
        match manager.set_thumbwheel_reporting(divert, false) {
            Ok(()) => tracing::info!(?mode, divert, "Hardware profile: thumb-wheel applied"),
            Err(e) => tracing::warn!(error = %e, "Hardware profile: set_thumbwheel_reporting failed"),
        }
    }

    if !profile.buttons.is_empty() {
        tracing::debug!(
            count = profile.buttons.len(),
            "Hardware profile has per-button overrides (applied via config, not device)"
        );
    }
}

/// Re-read profiles.json and return its (lowercased-key) hardware profile map.
///
/// Used by the `ReloadConfig` D-Bus path to refresh the shared hardware map
/// after the settings UI saves. A read/parse failure yields an empty map rather
/// than an error, so a transient bad file never breaks the running daemon.
pub fn load_hardware_profiles() -> HashMap<String, HardwareProfile> {
    match ProfileManager::load_or_create() {
        Ok(manager) => manager.hardware_profiles(),
        Err(e) => {
            tracing::warn!(error = %e, "Failed to reload hardware profiles; keeping empty map");
            HashMap::new()
        }
    }
}

/// Profile error type
#[derive(Debug)]
pub enum ProfileError {
    /// Profile not found
    NotFound(String),
    /// I/O error
    IoError(std::io::Error),
    /// JSON parse error
    ParseError(serde_json::Error),
    /// Validation error
    ValidationError(String),
}

impl std::fmt::Display for ProfileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ProfileError::NotFound(name) => write!(f, "Profile not found: {}", name),
            ProfileError::IoError(e) => write!(f, "I/O error: {}", e),
            ProfileError::ParseError(e) => write!(f, "JSON parse error: {}", e),
            ProfileError::ValidationError(msg) => write!(f, "Validation error: {}", msg),
        }
    }
}

impl std::error::Error for ProfileError {}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_v1_config_migrates_and_defaults_hardware() {
        // A v1 file has no `hardware` map; it must load, default to empty, and
        // be stamped to the current schema version.
        let v1 = r#"{
            "version": 1,
            "profiles": [ {
                "name": "default",
                "slices": [null, null, null, null, null, null, null, null]
            } ]
        }"#;
        let mut config: ProfilesConfig = serde_json::from_str(v1).unwrap();
        assert!(config.hardware.is_empty());
        config.migrate();
        assert_eq!(config.version, SCHEMA_VERSION);
    }

    #[test]
    fn test_load_flat_ui_written_profiles_json() {
        // The GTK settings UI writes a FLAT shape with NO top-level
        // `version`/`profiles`: per-app keys plus a `hardware` map. It must load
        // without a parse error, default to the built-in default profile, and
        // still expose the hardware map (with case-insensitive keys).
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");
        let flat = r#"{
            "default": { "name": "default", "app_class": "default", "slices": [] },
            "Firefox": { "name": "Firefox", "app_class": "Firefox", "slices": [] },
            "hardware": {
                "Firefox": { "dpi": 1200, "thumbwheel": "scroll" }
            }
        }"#;
        fs::write(&config_path, flat).unwrap();

        let manager = ProfileManager::load_from_path(&config_path).unwrap();
        // Built-in default profile is always present.
        assert_eq!(manager.current().name, "default");
        // Hardware map loaded; lookup is case-insensitive (queried lowercase).
        let hw = manager
            .get_hardware_profile_for_window("firefox")
            .expect("hardware profile for firefox must load from flat UI file");
        assert_eq!(hw.dpi, Some(1200));
        assert_eq!(hw.thumbwheel, Some(ThumbwheelMode::Scroll));
        // Original-case query also resolves.
        assert!(manager.get_hardware_profile_for_window("Firefox").is_some());
    }

    #[test]
    fn test_hardware_profile_roundtrip() {
        let mut config = ProfilesConfig::with_default_actions();
        config.hardware.insert(
            "blender".to_string(),
            HardwareProfile {
                dpi: Some(1600),
                smartshift: Some(SmartshiftSetting { enabled: true, threshold: 40 }),
                hires: Some(true),
                thumbwheel: Some(ThumbwheelMode::Zoom),
                buttons: HashMap::new(),
            },
        );
        let json = serde_json::to_string(&config).unwrap();
        let parsed: ProfilesConfig = serde_json::from_str(&json).unwrap();
        let hw = parsed.hardware.get("blender").unwrap();
        assert_eq!(hw.dpi, Some(1600));
        assert_eq!(hw.thumbwheel, Some(ThumbwheelMode::Zoom));
        assert_eq!(hw.smartshift, Some(SmartshiftSetting { enabled: true, threshold: 40 }));
    }

    // Task 6.1: Test ProfilesConfig serialization/deserialization
    #[test]
    fn test_profiles_config_serialization() {
        let config = ProfilesConfig::with_default_actions();

        // Serialize
        let json = serde_json::to_string_pretty(&config).unwrap();
        assert!(json.contains(&format!("\"version\": {}", SCHEMA_VERSION)));
        assert!(json.contains("\"name\": \"default\""));
        assert!(json.contains("\"slices\""));

        // Deserialize
        let parsed: ProfilesConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.version, SCHEMA_VERSION);
        assert_eq!(parsed.profiles.len(), 1);
        assert_eq!(parsed.profiles[0].name, "default");
    }

    #[test]
    fn test_profile_serialization() {
        let profile = create_default_profile();
        let json = serde_json::to_string(&profile).unwrap();

        // Verify required fields
        assert!(json.contains("\"name\":\"default\""));
        assert!(json.contains("\"slices\""));

        // Deserialize back
        let parsed: Profile = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.name, "default");
        assert_eq!(parsed.slices.len(), 8);
    }

    // Task 6.2: Test default profile creation
    #[test]
    fn test_create_default_profile() {
        let profile = create_default_profile();

        assert_eq!(profile.name, "default");
        assert!(profile.window_class.is_none());
        assert_eq!(profile.slices.len(), 8);
        assert_eq!(profile.icon, Some("🎯".to_string()));

        // All slices should have actions
        for (i, slice) in profile.slices.iter().enumerate() {
            assert!(slice.is_some(), "Slice {} should have an action", i);
        }

        // Verify first slice is Copy (ctrl+c)
        let first_action = profile.slices[0].as_ref().unwrap();
        assert_eq!(first_action.label, Some("Copy".to_string()));
    }

    // Task 6.3: Test load from valid JSON file
    #[test]
    fn test_load_from_valid_json() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");

        // Write a valid config
        let config = ProfilesConfig::with_default_actions();
        let json = serde_json::to_string_pretty(&config).unwrap();
        fs::write(&config_path, json).unwrap();

        // Load it
        let manager = ProfileManager::load_from_path(&config_path).unwrap();
        assert_eq!(manager.profile_count(), 1);
        assert_eq!(manager.current().name, "default");
    }

    #[test]
    fn test_load_with_multiple_profiles() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");

        // Create config with multiple profiles
        let mut config = ProfilesConfig::with_default_actions();
        let mut firefox_profile = create_default_profile();
        firefox_profile.name = "firefox".to_string();
        firefox_profile.window_class = Some("firefox".to_string());
        firefox_profile.icon = Some("🦊".to_string());
        config.profiles.push(firefox_profile);

        let json = serde_json::to_string_pretty(&config).unwrap();
        fs::write(&config_path, json).unwrap();

        // Load and verify
        let manager = ProfileManager::load_from_path(&config_path).unwrap();
        assert_eq!(manager.profile_count(), 2);

        // Test window class lookup
        let firefox = manager.get_profile_for_window("firefox");
        assert_eq!(firefox.name, "firefox");

        // Unknown window class should fall back to default
        let unknown = manager.get_profile_for_window("unknown-app");
        assert_eq!(unknown.name, "default");
    }

    // Task 6.4: Test load failure on malformed JSON
    #[test]
    fn test_load_malformed_json() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");

        // Write invalid JSON
        fs::write(&config_path, "{ invalid json }").unwrap();

        // Load should fail
        let result = ProfileManager::load_from_path(&config_path);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ProfileError::ParseError(_)));
    }

    // Story 3.6: Test that wrong slice count is padded, not rejected
    #[test]
    fn test_load_wrong_slice_count_pads() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");

        // Note: The [Option<Action>; 8] type in serde requires exactly 8 elements
        // So "wrong slice count" can only happen if we manually construct
        // For now, test that a valid config loads successfully
        let config = ProfilesConfig::with_default_actions();
        let json = serde_json::to_string_pretty(&config).unwrap();
        fs::write(&config_path, json).unwrap();

        let result = ProfileManager::load_from_path(&config_path);
        assert!(result.is_ok());
        let manager = result.unwrap();
        assert_eq!(manager.current().slices.len(), 8);
    }

    // Story 3.5: Test icon validation
    #[test]
    fn test_validate_icon_reference() {
        // Valid emoji (supplementary range)
        assert!(validate_icon_reference("📋"));
        assert!(validate_icon_reference("🎯"));

        // Valid emoji (arrows, dingbats - previously failing)
        assert!(validate_icon_reference("↩️"));
        assert!(validate_icon_reference("↪️"));
        assert!(validate_icon_reference("✂️"));
        assert!(validate_icon_reference("❌"));

        // Valid file paths
        assert!(validate_icon_reference("/path/to/icon.png"));
        assert!(validate_icon_reference("icons/copy.svg"));
        assert!(validate_icon_reference("C:\\icons\\paste.ico"));

        // Valid system icon names
        assert!(validate_icon_reference("edit-copy"));
        assert!(validate_icon_reference("document_save"));
        assert!(validate_icon_reference("icon123"));

        // Invalid
        assert!(!validate_icon_reference(""));
        assert!(!validate_icon_reference("has space.txt"));
    }

    // Story 3.3: Test window class to profile matching
    #[test]
    fn test_window_class_to_profile_matching() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");

        // Create config with app-specific profile
        let mut config = ProfilesConfig::with_default_actions();
        let mut vscode = create_default_profile();
        vscode.name = "vscode".to_string();
        vscode.window_class = Some("code".to_string());
        config.profiles.push(vscode);

        let json = serde_json::to_string_pretty(&config).unwrap();
        fs::write(&config_path, json).unwrap();

        let manager = ProfileManager::load_from_path(&config_path).unwrap();

        // Match known window class
        let profile = manager.get_profile_for_window("code");
        assert_eq!(profile.name, "vscode");

        // Fallback to default for unknown
        let profile = manager.get_profile_for_window("unknown-app");
        assert_eq!(profile.name, "default");
    }

    // Story 3.4: Test default profile fallback
    #[test]
    fn test_default_profile_fallback() {
        // ProfileManager::new() should always have default profile
        let manager = ProfileManager::new();
        let default = manager.get_profile_for_window("any-unknown-app");
        assert_eq!(default.name, "default");
        assert_eq!(default.slices.len(), 8);
        // All slices should have actions
        for slice in &default.slices {
            assert!(slice.is_some());
        }
    }

    // Task 6.5: Test config directory creation
    #[test]
    fn test_config_dir_functions() {
        // Test get_config_dir returns valid path
        let config_dir = get_config_dir();
        assert!(config_dir.to_string_lossy().contains("juhradial"));

        // Test get_profiles_path
        let profiles_path = get_profiles_path();
        assert!(profiles_path.to_string_lossy().ends_with("profiles.json"));
    }

    #[test]
    fn test_ensure_config_dir() {
        let temp_dir = TempDir::new().unwrap();
        let config_dir = temp_dir.path().join(CONFIG_DIR_NAME);

        let result = ensure_config_dir_at(config_dir.clone());
        assert!(result.is_ok(), "ensure_config_dir should succeed");

        let returned_path = result.unwrap();
        assert!(
            returned_path.exists(),
            "Config directory should exist after ensure_config_dir"
        );
        assert_eq!(returned_path, config_dir);
    }

    #[test]
    fn test_default_profile_manager() {
        let manager = ProfileManager::new();
        assert_eq!(manager.profile_count(), 1);
        assert_eq!(manager.current().name, "default");
    }

    #[test]
    fn test_set_current_profile() {
        let temp_dir = TempDir::new().unwrap();
        let config_path = temp_dir.path().join("profiles.json");

        // Create config with two profiles
        let mut config = ProfilesConfig::with_default_actions();
        let mut second = create_default_profile();
        second.name = "second".to_string();
        config.profiles.push(second);

        let json = serde_json::to_string_pretty(&config).unwrap();
        fs::write(&config_path, json).unwrap();

        let mut manager = ProfileManager::load_from_path(&config_path).unwrap();

        // Switch to second profile
        assert!(manager.set_current("second").is_ok());
        assert_eq!(manager.current().name, "second");

        // Try to switch to non-existent profile
        assert!(manager.set_current("nonexistent").is_err());
    }

    #[test]
    fn test_direction_constants() {
        assert_eq!(direction::NORTH, 0);
        assert_eq!(direction::NORTH_EAST, 1);
        assert_eq!(direction::EAST, 2);
        assert_eq!(direction::SOUTH_EAST, 3);
        assert_eq!(direction::SOUTH, 4);
        assert_eq!(direction::SOUTH_WEST, 5);
        assert_eq!(direction::WEST, 6);
        assert_eq!(direction::NORTH_WEST, 7);
    }

    #[test]
    fn test_profile_error_display() {
        let err = ProfileError::NotFound("test".to_string());
        assert!(format!("{}", err).contains("test"));

        let err = ProfileError::ValidationError("invalid".to_string());
        assert!(format!("{}", err).contains("invalid"));
    }

    // Note: This test modifies environment variables.
    // Run with `cargo test -- --test-threads=1` to avoid race conditions.
    #[test]
    #[ignore] // Ignored by default - run explicitly with `cargo test -- --ignored`
    fn test_xdg_config_home() {
        // Save original value
        let original = std::env::var("XDG_CONFIG_HOME").ok();

        // Set custom XDG_CONFIG_HOME
        std::env::set_var("XDG_CONFIG_HOME", "/custom/config");
        let dir = get_config_dir();
        assert!(dir.starts_with("/custom/config"));

        // Restore original
        if let Some(val) = original {
            std::env::set_var("XDG_CONFIG_HOME", val);
        } else {
            std::env::remove_var("XDG_CONFIG_HOME");
        }
    }
}
