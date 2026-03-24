//! Action execution for radial menu selections
//!
//! Supports keyboard shortcuts, shell commands, D-Bus calls, and KWin scripts.
//!
//! ## Key Synthesis (Story 2.6)
//! Uses xdotool for X11 and ydotool for Wayland to synthesize key events.
//!
//! ## Shell Commands (Story 2.8)
//! Executes commands via sh -c for shell interpretation, non-blocking.

use serde::{Deserialize, Serialize};
use std::process::Command;
use std::time::Instant;

/// Action types supported by radial menu
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "value")]
pub enum ActionType {
    /// Keyboard shortcut (e.g., "Ctrl+C")
    #[serde(rename = "shortcut")]
    Shortcut(String),

    /// Shell command (e.g., "dolphin ~")
    #[serde(rename = "command")]
    Command(String),

    /// D-Bus method call
    #[serde(rename = "dbus")]
    DBus(DBusCall),

    /// KWin script action
    #[serde(rename = "kwin")]
    KWin(String),

    /// No action (empty slice)
    #[serde(rename = "none")]
    None,
}

/// D-Bus method call specification
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DBusCall {
    /// D-Bus service name
    pub service: String,
    /// Object path
    pub path: String,
    /// Interface name
    pub interface: String,
    /// Method name
    pub method: String,
    /// Method arguments (as JSON)
    #[serde(default)]
    pub args: Vec<serde_json::Value>,
}

/// A complete action with icon and label
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Action {
    /// Action type and parameters
    #[serde(flatten)]
    pub action_type: ActionType,

    /// Display label
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,

    /// Icon (emoji, path, or system icon name)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub icon: Option<String>,
}

/// Action executor
pub struct ActionExecutor;

impl ActionExecutor {
    /// Execute an action
    ///
    /// Returns within 10ms for keyboard shortcuts (NFR-001)
    pub async fn execute(action: &Action) -> Result<(), ActionError> {
        match &action.action_type {
            ActionType::Shortcut(keys) => {
                Self::execute_shortcut(keys).await
            }
            ActionType::Command(cmd) => {
                Self::execute_command(cmd).await
            }
            ActionType::DBus(call) => {
                Self::execute_dbus(call).await
            }
            ActionType::KWin(script) => {
                Self::execute_kwin(script).await
            }
            ActionType::None => Ok(()),
        }
    }

    /// Execute keyboard shortcut via xdotool (Story 2.6)
    ///
    /// Supports modifiers: ctrl, shift, alt, super
    /// Format: "ctrl+c", "ctrl+shift+z", "super+e"
    ///
    /// AC1: Execution within 10ms
    async fn execute_shortcut(keys: &str) -> Result<(), ActionError> {
        let start = Instant::now();

        tracing::info!(keys, "Executing keyboard shortcut");

        // Convert our format to xdotool format
        // e.g., "ctrl+c" -> "ctrl+c", "ctrl+shift+z" -> "ctrl+shift+z"
        let xdotool_keys = keys.to_lowercase();

        // Try xdotool first (works on X11)
        let result = Command::new("xdotool")
            .args(["key", &xdotool_keys])
            .spawn();

        match result {
            Ok(mut child) => {
                // Don't wait for completion to meet <10ms requirement
                // Check if it started successfully
                match child.try_wait() {
                    Ok(Some(status)) if !status.success() => {
                        tracing::warn!("xdotool exited with error status");
                    }
                    Err(e) => {
                        tracing::warn!("Error checking xdotool status: {}", e);
                    }
                    _ => {}
                }
            }
            Err(e) => {
                // xdotool not available, try ydotool for Wayland
                tracing::debug!("xdotool failed: {}, trying ydotool", e);

                let ydotool_result = Command::new("ydotool")
                    .args(["key", &xdotool_keys])
                    .spawn();

                if let Err(e) = ydotool_result {
                    tracing::error!("Both xdotool and ydotool failed: {}", e);
                    return Err(ActionError::ExecutionFailed(format!(
                        "Key synthesis failed: {}",
                        e
                    )));
                }
            }
        }

        let elapsed = start.elapsed();
        tracing::info!(
            latency_us = elapsed.as_micros(),
            "Keyboard shortcut executed"
        );

        // AC1: Verify <10ms
        if elapsed.as_millis() > 10 {
            tracing::warn!(
                latency_ms = elapsed.as_millis(),
                "Shortcut execution exceeded 10ms target"
            );
        }

        Ok(())
    }

    /// Execute shell command (Story 2.8)
    ///
    /// Runs command via sh -c for shell interpretation.
    /// Non-blocking: spawns subprocess and returns immediately.
    ///
    /// AC1: Execution begins within 10ms
    async fn execute_command(cmd: &str) -> Result<(), ActionError> {
        let start = Instant::now();

        tracing::info!(cmd, "Executing shell command");

        // Use sh -c for shell interpretation (handles pipes, redirects, etc.)
        let result = Command::new("sh")
            .args(["-c", cmd])
            .spawn();

        match result {
            Ok(_child) => {
                // Don't wait for command to complete (AC2: non-blocking)
                tracing::debug!("Shell command spawned successfully");
            }
            Err(e) => {
                tracing::error!(cmd, error = %e, "Failed to execute shell command");
                return Err(ActionError::ExecutionFailed(format!(
                    "Shell command failed: {}",
                    e
                )));
            }
        }

        let elapsed = start.elapsed();
        tracing::info!(
            latency_us = elapsed.as_micros(),
            "Shell command spawned"
        );

        // AC1: Verify <10ms to spawn
        if elapsed.as_millis() > 10 {
            tracing::warn!(
                latency_ms = elapsed.as_millis(),
                "Command spawn exceeded 10ms target"
            );
        }

        Ok(())
    }

    async fn execute_dbus(call: &DBusCall) -> Result<(), ActionError> {
        tracing::info!(
            service = %call.service,
            path = %call.path,
            interface = %call.interface,
            method = %call.method,
            "Executing D-Bus call"
        );

        // Build dbus-send arguments
        let mut args = vec![
            "--session".to_string(),
            "--print-reply".to_string(),
            format!("--dest={}", call.service),
            call.path.clone(),
            format!("{}.{}", call.interface, call.method),
        ];

        // Append typed arguments
        for arg in &call.args {
            match arg {
                serde_json::Value::String(s) => args.push(format!("string:{}", s)),
                serde_json::Value::Bool(b) => args.push(format!("boolean:{}", b)),
                serde_json::Value::Number(n) => {
                    if let Some(i) = n.as_i64() {
                        args.push(format!("int32:{}", i));
                    } else if let Some(f) = n.as_f64() {
                        args.push(format!("double:{}", f));
                    }
                }
                _ => {}
            }
        }

        let result = Command::new("dbus-send")
            .args(&args)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();

        match result {
            Ok(status) if status.success() => Ok(()),
            Ok(status) => {
                tracing::warn!(exit_code = ?status.code(), "dbus-send exited with error");
                Err(ActionError::ExecutionFailed("dbus-send failed".to_string()))
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to execute dbus-send");
                Err(ActionError::ExecutionFailed(format!("dbus-send: {}", e)))
            }
        }
    }

    async fn execute_kwin(script: &str) -> Result<(), ActionError> {
        tracing::info!(script, "Executing KWin script");

        // Use dbus-send to invoke kglobalaccel shortcut
        // This is more reliable than loading KWin scripts for simple actions
        let result = Command::new("dbus-send")
            .args([
                "--session",
                "--print-reply",
                "--dest=org.kde.kglobalaccel",
                "/component/kwin",
                "org.kde.kglobalaccel.Component.invokeShortcut",
                &format!("string:{}", script),
            ])
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();

        match result {
            Ok(status) if status.success() => Ok(()),
            Ok(_) => {
                tracing::warn!("kglobalaccel invokeShortcut failed for: {}", script);
                Err(ActionError::ExecutionFailed(format!("KWin shortcut '{}' failed", script)))
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to invoke KWin shortcut");
                Err(ActionError::ExecutionFailed(format!("KWin: {}", e)))
            }
        }
    }
}

/// Action error type
#[derive(Debug)]
pub enum ActionError {
    /// Action execution failed with reason
    ExecutionFailed(String),
    /// Action timed out
    Timeout,
    /// Invalid action configuration
    InvalidAction,
    /// Shell command execution failed
    ShellExecution(String),
}

impl std::fmt::Display for ActionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ActionError::ExecutionFailed(msg) => write!(f, "Execution failed: {}", msg),
            ActionError::Timeout => write!(f, "Action timed out"),
            ActionError::InvalidAction => write!(f, "Invalid action configuration"),
            ActionError::ShellExecution(msg) => write!(f, "Shell execution failed: {}", msg),
        }
    }
}

impl std::error::Error for ActionError {}

/// Default actions for the 8 slices (Story 2.6)
/// N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7
pub fn get_default_actions() -> [Action; 8] {
    [
        // N (0): Copy
        Action {
            action_type: ActionType::Shortcut("ctrl+c".to_string()),
            label: Some("Copy".to_string()),
            icon: Some("📋".to_string()),
        },
        // NE (1): Paste
        Action {
            action_type: ActionType::Shortcut("ctrl+v".to_string()),
            label: Some("Paste".to_string()),
            icon: Some("📄".to_string()),
        },
        // E (2): Undo
        Action {
            action_type: ActionType::Shortcut("ctrl+z".to_string()),
            label: Some("Undo".to_string()),
            icon: Some("↩️".to_string()),
        },
        // SE (3): Redo
        Action {
            action_type: ActionType::Shortcut("ctrl+shift+z".to_string()),
            label: Some("Redo".to_string()),
            icon: Some("↪️".to_string()),
        },
        // S (4): Select All
        Action {
            action_type: ActionType::Shortcut("ctrl+a".to_string()),
            label: Some("Select All".to_string()),
            icon: Some("🔲".to_string()),
        },
        // SW (5): Cut
        Action {
            action_type: ActionType::Shortcut("ctrl+x".to_string()),
            label: Some("Cut".to_string()),
            icon: Some("✂️".to_string()),
        },
        // W (6): Save
        Action {
            action_type: ActionType::Shortcut("ctrl+s".to_string()),
            label: Some("Save".to_string()),
            icon: Some("💾".to_string()),
        },
        // NW (7): Close Tab
        Action {
            action_type: ActionType::Shortcut("ctrl+w".to_string()),
            label: Some("Close".to_string()),
            icon: Some("❌".to_string()),
        },
    ]
}

// ============================================================================
// Button Action Dispatch
// ============================================================================

use crate::config::ButtonAction;

/// Detect current desktop environment
pub fn detect_desktop() -> &'static str {
    std::env::var("XDG_CURRENT_DESKTOP")
        .map(|d| {
            let u = d.to_uppercase();
            if u.contains("KDE") || u.contains("PLASMA") {
                "kde"
            } else if u.contains("GNOME") {
                "gnome"
            } else if u.contains("HYPRLAND") {
                "hyprland"
            } else if u.contains("SWAY") {
                "sway"
            } else if u.contains("COSMIC") {
                "cosmic"
            } else {
                "unknown"
            }
        })
        .unwrap_or("unknown")
}

/// Execute a button action directly.
/// Returns Ok(true) if the action was handled, Ok(false) if it should use the
/// radial menu flow (caller handles ShowMenu/HideMenu).
pub async fn execute_button_action(action: ButtonAction) -> Result<bool, ActionError> {
    match action {
        ButtonAction::RadialMenu => {
            // Caller handles the radial menu show/hide flow
            Ok(false)
        }
        ButtonAction::VirtualDesktops => {
            execute_virtual_desktops().await?;
            Ok(true)
        }
        ButtonAction::None => Ok(true),
        ButtonAction::Smartshift => {
            tracing::warn!("SmartShift button action not yet implemented (requires HID++ write)");
            Ok(true)
        }
        ButtonAction::Custom => {
            tracing::warn!("Custom button action not yet implemented");
            Ok(true)
        }
        // All other actions map to keyboard shortcuts
        _ => {
            let shortcut = button_action_to_shortcut(action);
            if let Some(keys) = shortcut {
                let act = Action {
                    action_type: ActionType::Shortcut(keys.to_string()),
                    label: None,
                    icon: None,
                };
                ActionExecutor::execute(&act).await?;
            }
            Ok(true)
        }
    }
}

/// Execute virtual desktops overview toggle (desktop-specific)
async fn execute_virtual_desktops() -> Result<(), ActionError> {
    let desktop = detect_desktop();
    tracing::info!(desktop, "Triggering virtual desktops overview");

    match desktop {
        "gnome" => {
            // Toggle GNOME Activities overview via OverviewActive property
            let result = Command::new("dbus-send")
                .args([
                    "--session",
                    "--print-reply",
                    "--dest=org.gnome.Shell",
                    "/org/gnome/Shell",
                    "org.freedesktop.DBus.Properties.Get",
                    "string:org.gnome.Shell",
                    "string:OverviewActive",
                ])
                .output();

            // Check current state and toggle
            let currently_active = match result {
                Ok(output) => {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    stdout.contains("true")
                }
                Err(_) => false,
            };

            let new_state = if currently_active { "false" } else { "true" };
            let set_result = Command::new("dbus-send")
                .args([
                    "--session",
                    "--print-reply",
                    "--dest=org.gnome.Shell",
                    "/org/gnome/Shell",
                    "org.freedesktop.DBus.Properties.Set",
                    "string:org.gnome.Shell",
                    "string:OverviewActive",
                    &format!("variant:boolean:{}", new_state),
                ])
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();

            match set_result {
                Ok(status) if status.success() => Ok(()),
                _ => {
                    // Fallback: try Shell.Eval
                    tracing::debug!("OverviewActive property failed, trying Shell.Eval fallback");
                    let eval_result = Command::new("dbus-send")
                        .args([
                            "--session",
                            "--print-reply",
                            "--dest=org.gnome.Shell",
                            "/org/gnome/Shell",
                            "org.gnome.Shell.Eval",
                            "string:Main.overview.toggle();",
                        ])
                        .stdin(std::process::Stdio::null())
                        .stdout(std::process::Stdio::null())
                        .stderr(std::process::Stdio::null())
                        .status();

                    match eval_result {
                        Ok(status) if status.success() => Ok(()),
                        _ => Err(ActionError::ExecutionFailed(
                            "Failed to toggle GNOME overview".to_string(),
                        )),
                    }
                }
            }
        }
        "kde" => {
            // Toggle KDE Overview via kglobalaccel shortcut invocation
            ActionExecutor::execute_kwin("Overview").await
        }
        "hyprland" => {
            // Try Hyprspace overview plugin first, fall back to workspace switch
            let result = Command::new("hyprctl")
                .args(["dispatch", "overview:toggle"])
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .status();

            match result {
                Ok(status) if status.success() => Ok(()),
                _ => {
                    tracing::debug!("Hyprspace not available, using Super key for overview");
                    let act = Action {
                        action_type: ActionType::Shortcut("super".to_string()),
                        label: None,
                        icon: None,
                    };
                    ActionExecutor::execute(&act).await
                }
            }
        }
        "sway" => {
            // Sway has no native overview - synthesize Super key
            let act = Action {
                action_type: ActionType::Shortcut("super".to_string()),
                label: None,
                icon: None,
            };
            ActionExecutor::execute(&act).await
        }
        _ => {
            tracing::warn!(desktop, "Virtual desktops not supported on this desktop environment");
            Ok(())
        }
    }
}

/// Map a ButtonAction to the keyboard shortcut it should synthesize
fn button_action_to_shortcut(action: ButtonAction) -> Option<&'static str> {
    match action {
        ButtonAction::MiddleClick => Some("button2"),
        ButtonAction::Back => Some("alt+Left"),
        ButtonAction::Forward => Some("alt+Right"),
        ButtonAction::Copy => Some("ctrl+c"),
        ButtonAction::Paste => Some("ctrl+v"),
        ButtonAction::Undo => Some("ctrl+z"),
        ButtonAction::Redo => Some("ctrl+shift+z"),
        ButtonAction::Screenshot => Some("Print"),
        ButtonAction::VolumeUp => Some("XF86AudioRaiseVolume"),
        ButtonAction::VolumeDown => Some("XF86AudioLowerVolume"),
        ButtonAction::PlayPause => Some("XF86AudioPlay"),
        ButtonAction::Mute => Some("XF86AudioMute"),
        ButtonAction::ZoomIn => Some("ctrl+plus"),
        ButtonAction::ZoomOut => Some("ctrl+minus"),
        ButtonAction::ScrollLeftRight => None, // Handled by hardware, not keyboard shortcut
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_action_serialization() {
        let action = Action {
            action_type: ActionType::Shortcut("Ctrl+C".to_string()),
            label: Some("Copy".to_string()),
            icon: Some("📋".to_string()),
        };

        let json = serde_json::to_string(&action).unwrap();
        assert!(json.contains("shortcut"));
        assert!(json.contains("Ctrl+C"));
    }

    #[test]
    fn test_action_deserialization() {
        let json = r#"{"type":"shortcut","value":"ctrl+c","label":"Copy"}"#;
        let action: Action = serde_json::from_str(json).unwrap();

        match action.action_type {
            ActionType::Shortcut(keys) => assert_eq!(keys, "ctrl+c"),
            _ => panic!("Expected Shortcut action"),
        }
        assert_eq!(action.label, Some("Copy".to_string()));
    }

    #[test]
    fn test_command_action() {
        let action = Action {
            action_type: ActionType::Command("konsole".to_string()),
            label: Some("Terminal".to_string()),
            icon: None,
        };

        let json = serde_json::to_string(&action).unwrap();
        assert!(json.contains("command"));
        assert!(json.contains("konsole"));
    }

    #[test]
    fn test_none_action() {
        let action = Action {
            action_type: ActionType::None,
            label: None,
            icon: None,
        };

        let json = serde_json::to_string(&action).unwrap();
        assert!(json.contains("none"));
    }

    #[test]
    fn test_default_actions() {
        let actions = get_default_actions();

        assert_eq!(actions.len(), 8);

        // Verify N=Copy
        match &actions[0].action_type {
            ActionType::Shortcut(keys) => assert_eq!(keys, "ctrl+c"),
            _ => panic!("Expected Shortcut"),
        }

        // Verify S=Select All
        match &actions[4].action_type {
            ActionType::Shortcut(keys) => assert_eq!(keys, "ctrl+a"),
            _ => panic!("Expected Shortcut"),
        }
    }

    #[test]
    fn test_action_error_display() {
        let err = ActionError::ExecutionFailed("test error".to_string());
        assert!(format!("{}", err).contains("test error"));

        let err = ActionError::Timeout;
        assert!(format!("{}", err).contains("timed out"));

        let err = ActionError::ShellExecution("command not found".to_string());
        assert!(format!("{}", err).contains("Shell execution"));
    }

    #[tokio::test]
    async fn test_execute_none_action() {
        let action = Action {
            action_type: ActionType::None,
            label: None,
            icon: None,
        };

        let result = ActionExecutor::execute(&action).await;
        assert!(result.is_ok());
    }
}
