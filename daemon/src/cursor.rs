//! Cursor position query module
//!
//! Provides cross-protocol cursor position retrieval for Wayland and X11.
//! Uses KWin D-Bus API for Wayland, XQueryPointer for X11 fallback.

use std::process::Command;

/// Menu diameter in pixels (used for edge clamping)
pub const MENU_DIAMETER: i32 = 280;

/// Minimum margin from screen edges in pixels
pub const EDGE_MARGIN: i32 = 20;

/// Menu radius (half of diameter)
pub const MENU_RADIUS: i32 = MENU_DIAMETER / 2;

/// Screen dimensions for edge clamping
#[derive(Debug, Clone, Copy)]
pub struct ScreenBounds {
    pub width: i32,
    pub height: i32,
}

impl Default for ScreenBounds {
    fn default() -> Self {
        // Default to common resolution, will be queried at runtime
        Self {
            width: 1920,
            height: 1080,
        }
    }
}

/// Cursor position with coordinates
#[derive(Debug, Clone, Copy, Default)]
pub struct CursorPosition {
    pub x: i32,
    pub y: i32,
}

impl CursorPosition {
    /// Create a new cursor position
    pub fn new(x: i32, y: i32) -> Self {
        Self { x, y }
    }

    /// Apply edge clamping to ensure menu fits on screen
    ///
    /// Adjusts coordinates to maintain minimum margin from screen edges
    /// while keeping the full menu visible.
    ///
    /// # Arguments
    /// * `bounds` - Screen dimensions to clamp within
    ///
    /// # Returns
    /// New CursorPosition with clamped coordinates
    pub fn clamp_to_screen(&self, bounds: &ScreenBounds) -> Self {
        let min_x = EDGE_MARGIN + MENU_RADIUS;
        let max_x = bounds.width - EDGE_MARGIN - MENU_RADIUS;
        let min_y = EDGE_MARGIN + MENU_RADIUS;
        let max_y = bounds.height - EDGE_MARGIN - MENU_RADIUS;

        Self {
            x: self.x.clamp(min_x, max_x),
            y: self.y.clamp(min_y, max_y),
        }
    }
}

/// Get current cursor position
///
/// Attempts to query cursor position using available methods:
/// 1. KWin scripting (Wayland) - most accurate for Plasma 6 Wayland multi-monitor
/// 2. KWin D-Bus API (older Plasma versions)
/// 3. xdotool fallback (X11)
/// 4. Returns (0, 0) if all methods fail
pub fn get_cursor_position() -> CursorPosition {
    // Try KWin scripting first (works correctly on Plasma 6 Wayland multi-monitor)
    if let Some(pos) = get_cursor_via_kwin_script() {
        return pos;
    }

    // Try KWin D-Bus property (older Plasma versions)
    if let Some(pos) = get_cursor_via_kwin_dbus() {
        return pos;
    }

    // Try xdotool (works on X11)
    if let Some(pos) = get_cursor_via_xdotool() {
        return pos;
    }

    // Fallback: return placeholder
    tracing::warn!("Could not query cursor position, using default (0, 0)");
    CursorPosition::default()
}

/// Query cursor position via KWin scripting (for Plasma 6 Wayland)
///
/// This method uses KWin's JavaScript scripting API to get the true cursor position,
/// which works correctly across multiple monitors on Wayland.
/// The script calls back to our daemon via D-Bus with the position.
fn get_cursor_via_kwin_script() -> Option<CursorPosition> {
    use std::fs;

    let script_path = "/tmp/juhradial_cursor.js";

    // Create KWin script that calls our D-Bus method with cursor position
    let script = r#"
var pos = workspace.cursorPos;
callDBus("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
         "org.kde.juhradialmx.Daemon", "ReportCursorPosition",
         pos.x, pos.y);
"#;

    // Write script to temp file
    if fs::write(script_path, script).is_err() {
        return None;
    }

    // Load script via D-Bus
    let load_output = Command::new("dbus-send")
        .args([
            "--session",
            "--print-reply",
            "--dest=org.kde.KWin",
            "/Scripting",
            "org.kde.kwin.Scripting.loadScript",
            &format!("string:{}", script_path),
        ])
        .output()
        .ok()?;

    if !load_output.status.success() {
        return None;
    }

    // Parse script ID from output
    let stdout = String::from_utf8_lossy(&load_output.stdout);
    let script_id: i32 = stdout
        .lines()
        .find(|line| line.contains("int32"))
        .and_then(|line| line.split_whitespace().last())
        .and_then(|s| s.parse().ok())?;

    // Run the script
    let _ = Command::new("dbus-send")
        .args([
            "--session",
            "--print-reply",
            "--dest=org.kde.KWin",
            &format!("/Scripting/Script{}", script_id),
            "org.kde.kwin.Script.run",
        ])
        .output();

    // The script will call ReportCursorPosition which is handled by the daemon
    // For now, we can't easily get the result synchronously, so fall back to other methods
    None
}

/// Query cursor position via KWin D-Bus API (for Wayland)
fn get_cursor_via_kwin_dbus() -> Option<CursorPosition> {
    // Try various qdbus command names for different distros
    for cmd in &["qdbus-qt6", "qdbus6", "qdbus"] {
        // Try the cursorPos property (may not exist in all KWin versions)
        let output = Command::new(cmd)
            .args(["org.kde.KWin", "/KWin", "org.kde.KWin.cursorPos"])
            .output();

        if let Ok(output) = output {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                // Output format: "x, y" (e.g., "960, 540")
                let parts: Vec<&str> = stdout.trim().split(',').collect();
                if parts.len() >= 2 {
                    let x: i32 = parts[0].trim().parse().ok()?;
                    let y: i32 = parts[1].trim().parse().ok()?;
                    tracing::debug!(x, y, "Got cursor position via KWin D-Bus");
                    return Some(CursorPosition::new(x, y));
                }
            }
        }
    }

    // KWin cursorPos is not available in Plasma 6
    // Fall through to other methods
    None
}

/// Query cursor position via xdotool
fn get_cursor_via_xdotool() -> Option<CursorPosition> {
    let output = Command::new("xdotool")
        .args(["getmouselocation", "--shell"])
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut x: Option<i32> = None;
    let mut y: Option<i32> = None;

    for line in stdout.lines() {
        if let Some(val) = line.strip_prefix("X=") {
            x = val.parse().ok();
        } else if let Some(val) = line.strip_prefix("Y=") {
            y = val.parse().ok();
        }
    }

    match (x, y) {
        (Some(x), Some(y)) => Some(CursorPosition::new(x, y)),
        _ => None,
    }
}

/// Get screen bounds
///
/// Queries total screen dimensions across all monitors for edge clamping.
pub fn get_screen_bounds() -> ScreenBounds {
    // Try xrandr first (supports multi-monitor)
    if let Some(bounds) = get_screen_via_xrandr() {
        return bounds;
    }

    // Fallback to xdotool (single monitor)
    if let Some(bounds) = get_screen_via_xdotool() {
        return bounds;
    }

    // Fallback to default
    tracing::warn!("Could not query screen bounds, using default 1920x1080");
    ScreenBounds::default()
}

/// Query screen bounds via xrandr (for multi-monitor support)
fn get_screen_via_xrandr() -> Option<ScreenBounds> {
    let output = Command::new("xrandr")
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    // Look for "current WxH" in the first line
    // Example: "Screen 0: minimum 16 x 16, current 4480 x 1440, maximum 32767 x 32767"
    for line in stdout.lines() {
        if line.starts_with("Screen") && line.contains("current") {
            // Parse "current 4480 x 1440"
            if let Some(current_pos) = line.find("current") {
                let after_current = &line[current_pos + 8..];
                let parts: Vec<&str> = after_current.split(',').next()?.split_whitespace().collect();
                if parts.len() >= 3 && parts[1] == "x" {
                    let width = parts[0].parse().ok()?;
                    let height = parts[2].parse().ok()?;
                    tracing::debug!(width, height, "Got screen bounds via xrandr");
                    return Some(ScreenBounds { width, height });
                }
            }
        }
    }

    None
}

/// Query screen bounds via xdotool (fallback, single monitor only)
fn get_screen_via_xdotool() -> Option<ScreenBounds> {
    let output = Command::new("xdotool")
        .args(["getdisplaygeometry"])
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let parts: Vec<&str> = stdout.trim().split_whitespace().collect();

    if parts.len() >= 2 {
        let width = parts[0].parse().ok()?;
        let height = parts[1].parse().ok()?;
        return Some(ScreenBounds { width, height });
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cursor_position_new() {
        let pos = CursorPosition::new(100, 200);
        assert_eq!(pos.x, 100);
        assert_eq!(pos.y, 200);
    }

    #[test]
    fn test_edge_clamping_center() {
        // Cursor in center of screen should not be clamped
        let bounds = ScreenBounds { width: 1920, height: 1080 };
        let pos = CursorPosition::new(960, 540);
        let clamped = pos.clamp_to_screen(&bounds);

        assert_eq!(clamped.x, 960);
        assert_eq!(clamped.y, 540);
    }

    #[test]
    fn test_edge_clamping_top_left() {
        // Cursor at (0, 0) should be clamped to minimum valid position
        let bounds = ScreenBounds { width: 1920, height: 1080 };
        let pos = CursorPosition::new(0, 0);
        let clamped = pos.clamp_to_screen(&bounds);

        // min_x = EDGE_MARGIN + MENU_RADIUS = 20 + 140 = 160
        assert_eq!(clamped.x, EDGE_MARGIN + MENU_RADIUS);
        assert_eq!(clamped.y, EDGE_MARGIN + MENU_RADIUS);
    }

    #[test]
    fn test_edge_clamping_bottom_right() {
        // Cursor at bottom-right corner should be clamped
        let bounds = ScreenBounds { width: 1920, height: 1080 };
        let pos = CursorPosition::new(1920, 1080);
        let clamped = pos.clamp_to_screen(&bounds);

        // max_x = width - EDGE_MARGIN - MENU_RADIUS = 1920 - 20 - 140 = 1760
        // max_y = height - EDGE_MARGIN - MENU_RADIUS = 1080 - 20 - 140 = 920
        assert_eq!(clamped.x, 1920 - EDGE_MARGIN - MENU_RADIUS);
        assert_eq!(clamped.y, 1080 - EDGE_MARGIN - MENU_RADIUS);
    }

    #[test]
    fn test_edge_clamping_near_edge() {
        // Cursor 10px from left edge should be clamped
        let bounds = ScreenBounds { width: 1920, height: 1080 };
        let pos = CursorPosition::new(10, 540);
        let clamped = pos.clamp_to_screen(&bounds);

        assert_eq!(clamped.x, EDGE_MARGIN + MENU_RADIUS); // 160
        assert_eq!(clamped.y, 540); // Y unchanged
    }

    #[test]
    fn test_menu_constants() {
        assert_eq!(MENU_DIAMETER, 280);
        assert_eq!(EDGE_MARGIN, 20);
        assert_eq!(MENU_RADIUS, 140);
    }

    #[test]
    fn test_screen_bounds_default() {
        let bounds = ScreenBounds::default();
        assert_eq!(bounds.width, 1920);
        assert_eq!(bounds.height, 1080);
    }
}
