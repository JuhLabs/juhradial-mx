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
        // TODO: Make D-Bus method call via zbus
        tracing::info!(
            service = call.service,
            method = call.method,
            "Executing D-Bus call"
        );
        Ok(())
    }

    async fn execute_kwin(script: &str) -> Result<(), ActionError> {
        // TODO: Invoke KWin script via D-Bus
        tracing::info!(script, "Executing KWin script");
        Ok(())
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
