//! Bundled Themes Module (Story 4.2)
//!
//! Provides built-in themes that are compiled into the binary.
//! These themes are always available, regardless of filesystem state.

use crate::theme::Theme;

/// Catppuccin Mocha theme JSON (default)
const CATPPUCCIN_MOCHA_JSON: &str = include_str!("themes/catppuccin-mocha.json");

/// Vaporwave theme JSON (80s neon aesthetic)
const VAPORWAVE_JSON: &str = include_str!("themes/vaporwave.json");

/// Matrix Rain theme JSON (green monochrome)
const MATRIX_RAIN_JSON: &str = include_str!("themes/matrix-rain.json");

/// Name of the default bundled theme
pub const DEFAULT_THEME_NAME: &str = "catppuccin-mocha";

/// Information about a bundled theme
#[derive(Debug, Clone)]
pub struct BundledThemeInfo {
    /// Theme name (matches theme.json "name" field)
    pub name: &'static str,
    /// Display name (human readable)
    pub display_name: &'static str,
    /// Short description
    pub description: &'static str,
    /// Whether this is the default theme
    pub is_default: bool,
}

/// List of all bundled themes with metadata
pub const BUNDLED_THEME_INFO: &[BundledThemeInfo] = &[
    BundledThemeInfo {
        name: "catppuccin-mocha",
        display_name: "Catppuccin Mocha",
        description: "Warm pastel dark theme with lavender accent",
        is_default: true,
    },
    BundledThemeInfo {
        name: "vaporwave",
        display_name: "Vaporwave",
        description: "80s neon aesthetic with magenta and cyan",
        is_default: false,
    },
    BundledThemeInfo {
        name: "matrix-rain",
        display_name: "Matrix Rain",
        description: "Monochrome green hacker aesthetic",
        is_default: false,
    },
];

/// Get a bundled theme by name.
///
/// # Arguments
/// * `name` - The theme name (case-insensitive)
///
/// # Returns
/// * `Some(Theme)` if the theme exists and parses successfully
/// * `None` if the theme doesn't exist or fails to parse
///
/// # Example
/// ```ignore
/// let theme = get_bundled_theme("Catppuccin Mocha").unwrap();
/// assert_eq!(theme.name, "Catppuccin Mocha");
/// ```
pub fn get_bundled_theme(name: &str) -> Option<Theme> {
    let name_lower = name.to_lowercase();
    // Normalize separators: convert spaces and underscores to dashes
    let normalized = name_lower.replace(' ', "-").replace('_', "-");

    let json = match normalized.as_str() {
        "catppuccin-mocha" => Some(CATPPUCCIN_MOCHA_JSON),
        "vaporwave" => Some(VAPORWAVE_JSON),
        "matrix-rain" => Some(MATRIX_RAIN_JSON),
        _ => None,
    }?;

    Theme::from_json(json).ok()
}

/// Get the default bundled theme (Catppuccin Mocha).
///
/// This should never fail since the theme is compiled in and validated.
///
/// # Panics
/// Panics if the default theme fails to parse (this would be a bug).
pub fn get_default_theme() -> Theme {
    get_bundled_theme(DEFAULT_THEME_NAME)
        .expect("Default bundled theme must be valid")
}

/// List all bundled theme names.
///
/// # Returns
/// A vector of theme names that can be passed to `get_bundled_theme`.
pub fn list_bundled_themes() -> Vec<&'static str> {
    BUNDLED_THEME_INFO.iter().map(|info| info.name).collect()
}

/// Check if a theme name matches a bundled theme.
///
/// # Arguments
/// * `name` - The theme name to check (case-insensitive)
///
/// # Returns
/// `true` if the name matches a bundled theme
pub fn is_bundled_theme(name: &str) -> bool {
    get_bundled_theme(name).is_some()
}

/// Get bundled theme info by name.
///
/// # Arguments
/// * `name` - The theme name (case-insensitive)
///
/// # Returns
/// Theme info if found
pub fn get_bundled_theme_info(name: &str) -> Option<&'static BundledThemeInfo> {
    let name_lower = name.to_lowercase();
    BUNDLED_THEME_INFO.iter().find(|info| {
        info.name.to_lowercase() == name_lower
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_catppuccin_mocha_parses() {
        let theme = get_bundled_theme("catppuccin-mocha");
        assert!(theme.is_some(), "catppuccin-mocha should parse");

        let theme = theme.unwrap();
        assert_eq!(theme.name, "catppuccin-mocha");
        assert_eq!(theme.colors.base, "#1e1e2e");
        assert_eq!(theme.colors.accent, "#b4befe");
        assert_eq!(theme.glassmorphism.blur_radius, 24);
        assert!((theme.animation.glow_intensity - 1.0).abs() < 0.01);
    }

    #[test]
    fn test_vaporwave_parses() {
        let theme = get_bundled_theme("vaporwave");
        assert!(theme.is_some(), "vaporwave should parse");

        let theme = theme.unwrap();
        assert_eq!(theme.name, "vaporwave");
        assert_eq!(theme.colors.base, "#1a1a2e");
        assert_eq!(theme.colors.accent, "#ff6b9d");
        assert_eq!(theme.colors.accent_secondary, "#00f5d4"); // cyan
        assert!((theme.animation.glow_intensity - 1.5).abs() < 0.01);
    }

    #[test]
    fn test_matrix_rain_parses() {
        let theme = get_bundled_theme("matrix-rain");
        assert!(theme.is_some(), "matrix-rain should parse");

        let theme = theme.unwrap();
        assert_eq!(theme.name, "matrix-rain");
        assert_eq!(theme.colors.base, "#0d0d0d");
        assert_eq!(theme.colors.accent, "#00ff00");
        assert_eq!(theme.colors.text, "#00ff00");
        assert!((theme.animation.glow_intensity - 2.0).abs() < 0.01);
    }

    #[test]
    fn test_default_theme_is_catppuccin() {
        let theme = get_default_theme();
        assert_eq!(theme.name, "catppuccin-mocha");
    }

    #[test]
    fn test_case_insensitive_lookup() {
        // Dashed names
        assert!(get_bundled_theme("catppuccin-mocha").is_some());
        assert!(get_bundled_theme("CATPPUCCIN-MOCHA").is_some());
        assert!(get_bundled_theme("Catppuccin-Mocha").is_some());

        // Space names (aliases)
        assert!(get_bundled_theme("catppuccin mocha").is_some());
        assert!(get_bundled_theme("matrix rain").is_some());

        // Underscore names (aliases)
        assert!(get_bundled_theme("catppuccin_mocha").is_some());
        assert!(get_bundled_theme("matrix_rain").is_some());

        assert!(get_bundled_theme("VAPORWAVE").is_some());
    }

    #[test]
    fn test_invalid_theme_returns_none() {
        assert!(get_bundled_theme("nonexistent").is_none());
        assert!(get_bundled_theme("").is_none());
        assert!(get_bundled_theme("catppuccin latte").is_none());
    }

    #[test]
    fn test_list_bundled_themes() {
        let themes = list_bundled_themes();
        assert_eq!(themes.len(), 3);
        assert!(themes.contains(&"catppuccin-mocha"));
        assert!(themes.contains(&"vaporwave"));
        assert!(themes.contains(&"matrix-rain"));
    }

    #[test]
    fn test_is_bundled_theme() {
        assert!(is_bundled_theme("catppuccin-mocha"));
        assert!(is_bundled_theme("vaporwave"));
        assert!(is_bundled_theme("matrix-rain"));
        assert!(is_bundled_theme("catppuccin mocha")); // alias
        assert!(!is_bundled_theme("nonexistent"));
    }

    #[test]
    fn test_bundled_theme_info() {
        let info = get_bundled_theme_info("catppuccin-mocha");
        assert!(info.is_some());
        let info = info.unwrap();
        assert!(info.is_default);
        assert!(info.description.contains("pastel"));
        assert_eq!(info.display_name, "Catppuccin Mocha");

        let vaporwave_info = get_bundled_theme_info("vaporwave").unwrap();
        assert!(!vaporwave_info.is_default);
        assert!(vaporwave_info.description.contains("80s"));
    }

    #[test]
    fn test_catppuccin_mocha_ux_spec_values() {
        // Verify values match UX spec Section 4.3
        let theme = get_bundled_theme("catppuccin-mocha").unwrap();

        // Colors from UX spec
        assert_eq!(theme.colors.base, "#1e1e2e", "Base should match UX spec");
        assert_eq!(theme.colors.surface, "#313244", "Surface should match UX spec");
        assert_eq!(theme.colors.text, "#cdd6f4", "Text should match UX spec");
        assert_eq!(theme.colors.text_secondary, "#bac2de", "Text secondary should match");
        assert_eq!(theme.colors.accent, "#b4befe", "Accent (lavender) should match UX spec");
        assert_eq!(theme.colors.accent_secondary, "#89b4fa", "Accent secondary should match");
        assert_eq!(theme.colors.success, "#a6e3a1", "Success should match UX spec");
        assert_eq!(theme.colors.warning, "#fab387", "Warning should match UX spec");
        assert_eq!(theme.colors.error, "#f38ba8", "Error should match UX spec");
        assert_eq!(theme.colors.border, "#585b70", "Border should match");
        assert_eq!(theme.colors.shadow, "#11111b", "Shadow should match");

        // Glassmorphism from UX spec
        assert_eq!(theme.glassmorphism.blur_radius, 24, "Blur radius should be 24px");
        assert!((theme.glassmorphism.background_opacity - 0.75).abs() < 0.01, "Background opacity should be 75%");
        assert!((theme.glassmorphism.saturation - 1.8).abs() < 0.01, "Saturation should be 180%");
        assert!((theme.glassmorphism.border_opacity - 0.15).abs() < 0.01, "Border opacity should be 15%");
        assert!((theme.glassmorphism.noise_opacity - 0.04).abs() < 0.01, "Noise opacity should be 4%");

        // Animation from UX spec
        assert!((theme.animation.glow_intensity - 1.0).abs() < 0.01, "Glow intensity should be 1.0");
    }
}
