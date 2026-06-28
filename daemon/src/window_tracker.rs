//! Active-window tracking for per-application hardware profiles
//!
//! Reports the focused window's resource class so the daemon can apply a
//! per-app [`HardwareProfile`](crate::profiles::HardwareProfile). Each desktop
//! environment has its own proven source:
//!
//! - **KDE**: a persistent KWin script (loadScript + Script.run) connects to the
//!   activation signal and calls the daemon's `ReportActiveWindow` D-Bus method,
//!   the same loadScript/callDBus pipeline used for cursor positioning. Handles
//!   Plasma 6 (`windowActivated`/`activeWindow`) and Plasma 5
//!   (`clientActivated`/`activeClient`).
//! - **Hyprland**: reads the `activewindow` event from the `.socket2` event
//!   stream.
//! - **X11 / other**: polls `xprop _NET_ACTIVE_WINDOW` + `WM_CLASS`.
//!
//! Non-KDE sources push classes straight into the channel; KDE pushes via the
//! D-Bus method (which forwards into the same channel).
//!
//! SPDX-License-Identifier: GPL-3.0

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

use tokio::sync::mpsc::UnboundedSender;

use crate::actions::detect_desktop;

/// Persistent KWin script that reports the active window's resource class on
/// every activation change. Stays resident after `run()` because it connects to
/// a workspace signal (unlike the one-shot cursor script).
pub const KWIN_ACTIVE_WINDOW_SCRIPT: &str = r#"
function reportActive(w) {
    if (w && w.resourceClass) {
        callDBus("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
                 "org.kde.juhradialmx.Daemon", "ReportActiveWindow",
                 String(w.resourceClass));
    }
}
if (typeof workspace.windowActivated !== "undefined") {
    // Plasma 6
    workspace.windowActivated.connect(reportActive);
    reportActive(workspace.activeWindow);
} else if (typeof workspace.clientActivated !== "undefined") {
    // Plasma 5
    workspace.clientActivated.connect(reportActive);
    reportActive(workspace.activeClient);
}
"#;

/// Tracks the active window via the desktop-appropriate source.
pub struct WindowTracker {
    de: &'static str,
}

impl WindowTracker {
    /// Create a tracker bound to the detected desktop environment.
    pub fn new() -> Self {
        Self { de: detect_desktop() }
    }

    /// The detected desktop environment ("kde", "hyprland", ...).
    pub fn desktop(&self) -> &'static str {
        self.de
    }

    /// Whether a working active-window source exists for this environment.
    pub fn is_available(&self) -> bool {
        matches!(self.de, "kde" | "hyprland") || std::env::var_os("DISPLAY").is_some()
    }

    /// Run the tracker until `tx` is closed. Pushes each newly focused window's
    /// lowercased resource class into `tx`.
    ///
    /// KDE installs the persistent KWin script (which feeds `ReportActiveWindow`
    /// → the same `tx`), so this returns once the script is installed. Hyprland
    /// and X11 sources run their own loops on the blocking pool.
    pub async fn watch(self, tx: UnboundedSender<String>) {
        match self.de {
            "kde" => {
                if install_kwin_script(KWIN_ACTIVE_WINDOW_SCRIPT) {
                    tracing::info!("KWin active-window script installed (per-app hardware profiles)");
                } else {
                    tracing::warn!(
                        "Failed to install KWin active-window script; per-app hardware profiles inactive on KDE"
                    );
                }
            }
            "hyprland" => {
                let _ = tokio::task::spawn_blocking(move || hyprland_loop(tx)).await;
            }
            _ => {
                let _ = tokio::task::spawn_blocking(move || x11_poll_loop(tx)).await;
            }
        }
    }
}

impl Default for WindowTracker {
    fn default() -> Self {
        Self::new()
    }
}

/// Load and run a KWin script via D-Bus, returning whether it started. Mirrors
/// the cursor-script pipeline (loadScript → Script.run).
fn install_kwin_script(script: &str) -> bool {
    let mut temp_file = match tempfile::Builder::new().suffix(".js").tempfile() {
        Ok(f) => f,
        Err(e) => {
            tracing::warn!(error = %e, "Failed to create temp file for KWin script");
            return false;
        }
    };
    if let Err(e) = write!(temp_file, "{}", script) {
        tracing::warn!(error = %e, "Failed to write KWin script");
        return false;
    }
    let script_path = temp_file.path().to_string_lossy().to_string();

    let load_output = match Command::new("dbus-send")
        .args([
            "--session",
            "--print-reply",
            "--dest=org.kde.KWin",
            "/Scripting",
            "org.kde.kwin.Scripting.loadScript",
            &format!("string:{}", script_path),
        ])
        .output()
    {
        Ok(o) if o.status.success() => o,
        _ => {
            tracing::warn!("Failed to load KWin active-window script");
            return false;
        }
    };

    let stdout = String::from_utf8_lossy(&load_output.stdout);
    let script_id: Option<i32> = stdout
        .lines()
        .find(|line| line.contains("int32"))
        .and_then(|line| line.split_whitespace().last())
        .and_then(|s| s.parse().ok());

    let script_id = match script_id {
        Some(id) => id,
        None => {
            tracing::warn!("Failed to parse KWin script ID");
            return false;
        }
    };

    matches!(
        Command::new("dbus-send")
            .args([
                "--session",
                "--print-reply",
                "--dest=org.kde.KWin",
                &format!("/Scripting/Script{}", script_id),
                "org.kde.kwin.Script.run",
            ])
            .output(),
        Ok(o) if o.status.success()
    )
}

/// Path to the Hyprland `.socket2` event socket for this session.
fn hyprland_socket2_path() -> Option<PathBuf> {
    let sig = std::env::var("HYPRLAND_INSTANCE_SIGNATURE").ok()?;
    let runtime = std::env::var("XDG_RUNTIME_DIR").ok()?;
    Some(PathBuf::from(runtime).join("hypr").join(sig).join(".socket2.sock"))
}

/// Blocking Hyprland event loop: parses `activewindow>>CLASS,TITLE` lines and
/// pushes the class. Reconnects with backoff until `tx` closes.
fn hyprland_loop(tx: UnboundedSender<String>) {
    let path = match hyprland_socket2_path() {
        Some(p) => p,
        None => {
            tracing::warn!("Hyprland socket signature not found; window tracking disabled");
            return;
        }
    };

    loop {
        if tx.is_closed() {
            return;
        }
        match UnixStream::connect(&path) {
            Ok(stream) => {
                tracing::info!("Connected to Hyprland event socket (per-app hardware profiles)");
                let reader = BufReader::new(stream);
                for line in reader.lines() {
                    let line = match line {
                        Ok(l) => l,
                        Err(_) => break,
                    };
                    if let Some(rest) = line.strip_prefix("activewindow>>") {
                        let class = rest.split(',').next().unwrap_or("").trim().to_lowercase();
                        if !class.is_empty() && tx.send(class).is_err() {
                            return;
                        }
                    }
                }
            }
            Err(e) => tracing::debug!(error = %e, "Hyprland socket connect failed; retrying"),
        }
        std::thread::sleep(Duration::from_secs(2));
    }
}

/// Blocking X11 poll loop: reads the active window's WM_CLASS via xprop and
/// pushes it when it changes.
fn x11_poll_loop(tx: UnboundedSender<String>) {
    let mut last = String::new();
    loop {
        if tx.is_closed() {
            return;
        }
        if let Some(class) = x11_active_window_class() {
            if class != last {
                last = class.clone();
                if tx.send(class).is_err() {
                    return;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(750));
    }
}

/// Query the focused window's WM_CLASS via xprop. Returns the lowercased class.
fn x11_active_window_class() -> Option<String> {
    let root = Command::new("xprop")
        .args(["-root", "_NET_ACTIVE_WINDOW"])
        .output()
        .ok()?;
    if !root.status.success() {
        return None;
    }
    let root_out = String::from_utf8_lossy(&root.stdout);
    // "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x1c00007"
    let win_id = root_out.split_whitespace().last()?;
    if !win_id.starts_with("0x") {
        return None;
    }

    let class_out = Command::new("xprop")
        .args(["-id", win_id, "WM_CLASS"])
        .output()
        .ok()?;
    if !class_out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&class_out.stdout);
    // WM_CLASS(STRING) = "instance", "Class"
    parse_wm_class(&text)
}

/// Extract the class (second quoted field) from an `xprop WM_CLASS` line.
fn parse_wm_class(text: &str) -> Option<String> {
    let quoted: Vec<&str> = text.split('"').collect();
    // ["WM_CLASS... = ", instance, ", ", class, ""]
    let class = if quoted.len() >= 4 {
        quoted[3]
    } else if quoted.len() >= 2 {
        quoted[1]
    } else {
        return None;
    };
    let class = class.trim();
    if class.is_empty() {
        None
    } else {
        Some(class.to_lowercase())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kwin_script_handles_both_plasma_versions() {
        assert!(KWIN_ACTIVE_WINDOW_SCRIPT.contains("windowActivated"));
        assert!(KWIN_ACTIVE_WINDOW_SCRIPT.contains("activeWindow"));
        assert!(KWIN_ACTIVE_WINDOW_SCRIPT.contains("clientActivated"));
        assert!(KWIN_ACTIVE_WINDOW_SCRIPT.contains("activeClient"));
        assert!(KWIN_ACTIVE_WINDOW_SCRIPT.contains("ReportActiveWindow"));
    }

    #[test]
    fn parse_wm_class_extracts_class_field() {
        let line = "WM_CLASS(STRING) = \"navigator\", \"firefox\"";
        assert_eq!(parse_wm_class(line), Some("firefox".to_string()));
    }

    #[test]
    fn parse_wm_class_single_field() {
        let line = "WM_CLASS(STRING) = \"konsole\"";
        assert_eq!(parse_wm_class(line), Some("konsole".to_string()));
    }

    #[test]
    fn parse_wm_class_empty_is_none() {
        assert_eq!(parse_wm_class("WM_CLASS(STRING) = "), None);
    }

    #[test]
    fn hyprland_activewindow_line_parses() {
        let line = "activewindow>>firefox,Mozilla Firefox";
        let rest = line.strip_prefix("activewindow>>").unwrap();
        let class = rest.split(',').next().unwrap().trim().to_lowercase();
        assert_eq!(class, "firefox");
    }
}
