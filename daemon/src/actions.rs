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
use std::collections::HashMap;
use std::process::Command;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

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

/// Bound every `dbus-send` wait. These calls are awaited on the single gesture
/// dispatch task, so dbus-send's 25 second default would freeze the button, the
/// thumb wheel and macro triggers together whenever the compositor or the shell
/// is wedged.
const REPLY_TIMEOUT: &str = "--reply-timeout=2000";

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

        // session_var, not std::env: started from the systemd user unit the
        // daemon has neither variable, so this read said "X11" on a Wayland
        // session, skipped the uinput path below, and every shortcut action
        // died in xdotool with an empty DISPLAY (issue #60).
        let is_wayland = session_var("WAYLAND_DISPLAY").is_some()
            || session_var("XDG_SESSION_TYPE")
                .map(|s| s.eq_ignore_ascii_case("wayland"))
                .unwrap_or(false);

        // On Wayland, X11 input synthesis (xdotool) does not reach native
        // Wayland windows. Inject through the kernel uinput device via ydotool,
        // which needs evdev key CODES (not keysym names) and is the reliable
        // path on KDE Plasma Wayland. Unmapped chords fall through to xdotool.
        let mut injected = false;
        if is_wayland {
            if let Some(codes) = Self::shortcut_to_evdev_codes(keys) {
                injected = Self::inject_via_ydotool(keys, &codes);
                if !injected {
                    tracing::warn!(keys, "ydotool injection failed; trying xdotool");
                }
            } else {
                tracing::debug!(keys, "no evdev key mapping; using xdotool path");
            }
        }

        // X11 (or Wayland fallback): keysyms are case-sensitive (e.g.
        // XF86AudioRaiseVolume), so pass the ORIGINAL case to xdotool.
        if !injected {
            let mut cmd = Command::new("xdotool");
            cmd.args(["key", keys]);
            apply_session_env(&mut cmd);
            match cmd.spawn() {
                Ok(child) => reap_in_background(child, keys, "xdotool"),
                Err(e) => {
                    tracing::debug!("xdotool unavailable: {}, trying ydotool codes", e);
                    let ok = Self::shortcut_to_evdev_codes(keys)
                        .map(|c| Self::inject_via_ydotool(keys, &c))
                        .unwrap_or(false);
                    if !ok {
                        return Err(ActionError::ExecutionFailed(format!(
                            "Key synthesis failed for: {}",
                            keys
                        )));
                    }
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

    /// Map a shortcut string ("ctrl+plus", "XF86AudioRaiseVolume", "alt+Left")
    /// to evdev key codes (modifiers first, main key last) for uinput injection.
    /// Returns None for any token we do not map, so the caller can fall back to
    /// xdotool. Codes are from linux/input-event-codes.h.
    fn shortcut_to_evdev_codes(keys: &str) -> Option<Vec<u16>> {
        let mut codes = Vec::new();
        for tok in keys.split('+') {
            let code: u16 = match tok.trim().to_ascii_lowercase().as_str() {
                "ctrl" | "control" => 29,
                "shift" => 42,
                "alt" => 56,
                "super" | "meta" | "win" => 125,
                "a" => 30, "b" => 48, "c" => 46, "d" => 32, "e" => 18, "f" => 33,
                "g" => 34, "h" => 35, "i" => 23, "j" => 36, "k" => 37, "l" => 38,
                "m" => 50, "n" => 49, "o" => 24, "p" => 25, "q" => 16, "r" => 19,
                "s" => 31, "t" => 20, "u" => 22, "v" => 47, "w" => 17, "x" => 45,
                "y" => 21, "z" => 44,
                "1" => 2, "2" => 3, "3" => 4, "4" => 5, "5" => 6,
                "6" => 7, "7" => 8, "8" => 9, "9" => 10, "0" => 11,
                "plus" | "equal" => 13,
                "minus" => 12,
                "kp_add" => 78,
                "kp_subtract" => 74,
                "left" => 105, "right" => 106, "up" => 103, "down" => 108,
                "home" => 102, "end" => 107, "tab" => 15, "escape" | "esc" => 1,
                "space" => 57, "return" | "enter" => 28, "delete" => 111,
                "print" => 99,
                "xf86audioraisevolume" => 115,
                "xf86audiolowervolume" => 114,
                "xf86audiomute" => 113,
                "xf86audioplay" => 164,
                "xf86audionext" => 163,
                "xf86audioprev" => 165,
                _ => return None,
            };
            codes.push(code);
        }
        if codes.is_empty() {
            None
        } else {
            Some(codes)
        }
    }

    /// Inject a key chord through the kernel uinput device via ydotool: press
    /// every code in order, then release in reverse. ydotool uses uinput, so it
    /// drives both X11 and Wayland (incl. KDE Plasma). Returns true if started.
    fn inject_via_ydotool(keys: &str, codes: &[u16]) -> bool {
        let mut args: Vec<String> = vec!["key".to_string()];
        args.extend(codes.iter().map(|c| format!("{}:1", c)));
        args.extend(codes.iter().rev().map(|c| format!("{}:0", c)));
        match Command::new("ydotool").args(&args).spawn() {
            Ok(child) => {
                reap_in_background(child, keys, "ydotool");
                true
            }
            Err(_) => false,
        }
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
        let mut command = Command::new("sh");
        command.args(["-c", cmd]);
        // Button presets launch GUIs (Calculator) and compositor clients
        // (hyprctl), which need a display the unit environment does not carry.
        apply_session_env(&mut command);

        match command.spawn() {
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
            REPLY_TIMEOUT.to_string(),
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
                REPLY_TIMEOUT,
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

/// Reap a spawned key-synthesis helper off the press path and report a real
/// failure.
///
/// `try_wait()` straight after `spawn()` reports "still running" for a process
/// that is about to fail, so a broken helper was logged as a successful
/// shortcut for the whole of issue #60: the daemon printed "Keyboard shortcut
/// executed" while xdotool aborted with an empty DISPLAY. Waiting here would
/// blow the 10ms budget (NFR-001), so wait on a blocking task instead.
fn reap_in_background(mut child: std::process::Child, input: &str, tool: &'static str) {
    let input = input.to_string();
    tokio::task::spawn_blocking(move || match child.wait() {
        Ok(status) if !status.success() => tracing::warn!(
            input,
            tool,
            code = status.code().unwrap_or(-1),
            "input synthesis failed - nothing was sent"
        ),
        Err(e) => tracing::warn!(input, tool, error = %e, "could not reap input synthesis helper"),
        _ => {}
    });
}

/// Start `program` with `args` in `cwd` (a plugin script) with the session
/// environment a GUI helper needs. Non-blocking like a shell command; the
/// exit status is logged when the program ends.
pub fn spawn_program(program: &std::path::Path, args: &[String], cwd: &std::path::Path) -> Result<(), ActionError> {
    let mut command = Command::new(program);
    command.args(args).current_dir(cwd);
    apply_session_env(&mut command);
    let mut child = command.spawn().map_err(|e| {
        ActionError::ExecutionFailed(format!("{}: {}", program.display(), e))
    })?;
    let name = program.display().to_string();
    tokio::task::spawn_blocking(move || match child.wait() {
        Ok(status) if !status.success() => {
            tracing::warn!(program = %name, code = status.code().unwrap_or(-1), "Plugin script exited with an error")
        }
        Err(e) => tracing::warn!(program = %name, error = %e, "Could not reap plugin script"),
        _ => {}
    });
    Ok(())
}

/// Session variables a spawned helper needs and the daemon does not inherit.
const SESSION_VARS: [&str; 6] = [
    "DISPLAY",
    "XAUTHORITY",
    "WAYLAND_DISPLAY",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_TYPE",
    "HYPRLAND_INSTANCE_SIGNATURE",
];

/// Give a child the session environment the daemon was started without, so a
/// helper that needs a display (xdotool, hyprctl, a GUI the user mapped to a
/// button) can find one. Variables already in the daemon's environment are
/// inherited as usual and re-set to the same value.
///
/// Reads the manager environment once for all six names: one lookup per name
/// would fork `systemctl` six times on the press path.
fn apply_session_env(cmd: &mut Command) {
    with_session_env(|session| {
        for name in SESSION_VARS {
            let own = std::env::var(name).ok();
            if let Some(value) = prefer_process_value(own, || session.get(name).cloned()) {
                cmd.env(name, value);
            }
        }
    });
}

/// Read a session variable, falling back to the systemd user manager.
///
/// systemd composes a unit's environment when the unit starts. Plasma and GNOME
/// publish `XDG_CURRENT_DESKTOP`, `WAYLAND_DISPLAY`, `DISPLAY` and friends into
/// that manager only once the session is up, which is after the daemon's unit
/// has already started, and a process's environment cannot be rewritten
/// afterwards, so the daemon's own stays empty for the whole session.
/// `compositor.rs` works around the same trap for KWin detection (issue #32);
/// this is the general form.
pub fn session_var(name: &str) -> Option<String> {
    prefer_process_value(std::env::var(name).ok(), || {
        with_session_env(|session| session.get(name).cloned())
    })
}

/// The process value wins when it is set and non-empty; otherwise the session
/// one. Split out from [`session_var`] so the precedence is testable without
/// touching the ambient environment.
fn prefer_process_value(
    process: Option<String>,
    session: impl FnOnce() -> Option<String>,
) -> Option<String> {
    match process {
        Some(value) if !value.is_empty() => Some(value),
        _ => session(),
    }
}

/// The systemd user manager's environment as seen by `systemctl --user
/// show-environment`.
///
/// A session publishes its variables in stages, so an early read can be missing
/// the display ones: caching that answer permanently would pin the daemon to a
/// broken environment for the rest of its life, and re-reading on every miss
/// costs a fork per lookup on the press path. Keep re-reading only while the
/// display variables are still absent, and no more than once per
/// [`SESSION_ENV_RETRY`].
fn with_session_env<T>(f: impl FnOnce(&HashMap<String, String>) -> T) -> T {
    static CACHE: OnceLock<Mutex<Option<SessionEnv>>> = OnceLock::new();

    let cell = CACHE.get_or_init(|| Mutex::new(None));
    let mut cached = match cell.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };

    let stale = match cached.as_ref() {
        Some(env) => !env.settled && env.read_at.elapsed() >= SESSION_ENV_RETRY,
        None => true,
    };
    if stale {
        let vars = read_systemd_user_environment();
        let now = Instant::now();
        let has_display = vars.contains_key("WAYLAND_DISPLAY") || vars.contains_key("DISPLAY");
        let display_since = match cached.as_ref().and_then(|env| env.display_since) {
            Some(since) if has_display => Some(since),
            _ if has_display => Some(now),
            _ => None,
        };
        let settled = session_env_settled(&vars, display_since, now);
        *cached = Some(SessionEnv { vars, settled, display_since, read_at: now });
    }

    match cached.as_ref() {
        Some(env) => f(&env.vars),
        None => f(&HashMap::new()),
    }
}

/// How long to wait before re-reading a session environment that is not
/// settled yet.
const SESSION_ENV_RETRY: Duration = Duration::from_secs(2);

/// How long a display may be visible without `XDG_CURRENT_DESKTOP` before the
/// environment counts as final anyway (bare window managers never set it).
pub const SESSION_DESKTOP_GRACE: Duration = Duration::from_secs(180);

struct SessionEnv {
    vars: HashMap<String, String>,
    /// The session finished publishing, so this will not change again.
    settled: bool,
    /// When a display variable was first seen.
    display_since: Option<Instant>,
    read_at: Instant,
}

/// A session publishes in stages and can export `DISPLAY` before
/// `XDG_CURRENT_DESKTOP` (issue #138), so a display alone is not final: wait
/// for the desktop name too, or for [`SESSION_DESKTOP_GRACE`] after the
/// display appeared.
fn session_env_settled(
    vars: &HashMap<String, String>,
    display_since: Option<Instant>,
    now: Instant,
) -> bool {
    let Some(since) = display_since else {
        return false;
    };
    vars.contains_key("XDG_CURRENT_DESKTOP")
        || now.saturating_duration_since(since) >= SESSION_DESKTOP_GRACE
}

fn read_systemd_user_environment() -> HashMap<String, String> {
    match Command::new("systemctl")
        .args(["--user", "show-environment"])
        .output()
    {
        Ok(output) if output.status.success() => {
            parse_environment_block(&String::from_utf8_lossy(&output.stdout))
        }
        _ => HashMap::new(),
    }
}

/// Split systemd's `NAME=value` listing into pairs. Values that need it are
/// double-quoted, and the session variables read here never contain escapes.
fn parse_environment_block(block: &str) -> HashMap<String, String> {
    block
        .lines()
        .filter_map(|line| line.split_once('='))
        .map(|(name, value)| (name.to_string(), value.trim_matches('"').to_string()))
        .collect()
}

/// Detect current desktop environment
pub fn detect_desktop() -> &'static str {
    session_var("XDG_CURRENT_DESKTOP")
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

/// App-content zoom shortcut (NOT the screen magnifier, which zooms the whole
/// desktop and is disruptive). Uses the NUMPAD +/- keys: they are
/// layout-independent (the main-row -/= keys produce different characters on
/// non-US layouts, e.g. Norwegian), and browsers, editors and image viewers all
/// accept Ctrl+KP_Add / Ctrl+KP_Subtract for zoom.
fn zoom_shortcut(zoom_in: bool) -> &'static str {
    if zoom_in {
        "ctrl+KP_Add"
    } else {
        "ctrl+KP_Subtract"
    }
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
        // Desktop-portable presets resolve per-DE (see presets.rs)
        ButtonAction::ShowDesktop
        | ButtonAction::SwitchDesktopLeft
        | ButtonAction::SwitchDesktopRight
        | ButtonAction::TaskSwitcher
        | ButtonAction::CloseWindow
        | ButtonAction::LockScreen
        | ButtonAction::Calculator => {
            if let Some(preset) = crate::presets::Preset::from_button_action(action) {
                crate::presets::execute_preset(preset).await?;
            }
            Ok(true)
        }
        // Zoom uses layout-independent numpad Ctrl+/- (see zoom_shortcut).
        ButtonAction::ZoomIn | ButtonAction::ZoomOut => {
            let keys = zoom_shortcut(matches!(action, ButtonAction::ZoomIn));
            ActionExecutor::execute(&Action {
                action_type: ActionType::Shortcut(keys.to_string()),
                label: None,
                icon: None,
            })
            .await?;
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

/// Inject horizontal scroll clicks for the diverted thumb wheel.
///
/// Positive `clicks` scroll right, negative scroll left. Horizontal scroll on
/// X11 is mouse buttons 6 (left) and 7 (right); xdotool synthesizes these
/// directly, with ydotool as a Wayland fallback (consistent with the keyboard
/// shortcut path). Non-blocking: each click is spawned, not awaited.
pub async fn execute_horizontal_scroll(clicks: i32) -> Result<(), ActionError> {
    if clicks == 0 {
        return Ok(());
    }
    // Button 6 = scroll left, 7 = scroll right.
    let button = if clicks > 0 { "7" } else { "6" };
    let count = clicks.unsigned_abs().min(16);

    for _ in 0..count {
        let mut cmd = Command::new("xdotool");
        cmd.args(["click", button]);
        // Same hole as the shortcut path: without the session environment
        // xdotool dies on an empty DISPLAY and the click is lost (issue #60).
        apply_session_env(&mut cmd);
        match cmd.spawn() {
            Ok(child) => reap_in_background(child, button, "xdotool"),
            Err(e) => {
                tracing::debug!("xdotool horizontal scroll failed: {}, trying ydotool", e);
                // ydotool click button codes: 0x06 = left scroll, 0x07 = right scroll.
                let yd_button = if clicks > 0 { "0x07" } else { "0x06" };
                match Command::new("ydotool").args(["click", yd_button]).spawn() {
                    Ok(child) => reap_in_background(child, yd_button, "ydotool"),
                    Err(e2) => {
                        tracing::error!("Both xdotool and ydotool horizontal scroll failed: {}", e2);
                        return Err(ActionError::ExecutionFailed(format!(
                            "Horizontal scroll failed: {}",
                            e2
                        )));
                    }
                }
            }
        }
    }
    Ok(())
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
                    REPLY_TIMEOUT,
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
                    REPLY_TIMEOUT,
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
                            REPLY_TIMEOUT,
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
        ButtonAction::ZoomIn => Some("ctrl+KP_Add"),
        ButtonAction::ZoomOut => Some("ctrl+KP_Subtract"),
        ButtonAction::ScrollLeftRight => None, // Handled by hardware, not keyboard shortcut
        _ => None,
    }
}

#[cfg(test)]
mod tests {

    #[test]
    fn session_env_waits_for_the_desktop_name_after_the_display() {
        let now = Instant::now();
        let display_only: HashMap<String, String> =
            [("DISPLAY".to_string(), ":0".to_string())].into_iter().collect();
        assert!(!session_env_settled(&display_only, None, now));
        assert!(!session_env_settled(&display_only, Some(now), now));
        assert!(session_env_settled(
            &display_only,
            Some(now),
            now + SESSION_DESKTOP_GRACE
        ));
        let mut full = display_only.clone();
        full.insert("XDG_CURRENT_DESKTOP".into(), "KDE".into());
        assert!(session_env_settled(&full, Some(now), now));
        let desktop_only: HashMap<String, String> =
            [("XDG_CURRENT_DESKTOP".to_string(), "KDE".to_string())].into_iter().collect();
        assert!(!session_env_settled(&desktop_only, None, now));
    }
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

    #[test]
    fn environment_block_splits_on_the_first_equals() {
        let env = parse_environment_block(
            "XDG_CURRENT_DESKTOP=KDE\n\
             DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus\n\
             XAUTHORITY=\"/run/user/1000/xauth_UeOZcX\"\n",
        );

        assert_eq!(env.get("XDG_CURRENT_DESKTOP").unwrap(), "KDE");
        // A value may itself contain '=' - only the first one separates.
        assert_eq!(
            env.get("DBUS_SESSION_BUS_ADDRESS").unwrap(),
            "unix:path=/run/user/1000/bus"
        );
        // systemd quotes values that need it; the quotes are not part of them.
        assert_eq!(
            env.get("XAUTHORITY").unwrap(),
            "/run/user/1000/xauth_UeOZcX"
        );
    }

    #[test]
    fn a_process_value_wins_over_the_session_one() {
        let picked = prefer_process_value(Some("wayland-0".to_string()), || {
            panic!("must not consult the session when the process has a value")
        });
        assert_eq!(picked.as_deref(), Some("wayland-0"));
    }

    #[test]
    fn an_unset_or_empty_process_value_falls_back_to_the_session() {
        // Empty counts as unset: systemd exports DISPLAY= on some sessions,
        // and xdotool treats that exactly like no display at all.
        for own in [None, Some(String::new())] {
            let picked = prefer_process_value(own, || Some(":0".to_string()));
            assert_eq!(picked.as_deref(), Some(":0"));
        }
    }

    #[test]
    fn a_variable_neither_side_has_is_none() {
        assert_eq!(prefer_process_value(None, || None), None);
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
