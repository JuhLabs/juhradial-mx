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
//! - **X11 / other**: watches `_NET_ACTIVE_WINDOW` with `xprop -spy`, then reads
//!   `WM_CLASS` when focus changes.
//!
//! Non-KDE sources push classes straight into the channel; KDE pushes via the
//! D-Bus method (which forwards into the same channel).
//!
//! SPDX-License-Identifier: GPL-3.0

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader as AsyncBufReader};
use tokio::process::{Child, ChildStdout, Command as AsyncCommand};
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
        matches!(self.de, "kde" | "hyprland") || crate::actions::session_var("DISPLAY").is_some()
    }

    /// Run the tracker until `tx` is closed. Pushes each newly focused window's
    /// lowercased resource class into `tx`.
    ///
    /// KDE installs the persistent KWin script (which feeds `ReportActiveWindow`
    /// → the same `tx`), so this returns once the script is installed. Hyprland
    /// runs its loop on the blocking pool; X11 uses an async `xprop -spy`
    /// subprocess so it can stop the child promptly when the channel closes.
    pub async fn watch(self, tx: UnboundedSender<String>) {
        match self.de {
            "kde" => {
                // install_kwin_script blocks on two dbus-send calls; keep them
                // off the async worker this future runs on.
                let installed = tokio::task::spawn_blocking(|| {
                    install_kwin_script(KWIN_ACTIVE_WINDOW_SCRIPT)
                })
                .await
                .unwrap_or(false);
                if installed {
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
                x11_watch_loop(tx).await;
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
    // session_var, like detect_desktop: the branch that lands here is picked
    // from the session environment, so the signature has to come from the same
    // place or the Hyprland arm resolves to nothing and tracking stops dead.
    let sig = crate::actions::session_var("HYPRLAND_INSTANCE_SIGNATURE")?;
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

const XPROP_RESTART_DELAY: Duration = Duration::from_secs(2);
const XPROP_QUERY_TIMEOUT: Duration = Duration::from_secs(2);
const XPROP_CLASS_OUTPUT_LIMIT: usize = 16 * 1024;

/// Watch the X11 root window for focus changes with one persistent `xprop -spy`
/// process. The watcher is restarted with a bounded delay after EOF or failure,
/// and is explicitly killed and reaped when the receiver closes.
async fn x11_watch_loop(tx: UnboundedSender<String>) {
    x11_watch_loop_with_program(tx, PathBuf::from("xprop"), XPROP_RESTART_DELAY).await;
}

async fn x11_watch_loop_with_program(
    tx: UnboundedSender<String>,
    xprop_program: PathBuf,
    restart_delay: Duration,
) {
    let mut last_class = String::new();
    let mut last_active_id = None;

    loop {
        if tx.is_closed() {
            return;
        }

        let mut command = AsyncCommand::new(&xprop_program);
        command
            .args(["-root", "-spy", "_NET_ACTIVE_WINDOW"])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);

        match command.spawn() {
            Ok(mut child) => {
                let Some(stdout) = child.stdout.take() else {
                    tracing::warn!("xprop watcher stdout unavailable; retrying");
                    stop_child(&mut child).await;
                    if wait_for_retry_or_close(&tx, restart_delay).await {
                        return;
                    }
                    continue;
                };

                tracing::debug!("Started X11 active-window watcher with xprop -spy");
                let mut lines = AsyncBufReader::new(stdout).lines();

                loop {
                    let line = tokio::select! {
                        _ = tx.closed() => {
                            stop_child(&mut child).await;
                            return;
                        }
                        line = lines.next_line() => line,
                    };

                    let line = match line {
                        Ok(Some(line)) => line,
                        Ok(None) => {
                            tracing::debug!("xprop watcher reached EOF; retrying");
                            break;
                        }
                        Err(error) => {
                            tracing::debug!(%error, "Failed to read xprop watcher output; retrying");
                            break;
                        }
                    };

                    let Some(win_id) = parse_active_window_id(&line) else {
                        tracing::debug!(line = %line, "Ignoring malformed xprop active-window line");
                        continue;
                    };

                    if last_active_id == Some(win_id) {
                        continue;
                    }
                    // A null focus is a successful transition by itself and
                    // resets deduplication so the previous window is queried if
                    // it becomes active again.
                    if win_id == 0 {
                        last_active_id = Some(0);
                        continue;
                    }
                    let win_id_arg = format!("0x{win_id:x}");

                    let class = x11_window_class(&xprop_program, &win_id_arg, &tx).await;
                    if tx.is_closed() {
                        stop_child(&mut child).await;
                        return;
                    }

                    if let Some(class) = class {
                        // Cache nonzero IDs only after WM_CLASS succeeds. A
                        // transient failure must leave the same ID retryable,
                        // including when the spy process restarts.
                        last_active_id = Some(win_id);
                        if class == last_class {
                            continue;
                        }
                        last_class = class.clone();
                        if tx.send(class).is_err() {
                            stop_child(&mut child).await;
                            return;
                        }
                    }
                }

                // EOF normally means xprop exited. If it only closed stdout,
                // stop it rather than waiting forever and blocking the restart.
                stop_child(&mut child).await;
            }
            Err(error) => {
                tracing::debug!(%error, "Failed to start xprop watcher; retrying");
            }
        }

        if wait_for_retry_or_close(&tx, restart_delay).await {
            return;
        }
    }
}

async fn wait_for_retry_or_close(tx: &UnboundedSender<String>, delay: Duration) -> bool {
    tokio::select! {
        _ = tx.closed() => true,
        _ = tokio::time::sleep(delay) => false,
    }
}

async fn stop_child(child: &mut Child) {
    match child.try_wait() {
        Ok(Some(_)) => return,
        Ok(None) => {}
        Err(error) => tracing::debug!(%error, "Failed to inspect xprop process before shutdown"),
    }

    if let Err(error) = child.start_kill() {
        tracing::debug!(%error, "Failed to stop xprop process");
    }
    if let Err(error) = child.wait().await {
        tracing::debug!(%error, "Failed to reap stopped xprop process");
    }
}

/// Extract a syntactically valid X11 window ID from an `_NET_ACTIVE_WINDOW` line.
/// Zero is retained as a focus transition, but is never queried for `WM_CLASS`.
fn parse_active_window_id(text: &str) -> Option<u64> {
    let win_id = text.split_whitespace().last()?;
    let hex = win_id.strip_prefix("0x")?;
    if hex.is_empty() || hex.chars().any(|c| !c.is_ascii_hexdigit()) {
        return None;
    }
    u64::from_str_radix(hex, 16).ok()
}

/// Query a focused window's WM_CLASS via xprop. Returns the lowercased class.
/// The helper is explicitly killed and reaped on timeout or receiver closure so
/// cancelling the watcher cannot leave a zombie behind.
async fn x11_window_class(
    xprop_program: &Path,
    win_id: &str,
    tx: &UnboundedSender<String>,
) -> Option<String> {
    let mut command = AsyncCommand::new(xprop_program);
    command
        .args(["-id", win_id, "WM_CLASS"])
        .stdout(Stdio::piped())
        // `Command::output` captured and discarded stderr. Keep it suppressed
        // without a second pipe that a noisy helper could fill and deadlock.
        .stderr(Stdio::null())
        .kill_on_drop(true);

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            tracing::debug!(%error, window_id = win_id, "Failed to query X11 WM_CLASS");
            return None;
        }
    };
    let Some(stdout) = child.stdout.take() else {
        tracing::debug!(window_id = win_id, "xprop WM_CLASS stdout unavailable");
        stop_child(&mut child).await;
        return None;
    };

    let query = async { tokio::join!(child.wait(), read_xprop_class_output(stdout)) };
    let (status, stdout) = match tokio::select! {
        _ = tx.closed() => None,
        result = tokio::time::timeout(XPROP_QUERY_TIMEOUT, query) => Some(result),
    } {
        None => {
            stop_child(&mut child).await;
            return None;
        }
        Some(Err(_)) => {
            tracing::debug!(window_id = win_id, "Timed out querying X11 WM_CLASS");
            stop_child(&mut child).await;
            return None;
        }
        Some(Ok(result)) => result,
    };

    let status = match status {
        Ok(status) => status,
        Err(error) => {
            tracing::debug!(%error, window_id = win_id, "Failed to wait for X11 WM_CLASS helper");
            stop_child(&mut child).await;
            return None;
        }
    };
    let stdout = match stdout {
        Ok(stdout) => stdout,
        Err(error) => {
            tracing::debug!(%error, window_id = win_id, "Failed to read X11 WM_CLASS output");
            return None;
        }
    };

    if !status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&stdout);
    parse_wm_class(&text)
}

/// Drain the helper's stdout to EOF while retaining only the small prefix that
/// can contain one WM_CLASS response. Draining prevents a full pipe from
/// blocking the child before `wait`, while the cap avoids unbounded allocation.
async fn read_xprop_class_output(mut stdout: ChildStdout) -> std::io::Result<Vec<u8>> {
    let mut output = Vec::with_capacity(256);
    let mut buffer = [0_u8; 1024];
    loop {
        let read = stdout.read(&mut buffer).await?;
        if read == 0 {
            break;
        }
        let retained = read.min(XPROP_CLASS_OUTPUT_LIMIT.saturating_sub(output.len()));
        output.extend_from_slice(&buffer[..retained]);
    }
    Ok(output)
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
    use std::fs;
    use std::os::unix::fs::PermissionsExt;

    static XPROP_TEST_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

    fn write_executable(path: &Path, contents: &str) {
        fs::write(path, contents).unwrap();
        let mut permissions = fs::metadata(path).unwrap().permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(path, permissions).unwrap();
    }

    async fn wait_for_log_lines(path: &Path, prefix: &str, count: usize) -> String {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let log = fs::read_to_string(path).unwrap_or_default();
                if log.lines().filter(|line| line.starts_with(prefix)).count() >= count {
                    return log;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("timed out waiting for fake xprop log")
    }

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
    fn parse_active_window_id_handles_valid_null_and_malformed_ids() {
        let line = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x1c00007";
        assert_eq!(parse_active_window_id(line), Some(0x1c00007));
        assert_eq!(
            parse_active_window_id("_NET_ACTIVE_WINDOW: not found."),
            None
        );
        assert_eq!(parse_active_window_id("window id # 0x0"), Some(0));
        assert_eq!(parse_active_window_id("window id # 0xnothex"), None);
    }

    #[tokio::test]
    async fn x11_window_class_reaps_helper_after_timeout() {
        let _guard = XPROP_TEST_LOCK.lock().await;
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("fake-xprop");
        let pid_path = temp.path().join("query.pid");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
if [ "$1" = "-id" ] && [ "$3" = "WM_CLASS" ]; then
    printf '%s\n' "$$" > '{}'
    exec sleep 3600
fi
exit 64
"#,
                pid_path.display()
            ),
        );

        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();
        assert_eq!(
            tokio::time::timeout(
                XPROP_QUERY_TIMEOUT + Duration::from_secs(2),
                x11_window_class(&script, "0x400001", &tx),
            )
            .await
            .expect("WM_CLASS query did not honor its timeout"),
            None
        );

        let query_pid = fs::read_to_string(&pid_path)
            .expect("fake xprop did not record its PID")
            .trim()
            .parse::<u32>()
            .unwrap();
        assert!(
            !PathBuf::from(format!("/proc/{query_pid}")).exists(),
            "timed-out WM_CLASS helper was not reaped"
        );
    }

    #[tokio::test]
    async fn x11_window_class_drains_large_success_output_before_waiting() {
        let _guard = XPROP_TEST_LOCK.lock().await;
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("fake-xprop");
        let pid_path = temp.path().join("query.pid");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
if [ "$1" = "-id" ] && [ "$3" = "WM_CLASS" ]; then
    printf '%s\n' "$$" > '{}'
    printf '%s\n' 'WM_CLASS(STRING) = "navigator", "Firefox"'
    payload='0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
    count=0
    while [ "$count" -lt 16384 ]; do
        printf '%s' "$payload"
        count=$((count + 1))
    done
    exit 0
fi
exit 64
"#,
                pid_path.display()
            ),
        );

        let (tx, _rx) = tokio::sync::mpsc::unbounded_channel();
        assert_eq!(
            tokio::time::timeout(
                XPROP_QUERY_TIMEOUT + Duration::from_secs(1),
                x11_window_class(&script, "0x400003", &tx),
            )
            .await
            .expect("successful WM_CLASS helper blocked while writing large stdout"),
            Some("firefox".to_string())
        );

        let query_pid = fs::read_to_string(&pid_path)
            .expect("fake xprop did not record its PID")
            .trim()
            .parse::<u32>()
            .unwrap();
        assert!(
            !PathBuf::from(format!("/proc/{query_pid}")).exists(),
            "successful large-output WM_CLASS helper was not reaped"
        );
    }

    #[tokio::test]
    async fn x11_window_class_reaps_blocked_helper_when_receiver_closes() {
        let _guard = XPROP_TEST_LOCK.lock().await;
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("fake-xprop");
        let log_path = temp.path().join("xprop.log");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
LOG='{}'
if [ "$1" = "-id" ] && [ "$3" = "WM_CLASS" ]; then
    printf 'query %s\n' "$$" >> "$LOG"
    exec sleep 3600
fi
exit 64
"#,
                log_path.display()
            ),
        );

        let (tx, rx) = tokio::sync::mpsc::unbounded_channel::<String>();
        let query = x11_window_class(&script, "0x400002", &tx);
        tokio::pin!(query);
        let log = tokio::select! {
            log = wait_for_log_lines(&log_path, "query ", 1) => log,
            class = &mut query => panic!("WM_CLASS helper exited before receiver close: {class:?}"),
        };
        let query_pid = log
            .lines()
            .find_map(|line| line.strip_prefix("query "))
            .unwrap()
            .parse::<u32>()
            .unwrap();

        drop(rx);
        assert_eq!(query.await, None);
        assert!(
            !PathBuf::from(format!("/proc/{query_pid}")).exists(),
            "receiver-close WM_CLASS helper was not reaped"
        );
    }

    #[tokio::test]
    async fn x11_watcher_deduplicates_active_ids_tracks_null_transition_and_stops_spy() {
        let _guard = XPROP_TEST_LOCK.lock().await;
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("fake-xprop");
        let log_path = temp.path().join("xprop.log");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
LOG='{}'
if [ "$1" = "-root" ] && [ "$2" = "-spy" ] && [ "$3" = "_NET_ACTIVE_WINDOW" ]; then
    printf 'spy %s\n' "$$" >> "$LOG"
    printf '%s\n' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x100001' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x100001' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x100002' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x100002' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x100003'
    exec sleep 3600
fi
if [ "$1" = "-id" ] && [ "$3" = "WM_CLASS" ]; then
    printf 'query %s\n' "$2" >> "$LOG"
    if [ "$2" = "0x100001" ]; then
        printf '%s\n' 'WM_CLASS(STRING) = "navigator", "Firefox"'
    else
        printf '%s\n' 'WM_CLASS(STRING) = "chromium", "Chromium"'
    fi
    exit 0
fi
exit 64
"#,
                log_path.display()
            ),
        );

        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
        let handle = tokio::spawn(x11_watch_loop_with_program(
            tx,
            script,
            Duration::from_millis(10),
        ));

        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), rx.recv())
                .await
                .unwrap(),
            Some("firefox".to_string())
        );
        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), rx.recv())
                .await
                .unwrap(),
            Some("chromium".to_string())
        );

        let log = wait_for_log_lines(&log_path, "query ", 4).await;
        assert_eq!(
            log.lines().filter(|line| line.starts_with("spy ")).count(),
            1
        );
        assert_eq!(
            log.lines()
                .filter(|line| line.starts_with("query "))
                .count(),
            4
        );
        assert_eq!(
            log.lines().filter(|line| *line == "query 0x100001").count(),
            1,
            "repeated identical active IDs must issue one WM_CLASS query"
        );
        assert_eq!(
            log.lines().filter(|line| *line == "query 0x100002").count(),
            2,
            "0x0 must reset active-ID deduplication before the window returns"
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(100), rx.recv())
                .await
                .is_err(),
            "unchanged WM_CLASS should not be sent twice"
        );

        let spy_pid = log
            .lines()
            .find_map(|line| line.strip_prefix("spy "))
            .unwrap()
            .parse::<u32>()
            .unwrap();
        drop(rx);
        tokio::time::timeout(Duration::from_secs(2), handle)
            .await
            .expect("watcher did not stop after receiver closed")
            .unwrap();
        assert!(
            !PathBuf::from(format!("/proc/{spy_pid}")).exists(),
            "xprop -spy process was not reaped"
        );
    }

    #[tokio::test]
    async fn x11_watcher_retries_same_active_id_after_transient_class_query_failure() {
        let _guard = XPROP_TEST_LOCK.lock().await;
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("fake-xprop");
        let log_path = temp.path().join("xprop.log");
        let query_count_path = temp.path().join("query-count");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
LOG='{}'
QUERY_COUNT='{}'
if [ "$1" = "-root" ] && [ "$2" = "-spy" ] && [ "$3" = "_NET_ACTIVE_WINDOW" ]; then
    printf 'spy %s\n' "$$" >> "$LOG"
    printf '%s\n' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x300001' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x300001' \
        '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x300001'
    exec sleep 3600
fi
if [ "$1" = "-id" ] && [ "$3" = "WM_CLASS" ]; then
    printf 'query %s\n' "$2" >> "$LOG"
    count=$(cat "$QUERY_COUNT" 2>/dev/null || printf '0')
    count=$((count + 1))
    printf '%s' "$count" > "$QUERY_COUNT"
    if [ "$count" -eq 1 ]; then
        exit 1
    fi
    printf '%s\n' 'WM_CLASS(STRING) = "code", "Code"'
    exit 0
fi
exit 64
"#,
                log_path.display(),
                query_count_path.display()
            ),
        );

        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
        let handle = tokio::spawn(x11_watch_loop_with_program(
            tx,
            script,
            Duration::from_millis(10),
        ));

        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), rx.recv())
                .await
                .expect("same-ID retry did not recover after transient WM_CLASS failure"),
            Some("code".to_string())
        );

        let log = wait_for_log_lines(&log_path, "query ", 2).await;
        assert_eq!(
            log.lines().filter(|line| *line == "query 0x300001").count(),
            2,
            "the failed query must be retried once, then the successful ID must dedupe"
        );
        assert!(
            tokio::time::timeout(Duration::from_millis(100), rx.recv())
                .await
                .is_err(),
            "the duplicate after a successful query must not emit again"
        );

        let spy_pid = log
            .lines()
            .find_map(|line| line.strip_prefix("spy "))
            .unwrap()
            .parse::<u32>()
            .unwrap();
        drop(rx);
        tokio::time::timeout(Duration::from_secs(2), handle)
            .await
            .expect("watcher did not stop after receiver closed")
            .unwrap();
        assert!(
            !PathBuf::from(format!("/proc/{spy_pid}")).exists(),
            "xprop -spy process was not reaped"
        );
    }

    #[tokio::test]
    async fn x11_watcher_restarts_after_spy_eof() {
        let _guard = XPROP_TEST_LOCK.lock().await;
        let temp = tempfile::tempdir().unwrap();
        let script = temp.path().join("fake-xprop");
        let log_path = temp.path().join("xprop.log");
        write_executable(
            &script,
            &format!(
                r#"#!/bin/sh
LOG='{}'
if [ "$1" = "-root" ] && [ "$2" = "-spy" ]; then
    printf 'spy %s\n' "$$" >> "$LOG"
    printf '%s\n' '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x200001'
    exit 0
fi
if [ "$1" = "-id" ]; then
    printf '%s\n' 'WM_CLASS(STRING) = "terminal", "Konsole"'
    exit 0
fi
exit 64
"#,
                log_path.display()
            ),
        );

        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();
        let handle = tokio::spawn(x11_watch_loop_with_program(
            tx,
            script,
            Duration::from_millis(10),
        ));

        assert_eq!(
            tokio::time::timeout(Duration::from_secs(2), rx.recv())
                .await
                .unwrap(),
            Some("konsole".to_string())
        );
        let log = wait_for_log_lines(&log_path, "spy ", 2).await;
        assert!(log.lines().filter(|line| line.starts_with("spy ")).count() >= 2);

        drop(rx);
        tokio::time::timeout(Duration::from_secs(2), handle)
            .await
            .expect("watcher did not stop during restart cycle")
            .unwrap();
    }

    #[test]
    fn hyprland_activewindow_line_parses() {
        let line = "activewindow>>firefox,Mozilla Firefox";
        let rest = line.strip_prefix("activewindow>>").unwrap();
        let class = rest.split(',').next().unwrap().trim().to_lowercase();
        assert_eq!(class, "firefox");
    }
}
