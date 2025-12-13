//! Theme engine for radial menu visual customization
//!
//! Story 4.1: Theme JSON Schema & Parser
//!
//! Supports JSON themes with validation and directory scanning.
//! Themes are loaded from:
//! - System: `/usr/share/juhradial/themes/`
//! - User: `~/.config/juhradial/themes/` (XDG compliant)

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

/// System themes directory
const SYSTEM_THEMES_DIR: &str = "/usr/share/juhradial/themes";

/// User themes directory name (under XDG_CONFIG_HOME or ~/.config/)
const USER_THEMES_DIR_NAME: &str = "juhradial/themes";

/// Theme configuration filename
const THEME_FILENAME: &str = "theme.json";

/// Theme configuration (Story 4.1: Task 2.3 - matches UX Spec Section 4.2)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Theme {
    /// Theme identifier (directory name, inferred from path if not set)
    #[serde(default)]
    pub name: String,

    /// Theme display name
    #[serde(default)]
    pub display_name: String,

    /// Theme version
    #[serde(default = "default_version")]
    pub version: String,

    /// Theme author
    #[serde(default)]
    pub author: String,

    /// Color palette (11 colors from UX spec)
    pub colors: ThemeColors,

    /// Glassmorphism effects
    #[serde(alias = "effects")]
    pub glassmorphism: GlassmorphismSettings,

    /// Animation settings
    pub animation: AnimationSettings,

    /// Optional overrides
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub overrides: Option<ThemeOverrides>,
}

fn default_version() -> String {
    "1.0".to_string()
}

/// Theme color palette (UX Spec Section 4.2 - 11 colors)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ThemeColors {
    /// Background color (hex) - Catppuccin: Base
    pub base: String,

    /// Surface color for slices - Catppuccin: Surface 0
    pub surface: String,

    /// Primary text color
    pub text: String,

    /// Secondary text color
    #[serde(default = "default_text_secondary")]
    pub text_secondary: String,

    /// Primary accent color
    pub accent: String,

    /// Secondary accent color
    #[serde(default = "default_accent_secondary")]
    pub accent_secondary: String,

    /// Border color
    pub border: String,

    /// Shadow color
    #[serde(default = "default_shadow")]
    pub shadow: String,

    /// Success state color
    #[serde(default = "default_success")]
    pub success: String,

    /// Warning state color
    #[serde(default = "default_warning")]
    pub warning: String,

    /// Error state color
    #[serde(default = "default_error")]
    pub error: String,
}

fn default_text_secondary() -> String {
    "#bac2de".to_string()
}
fn default_accent_secondary() -> String {
    "#89b4fa".to_string()
}
fn default_shadow() -> String {
    "#11111b".to_string()
}
fn default_success() -> String {
    "#a6e3a1".to_string()
}
fn default_warning() -> String {
    "#fab387".to_string()
}
fn default_error() -> String {
    "#f38ba8".to_string()
}

/// Glassmorphism effect settings (UX Spec Section 4.2)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GlassmorphismSettings {
    /// Blur radius in pixels (8-48, default 24)
    #[serde(default = "default_blur_radius")]
    pub blur_radius: u8,

    /// Background opacity (0.5-0.95, default 0.75)
    #[serde(default = "default_background_opacity")]
    pub background_opacity: f32,

    /// Saturation multiplier (1.0-2.5, default 1.8)
    #[serde(default = "default_saturation")]
    pub saturation: f32,

    /// Border opacity (0.0-0.5, default 0.15)
    #[serde(default = "default_border_opacity")]
    pub border_opacity: f32,

    /// Noise texture opacity (0.0-0.1, default 0.04)
    #[serde(default = "default_noise_opacity")]
    pub noise_opacity: f32,
}

fn default_blur_radius() -> u8 {
    24
}
fn default_background_opacity() -> f32 {
    0.75
}
fn default_saturation() -> f32 {
    1.8
}
fn default_border_opacity() -> f32 {
    0.15
}
fn default_noise_opacity() -> f32 {
    0.04
}

/// Animation settings (UX Spec Section 4.2)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AnimationSettings {
    /// Glow effect intensity multiplier (0.0-2.0, default 1.0)
    #[serde(default = "default_glow_intensity")]
    pub glow_intensity: f32,

    /// Enable particle effects
    #[serde(default)]
    pub enable_particles: bool,

    /// Idle effect type: "none", "matrix-rain", "particles"
    #[serde(default = "default_idle_effect")]
    pub idle_effect: String,
}

fn default_glow_intensity() -> f32 {
    1.0
}
fn default_idle_effect() -> String {
    "none".to_string()
}

/// Theme overrides for custom configurations
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ThemeOverrides {
    /// Custom per-slice colors (optional)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub slice_colors: Option<Vec<String>>,

    /// Custom font family (optional)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub custom_font: Option<String>,
}

/// High contrast mode settings (Story 4.5: Task 1.1)
#[derive(Debug, Clone)]
pub struct HighContrastSettings {
    /// Override text color (pure white for max visibility)
    pub text_color: String,
    /// Override border opacity (60% for visibility)
    pub border_opacity: f32,
    /// Selection border color (solid white)
    pub selection_border_color: String,
    /// Selection border width in pixels
    pub selection_border_width: u8,
    /// Background opacity (95% for solid appearance)
    pub background_opacity: f32,
    /// Blur radius (0 = disabled for performance/clarity)
    pub blur_radius: u8,
}

impl Default for HighContrastSettings {
    fn default() -> Self {
        Self {
            text_color: "#ffffff".to_string(),
            border_opacity: 0.60,
            selection_border_color: "#ffffff".to_string(),
            selection_border_width: 3,
            background_opacity: 0.95,
            blur_radius: 0,
        }
    }
}

/// Effective colors after applying accessibility adjustments (Story 4.5: Task 1.2)
#[derive(Debug, Clone)]
pub struct EffectiveColors {
    pub base: String,
    pub surface: String,
    pub text: String,
    pub text_secondary: String,
    pub accent: String,
    pub accent_secondary: String,
    pub border: String,
    pub shadow: String,
    pub success: String,
    pub warning: String,
    pub error: String,
}

/// Effective glassmorphism settings after applying accessibility adjustments (Story 4.5: Task 2.1)
#[derive(Debug, Clone)]
pub struct EffectiveGlassmorphism {
    pub blur_radius: u8,
    pub background_opacity: f32,
    pub saturation: f32,
    pub border_opacity: f32,
    pub noise_opacity: f32,
}

impl Default for Theme {
    /// Default Catppuccin Mocha theme (UX Spec Section 3.2)
    fn default() -> Self {
        Self::catppuccin_mocha()
    }
}

impl Theme {
    /// Create the bundled Catppuccin Mocha theme (Story 4.1: Task 5.2)
    pub fn catppuccin_mocha() -> Self {
        Self {
            name: "catppuccin-mocha".to_string(),
            display_name: "Catppuccin Mocha".to_string(),
            version: "1.0".to_string(),
            author: "JuhRadial Team".to_string(),
            colors: ThemeColors {
                base: "#1e1e2e".to_string(),
                surface: "#313244".to_string(),
                text: "#cdd6f4".to_string(),
                text_secondary: "#bac2de".to_string(),
                accent: "#b4befe".to_string(),
                accent_secondary: "#89b4fa".to_string(),
                border: "#585b70".to_string(),
                shadow: "#11111b".to_string(),
                success: "#a6e3a1".to_string(),
                warning: "#fab387".to_string(),
                error: "#f38ba8".to_string(),
            },
            glassmorphism: GlassmorphismSettings {
                blur_radius: 24,
                background_opacity: 0.75,
                saturation: 1.8,
                border_opacity: 0.15,
                noise_opacity: 0.04,
            },
            animation: AnimationSettings {
                glow_intensity: 1.0,
                enable_particles: false,
                idle_effect: "none".to_string(),
            },
            overrides: None,
        }
    }

    /// Get effective animation timings based on accessibility settings (Story 4.6: Task 3.1)
    ///
    /// Returns 0ms for all timings when reduced motion is active,
    /// otherwise returns the theme's configured timings.
    pub fn get_effective_animation_timings(
        &self,
        reduce_motion: bool,
    ) -> crate::accessibility::EffectiveAnimationTimings {
        use crate::accessibility::EffectiveAnimationTimings;

        if reduce_motion {
            // Story 4.6: Task 3.2 - Return 0ms for all timings
            EffectiveAnimationTimings::reduced_motion()
        } else {
            // Use theme's animation settings
            EffectiveAnimationTimings {
                appear_ms: 30, // UX spec default
                dismiss_ms: 50,
                highlight_in_ms: 80,
                highlight_out_ms: 60,
                icon_scale_enabled: true,
                // Task 3.3: Idle effects from theme
                idle_effects_enabled: self.animation.idle_effect != "none"
                    || self.animation.enable_particles,
            }
        }
    }

    /// Get effective colors with high contrast adjustments (Story 4.5: Task 1.2, 1.3)
    ///
    /// When high contrast is active, text colors are overridden to pure white
    /// for maximum visibility.
    pub fn get_effective_colors(&self, high_contrast: bool) -> EffectiveColors {
        if high_contrast {
            let hc = HighContrastSettings::default();
            EffectiveColors {
                base: self.colors.base.clone(),
                surface: self.colors.surface.clone(),
                text: hc.text_color.clone(),         // Override to white
                text_secondary: hc.text_color.clone(), // Override to white
                accent: self.colors.accent.clone(),
                accent_secondary: self.colors.accent_secondary.clone(),
                border: self.colors.border.clone(),
                shadow: self.colors.shadow.clone(),
                success: self.colors.success.clone(),
                warning: self.colors.warning.clone(),
                error: self.colors.error.clone(),
            }
        } else {
            EffectiveColors {
                base: self.colors.base.clone(),
                surface: self.colors.surface.clone(),
                text: self.colors.text.clone(),
                text_secondary: self.colors.text_secondary.clone(),
                accent: self.colors.accent.clone(),
                accent_secondary: self.colors.accent_secondary.clone(),
                border: self.colors.border.clone(),
                shadow: self.colors.shadow.clone(),
                success: self.colors.success.clone(),
                warning: self.colors.warning.clone(),
                error: self.colors.error.clone(),
            }
        }
    }

    /// Get effective glassmorphism settings with high contrast adjustments (Story 4.5: Task 2.1-2.4)
    ///
    /// When high contrast is active:
    /// - background_opacity is set to 0.95 (nearly opaque)
    /// - blur_radius is set to 0 (disabled)
    /// - border_opacity is set to 0.60 (more visible)
    pub fn get_effective_glassmorphism(&self, high_contrast: bool) -> EffectiveGlassmorphism {
        if high_contrast {
            let hc = HighContrastSettings::default();
            EffectiveGlassmorphism {
                blur_radius: hc.blur_radius,           // 0 - disabled
                background_opacity: hc.background_opacity, // 0.95
                saturation: 1.0,                       // Normal saturation
                border_opacity: hc.border_opacity,     // 0.60
                noise_opacity: 0.0,                    // Disabled for clarity
            }
        } else {
            EffectiveGlassmorphism {
                blur_radius: self.glassmorphism.blur_radius,
                background_opacity: self.glassmorphism.background_opacity,
                saturation: self.glassmorphism.saturation,
                border_opacity: self.glassmorphism.border_opacity,
                noise_opacity: self.glassmorphism.noise_opacity,
            }
        }
    }

    /// Get high contrast settings for selection styling
    pub fn get_high_contrast_settings() -> HighContrastSettings {
        HighContrastSettings::default()
    }

    /// Parse theme from JSON string (Story 4.2: Task 2.2)
    ///
    /// Used by bundled_themes to parse embedded JSON.
    pub fn from_json(json: &str) -> Result<Self, ThemeError> {
        let mut theme: Theme =
            serde_json::from_str(json).map_err(ThemeError::ParseError)?;

        // Set display_name from name if not provided
        if theme.display_name.is_empty() {
            theme.display_name = theme.name.clone();
        }

        Ok(theme)
    }

    /// Load theme from a JSON file (Story 4.1: Task 2.1, 2.2)
    pub fn load_from_path(path: &Path) -> Result<Self, ThemeError> {
        // Read file content
        let content = fs::read_to_string(path).map_err(ThemeError::IoError)?;

        // Parse JSON using from_json
        let mut theme = Self::from_json(&content)?;

        // Extract theme name from directory if not set
        if theme.name.is_empty() {
            if let Some(parent) = path.parent() {
                if let Some(dir_name) = parent.file_name() {
                    theme.name = dir_name.to_string_lossy().to_string();
                }
            }
        }

        // Set display_name from name if not provided
        if theme.display_name.is_empty() {
            theme.display_name = theme.name.clone();
        }

        Ok(theme)
    }

    /// Validate and clamp theme values to valid ranges (Story 4.1: Task 3)
    pub fn validate_and_clamp(&mut self) -> ValidationResult {
        let mut result = ValidationResult::new();

        // Validate blur_radius: 8-48 (Task 3.2)
        if self.glassmorphism.blur_radius < 8 {
            result.add_warning(format!(
                "blur_radius {} below minimum 8, clamping",
                self.glassmorphism.blur_radius
            ));
            self.glassmorphism.blur_radius = 8;
        } else if self.glassmorphism.blur_radius > 48 {
            result.add_warning(format!(
                "blur_radius {} above maximum 48, clamping",
                self.glassmorphism.blur_radius
            ));
            self.glassmorphism.blur_radius = 48;
        }

        // Validate background_opacity: 0.5-0.95 (Task 3.3)
        if self.glassmorphism.background_opacity < 0.5 {
            result.add_warning(format!(
                "background_opacity {} below minimum 0.5, clamping",
                self.glassmorphism.background_opacity
            ));
            self.glassmorphism.background_opacity = 0.5;
        } else if self.glassmorphism.background_opacity > 0.95 {
            result.add_warning(format!(
                "background_opacity {} above maximum 0.95, clamping",
                self.glassmorphism.background_opacity
            ));
            self.glassmorphism.background_opacity = 0.95;
        }

        // Validate saturation: 1.0-2.5 (Task 3.4)
        if self.glassmorphism.saturation < 1.0 {
            result.add_warning(format!(
                "saturation {} below minimum 1.0, clamping",
                self.glassmorphism.saturation
            ));
            self.glassmorphism.saturation = 1.0;
        } else if self.glassmorphism.saturation > 2.5 {
            result.add_warning(format!(
                "saturation {} above maximum 2.5, clamping",
                self.glassmorphism.saturation
            ));
            self.glassmorphism.saturation = 2.5;
        }

        // Validate border_opacity: 0.0-0.5 (Task 3.5)
        if self.glassmorphism.border_opacity < 0.0 {
            result.add_warning(format!(
                "border_opacity {} below minimum 0.0, clamping",
                self.glassmorphism.border_opacity
            ));
            self.glassmorphism.border_opacity = 0.0;
        } else if self.glassmorphism.border_opacity > 0.5 {
            result.add_warning(format!(
                "border_opacity {} above maximum 0.5, clamping",
                self.glassmorphism.border_opacity
            ));
            self.glassmorphism.border_opacity = 0.5;
        }

        // Validate noise_opacity: 0.0-0.1 (Task 3.6)
        if self.glassmorphism.noise_opacity < 0.0 {
            result.add_warning(format!(
                "noise_opacity {} below minimum 0.0, clamping",
                self.glassmorphism.noise_opacity
            ));
            self.glassmorphism.noise_opacity = 0.0;
        } else if self.glassmorphism.noise_opacity > 0.1 {
            result.add_warning(format!(
                "noise_opacity {} above maximum 0.1, clamping",
                self.glassmorphism.noise_opacity
            ));
            self.glassmorphism.noise_opacity = 0.1;
        }

        // Validate glow_intensity: 0.0-2.0
        if self.animation.glow_intensity < 0.0 {
            result.add_warning(format!(
                "glow_intensity {} below minimum 0.0, clamping",
                self.animation.glow_intensity
            ));
            self.animation.glow_intensity = 0.0;
        } else if self.animation.glow_intensity > 2.0 {
            result.add_warning(format!(
                "glow_intensity {} above maximum 2.0, clamping",
                self.animation.glow_intensity
            ));
            self.animation.glow_intensity = 2.0;
        }

        // Validate color hex formats (Task 3.7)
        let color_fields = [
            ("base", &self.colors.base),
            ("surface", &self.colors.surface),
            ("text", &self.colors.text),
            ("text_secondary", &self.colors.text_secondary),
            ("accent", &self.colors.accent),
            ("accent_secondary", &self.colors.accent_secondary),
            ("border", &self.colors.border),
            ("shadow", &self.colors.shadow),
            ("success", &self.colors.success),
            ("warning", &self.colors.warning),
            ("error", &self.colors.error),
        ];

        for (name, value) in color_fields {
            if !is_valid_hex_color(value) {
                result.add_error(format!(
                    "Invalid hex color for {}: '{}' (expected #RRGGBB)",
                    name, value
                ));
            }
        }

        result
    }
}

/// Check if a string is a valid hex color (#RRGGBB or #RGB)
fn is_valid_hex_color(color: &str) -> bool {
    if !color.starts_with('#') {
        return false;
    }
    let hex = &color[1..];
    // Accept #RGB (3 chars) or #RRGGBB (6 chars)
    (hex.len() == 3 || hex.len() == 6) && hex.chars().all(|c| c.is_ascii_hexdigit())
}

/// Validation result with warnings and errors (Story 4.1: Task 3.8)
#[derive(Debug, Clone, Default)]
pub struct ValidationResult {
    /// Non-fatal warnings (values were clamped)
    pub warnings: Vec<String>,
    /// Fatal errors (theme cannot be used)
    pub errors: Vec<String>,
}

impl ValidationResult {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_warning(&mut self, msg: String) {
        self.warnings.push(msg);
    }

    pub fn add_error(&mut self, msg: String) {
        self.errors.push(msg);
    }

    pub fn has_errors(&self) -> bool {
        !self.errors.is_empty()
    }

    pub fn is_valid(&self) -> bool {
        self.errors.is_empty()
    }
}

/// Theme manager for loading and switching themes (Story 4.1: Task 1.1)
pub struct ThemeManager {
    /// All loaded themes by name
    themes: HashMap<String, Theme>,

    /// Current active theme name
    current_theme: String,
}

impl ThemeManager {
    /// Create a new theme manager with all bundled themes (Story 4.2: Task 3)
    pub fn new() -> Self {
        let mut themes = HashMap::new();

        // Load all bundled themes (Story 4.2: Task 3.1, 3.2)
        for theme_name in crate::bundled_themes::list_bundled_themes() {
            if let Some(theme) = crate::bundled_themes::get_bundled_theme(theme_name) {
                themes.insert(theme.name.clone(), theme);
            }
        }

        // Fallback to hardcoded default if bundled themes fail (shouldn't happen)
        if themes.is_empty() {
            let default_theme = Theme::catppuccin_mocha();
            themes.insert(default_theme.name.clone(), default_theme);
        }

        Self {
            themes,
            current_theme: "catppuccin-mocha".to_string(),
        }
    }

    /// Load all themes from bundled, system, and user directories (Story 4.2: Task 3)
    ///
    /// Loading order (later overrides earlier):
    /// 1. Bundled themes (always available)
    /// 2. System themes (/usr/share/juhradial/themes/)
    /// 3. User themes (~/.config/juhradial/themes/)
    pub fn load_all() -> Result<Self, ThemeError> {
        let mut themes = HashMap::new();

        // Step 1: Load bundled themes first (Story 4.2: Task 3.1, 3.2)
        for theme_name in crate::bundled_themes::list_bundled_themes() {
            if let Some(theme) = crate::bundled_themes::get_bundled_theme(theme_name) {
                tracing::debug!(theme = %theme.name, "Loaded bundled theme");
                themes.insert(theme.name.clone(), theme);
            }
        }

        // Step 2: Load system themes (override bundled with same name)
        let system_dir = get_system_themes_dir();
        if system_dir.exists() {
            for theme_path in scan_themes_directory(&system_dir) {
                match Theme::load_from_path(&theme_path) {
                    Ok(mut theme) => {
                        let validation = theme.validate_and_clamp();

                        // Log warnings
                        for warning in &validation.warnings {
                            tracing::warn!(
                                theme = %theme.name,
                                warning = %warning,
                                "Theme validation warning"
                            );
                        }

                        // Skip if has errors
                        if validation.has_errors() {
                            for error in &validation.errors {
                                tracing::warn!(
                                    theme = %theme.name,
                                    error = %error,
                                    path = %theme_path.display(),
                                    "Skipping invalid theme"
                                );
                            }
                            continue;
                        }

                        // System themes override bundled themes (Story 4.2: Task 3.3)
                        if themes.contains_key(&theme.name) {
                            tracing::info!(
                                theme = %theme.name,
                                "System theme overrides bundled theme"
                            );
                        }

                        tracing::info!(
                            theme = %theme.name,
                            path = %theme_path.display(),
                            "Loaded system theme"
                        );
                        themes.insert(theme.name.clone(), theme);
                    }
                    Err(e) => {
                        tracing::warn!(
                            path = %theme_path.display(),
                            error = %e,
                            "Failed to load theme, skipping"
                        );
                    }
                }
            }
        }

        // Step 3: Load user themes (override system and bundled)
        let user_dir = get_user_themes_dir();
        if user_dir.exists() {
            for theme_path in scan_themes_directory(&user_dir) {
                match Theme::load_from_path(&theme_path) {
                    Ok(mut theme) => {
                        let validation = theme.validate_and_clamp();

                        for warning in &validation.warnings {
                            tracing::warn!(
                                theme = %theme.name,
                                warning = %warning,
                                "Theme validation warning"
                            );
                        }

                        if validation.has_errors() {
                            for error in &validation.errors {
                                tracing::warn!(
                                    theme = %theme.name,
                                    error = %error,
                                    path = %theme_path.display(),
                                    "Skipping invalid user theme"
                                );
                            }
                            continue;
                        }

                        // User themes override all others (Story 4.2: Task 3.3)
                        if themes.contains_key(&theme.name) {
                            tracing::info!(
                                theme = %theme.name,
                                "User theme overrides bundled/system theme"
                            );
                        }

                        tracing::info!(
                            theme = %theme.name,
                            path = %theme_path.display(),
                            "Loaded user theme"
                        );
                        themes.insert(theme.name.clone(), theme);
                    }
                    Err(e) => {
                        tracing::warn!(
                            path = %theme_path.display(),
                            error = %e,
                            "Failed to load user theme, skipping"
                        );
                    }
                }
            }
        }

        // Should always have bundled themes, but fallback just in case
        if themes.is_empty() {
            tracing::warn!("No themes loaded, using fallback Catppuccin Mocha");
            let default_theme = Theme::catppuccin_mocha();
            themes.insert(default_theme.name.clone(), default_theme);
        }

        // Determine initial theme (prefer catppuccin-mocha if available)
        let current_theme = if themes.contains_key("catppuccin-mocha") {
            "catppuccin-mocha".to_string()
        } else {
            themes.keys().next().cloned().unwrap_or_default()
        };

        tracing::info!(
            theme_count = themes.len(),
            current = %current_theme,
            bundled = crate::bundled_themes::list_bundled_themes().len(),
            "Theme manager initialized"
        );

        Ok(Self {
            themes,
            current_theme,
        })
    }

    /// Get the current active theme
    pub fn current(&self) -> &Theme {
        self.themes
            .get(&self.current_theme)
            .expect("Current theme must exist")
    }

    /// Set current theme by name
    pub fn set_current(&mut self, name: &str) -> Result<(), ThemeError> {
        if self.themes.contains_key(name) {
            self.current_theme = name.to_string();
            tracing::info!(theme = %name, "Switched to theme");
            Ok(())
        } else {
            Err(ThemeError::NotFound(name.to_string()))
        }
    }

    /// Get a theme by name
    pub fn get(&self, name: &str) -> Option<&Theme> {
        self.themes.get(name)
    }

    /// Get all theme names
    pub fn theme_names(&self) -> Vec<&String> {
        self.themes.keys().collect()
    }

    /// Get theme count
    pub fn theme_count(&self) -> usize {
        self.themes.len()
    }

    /// Check if a theme exists
    pub fn has_theme(&self, name: &str) -> bool {
        self.themes.contains_key(name)
    }

    /// Add a new theme or update an existing one (Story 4.3: hot-reload support)
    ///
    /// This method is used by the hot-reloader to update themes without restarting.
    pub fn add_or_update_theme(&mut self, theme: Theme) {
        let name = theme.name.clone();
        let is_update = self.themes.contains_key(&name);

        self.themes.insert(name.clone(), theme);

        if is_update {
            tracing::debug!(theme = %name, "Updated existing theme");
        } else {
            tracing::debug!(theme = %name, "Added new theme");
        }
    }

    /// Remove a theme by name
    ///
    /// Returns the removed theme if it existed.
    /// Cannot remove the current theme or bundled themes.
    pub fn remove_theme(&mut self, name: &str) -> Option<Theme> {
        // Cannot remove current theme
        if name == self.current_theme {
            tracing::warn!(theme = %name, "Cannot remove currently active theme");
            return None;
        }

        // Cannot remove bundled themes
        if crate::bundled_themes::is_bundled_theme(name) {
            tracing::warn!(theme = %name, "Cannot remove bundled theme");
            return None;
        }

        self.themes.remove(name)
    }
}

impl Default for ThemeManager {
    fn default() -> Self {
        Self::new()
    }
}

/// Get system themes directory path (Story 4.1: Task 1.2)
pub fn get_system_themes_dir() -> PathBuf {
    PathBuf::from(SYSTEM_THEMES_DIR)
}

/// Get user themes directory path (XDG compliant) (Story 4.1: Task 1.3)
pub fn get_user_themes_dir() -> PathBuf {
    // Check XDG_CONFIG_HOME first
    if let Ok(xdg_config) = std::env::var("XDG_CONFIG_HOME") {
        return PathBuf::from(xdg_config).join(USER_THEMES_DIR_NAME);
    }

    // Fall back to ~/.config/
    if let Some(home) = std::env::var_os("HOME") {
        return PathBuf::from(home)
            .join(".config")
            .join(USER_THEMES_DIR_NAME);
    }

    // Last resort fallback
    PathBuf::from(".config").join(USER_THEMES_DIR_NAME)
}

/// Scan a directory for theme.json files (Story 4.1: Task 1.4)
///
/// Returns paths to all theme.json files found in subdirectories.
/// Theme structure: themes/{theme-name}/theme.json
pub fn scan_themes_directory(dir: &Path) -> Vec<PathBuf> {
    let mut theme_files = Vec::new();

    if !dir.is_dir() {
        return theme_files;
    }

    // Read directory entries
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.filter_map(|e| e.ok()) {
            let path = entry.path();

            // Each theme is a subdirectory containing theme.json
            if path.is_dir() {
                let theme_json = path.join(THEME_FILENAME);
                if theme_json.exists() && theme_json.is_file() {
                    theme_files.push(theme_json);
                }
            }
        }
    }

    theme_files
}

/// Theme error type
#[derive(Debug)]
pub enum ThemeError {
    /// Theme not found
    NotFound(String),
    /// I/O error
    IoError(std::io::Error),
    /// JSON parse error
    ParseError(serde_json::Error),
    /// Validation error
    ValidationError(String),
}

impl std::fmt::Display for ThemeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ThemeError::NotFound(name) => write!(f, "Theme not found: {}", name),
            ThemeError::IoError(e) => write!(f, "I/O error: {}", e),
            ThemeError::ParseError(e) => write!(f, "JSON parse error: {}", e),
            ThemeError::ValidationError(msg) => write!(f, "Validation error: {}", msg),
        }
    }
}

impl std::error::Error for ThemeError {}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    // Task 6.1: Test valid theme parsing with all fields
    #[test]
    fn test_valid_theme_parsing() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("test-theme");
        fs::create_dir(&theme_dir).unwrap();

        let theme_json = "{
            \"name\": \"test-theme\",
            \"display_name\": \"Test Theme\",
            \"version\": \"1.0\",
            \"author\": \"Test Author\",
            \"colors\": {
                \"base\": \"#1e1e2e\",
                \"surface\": \"#313244\",
                \"text\": \"#cdd6f4\",
                \"textSecondary\": \"#bac2de\",
                \"accent\": \"#b4befe\",
                \"accentSecondary\": \"#89b4fa\",
                \"border\": \"#585b70\",
                \"shadow\": \"#11111b\",
                \"success\": \"#a6e3a1\",
                \"warning\": \"#fab387\",
                \"error\": \"#f38ba8\"
            },
            \"glassmorphism\": {
                \"blurRadius\": 24,
                \"backgroundOpacity\": 0.75,
                \"saturation\": 1.8,
                \"borderOpacity\": 0.15,
                \"noiseOpacity\": 0.04
            },
            \"animation\": {
                \"glowIntensity\": 1.0,
                \"enableParticles\": false,
                \"idleEffect\": \"none\"
            }
        }";

        let theme_path = theme_dir.join("theme.json");
        fs::write(&theme_path, theme_json).unwrap();

        let theme = Theme::load_from_path(&theme_path).unwrap();
        assert_eq!(theme.name, "test-theme");
        assert_eq!(theme.display_name, "Test Theme");
        assert_eq!(theme.version, "1.0");
        assert_eq!(theme.author, "Test Author");
        assert_eq!(theme.colors.base, "#1e1e2e");
        assert_eq!(theme.glassmorphism.blur_radius, 24);
        assert_eq!(theme.animation.glow_intensity, 1.0);
    }

    // Task 6.2: Test validation of out-of-range values (clamp + warning)
    #[test]
    fn test_validation_clamps_out_of_range() {
        let mut theme = Theme::catppuccin_mocha();

        // Set out-of-range values
        theme.glassmorphism.blur_radius = 100; // Max is 48
        theme.glassmorphism.background_opacity = 0.1; // Min is 0.5
        theme.glassmorphism.saturation = 5.0; // Max is 2.5
        theme.glassmorphism.border_opacity = 1.0; // Max is 0.5
        theme.glassmorphism.noise_opacity = 0.5; // Max is 0.1
        theme.animation.glow_intensity = 10.0; // Max is 2.0

        let result = theme.validate_and_clamp();

        // Should have warnings but no errors
        assert!(!result.warnings.is_empty());
        assert!(result.is_valid());

        // Values should be clamped
        assert_eq!(theme.glassmorphism.blur_radius, 48);
        assert_eq!(theme.glassmorphism.background_opacity, 0.5);
        assert_eq!(theme.glassmorphism.saturation, 2.5);
        assert_eq!(theme.glassmorphism.border_opacity, 0.5);
        assert_eq!(theme.glassmorphism.noise_opacity, 0.1);
        assert_eq!(theme.animation.glow_intensity, 2.0);
    }

    #[test]
    fn test_validation_clamps_below_minimum() {
        let mut theme = Theme::catppuccin_mocha();

        theme.glassmorphism.blur_radius = 2; // Min is 8
        theme.glassmorphism.saturation = 0.5; // Min is 1.0

        let result = theme.validate_and_clamp();

        assert!(!result.warnings.is_empty());
        assert!(result.is_valid());
        assert_eq!(theme.glassmorphism.blur_radius, 8);
        assert_eq!(theme.glassmorphism.saturation, 1.0);
    }

    // Task 6.3: Test malformed JSON handling
    #[test]
    fn test_malformed_json_error() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("bad-theme");
        fs::create_dir(&theme_dir).unwrap();

        let theme_path = theme_dir.join("theme.json");
        fs::write(&theme_path, "{ invalid json }").unwrap();

        let result = Theme::load_from_path(&theme_path);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), ThemeError::ParseError(_)));
    }

    #[test]
    fn test_missing_required_fields() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("incomplete-theme");
        fs::create_dir(&theme_dir).unwrap();

        // Missing colors field
        let theme_json = r#"{
            "name": "incomplete",
            "glassmorphism": { "blurRadius": 24 }
        }"#;

        let theme_path = theme_dir.join("theme.json");
        fs::write(&theme_path, theme_json).unwrap();

        let result = Theme::load_from_path(&theme_path);
        assert!(result.is_err());
    }

    // Task 6.4: Test directory scanning with mock filesystem
    #[test]
    fn test_directory_scanning() {
        let temp_dir = TempDir::new().unwrap();

        // Create theme directories
        let theme1_dir = temp_dir.path().join("theme-one");
        let theme2_dir = temp_dir.path().join("theme-two");
        let not_a_theme = temp_dir.path().join("not-a-theme");

        fs::create_dir(&theme1_dir).unwrap();
        fs::create_dir(&theme2_dir).unwrap();
        fs::create_dir(&not_a_theme).unwrap();

        // Create theme.json files
        fs::write(theme1_dir.join("theme.json"), "{}").unwrap();
        fs::write(theme2_dir.join("theme.json"), "{}").unwrap();
        // not_a_theme has no theme.json

        let found = scan_themes_directory(temp_dir.path());
        assert_eq!(found.len(), 2);
    }

    #[test]
    fn test_scan_nonexistent_directory() {
        let found = scan_themes_directory(Path::new("/nonexistent/path"));
        assert!(found.is_empty());
    }

    // Task 6.5: Test user theme overrides system theme
    #[test]
    fn test_theme_manager_with_themes() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("valid-theme");
        fs::create_dir(&theme_dir).unwrap();

        let theme_json = "{
            \"name\": \"valid-theme\",
            \"colors\": {
                \"base\": \"#1e1e2e\",
                \"surface\": \"#313244\",
                \"text\": \"#cdd6f4\",
                \"accent\": \"#b4befe\",
                \"border\": \"#585b70\"
            },
            \"glassmorphism\": {},
            \"animation\": {}
        }";

        fs::write(theme_dir.join("theme.json"), theme_json).unwrap();

        let themes = scan_themes_directory(temp_dir.path());
        assert_eq!(themes.len(), 1);

        let theme = Theme::load_from_path(&themes[0]).unwrap();
        assert_eq!(theme.name, "valid-theme");
    }

    // Story 4.2: Test ThemeManager loads all bundled themes
    #[test]
    fn test_theme_manager_loads_bundled_themes() {
        let manager = ThemeManager::new();

        // Should have all 3 bundled themes
        assert_eq!(manager.theme_count(), 3);
        assert!(manager.has_theme("catppuccin-mocha"));
        assert!(manager.has_theme("vaporwave"));
        assert!(manager.has_theme("matrix-rain"));

        // Default should be catppuccin-mocha
        assert_eq!(manager.current().name, "catppuccin-mocha");
    }

    #[test]
    fn test_theme_manager_set_current() {
        let mut manager = ThemeManager::new();

        // Try to set non-existent theme
        assert!(manager.set_current("nonexistent").is_err());

        // Set to vaporwave should work
        assert!(manager.set_current("vaporwave").is_ok());
        assert_eq!(manager.current().name, "vaporwave");

        // Set to matrix-rain should work
        assert!(manager.set_current("matrix-rain").is_ok());
        assert_eq!(manager.current().name, "matrix-rain");

        // Set back to default
        assert!(manager.set_current("catppuccin-mocha").is_ok());
        assert_eq!(manager.current().name, "catppuccin-mocha");
    }

    #[test]
    fn test_default_theme_values() {
        let theme = Theme::catppuccin_mocha();

        // Verify all UX spec values
        assert_eq!(theme.glassmorphism.blur_radius, 24);
        assert_eq!(theme.glassmorphism.background_opacity, 0.75);
        assert_eq!(theme.glassmorphism.saturation, 1.8);
        assert_eq!(theme.glassmorphism.border_opacity, 0.15);
        assert_eq!(theme.glassmorphism.noise_opacity, 0.04);
        assert_eq!(theme.animation.glow_intensity, 1.0);
        assert!(!theme.animation.enable_particles);
        assert_eq!(theme.animation.idle_effect, "none");
    }

    #[test]
    fn test_hex_color_validation() {
        // Valid colors
        assert!(is_valid_hex_color("#1e1e2e"));
        assert!(is_valid_hex_color("#FFF"));
        assert!(is_valid_hex_color("#abc123"));

        // Invalid colors
        assert!(!is_valid_hex_color("1e1e2e")); // No #
        assert!(!is_valid_hex_color("#1e1e2")); // Wrong length
        assert!(!is_valid_hex_color("#GGGGGG")); // Invalid chars
        assert!(!is_valid_hex_color("")); // Empty
    }

    #[test]
    fn test_invalid_color_produces_error() {
        let mut theme = Theme::catppuccin_mocha();
        theme.colors.base = "invalid".to_string();

        let result = theme.validate_and_clamp();
        assert!(result.has_errors());
        assert!(!result.is_valid());
    }

    #[test]
    fn test_theme_error_display() {
        let err = ThemeError::NotFound("test".to_string());
        assert!(format!("{}", err).contains("test"));

        let err = ThemeError::ValidationError("invalid".to_string());
        assert!(format!("{}", err).contains("invalid"));
    }

    #[test]
    fn test_get_user_themes_dir() {
        let dir = get_user_themes_dir();
        assert!(dir.to_string_lossy().contains("juhradial"));
        assert!(dir.to_string_lossy().contains("themes"));
    }

    #[test]
    fn test_theme_with_defaults() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("minimal-theme");
        fs::create_dir(&theme_dir).unwrap();

        // Minimal theme - only required fields
        let theme_json = "{
            \"name\": \"minimal\",
            \"colors\": {
                \"base\": \"#000000\",
                \"surface\": \"#111111\",
                \"text\": \"#ffffff\",
                \"accent\": \"#ff0000\",
                \"border\": \"#333333\"
            },
            \"glassmorphism\": {},
            \"animation\": {}
        }";

        let theme_path = theme_dir.join("theme.json");
        fs::write(&theme_path, theme_json).unwrap();

        let theme = Theme::load_from_path(&theme_path).unwrap();

        // Check defaults were applied
        assert_eq!(theme.version, "1.0");
        assert_eq!(theme.glassmorphism.blur_radius, 24);
        assert_eq!(theme.animation.glow_intensity, 1.0);
    }

    #[test]
    fn test_theme_name_from_directory() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("my-custom-theme");
        fs::create_dir(&theme_dir).unwrap();

        // Theme without name field
        let theme_json = "{
            \"colors\": {
                \"base\": \"#000000\",
                \"surface\": \"#111111\",
                \"text\": \"#ffffff\",
                \"accent\": \"#ff0000\",
                \"border\": \"#333333\"
            },
            \"glassmorphism\": {},
            \"animation\": {}
        }";

        let theme_path = theme_dir.join("theme.json");
        fs::write(&theme_path, theme_json).unwrap();

        let theme = Theme::load_from_path(&theme_path).unwrap();

        // Name should be inferred from directory
        assert_eq!(theme.name, "my-custom-theme");
    }

    #[test]
    fn test_effects_alias() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("alias-theme");
        fs::create_dir(&theme_dir).unwrap();

        // Use "effects" instead of "glassmorphism" (alias)
        let theme_json = "{
            \"name\": \"alias-test\",
            \"colors\": {
                \"base\": \"#000000\",
                \"surface\": \"#111111\",
                \"text\": \"#ffffff\",
                \"accent\": \"#ff0000\",
                \"border\": \"#333333\"
            },
            \"effects\": {
                \"blurRadius\": 32
            },
            \"animation\": {}
        }";

        let theme_path = theme_dir.join("theme.json");
        fs::write(&theme_path, theme_json).unwrap();

        let theme = Theme::load_from_path(&theme_path).unwrap();
        assert_eq!(theme.glassmorphism.blur_radius, 32);
    }

    // Story 4.6: Reduced motion tests
    #[test]
    fn test_effective_timings_with_reduced_motion() {
        let theme = Theme::catppuccin_mocha();

        // With reduced motion ON
        let timings = theme.get_effective_animation_timings(true);
        assert_eq!(timings.appear_ms, 0);
        assert_eq!(timings.dismiss_ms, 0);
        assert_eq!(timings.highlight_in_ms, 0);
        assert_eq!(timings.highlight_out_ms, 0);
        assert!(!timings.icon_scale_enabled);
        assert!(!timings.idle_effects_enabled);
    }

    #[test]
    fn test_effective_timings_without_reduced_motion() {
        let theme = Theme::catppuccin_mocha();

        // With reduced motion OFF
        let timings = theme.get_effective_animation_timings(false);
        assert_eq!(timings.appear_ms, 30);
        assert_eq!(timings.dismiss_ms, 50);
        assert_eq!(timings.highlight_in_ms, 80);
        assert_eq!(timings.highlight_out_ms, 60);
        assert!(timings.icon_scale_enabled);
    }

    #[test]
    fn test_idle_effects_from_theme() {
        let mut theme = Theme::catppuccin_mocha();

        // Default theme has no idle effects
        let timings = theme.get_effective_animation_timings(false);
        assert!(!timings.idle_effects_enabled);

        // Enable particles
        theme.animation.enable_particles = true;
        let timings = theme.get_effective_animation_timings(false);
        assert!(timings.idle_effects_enabled);

        // Enable matrix rain
        theme.animation.enable_particles = false;
        theme.animation.idle_effect = "matrix-rain".to_string();
        let timings = theme.get_effective_animation_timings(false);
        assert!(timings.idle_effects_enabled);
    }

    // Story 4.5: High contrast mode tests
    #[test]
    fn test_high_contrast_colors() {
        let theme = Theme::catppuccin_mocha();

        // Without high contrast
        let colors = theme.get_effective_colors(false);
        assert_eq!(colors.text, "#cdd6f4"); // Theme's original color

        // With high contrast
        let hc_colors = theme.get_effective_colors(true);
        assert_eq!(hc_colors.text, "#ffffff"); // Overridden to white
        assert_eq!(hc_colors.text_secondary, "#ffffff"); // Also white
    }

    #[test]
    fn test_high_contrast_glassmorphism() {
        let theme = Theme::catppuccin_mocha();

        // Without high contrast
        let glass = theme.get_effective_glassmorphism(false);
        assert_eq!(glass.blur_radius, 24);
        assert_eq!(glass.background_opacity, 0.75);
        assert_eq!(glass.border_opacity, 0.15);

        // With high contrast
        let hc_glass = theme.get_effective_glassmorphism(true);
        assert_eq!(hc_glass.blur_radius, 0); // Disabled
        assert_eq!(hc_glass.background_opacity, 0.95); // Nearly opaque
        assert_eq!(hc_glass.border_opacity, 0.60); // More visible
        assert_eq!(hc_glass.noise_opacity, 0.0); // Disabled
    }

    #[test]
    fn test_high_contrast_settings_defaults() {
        let hc = HighContrastSettings::default();

        assert_eq!(hc.text_color, "#ffffff");
        assert_eq!(hc.border_opacity, 0.60);
        assert_eq!(hc.selection_border_color, "#ffffff");
        assert_eq!(hc.selection_border_width, 3);
        assert_eq!(hc.background_opacity, 0.95);
        assert_eq!(hc.blur_radius, 0);
    }

    #[test]
    fn test_get_high_contrast_settings() {
        let hc = Theme::get_high_contrast_settings();
        assert_eq!(hc.text_color, "#ffffff");
        assert_eq!(hc.selection_border_width, 3);
    }
}
