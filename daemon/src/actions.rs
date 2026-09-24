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
                Self::execute_shortcut(keys, 1).await
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
    async fn execute_shortcut(keys: &str, repeats: u8) -> Result<(), ActionError> {
        if repeats == 0 {
            return Ok(());
        }

        let start = Instant::now();

        tracing::info!(keys, repeats, "Executing keyboard shortcut");

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
                injected = Self::inject_via_ydotool(keys, &codes, repeats);
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
            cmd.args(Self::xdotool_shortcut_args(keys, repeats));
            apply_session_env(&mut cmd);
            match cmd.spawn() {
                Ok(child) => reap_in_background(child, keys, "xdotool"),
                Err(e) => {
                    tracing::debug!("xdotool unavailable: {}, trying ydotool codes", e);
                    let ok = Self::shortcut_to_evdev_codes(keys)
                        .map(|c| Self::inject_via_ydotool(keys, &c, repeats))
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
                "kp_0" => 82, "kp_1" => 79, "kp_2" => 80, "kp_3" => 81, "kp_4" => 75,
                "kp_5" => 76, "kp_6" => 77, "kp_7" => 71, "kp_8" => 72, "kp_9" => 73,
                "kp_decimal" => 83, "kp_multiply" => 55, "kp_divide" => 98, "kp_enter" => 96,
                "left" => 105, "right" => 106, "up" => 103, "down" => 108,
                "home" => 102, "end" => 107, "tab" => 15, "escape" | "esc" => 1,
                "space" => 57, "return" | "enter" => 28, "delete" => 111,
                "print" => 99,
                "page_up" | "prior" => 104, "page_down" | "next" => 109,
                "insert" => 110, "backspace" => 14, "pause" => 119, "menu" => 127,
                "f1" => 59, "f2" => 60, "f3" => 61, "f4" => 62, "f5" => 63, "f6" => 64,
                "f7" => 65, "f8" => 66, "f9" => 67, "f10" => 68, "f11" => 87, "f12" => 88,
                "f13" => 183, "f14" => 184, "f15" => 185, "f16" => 186, "f17" => 187,
                "f18" => 188, "f19" => 189, "f20" => 190, "f21" => 191, "f22" => 192,
                "f23" => 193, "f24" => 194,
                "comma" => 51, "period" => 52, "slash" => 53, "semicolon" => 39,
                "apostrophe" => 40, "bracketleft" => 26, "bracketright" => 27,
                "backslash" => 43, "grave" => 41,
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

    /// Build one xdotool invocation for the complete shortcut burst.
    fn xdotool_shortcut_args(keys: &str, repeats: u8) -> Vec<String> {
        let mut args = vec!["key".to_string()];
        if repeats > 1 {
            args.extend(["--repeat".to_string(), repeats.to_string()]);
        }
        args.push(keys.to_string());
        args
    }

    /// Build one ydotool invocation for the complete shortcut burst. ydotool's
    /// `key` subcommand has no repeat flag, but accepts an arbitrary sequence of
    /// press/release events, so repeat the chord inside one argument vector.
    fn ydotool_shortcut_args(codes: &[u16], repeats: u8) -> Vec<String> {
        let mut args = vec!["key".to_string()];
        for _ in 0..repeats {
            args.extend(codes.iter().map(|c| format!("{}:1", c)));
            args.extend(codes.iter().rev().map(|c| format!("{}:0", c)));
        }
        args
    }

    /// Inject a key chord through the kernel uinput device via ydotool: press
    /// every code in order, then release in reverse. ydotool uses uinput, so it
    /// drives both X11 and Wayland (incl. KDE Plasma). Returns true if started.
    fn inject_via_ydotool(keys: &str, codes: &[u16], repeats: u8) -> bool {
        let args = Self::ydotool_shortcut_args(codes, repeats);
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
        // Button presets launch GUIs (Calculator) and compositor clients
        // (hyprctl), which need a display the unit environment does not carry.
        match spawn_for_user("sh", &["-c", cmd]) {
            Ok(()) => {
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
pub(crate) fn apply_session_env(cmd: &mut Command) {
    cmd.envs(session_env());
}

fn session_env() -> Vec<(&'static str, String)> {
    with_session_env(|session| {
        SESSION_VARS
            .into_iter()
            .filter_map(|name| {
                let own = std::env::var(name).ok();
                prefer_process_value(own, || session.get(name).cloned()).map(|v| (name, v))
            })
            .collect()
    })
}

/// Start a program the user asked for (a shell command, a link) with the
/// session environment. Under the systemd user unit a direct child would
/// inherit the unit's hardening (NoNewPrivileges, so no sudo in a terminal
/// opened from a key; MemoryMax and CPUQuota) and be killed with every daemon
/// restart, so it runs as its own transient user service instead.
/// KillMode=process keeps launchers that fork and exit (code, flatpak run)
/// alive, on every systemd version. If systemd-run refuses, the program starts
/// directly after all.
pub(crate) fn spawn_for_user(program: &str, args: &[&str]) -> std::io::Result<()> {
    let label = program.to_string();
    let owned: Vec<String> = args.iter().map(|a| a.to_string()).collect();
    let service = std::env::var_os("INVOCATION_ID").map(|_| {
        let mut env = session_env();
        if let Ok(path) = std::env::var("PATH") {
            env.push(("PATH", path));
        }
        transient_service_args(program, &owned, &env)
    });
    let (program, args) = (label.clone(), owned);
    let direct = move || {
        let mut cmd = Command::new(&program);
        cmd.args(&args);
        apply_session_env(&mut cmd);
        cmd.spawn().map(reap_quietly)
    };
    let Some(service) = service else { return direct() };
    let Ok(mut child) = Command::new("systemd-run").args(&service).spawn() else {
        return direct();
    };
    tokio::task::spawn_blocking(move || {
        if !child.wait().is_ok_and(|status| status.success()) {
            tracing::warn!(program = label, "systemd-run refused the launch; starting it directly");
            if let Err(e) = direct() {
                tracing::error!(program = label, error = %e, "Failed to start program");
            }
        }
    });
    Ok(())
}

/// `systemd-run` arguments that start `program` as a transient user service.
fn transient_service_args(program: &str, args: &[String], env: &[(&str, String)]) -> Vec<String> {
    let mut out: Vec<String> = ["--user", "--quiet", "--collect", "--property=KillMode=process"]
        .map(String::from)
        .into();
    out.extend(env.iter().map(|(name, value)| format!("--setenv={name}={value}")));
    out.push("--".to_string());
    out.push(program.to_string());
    out.extend(args.iter().cloned());
    out
}

/// Wait for a launched program off the async workers so it never lingers as
/// a zombie; its exit status is the program's own business.
fn reap_quietly(mut child: std::process::Child) {
    tokio::task::spawn_blocking(move || {
        let _ = child.wait();
    });
}

/// True on a Wayland session, where X11 input synthesis (xdotool) misses
/// native windows and uinput (ydotool) is the path that works.
pub fn is_wayland_session() -> bool {
    session_var("WAYLAND_DISPLAY").is_some()
        || session_var("XDG_SESSION_TYPE")
            .map(|s| s.eq_ignore_ascii_case("wayland"))
            .unwrap_or(false)
}

/// The evdev code of one key name ("ctrl", "F13", "Page_Up") for uinput.
pub fn key_code(name: &str) -> Option<u16> {
    match ActionExecutor::shortcut_to_evdev_codes(name)?.as_slice() {
        [code] => Some(*code),
        _ => None,
    }
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

/// The HID++ manager, for button actions that talk to the mouse itself
/// (SmartShift toggle). Registered once by main at startup.
static DEVICE: OnceLock<crate::hidpp::SharedHapticManager> = OnceLock::new();

pub fn set_device_manager(manager: crate::hidpp::SharedHapticManager) {
    let _ = DEVICE.set(manager);
}

/// The shared HID++ manager, once main registered it.
pub fn device_manager() -> Option<crate::hidpp::SharedHapticManager> {
    DEVICE.get().cloned()
}

/// Pulse the mouse for a daemon event (DPI change, macro start/finish,
/// gesture tick, ...). Off the caller's thread: the HID++ write waits on the
/// device lock, and callers include the cursor-motion loop.
pub fn pulse(event: crate::hidpp::HapticEvent) {
    let Some(manager) = DEVICE.get().cloned() else { return };
    std::thread::spawn(move || {
        if let Ok(mut m) = manager.lock() {
            let _ = m.emit(event);
        }
    });
}

/// `times` pulses in a row (a DPI stage: one for the first preset, two for
/// the second, ...).
pub fn pulse_times(event: crate::hidpp::HapticEvent, times: usize) {
    let Some(manager) = DEVICE.get().cloned() else { return };
    std::thread::spawn(move || {
        for i in 0..times.clamp(1, 5) {
            if i > 0 {
                std::thread::sleep(std::time::Duration::from_millis(170));
            }
            if let Ok(mut m) = manager.lock() {
                let _ = m.emit(event);
            }
        }
    });
}

/// Flip the wheel between ratchet and free-spin, keeping the SmartShift
/// threshold (what the wheel-mode button under the wheel does).
async fn toggle_wheel_mode() -> Result<(), ActionError> {
    let manager = DEVICE
        .get()
        .cloned()
        .ok_or_else(|| ActionError::ExecutionFailed("no HID++ device".into()))?;
    tokio::task::spawn_blocking(move || {
        let mut m = manager
            .lock()
            .map_err(|_| ActionError::ExecutionFailed("device lock poisoned".into()))?;
        let (mode, auto_disengage, _) = m
            .get_smartshift()
            .ok_or_else(|| ActionError::ExecutionFailed("SmartShift not readable".into()))?;
        m.set_smartshift(next_wheel_mode(mode), auto_disengage, 0)
            .map_err(|e| ActionError::ExecutionFailed(e.to_string()))
    })
    .await
    .map_err(|e| ActionError::ExecutionFailed(e.to_string()))?
}

/// HID++ 0x2111 wheel mode: 1 = free-spin, 2 = ratchet.
fn next_wheel_mode(mode: u8) -> u8 {
    if mode == 1 {
        2
    } else {
        1
    }
}

/// A key chord as Settings records it: "+"-joined key names, nothing else.
pub fn is_shortcut_text(keys: &str) -> bool {
    !keys.is_empty()
        && keys.len() <= 64
        && keys.split('+').all(|k| !k.is_empty() && k.chars().all(|c| c.is_ascii_alphanumeric() || c == '_'))
}

/// Easy-Switch the mouse to host slot 1-3, or the next slot. Switching to
/// the slot the mouse is on already does nothing (the link would drop and
/// come back for no reason).
async fn switch_host(action: ButtonAction) -> Result<(), ActionError> {
    let manager = DEVICE
        .get()
        .cloned()
        .ok_or_else(|| ActionError::ExecutionFailed("no HID++ device".into()))?;
    tokio::task::spawn_blocking(move || {
        let mut m = manager
            .lock()
            .map_err(|_| ActionError::ExecutionFailed("device lock poisoned".into()))?;
        let (hosts, current) = m
            .get_easy_switch_info()
            .ok_or_else(|| ActionError::ExecutionFailed("Easy-Switch not readable".into()))?;
        let target = match target_host(action, hosts, current) {
            Some(t) => t,
            None => return Ok(()),
        };
        m.set_current_host(target).map_err(ActionError::ExecutionFailed)?;
        crate::link_state::report(crate::link_state::LinkState::Away, None);
        Ok(())
    })
    .await
    .map_err(|e| ActionError::ExecutionFailed(e.to_string()))?
}

/// 0-based slot a host action switches to; None when it is the current slot
/// or outside the slots the mouse has.
fn target_host(action: ButtonAction, hosts: u8, current: u8) -> Option<u8> {
    let hosts = hosts.clamp(1, 3);
    let target = match action {
        ButtonAction::Host1 => 0,
        ButtonAction::Host2 => 1,
        ButtonAction::Host3 => 2,
        ButtonAction::HostNext => (current + 1) % hosts,
        _ => return None,
    };
    (target < hosts && target != current).then_some(target)
}

/// DPI step for DPI up / down, and the sensor range used when the mouse does
/// not report one (MX Master 4: 200 to 8000).
const DPI_STEP: u16 = 200;
const DPI_RANGE_FALLBACK: (u16, u16) = (200, 8000);

/// Where a DPI action lands from `current`: the next preset (wrapping), or
/// one step up or down inside the sensor range.
pub fn next_dpi(action: ButtonAction, current: u16, presets: &[u16], range: (u16, u16)) -> Option<u16> {
    let (lo, hi) = range;
    match action {
        ButtonAction::DpiUp => Some(current.saturating_add(DPI_STEP).clamp(lo, hi)),
        ButtonAction::DpiDown => Some(current.saturating_sub(DPI_STEP).clamp(lo, hi)),
        ButtonAction::DpiCycle => {
            let mut p: Vec<u16> = presets.iter().copied().filter(|d| (lo..=hi).contains(d)).collect();
            p.sort_unstable();
            p.dedup();
            p.iter().copied().find(|&d| d > current).or_else(|| p.first().copied())
        }
        _ => None,
    }
}

/// Read the mouse's DPI and sensor range (lowest, highest).
pub async fn read_dpi() -> Option<(u16, (u16, u16))> {
    let manager = DEVICE.get().cloned()?;
    tokio::task::spawn_blocking(move || {
        let mut m = manager.lock().ok()?;
        let dpi = m.get_dpi()?;
        let range = m.dpi_caps().map_or(DPI_RANGE_FALLBACK, |c| (c.min, c.max));
        Some((dpi, range))
    })
    .await
    .ok()
    .flatten()
}

/// Write a DPI to the mouse (DPI button actions).
pub async fn write_dpi(dpi: u16) -> Result<(), ActionError> {
    let manager = DEVICE
        .get()
        .cloned()
        .ok_or_else(|| ActionError::ExecutionFailed("no HID++ device".into()))?;
    tokio::task::spawn_blocking(move || {
        manager
            .lock()
            .map_err(|_| ActionError::ExecutionFailed("device lock poisoned".into()))?
            .set_dpi(dpi)
            .map_err(|e| ActionError::ExecutionFailed(e.to_string()))
    })
    .await
    .map_err(|e| ActionError::ExecutionFailed(e.to_string()))?
}

/// Press (`down`) or release the keys of a shortcut: hold-while-pressed
/// custom actions (push-to-talk). Modifiers go down first and come up last.
pub fn shortcut_edge(keys: &str, down: bool) -> Result<(), ActionError> {
    let codes = ActionExecutor::shortcut_to_evdev_codes(keys);
    let (program, args) = match (is_wayland_session(), codes) {
        (true, Some(codes)) => ("ydotool", ydotool_edge_args(&codes, down)),
        _ => ("xdotool", vec![if down { "keydown" } else { "keyup" }.to_string(), keys.to_string()]),
    };
    let mut cmd = Command::new(program);
    cmd.args(&args);
    apply_session_env(&mut cmd);
    let child = cmd
        .spawn()
        .map_err(|e| ActionError::ExecutionFailed(format!("{program} failed: {e}")))?;
    reap_in_background(child, keys, program);
    Ok(())
}

fn ydotool_edge_args(codes: &[u16], down: bool) -> Vec<String> {
    let mut args = vec!["key".to_string()];
    if down {
        args.extend(codes.iter().map(|c| format!("{c}:1")));
    } else {
        args.extend(codes.iter().rev().map(|c| format!("{c}:0")));
    }
    args
}

/// Paste `text` into the focused window through the clipboard, then press
/// Enter when asked. Layout-safe: typing through uinput maps characters through
/// the keyboard layout and mangles / " @ on many layouts.
pub async fn paste_text(text: &str, paste_with: &str, enter: bool) -> Result<(), ActionError> {
    use std::io::Write;
    let (program, args): (&str, &[&str]) = if is_wayland_session() {
        ("wl-copy", &[])
    } else {
        ("xclip", &["-selection", "clipboard"])
    };
    let mut cmd = Command::new(program);
    cmd.args(args).stdin(std::process::Stdio::piped());
    apply_session_env(&mut cmd);
    let mut child = cmd
        .spawn()
        .map_err(|e| ActionError::ExecutionFailed(format!("{program} failed: {e}")))?;
    if let Some(mut stdin) = child.stdin.take() {
        stdin
            .write_all(text.as_bytes())
            .map_err(|e| ActionError::ExecutionFailed(format!("{program} failed: {e}")))?;
    }
    // Both tools fork a selection owner and exit once the clipboard is set.
    let copied = tokio::task::spawn_blocking(move || child.wait())
        .await
        .map_err(|e| ActionError::ExecutionFailed(e.to_string()))?
        .map_err(|e| ActionError::ExecutionFailed(e.to_string()))?;
    if !copied.success() {
        return Err(ActionError::ExecutionFailed(format!("{program} could not set the clipboard")));
    }
    let chord = if paste_with.trim().is_empty() { "ctrl+v" } else { paste_with.trim() };
    ActionExecutor::execute_shortcut(chord, 1).await?;
    if enter {
        // Let the target take the paste before the Enter arrives.
        tokio::time::sleep(Duration::from_millis(120)).await;
        ActionExecutor::execute_shortcut("Return", 1).await?;
    }
    Ok(())
}

/// Open a web or mail link in the user's browser (custom button action).
/// Only http, https and mailto: the value comes from config.json.
pub fn open_url(url: &str) -> Result<(), ActionError> {
    let lower = url.to_ascii_lowercase();
    if !(lower.starts_with("https://") || lower.starts_with("http://") || lower.starts_with("mailto:")) {
        return Err(ActionError::ExecutionFailed(format!("not a web link: {url}")));
    }
    spawn_for_user("xdg-open", &[url])
        .map_err(|e| ActionError::ExecutionFailed(format!("xdg-open failed: {e}")))
}

/// A mouse button the daemon can click on the user's behalf.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MouseButton {
    Left,
    Right,
    Middle,
    Back,
    Forward,
}

impl MouseButton {
    /// `ydotool click` code: button index | 0x40 down | 0x80 up. Back and
    /// Forward are SIDE (BTN_SIDE) and EXTR (BTN_EXTRA), what a physical MX
    /// mouse sends and what browsers map to history back/forward.
    fn ydotool_code(self) -> &'static str {
        match self {
            MouseButton::Left => "0xC0",
            MouseButton::Right => "0xC1",
            MouseButton::Middle => "0xC2",
            MouseButton::Back => "0xC3",
            MouseButton::Forward => "0xC4",
        }
    }

    /// X11 core button number for `xdotool click`.
    fn xdotool_button(self) -> &'static str {
        match self {
            MouseButton::Left => "1",
            MouseButton::Middle => "2",
            MouseButton::Right => "3",
            MouseButton::Back => "8",
            MouseButton::Forward => "9",
        }
    }
}

/// Click a real mouse button: uinput (ydotool) on Wayland, where X11
/// synthesis never reaches native windows; xdotool on X11 or as fallback.
pub fn click_mouse_button(button: MouseButton) -> Result<(), ActionError> {
    let wayland = session_var("WAYLAND_DISPLAY").is_some()
        || session_var("XDG_SESSION_TYPE")
            .map(|s| s.eq_ignore_ascii_case("wayland"))
            .unwrap_or(false);
    if wayland {
        if let Ok(child) = Command::new("ydotool")
            .args(["click", button.ydotool_code()])
            .spawn()
        {
            reap_in_background(child, button.ydotool_code(), "ydotool");
            return Ok(());
        }
        tracing::warn!(?button, "ydotool click failed; trying xdotool");
    }
    let mut cmd = Command::new("xdotool");
    cmd.args(["click", button.xdotool_button()]);
    apply_session_env(&mut cmd);
    match cmd.spawn() {
        Ok(child) => {
            reap_in_background(child, button.xdotool_button(), "xdotool");
            Ok(())
        }
        Err(e) => Err(ActionError::ExecutionFailed(format!("mouse click failed: {e}"))),
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
            toggle_wheel_mode().await?;
            Ok(true)
        }
        // Real mouse buttons, not key chords: apps that listen for BTN_SIDE
        // (file managers, games, CAD) never saw alt+Left, and xdotool key
        // button2 was not a middle click at all (audit P0 #4).
        ButtonAction::MiddleClick => {
            click_mouse_button(MouseButton::Middle)?;
            Ok(true)
        }
        ButtonAction::Back => {
            click_mouse_button(MouseButton::Back)?;
            Ok(true)
        }
        ButtonAction::Forward => {
            click_mouse_button(MouseButton::Forward)?;
            Ok(true)
        }
        ButtonAction::LeftClick => {
            click_mouse_button(MouseButton::Left)?;
            Ok(true)
        }
        ButtonAction::RightClick => {
            click_mouse_button(MouseButton::Right)?;
            Ok(true)
        }
        ButtonAction::ScrollLeft | ButtonAction::ScrollRight => {
            execute_horizontal_scroll(if action == ButtonAction::ScrollRight { 1 } else { -1 }).await?;
            Ok(true)
        }
        ButtonAction::Host1 | ButtonAction::Host2 | ButtonAction::Host3 | ButtonAction::HostNext => {
            switch_host(action).await?;
            Ok(true)
        }
        // Need the slot (custom) or daemon state (DPI, gaming mode): the
        // event loop in main.rs runs these before calling here.
        ButtonAction::Custom
        | ButtonAction::DpiCycle
        | ButtonAction::DpiUp
        | ButtonAction::DpiDown
        | ButtonAction::DpiShift
        | ButtonAction::GamingMode => {
            tracing::warn!(%action, "Action needs the daemon event loop; ignored here");
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

/// Execute a button action repeatedly. Shortcut-backed actions (including every
/// diverted ThumbWheel button output) are synthesized by a single helper
/// process; other action kinds preserve their existing per-execution behavior.
pub async fn execute_button_action_repeated(
    action: ButtonAction,
    repeats: u8,
) -> Result<bool, ActionError> {
    if repeats == 0 {
        return Ok(true);
    }
    if repeats == 1 {
        return execute_button_action(action).await;
    }

    let shortcut = match action {
        ButtonAction::ZoomIn | ButtonAction::ZoomOut => {
            Some(zoom_shortcut(matches!(action, ButtonAction::ZoomIn)))
        }
        _ => button_action_to_shortcut(action),
    };
    if let Some(keys) = shortcut {
        ActionExecutor::execute_shortcut(keys, repeats).await?;
        return Ok(true);
    }

    let mut handled = true;
    for _ in 0..repeats {
        handled &= execute_button_action(action).await?;
    }
    Ok(handled)
}

/// Build one xdotool command for a complete horizontal-scroll burst.
fn xdotool_horizontal_scroll_args(clicks: i32) -> Option<Vec<String>> {
    let count = clicks.unsigned_abs().min(16);
    if count == 0 {
        return None;
    }
    let button = if clicks > 0 { "7" } else { "6" };
    Some(vec![
        "click".to_string(),
        "--repeat".to_string(),
        count.to_string(),
        "--delay".to_string(),
        "0".to_string(),
        button.to_string(),
    ])
}

/// Build one ydotool command for a complete horizontal-scroll burst.
///
/// ydotool's `click` IDs 0x06/0x07 are BACK/TASK buttons, not wheel directions.
/// Its `mousemove --wheel -- X Y` form emits X as one signed REL_HWHEEL value
/// and Y as REL_WHEEL, so the signed magnitude carries the complete burst in a
/// single process without a shell.
fn ydotool_horizontal_scroll_args(clicks: i32) -> Option<Vec<String>> {
    let horizontal = clicks.clamp(-16, 16);
    if horizontal == 0 {
        return None;
    }
    Some(vec![
        "mousemove".to_string(),
        "--wheel".to_string(),
        "--".to_string(),
        horizontal.to_string(),
        "0".to_string(),
    ])
}

/// Inject horizontal scroll clicks for the diverted thumb wheel.
///
/// Positive `clicks` scroll right, negative scroll left. Horizontal scroll on
/// X11 is mouse buttons 6 (left) and 7 (right); xdotool synthesizes these
/// directly, with ydotool as a Wayland fallback (consistent with the keyboard
/// shortcut path). Non-blocking: the complete burst is spawned once and reaped
/// in the background.
pub async fn execute_horizontal_scroll(clicks: i32) -> Result<(), ActionError> {
    let Some(args) = xdotool_horizontal_scroll_args(clicks) else {
        return Ok(());
    };
    let count = clicks.unsigned_abs().min(16);
    let input = format!("horizontal scroll x{count}");

    let mut cmd = Command::new("xdotool");
    cmd.args(&args);
    // Same hole as the shortcut path: without the session environment xdotool
    // dies on an empty DISPLAY and the click is lost (issue #60).
    apply_session_env(&mut cmd);
    match cmd.spawn() {
        Ok(child) => reap_in_background(child, &input, "xdotool"),
        Err(e) => {
            tracing::debug!("xdotool horizontal scroll failed: {}, trying ydotool", e);
            let yd_args = ydotool_horizontal_scroll_args(clicks)
                .expect("non-zero clicks always produce ydotool arguments");
            match Command::new("ydotool").args(&yd_args).spawn() {
                Ok(child) => reap_in_background(child, &input, "ydotool"),
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
        // Clicked as real mouse buttons in execute_button_action.
        ButtonAction::MiddleClick | ButtonAction::Back | ButtonAction::Forward => None,
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
        ButtonAction::TabNext => Some("ctrl+Tab"),
        ButtonAction::TabPrev => Some("ctrl+shift+Tab"),
        ButtonAction::TabClose => Some("ctrl+w"),
        ButtonAction::TabReopen => Some("ctrl+shift+t"),
        ButtonAction::PageUp => Some("Page_Up"),
        ButtonAction::PageDown => Some("Page_Down"),
        ButtonAction::Home => Some("Home"),
        ButtonAction::End => Some("End"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {

    #[test]
    fn host_actions_pick_the_slot_and_skip_the_current_one() {
        assert_eq!(target_host(ButtonAction::Host2, 3, 0), Some(1));
        assert_eq!(target_host(ButtonAction::Host1, 3, 0), None);
        assert_eq!(target_host(ButtonAction::HostNext, 3, 2), Some(0));
        assert_eq!(target_host(ButtonAction::HostNext, 3, 0), Some(1));
        assert_eq!(target_host(ButtonAction::Host3, 2, 0), None);
        assert_eq!(target_host(ButtonAction::Copy, 3, 0), None);
    }

    #[test]
    fn dpi_actions_step_within_range_and_cycle_presets() {
        let range = (200, 8000);
        assert_eq!(next_dpi(ButtonAction::DpiUp, 1600, &[], range), Some(1800));
        assert_eq!(next_dpi(ButtonAction::DpiUp, 7900, &[], range), Some(8000));
        assert_eq!(next_dpi(ButtonAction::DpiDown, 300, &[], range), Some(200));
        let presets = [3200, 800, 1600, 60_000];
        assert_eq!(next_dpi(ButtonAction::DpiCycle, 800, &presets, range), Some(1600));
        assert_eq!(next_dpi(ButtonAction::DpiCycle, 1000, &presets, range), Some(1600));
        assert_eq!(next_dpi(ButtonAction::DpiCycle, 3200, &presets, range), Some(800));
        assert_eq!(next_dpi(ButtonAction::DpiCycle, 800, &[], range), None);
        assert_eq!(next_dpi(ButtonAction::Copy, 800, &presets, range), None);
    }

    #[test]
    fn recorder_keys_have_evdev_codes() {
        for keys in ["ctrl+Page_Up", "Page_Down", "shift+F13", "F24", "Insert", "ctrl+alt+Print",
                     "super+comma", "ctrl+BackSpace", "Home", "End"] {
            assert!(ActionExecutor::shortcut_to_evdev_codes(keys).is_some(), "{keys}");
        }
        assert_eq!(ActionExecutor::shortcut_to_evdev_codes("F13"), Some(vec![183]));
        assert_eq!(ActionExecutor::shortcut_to_evdev_codes("ctrl+Page_Up"), Some(vec![29, 104]));
    }

    #[test]
    fn new_vocabulary_shortcuts() {
        assert_eq!(button_action_to_shortcut(ButtonAction::TabReopen), Some("ctrl+shift+t"));
        assert_eq!(button_action_to_shortcut(ButtonAction::PageDown), Some("Page_Down"));
        for a in [ButtonAction::TabNext, ButtonAction::TabPrev, ButtonAction::TabClose,
                  ButtonAction::PageUp, ButtonAction::Home, ButtonAction::End] {
            let keys = button_action_to_shortcut(a).unwrap();
            assert!(ActionExecutor::shortcut_to_evdev_codes(keys).is_some(), "{keys}");
        }
    }

    #[test]
    fn shortcut_text_is_key_names_only() {
        assert!(is_shortcut_text("ctrl+shift+Page_Up"));
        assert!(is_shortcut_text("XF86AudioPlay"));
        assert!(!is_shortcut_text(""));
        assert!(!is_shortcut_text("ctrl++"));
        assert!(!is_shortcut_text("ctrl+c; rm -rf ~"));
        assert!(!is_shortcut_text("--help"));
    }

    #[test]
    fn open_url_refuses_anything_but_web_and_mail_links() {
        assert!(open_url("file:///etc/passwd").is_err());
        assert!(open_url("javascript:alert(1)").is_err());
        assert!(open_url("--help").is_err());
    }

    #[test]
    fn mouse_button_codes_match_ydotool_and_x11() {
        assert_eq!(MouseButton::Middle.ydotool_code(), "0xC2");
        assert_eq!(MouseButton::Back.ydotool_code(), "0xC3"); // BTN_SIDE
        assert_eq!(MouseButton::Forward.ydotool_code(), "0xC4"); // BTN_EXTRA
        assert_eq!(MouseButton::Middle.xdotool_button(), "2");
        assert_eq!(MouseButton::Back.xdotool_button(), "8");
        assert_eq!(MouseButton::Forward.xdotool_button(), "9");
    }

    #[test]
    fn remapped_mouse_buttons_are_not_key_chords() {
        for action in [ButtonAction::MiddleClick, ButtonAction::Back, ButtonAction::Forward] {
            assert_eq!(button_action_to_shortcut(action), None, "{action}");
        }
    }

    #[test]
    fn wheel_mode_toggle_flips_ratchet_and_free_spin() {
        assert_eq!(next_wheel_mode(1), 2);
        assert_eq!(next_wheel_mode(2), 1);
    }

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
    #[test]
    fn held_shortcuts_press_in_order_and_release_in_reverse() {
        let codes = ActionExecutor::shortcut_to_evdev_codes("ctrl+shift+v").unwrap();
        assert_eq!(ydotool_edge_args(&codes, true), ["key", "29:1", "42:1", "47:1"]);
        assert_eq!(ydotool_edge_args(&codes, false), ["key", "47:0", "42:0", "29:0"]);
        assert_eq!(ActionExecutor::shortcut_to_evdev_codes("Return").unwrap(), [28]);
        // Blender's numpad views reach native Wayland windows through uinput too.
        assert_eq!(ActionExecutor::shortcut_to_evdev_codes("ctrl+KP_7").unwrap(), [29, 71]);
        assert_eq!(ActionExecutor::shortcut_to_evdev_codes("KP_Decimal").unwrap(), [83]);
    }

    #[test]
    fn user_programs_run_as_their_own_user_service() {
        let args = transient_service_args(
            "sh",
            &["-c".to_string(), "code ~/notes".to_string()],
            &[("WAYLAND_DISPLAY", "wayland-0".to_string()), ("PATH", "/usr/bin:/bin".to_string())],
        );
        assert_eq!(
            args,
            [
                "--user", "--quiet", "--collect", "--property=KillMode=process",
                "--setenv=WAYLAND_DISPLAY=wayland-0", "--setenv=PATH=/usr/bin:/bin",
                "--", "sh", "-c", "code ~/notes",
            ]
        );
    }

    #[test]
    fn repeated_shortcuts_use_one_batched_helper_argument_vector() {
        assert_eq!(
            ActionExecutor::xdotool_shortcut_args("XF86AudioRaiseVolume", 4),
            ["key", "--repeat", "4", "XF86AudioRaiseVolume"]
        );
        assert_eq!(
            ActionExecutor::xdotool_shortcut_args("ctrl+c", 1),
            ["key", "ctrl+c"]
        );

        assert_eq!(
            ActionExecutor::ydotool_shortcut_args(&[29, 78], 3),
            [
                "key", "29:1", "78:1", "78:0", "29:0", "29:1", "78:1", "78:0", "29:0", "29:1",
                "78:1", "78:0", "29:0",
            ]
        );
    }

    /// Interpret the documented ydotool `mousemove --wheel -- X Y` grammar:
    /// X is REL_HWHEEL and Y is REL_WHEEL. Keeping this decoder in the test
    /// makes the assertion about emitted wheel motion rather than duplicating
    /// the production argument constants.
    fn ydotool_wheel_delta(args: &[String]) -> Option<(i32, i32)> {
        let [subcommand, wheel, separator, horizontal, vertical] = args else {
            return None;
        };
        if subcommand != "mousemove" || (wheel != "--wheel" && wheel != "-w") || separator != "--" {
            return None;
        }
        Some((horizontal.parse().ok()?, vertical.parse().ok()?))
    }

    #[test]
    fn horizontal_scroll_uses_one_batched_helper_with_real_wheel_semantics() {
        assert_eq!(
            xdotool_horizontal_scroll_args(5).unwrap(),
            ["click", "--repeat", "5", "--delay", "0", "7"]
        );
        assert_eq!(
            xdotool_horizontal_scroll_args(i32::MAX).unwrap(),
            ["click", "--repeat", "16", "--delay", "0", "7"]
        );

        let right = ydotool_horizontal_scroll_args(5).unwrap();
        let left = ydotool_horizontal_scroll_args(-5).unwrap();
        let clamped = ydotool_horizontal_scroll_args(i32::MIN).unwrap();
        assert_eq!(ydotool_wheel_delta(&right), Some((5, 0)), "{right:?}");
        assert_eq!(ydotool_wheel_delta(&left), Some((-5, 0)), "{left:?}");
        assert_eq!(ydotool_wheel_delta(&clamped), Some((-16, 0)), "{clamped:?}");

        // ydotool click IDs 0x06/0x07 are BACK/TASK buttons. Without the
        // 0x40/0x80 press/release bits they do nothing, and even complete
        // clicks would still be buttons rather than REL_HWHEEL movement.
        let invalid_button_click = ["click", "--repeat=5", "0x06"].map(String::from);
        assert_eq!(ydotool_wheel_delta(&invalid_button_click), None);

        assert!(xdotool_horizontal_scroll_args(0).is_none());
        assert!(ydotool_horizontal_scroll_args(0).is_none());
    }


}
