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
}

fn default_menu_appear() -> String { "damp_state_change".to_string() }
fn default_slice_change() -> String { "subtle_collision".to_string() }
fn default_confirm() -> String { "sharp_state_change".to_string() }
fn default_invalid() -> String { "angry_alert".to_string() }

impl Default for HapticEventConfig {
    fn default() -> Self {
        Self {
            menu_appear: default_menu_appear(),
            slice_change: default_slice_change(),
            confirm: default_confirm(),
            invalid: default_invalid(),
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
}

fn default_true() -> bool { true }
fn default_pattern() -> String { "subtle_collision".to_string() }
fn default_debounce() -> u64 { 20 }
fn default_slice_debounce() -> u64 { 20 }
fn default_reentry_debounce() -> u64 { 50 }

impl Default for HapticConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            default_pattern: default_pattern(),
            per_event: HapticEventConfig::default(),
            debounce_ms: 20,
            slice_debounce_ms: 20,
            reentry_debounce_ms: 50,
        }
    }
}

impl HapticConfig {
    /// Validate all values
    pub fn validate(&mut self) {
        self.per_event.validate();
    }

    /// Check if haptics are effectively disabled
    pub fn is_disabled(&self) -> bool {
        !self.enabled
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
            let mut config = Self::default();
            config.config_path = Some(path.to_path_buf());
            return Ok(config);
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
        assert_eq!(config.haptics.intensity, 50);
        assert_eq!(config.theme, "catppuccin-mocha");
    }

    #[test]
    fn test_zero_intensity_disables() {
        let json = r#"{"haptics": {"intensity": 0}}"#;
        let config: Config = serde_json::from_str(json).unwrap();

        assert!(!config.haptics_enabled()); // Effectively disabled
        assert!(config.haptics.is_disabled());
    }

    #[test]
    fn test_legacy_getters() {
        let config = Config::default();
        assert_eq!(config.haptic_intensity(), 50);
        assert!(config.haptics_enabled());
    }

    #[test]
    fn test_config_serialization() {
        let config = Config::default();
        let json = serde_json::to_string_pretty(&config).unwrap();

        // Should contain expected fields
        assert!(json.contains("haptics"));
        assert!(json.contains("intensity"));
        assert!(json.contains("catppuccin-mocha"));
    }
}
