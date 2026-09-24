//! JuhRadial MX Daemon
//!
//! A daemon for Linux that provides radial menu functionality for the
//! Logitech MX Master 4 mouse via evdev input and KWin overlay.

use clap::Parser;
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::Instant;
use tokio::sync::mpsc;
use tokio::time::{Duration, sleep};
use tracing::{Level, debug, error, info, warn};
use tracing_subscriber::FmtSubscriber;

use juhradiald::{
    battery::{new_shared_state, start_battery_updater_shared, SharedBatteryState},
    config::load_shared_config,
    dbus::{DBUS_NAME, DBUS_PATH, SharedDeviceName, claim_name, init_dbus_service_with_device},
    evdev::{EvdevError, EvdevHandler, GestureEvent},
    gaming::{new_shared_gaming_mode, AutoSource},
    hidpp::{HapticEvent, SharedHapticManager},
    hidraw::{HidrawError, HidrawHandler},
    macros::{MacroEngine, MacroRecorder, TriggerMap},
    new_shared_haptic_manager,
    profiles::{ProfileManager, SharedHardwareProfiles},
    window_tracker::{tracker_decision, TrackerDecision, WindowTracker},
};

use std::collections::HashMap;
use std::sync::{Arc, Mutex, RwLock};

/// Fallback poll interval when no device is found (60 seconds).
///
/// The inotify hotplug watcher on `/dev/input/` wakes the loops the instant a
/// new event* device appears, so the timer is purely a safety net for hotplug
/// failure modes. The previous 2-second cadence opened every evdev node on
/// every tick (including the MX mouse currently streaming events through
/// another task), causing visible cursor stutter every 2 seconds. 60 seconds
/// matches the cost of a missed hotplug, barely perceptible, without
/// generating periodic contention on active input devices.
const DEVICE_POLL_INTERVAL_SECS: u64 = 60;

/// Poll interval while the HID++ listener is disconnected.
///
/// This path only runs after the listener has lost the mouse or before it has
/// found one, so a shorter cadence does not reintroduce the steady-state evdev
/// scanning stutter that `DEVICE_POLL_INTERVAL_SECS` avoids.
const HIDRAW_RECONNECT_POLL_INTERVAL_SECS: u64 = 5;

/// How long the daemon keeps waiting for the desktop session to export its
/// environment before giving up on window tracking. Plasma on a slow boot
/// has been seen to take tens of seconds after the unit starts.
const WINDOW_TRACKER_WAIT: Duration = Duration::from_secs(180);

/// Emit monotonic checkpoints so cold-start latency can be attributed to a
/// concrete phase instead of inferring it from process activation.
fn log_startup_phase(started_at: &Instant, phase: &'static str) {
    info!(
        phase,
        elapsed_ms = started_at.elapsed().as_millis() as u64,
        "Startup phase completed"
    );
}

/// Decide whether a /dev/input hotplug event was caused by the daemon's own
/// button-suppression virtual device, updating `own_vdev_paths` as vdev nodes
/// come and go. `name_of` resolves an event node to its kernel device name
/// (sysfs in production, injected for tests).
///
/// Why this exists (issues #121/#125): the suppression vdev is created on
/// every MX connection (`GESTURE_BUTTON_CODES` is never empty), and building
/// or dropping it fires genuine Create/Remove inotify events that look like a
/// real plug/unplug. `run_evdev_loop`/`run_hidraw_loop` cancel a healthy
/// session on *any* hotplug notification (required for Easy-Switch host
/// changes and Bolt sleep recovery, issue #102), so without this filter the
/// vdev's own churn self-triggers a reconnect loop. On USB/Bolt the
/// round-trip usually lands inside one debounce window and self-corrects; on
/// Bluetooth it is slow enough to escape the debounce repeatedly, producing a
/// sustained cursor-lag loop.
///
/// A Create is recognized by reading the node's name from sysfs at the moment
/// the event is processed. The vdev cannot pre-register its own paths: the
/// kernel publishes the node (and inotify fires) during `build()`, before the
/// daemon can learn what path it got. A Remove cannot be named (the node is
/// already gone), so it is matched against the paths recorded from their
/// Creates - inotify delivers events in order, so a vdev's Create is always
/// observed before its Remove. Mixed events (any non-vdev path) are
/// conservatively treated as real hotplug.
fn hotplug_event_is_self_caused(
    kind: &notify::EventKind,
    paths: &[std::path::PathBuf],
    own_vdev_paths: &mut std::collections::HashSet<std::path::PathBuf>,
    name_of: impl Fn(&std::path::Path) -> Option<String>,
) -> bool {
    use notify::EventKind;
    if paths.is_empty() {
        return false;
    }
    match kind {
        EventKind::Create(_) => {
            // No short-circuit: every vdev path must be recorded even when a
            // real path in the same event makes the event itself real,
            // otherwise the vdev's later Remove would count as real hotplug.
            let mut all_ours = true;
            for path in paths {
                if name_of(path).as_deref() == Some(juhradiald::evdev::VIRTUAL_DEVICE_NAME) {
                    own_vdev_paths.insert(path.clone());
                } else {
                    // A Create on a recorded path whose name is no longer the
                    // vdev means the vdev's Remove was lost (e.g. inotify
                    // queue overflow) and the kernel reused the event number:
                    // evict the stale entry so the new real device's eventual
                    // Remove is not swallowed as self-caused.
                    own_vdev_paths.remove(path);
                    all_ours = false;
                }
            }
            all_ours
        }
        EventKind::Remove(_) => {
            let mut all_ours = true;
            for path in paths {
                if !own_vdev_paths.remove(path) {
                    all_ours = false;
                }
            }
            all_ours
        }
        _ => false,
    }
}

/// Kernel device name of an input event node, read from sysfs.
///
/// Reads `/sys/class/input/<eventN>/device/name`, which exists by the time
/// devtmpfs publishes `/dev/input/<eventN>`. Deliberately does NOT open the
/// event node itself: opening every new node from the watcher is how the
/// issue #15 scan feedback loop started.
fn sysfs_input_device_name(path: &std::path::Path) -> Option<String> {
    let node = path.file_name()?.to_str()?;
    let name_path = std::path::Path::new("/sys/class/input")
        .join(node)
        .join("device/name");
    std::fs::read_to_string(name_path)
        .ok()
        .map(|s| s.trim_end().to_string())
}

/// Spawn a background thread that watches /dev/input/ for device hotplug events
/// using inotify. Returns a Notify that fires when event* devices appear or
/// disappear. This allows evdev loops to re-scan immediately instead of waiting
/// for the fallback poll (`DEVICE_POLL_INTERVAL_SECS`).
///
/// Only reacts to Create/Remove events (actual device plug/unplug). Access events
/// (e.g. Close(Write)) are filtered out to prevent a feedback loop where our own
/// device scanning triggers inotify events that cause more scanning. Create/Remove
/// of the daemon's own button-suppression vdev is filtered out too - see
/// `hotplug_event_is_self_caused` (issues #121/#125). A 500ms debounce window
/// coalesces rapid events from USB hubs into a single notification.
fn spawn_device_hotplug_watcher() -> Arc<tokio::sync::Notify> {
    let hotplug = Arc::new(tokio::sync::Notify::new());
    let hotplug_tx = hotplug.clone();

    std::thread::spawn(move || {
        use notify::{Config, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
        use std::sync::mpsc::channel;
        use std::time::Instant;

        let (tx, rx) = channel();
        let config = Config::default().with_poll_interval(Duration::from_millis(200));

        let mut watcher = match RecommendedWatcher::new(tx, config) {
            Ok(w) => w,
            Err(e) => {
                warn!(
                    "Device hotplug watcher init failed: {} - falling back to polling",
                    e
                );
                return;
            }
        };

        let input_dir = std::path::PathBuf::from("/dev/input");
        if let Err(e) = watcher.watch(&input_dir, RecursiveMode::NonRecursive) {
            warn!(
                "Failed to watch /dev/input/: {} - falling back to polling",
                e
            );
            return;
        }

        info!("Device hotplug watcher active on /dev/input/");

        let mut last_notify = Instant::now() - Duration::from_secs(1);
        let debounce = Duration::from_millis(500);
        // Paths of the daemon's own suppression vdev(s), maintained from the
        // events themselves (Create records, Remove consumes). Lives in this
        // thread only, so there is no cross-thread registration race.
        let mut own_vdev_paths = std::collections::HashSet::new();

        loop {
            match rx.recv() {
                Ok(Ok(event)) => {
                    // Only react to actual device creation/removal - NOT access events.
                    // Our own scanning opens /dev/input/event* files, which generates
                    // Access(Close(Write)) inotify events. If we react to those, we
                    // enter an infinite scan loop (~50ms cycle) that saturates the
                    // input subsystem and can block other devices (see issue #15).
                    let is_hotplug =
                        matches!(event.kind, EventKind::Create(_) | EventKind::Remove(_));
                    if !is_hotplug {
                        continue;
                    }

                    let is_event_device = event.paths.iter().any(|p| {
                        p.file_name()
                            .and_then(|n| n.to_str())
                            .map(|n| n.starts_with("event"))
                            .unwrap_or(false)
                    });
                    if !is_event_device {
                        continue;
                    }

                    // Must run before the debounce: a debounced-away Create
                    // would never record the vdev path, and its Remove would
                    // then restart the session as if a real device unplugged.
                    if hotplug_event_is_self_caused(
                        &event.kind,
                        &event.paths,
                        &mut own_vdev_paths,
                        sysfs_input_device_name,
                    ) {
                        debug!(
                            "Hotplug event on own virtual device ignored: {:?}",
                            event.paths
                        );
                        continue;
                    }

                    // Debounce: coalesce rapid events (e.g. USB hub enumerating
                    // multiple devices) into a single scan notification.
                    let now = Instant::now();
                    if now.duration_since(last_notify) < debounce {
                        debug!("Device hotplug debounced: {:?}", event.kind);
                        continue;
                    }
                    last_notify = now;

                    info!("Device hotplug detected: {:?}", event.kind);
                    hotplug_tx.notify_waiters();
                }
                Ok(Err(e)) => {
                    warn!("Device watcher error: {}", e);
                }
                Err(_) => {
                    // Channel closed
                    break;
                }
            }
        }
    });

    hotplug
}

/// JuhRadial MX Daemon - Radial menu for Logitech MX Master 4
#[derive(Parser, Debug)]
#[command(name = "juhradiald")]
#[command(version, about, long_about = None)]
struct Args {
    /// Configuration file path
    #[arg(short, long, default_value = "~/.config/juhradial/config.json")]
    config: String,

    /// Enable verbose logging
    #[arg(short, long)]
    verbose: bool,

    /// List all Logitech devices and exit
    #[arg(long)]
    list_devices: bool,

    /// Write the configuration (config, profiles, macros, icons, themes) to a zip file and exit
    #[arg(long, value_name = "FILE", conflicts_with = "import")]
    export: Option<PathBuf>,

    /// Restore a zip written by --export (the current config.json and profiles.json are kept as .bak) and exit
    #[arg(long, value_name = "FILE")]
    import: Option<PathBuf>,
}

/// The lowercased class the first time it is focused in this run, else None.
/// Profiles are keyed by lowercased class, so "Firefox" and "firefox" are one
/// application.
fn first_sighting(seen: &mut HashSet<String>, class: &str) -> Option<String> {
    let app = class.trim().to_lowercase();
    if app.is_empty() || !seen.insert(app.clone()) {
        return None;
    }
    Some(app)
}

/// Config directory the backup commands operate on (XDG aware).
fn backup_config_dir() -> PathBuf {
    juhradiald::config::Config::default_config_dir()
        .unwrap_or_else(juhradiald::profiles::get_config_dir)
}

/// `juhradiald --export FILE`: no logging, no bus name, no device access.
fn run_export(dest: &std::path::Path) -> Result<(), Box<dyn std::error::Error>> {
    let dir = backup_config_dir();
    match juhradiald::backup::export(&dir, dest) {
        Ok(files) => {
            println!(
                "Exported {} file(s) from {} to {}",
                files.len(),
                dir.display(),
                dest.display()
            );
            Ok(())
        }
        Err(e) => {
            eprintln!("Export failed: {}", e);
            std::process::exit(1);
        }
    }
}

/// `juhradiald --import FILE`: restore, then ask a running daemon to reload.
async fn run_import(src: &std::path::Path) -> Result<(), Box<dyn std::error::Error>> {
    let dir = backup_config_dir();
    let report = match juhradiald::backup::import(&dir, src) {
        Ok(report) => report,
        Err(e) => {
            eprintln!("Import failed: {}", e);
            std::process::exit(1);
        }
    };
    println!(
        "Imported {} file(s) from a {} backup into {}",
        report.files.len(),
        report.version,
        dir.display()
    );
    for bak in &report.backed_up {
        println!("Previous {} kept as {}", bak.trim_end_matches(".bak"), bak);
    }
    if reload_running_daemon().await {
        println!("Running daemon reloaded");
    } else {
        println!("No running daemon to reload; the import applies on the next start");
    }
    Ok(())
}

/// ReloadConfig plus ReloadMacroTriggers on the daemon that owns the bus
/// name, if any. False when no daemon answers.
async fn reload_running_daemon() -> bool {
    let Ok(connection) = zbus::Connection::session().await else {
        return false;
    };
    let Ok(proxy) = zbus::proxy::Proxy::new(
        &connection,
        DBUS_NAME,
        DBUS_PATH,
        "org.kde.juhradialmx.Daemon",
    )
    .await
    else {
        return false;
    };
    if proxy.call_method("ReloadConfig", &()).await.is_err() {
        return false;
    }
    let _ = proxy.call_method("ReloadMacroTriggers", &()).await;
    true
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();

    // Backup commands run before logging and before the bus-name claim: they
    // must work while a daemon is running and print only their own summary.
    if let Some(dest) = args.export.as_deref() {
        return run_export(dest);
    }
    if let Some(src) = args.import.as_deref() {
        return run_import(src).await;
    }

    // Initialize logging
    let level = if args.verbose {
        Level::DEBUG
    } else {
        Level::INFO
    };
    let subscriber = FmtSubscriber::builder().with_max_level(level).finish();
    tracing::subscriber::set_global_default(subscriber)?;

    info!("JuhRadial MX Daemon starting...");
    let startup_started_at = Instant::now();

    // Handle --list-devices flag
    if args.list_devices {
        list_logitech_devices();
        return Ok(());
    }

    // Single-instance guard, and it must run BEFORE any device work. At login
    // the systemd user service and the autostart launcher race to start a
    // daemon (issue #60): the launcher's NameHasOwner check is check-then-act,
    // so a second copy can always slip through. Claiming the well-known name
    // atomically here makes the first daemon win and every later copy exit
    // cleanly (exit 0, so Restart=on-abnormal never sees a refused claim as a
    // crash) before it has diverted buttons or opened any device. Claiming
    // this early also shrinks the launcher's race window: the name becomes
    // visible immediately instead of after the ~1.5s HID++ probe.
    let dbus_connection = zbus::Connection::session().await.map_err(|e| {
        error!("Failed to connect to session D-Bus: {}", e);
        e
    })?;
    if !claim_name(&dbus_connection, DBUS_NAME).await? {
        info!(
            "another juhradiald already owns {}; exiting (single-instance guard)",
            DBUS_NAME
        );
        return Ok(());
    }
    log_startup_phase(&startup_started_at, "bus-name claim");

    info!("Configuration: {}", args.config);

    // Create shared battery state
    let battery_state = new_shared_state();

    // Load shared configuration (supports hot-reload via ReloadConfig D-Bus method)
    let shared_config = match load_shared_config() {
        Ok(config) => {
            info!("Configuration loaded successfully");
            config
        }
        Err(e) => {
            warn!("Failed to load config, using defaults: {}", e);
            juhradiald::config::new_shared_config()
        }
    };
    log_startup_phase(&startup_started_at, "config");

    // Initialize haptic manager for MX4 haptic feedback
    let haptic_config = shared_config.read().unwrap().haptics.clone();
    let haptic_manager = new_shared_haptic_manager(&haptic_config);

    // Try to connect to MX Master 4 for haptic feedback and divert gesture buttons.
    // HID++ probing does blocking hidraw I/O with std::thread::sleep, running it
    // directly on the tokio runtime stalls every other task (evdev, hidraw, dbus)
    // for up to ~1.5s on cold start. spawn_blocking moves it onto the blocking
    // thread pool so the runtime keeps servicing input events during startup.
    let mx4_hidraw_path;
    let mx4_device_name: Option<String>;
    {
        let manager_for_probe = haptic_manager.clone();
        let probe = tokio::task::spawn_blocking(move || {
            let mut manager = manager_for_probe.lock().unwrap();
            let connect_result = manager.connect();
            // Divert immediately while we still hold the lock so we don't race
            // the battery updater on the same hidraw fd.
            let divert_result = if matches!(connect_result, Ok(true)) {
                Some(manager.divert_buttons())
            } else {
                None
            };
            let path = manager.device_path();
            let name = manager.get_device_name_string();
            let unit = manager.unit_id();
            (connect_result, divert_result, path, name, unit)
        })
        .await
        .expect("HID++ probe task panicked");

        // Per-device overrides (config `devices.<unit>`): select the connected
        // mouse before the reassigned-button diverts below read the config.
        if let Some(unit) = probe.4 {
            let key = juhradiald::config::Config::unit_key(unit);
            if let Ok(mut cfg) = shared_config.write() {
                let applied = cfg.apply_device_overrides(&key);
                info!(unit = %key, applied, "HID++ device unit id");
            }
        }

        match probe.0 {
            Ok(true) => {
                info!("Haptic feedback connected to MX Master 4");
                match probe.1 {
                    Some(Ok(n)) if n > 0 => info!(count = n, "Gesture buttons diverted via HID++"),
                    Some(Ok(_)) => {
                        warn!("No gesture buttons found to divert - thumb button may not work")
                    }
                    Some(Err(e)) => warn!("Button divert failed (non-fatal): {}", e),
                    None => {}
                }
            }
            Ok(false) => info!("No MX Master 4 found for haptics (optional)"),
            Err(e) => warn!("Haptic connection error (non-fatal): {}", e),
        }
        mx4_hidraw_path = probe.2;
        mx4_device_name = probe.3;
        if let Some(ref path) = mx4_hidraw_path {
            info!(path = %path.display(), "MX Master 4 hidraw path for event listener");
        }
        if let Some(ref name) = mx4_device_name {
            info!(name = %name, "HID++ device name");
        }
    }
    log_startup_phase(&startup_started_at, "hidpp_bootstrap");

    // Clone haptic_manager for battery updater before passing to D-Bus
    let haptic_manager_for_battery = haptic_manager.clone();

    // Determine device mode:
    // 1. Check config for user override (settings "Generic" toggle)
    // 2. If HID++ connected -> "logitech" (already have mx4_hidraw_path)
    // 3. Else try evdev MX detection
    // 4. Else try generic mouse detection
    let config_device_mode = read_device_mode_from_config();
    info!("Config device_mode: {}", config_device_mode);

    let (device_mode, device_name) = if config_device_mode == "generic" {
        // User forced generic mode via settings toggle
        let name = match EvdevHandler::find_any_mouse() {
            Ok(info) => {
                info!("Device mode: generic (forced, detected: {})", info.name);
                info.name
            }
            Err(_) => {
                info!("Device mode: generic (forced, no mouse detected yet)");
                "Generic Mouse".to_string()
            }
        };
        ("generic".to_string(), name)
    } else if mx4_hidraw_path.is_some() {
        // HID++ found a Logitech device - use actual device name from HID++ protocol
        let name = mx4_device_name.unwrap_or_else(|| "Logitech MX Master".to_string());
        info!("Device mode: logitech (HID++ connected, device: {})", name);
        ("logitech".to_string(), name)
    } else {
        // Try evdev MX detection
        match EvdevHandler::find_device() {
            Ok(info) => {
                info!("Device mode: logitech (evdev MX detected: {})", info.name);
                ("logitech".to_string(), info.name)
            }
            Err(_) => {
                // Try generic mouse fallback
                match EvdevHandler::find_any_mouse() {
                    Ok(info) => {
                        info!("Device mode: generic (detected: {})", info.name);
                        ("generic".to_string(), info.name)
                    }
                    Err(_) => {
                        warn!("No mouse detected at startup - will poll for connection");
                        ("logitech".to_string(), "Unknown".to_string())
                    }
                }
            }
        }
    };
    log_startup_phase(&startup_started_at, "device_mode");
    // Shared, live-updatable cell: the startup guess above can be wrong (e.g.
    // an evdev fallback name because HID++ hadn't finished connecting yet
    // over Bolt) and gets corrected by run_hidraw_loop once HID++ confirms
    // the real name, potentially well after this point.
    let device_name_state: SharedDeviceName = Arc::new(tokio::sync::RwLock::new(device_name));

    // Initialize gaming mode and macro subsystem
    let gaming_mode = new_shared_gaming_mode(haptic_manager.clone());
    if let (Ok(cfg), Ok(mut gm)) = (shared_config.read(), gaming_mode.write()) {
        gm.apply_config(&cfg.gaming);
    }
    let macro_engine = Arc::new(Mutex::new(MacroEngine::new()));
    let macro_recorder = Arc::new(Mutex::new(MacroRecorder::new()));
    let trigger_map = Arc::new(std::sync::RwLock::new(TriggerMap::default()));

    // Load existing macro triggers from disk at startup
    // The startup divert below; the hidraw loop reads bindings live after.
    let _startup_macro_cids: Vec<u16>;
    let macro_evdev_codes: HashSet<u16>;
    {
        // Pull what we need out of the trigger map, then drop the write lock
        // before we await on the blocking divert task, clippy's
        // `await_holding_lock` lint is correct: a std RwLock guard is poisoned
        // territory across an await.
        let pending_cids: Vec<(u16, u16)>;
        {
            let mut map = trigger_map.write().unwrap();
            map.reload();
            info!(count = map.len(), "Macro triggers loaded at startup");
            macro_evdev_codes = map.evdev_codes().into_iter().collect();
            pending_cids = map
                .evdev_codes()
                .into_iter()
                .filter_map(|code| {
                    juhradiald::hidraw::evdev_keycode_to_cid(code).map(|cid| (code, cid))
                })
                .collect();
        }
        let initial_remapped_cids = shared_config
            .read()
            .map(|config| config.remapped_button_cids())
            .unwrap_or_default();

        _startup_macro_cids = if pending_cids.is_empty() && initial_remapped_cids.is_empty() {
            Vec::new()
        } else {
            // Scan REPROG_CONTROLS_V4 once, then send one long request per
            // matching macro. Re-scanning every control for every macro could
            // multiply cold-start I/O by the macro count.
            let manager_for_divert = haptic_manager.clone();
            tokio::task::spawn_blocking(move || {
                let mut mgr = manager_for_divert.lock().unwrap();
                let requested_cids: Vec<u16> = pending_cids
                    .iter()
                    .map(|(_, cid)| *cid)
                    .chain(initial_remapped_cids.iter().copied())
                    .collect();
                let diverted_cids: HashSet<u16> = match mgr.divert_buttons_by_cid(&requested_cids) {
                    Ok(cids) => cids.into_iter().collect(),
                    Err(e) => {
                        warn!(error = %e, "Failed to scan macro buttons for HID++ divert");
                        HashSet::new()
                    }
                };
                let mut cids = Vec::new();
                for (evdev_code, cid) in pending_cids {
                    if diverted_cids.contains(&cid) {
                        info!(
                            evdev_code = format!("0x{:04X}", evdev_code),
                            cid = format!("0x{:04X}", cid),
                            "Macro button diverted via HID++"
                        );
                        cids.push(cid);
                    } else {
                        warn!(
                            evdev_code = format!("0x{:04X}", evdev_code),
                            cid = format!("0x{:04X}", cid),
                            "Could not divert macro button (not found, not divertable, or HID++ update failed)"
                        );
                    }
                }
                for cid in initial_remapped_cids {
                    if diverted_cids.contains(&cid) {
                        info!(
                            cid = format!("0x{:04X}", cid),
                            "Reassigned button diverted via HID++"
                        );
                    } else {
                        warn!(
                            cid = format!("0x{:04X}", cid),
                            "Could not divert reassigned button (not found, not divertable, or HID++ update failed)"
                        );
                    }
                }
                cids
            })
            .await
            .expect("macro divert task panicked")
        };
    }
    log_startup_phase(&startup_started_at, "macro_diverts");

    // Clone trigger_map and macro_engine for event processing (macro trigger detection)
    // Must clone before D-Bus init which moves them
    let trigger_map_for_events = trigger_map.clone();
    let trigger_map_for_hidraw = trigger_map.clone();
    let trigger_map_for_evdev = trigger_map.clone();
    let trigger_map_for_focus = trigger_map.clone();
    let macro_engine_for_events = macro_engine.clone();

    // Active-window channel for per-app hardware profiles. The D-Bus service
    // (KWin script path) and the WindowTracker (Hyprland/X11 paths) both push
    // resource classes here; a single consumer applies matching profiles.
    let (active_window_tx, active_window_rx) =
        tokio::sync::mpsc::unbounded_channel::<String>();
    // Clone the haptic manager for the profile consumer before it is moved into
    // the D-Bus service below.
    let haptic_manager_for_profiles = haptic_manager_for_battery.clone();
    // Button actions that talk to the mouse itself (SmartShift toggle).
    juhradiald::actions::set_device_manager(haptic_manager_for_battery.clone());

    // Shared per-app hardware profile map. Created empty here, populated once
    // profiles.json is loaded below, and refreshed by `ReloadConfig` whenever
    // the settings UI saves. Both the D-Bus service and the focus-change
    // consumer hold a clone, so a UI save reaches the consumer without restart.
    let hardware_profiles: SharedHardwareProfiles = Arc::new(RwLock::new(HashMap::new()));

    // Pointer/scroll replay after reconnect or wake needs the focused app's
    // profile and the gaming DPI, owned elsewhere; share them.
    let replay_ctx = juhradiald::replay::ReplayContext {
        gaming_mode: gaming_mode.clone(),
        hardware_profiles: hardware_profiles.clone(),
        active_profile: juhradiald::replay::new_shared_active_profile(),
    };

    // Export the D-Bus service on the connection that already holds the
    // single-instance name claim from startup.
    match init_dbus_service_with_device(
        &dbus_connection,
        battery_state.clone(),
        shared_config.clone(),
        haptic_manager,
        device_mode.clone(),
        device_name_state.clone(),
        gaming_mode.clone(),
        macro_engine,
        macro_recorder,
        trigger_map,
        active_window_tx.clone(),
        hardware_profiles.clone(),
    )
    .await
    {
        Ok(()) => {
            info!(
                "D-Bus service initialized successfully (mode={}, device={})",
                device_mode,
                device_name_state.read().await
            );
        }
        Err(e) => {
            error!("Failed to initialize D-Bus service: {}", e);
            return Err(e.into());
        }
    };
    log_startup_phase(&startup_started_at, "dbus");

    // Detect KWin by D-Bus name ownership (not XDG_CURRENT_DESKTOP, which is
    // empty when systemd starts the daemon at cold boot, issue #32). The watcher
    // seeds the flag and follows KWin restarts on the same session connection.
    let kwin_availability = juhradiald::compositor::KWinAvailability::new();
    let kwin_scripting = juhradiald::compositor::KWinScripting::new(dbus_connection.clone());
    {
        let conn = dbus_connection.clone();
        let kwin = kwin_availability.clone();
        tokio::spawn(async move { juhradiald::compositor::run_kwin_watcher(conn, kwin).await });
    }
    // Feral GameMode: automatic gaming mode (never starts gamemoded).
    {
        let conn = dbus_connection.clone();
        let gaming = gaming_mode.clone();
        tokio::spawn(async move { juhradiald::gamemode::run_gamemode_watcher(conn, gaming).await });
    }
    // Screen lock (logind LockedHint): the keypad goes blank while locked.
    tokio::spawn(async { juhradiald::screen_lock::run(juhradiald::keypad::set_screen_locked).await });
    // ---- MX Keypad ----
    // The guard stops the HID worker on daemon shutdown. Both HID and action
    // execution have their own blocking workers, independent of mouse input.
    let (_keypad_worker, mut keypad_events) = juhradiald::keypad::start(shared_config.clone());
    {
        let mut actions = ActionContext {
            connection: dbus_connection.clone(), config: shared_config.clone(),
            macro_engine: macro_engine_for_events.clone(), gaming_mode: gaming_mode.clone(), shift_restore: None, held_custom: None,
        };
        let kwin = kwin_availability.clone();
        let kwin_scripting = kwin_scripting.clone();
        tokio::task::spawn_blocking(move || {
            let Ok(rt) = tokio::runtime::Builder::new_current_thread().enable_all().build() else { return };
            rt.block_on(async move {
                use juhradiald::config::ButtonAction;
                use juhradiald::keypad::Event;
                while let Some(event) = keypad_events.recv().await {
                    match event {
                        Event::Connection(connected) => {
                            let _ = actions.connection.emit_signal(None::<&str>, DBUS_PATH,
                                "org.kde.juhradialmx.Daemon", "KeypadStatusChanged", &(connected,)).await;
                        }
                        Event::Pressed(page, key) => {
                            let _ = actions.connection.emit_signal(None::<&str>, DBUS_PATH,
                                "org.kde.juhradialmx.Daemon", "KeypadKeyPressed", &(page, key)).await;
                        }
                        Event::Action { binding, pressed } => {
                            if binding.action == ButtonAction::Custom {
                                run_custom_action(&binding.custom, &actions.macro_engine, pressed).await;
                            } else if binding.action == ButtonAction::RadialMenu {
                                let suppressed = actions.gaming_mode.read().is_ok_and(|g| g.should_suppress_overlay());
                                match keypad_ring_route(pressed, suppressed, kwin.is_owned()) {
                                    KeypadRing::Hide => { let _ = emit_hide_menu(&actions.connection).await; }
                                    KeypadRing::Suppressed => debug!("Keypad Actions Ring suppressed - gaming mode active"),
                                    KeypadRing::KWinScript => {
                                        // Same as the gesture button: the KWin script calls
                                        // ShowMenuAtCursor with KWin's own cursor position.
                                        let conn = actions.connection.clone();
                                        juhradiald::compositor::trigger_kwin_cursor_script(Some(&kwin_scripting), move || async move {
                                            let p = juhradiald::cursor::get_cursor_position();
                                            let _ = emit_menu_requested(&conn, p.x, p.y).await;
                                        }).await;
                                    }
                                    KeypadRing::CursorQuery => {
                                        let p = juhradiald::cursor::get_cursor_position();
                                        let _ = emit_menu_requested(&actions.connection, p.x, p.y).await;
                                    }
                                }
                            } else {
                                actions.run(binding.action, pressed, None, 1).await;
                            }
                        }
                    }
                }
            });
        });
    }
    // ---- End MX Keypad ----

    let kwin_context = KWinContext {
        availability: kwin_availability,
        scripting: kwin_scripting,
        gaming: gaming_mode.clone(),
    };

    let haptic_manager_for_hidraw = haptic_manager_for_battery.clone();

    // Live battery notifications update the same shared state the active poller
    // writes, so GetBatteryStatus reflects them even when the active query fails.
    let battery_state_for_events = battery_state.clone();

    // Start inotify watcher on /dev/input/ for instant device hotplug detection.
    // Shared across the evdev loops and the hidraw loop; the battery updater
    // also fires it when a failing poll starts succeeding again, which is how
    // a Bolt radio wake is detected without any node hotplug (issue #102).
    let hotplug_notify = spawn_device_hotplug_watcher();

    // Spawn battery status updater (shares HidppDevice with haptic via SharedHapticManager)
    let battery_radio_recovered = hotplug_notify.clone();
    let battery_handle = tokio::spawn(async move {
        start_battery_updater_shared(
            battery_state,
            haptic_manager_for_battery,
            battery_radio_recovered,
        )
        .await
    });

    // Load profiles (Story 3.1: Task 5)
    // Creates default profiles.json if it doesn't exist
    let profile_manager = match ProfileManager::load_or_create() {
        Ok(manager) => {
            info!(
                profile_count = manager.profile_count(),
                "Profile manager initialized"
            );
            manager
        }
        Err(e) => {
            error!("Failed to load profiles: {}", e);
            warn!("Using in-memory default profile");
            ProfileManager::new()
        }
    };

    // Log current profile
    let current = profile_manager.current();
    info!(profile = current.name, "Active profile loaded");

    // Seed the shared hardware map from the freshly loaded profiles so the
    // focus-change consumer and ReloadConfig share one source of truth.
    match hardware_profiles.write() {
        Ok(mut map) => *map = profile_manager.hardware_profiles(),
        Err(e) => error!(error = %e, "Failed to seed shared hardware profiles"),
    }
    log_startup_phase(&startup_started_at, "profiles");

    // Window tracker for per-app HARDWARE profiles (Story 3.2/3.3) and the
    // KDE monitor-switch haptic script. Both depend on the desktop, which a
    // systemd user unit started at default.target cannot know yet: the
    // session exports XDG_CURRENT_DESKTOP / WAYLAND_DISPLAY into the user
    // manager seconds later (see actions::session_var). Deciding once at
    // startup left a slow boot with no tracker and no monitor-switch haptic
    // for the whole session (issue #138, Bazzite), so keep re-checking until
    // the desktop is known, then start both.
    {
        let watch_tx = active_window_tx.clone();
        tokio::spawn(async move {
            let started = Instant::now();
            // Started inside the session (not by systemd at default.target):
            // the process environment is already complete.
            let env_from_process = std::env::var_os("DISPLAY").is_some()
                || std::env::var_os("WAYLAND_DISPLAY").is_some();
            let tracker = loop {
                let tracker = WindowTracker::new();
                match tracker_decision(
                    tracker.desktop(),
                    tracker.is_available(),
                    env_from_process,
                    started.elapsed(),
                    WINDOW_TRACKER_WAIT,
                ) {
                    TrackerDecision::Start => break Some(tracker),
                    TrackerDecision::GiveUp => break None,
                    TrackerDecision::Wait => {}
                }
                sleep(Duration::from_secs(2)).await;
            };
            let Some(tracker) = tracker else {
                warn!("Window tracking unavailable - per-app hardware profiles inactive");
                return;
            };
            let desktop = tracker.desktop();
            info!(
                desktop,
                waited_ms = started.elapsed().as_millis() as u64,
                "Window tracking enabled for per-app hardware profiles"
            );
            // Monitor-switch haptic on KDE (X11 or Wayland): a persistent KWin
            // script (installed once, like the active-window script) reports
            // screen crossings directly via TriggerHaptic - see
            // cursor::KWIN_CURSOR_SCREEN_SCRIPT for why this needs to be
            // KWin-native rather than the overlay's own ambient cursor poll
            // (stale on KDE Wayland outside an open menu). The overlay skips
            // its own poll on all of KDE for this reason, so a failed install
            // here means no monitor-switch haptic at all on KDE.
            if desktop == "kde" {
                tokio::spawn(async {
                    let installed =
                        tokio::task::spawn_blocking(juhradiald::cursor::watch_cursor_screen_kde)
                            .await
                            .unwrap_or(false);
                    if installed {
                        info!("KWin cursor-screen script installed (monitor-switch haptic)");
                    } else {
                        warn!("Failed to install KWin cursor-screen script; monitor-switch haptic inactive on KDE");
                    }
                });
            }
            tracker.watch(watch_tx).await;
        });
    }

    // Consumer: on each focus change, look up and apply the per-app hardware
    // profile (volatile only). No-op when no profile matches, so the default
    // (empty hardware map) leaves device state untouched.
    {
        let hw_manager = haptic_manager_for_profiles;
        // Read the live shared map (refreshed by ReloadConfig) instead of a
        // one-time snapshot, so UI saves take effect without a daemon restart.
        let hw_profiles = hardware_profiles.clone();
        // Profiles override only the thumb-wheel mode; the invert setting is
        // global, so read it live from the shared config (issue #127).
        let hw_config = shared_config.clone();
        // The tray tooltip and badge follow the applied profile.
        let profile_connection = dbus_connection.clone();
        let focus_replay = replay_ctx.clone();
        let focus_triggers = trigger_map_for_focus;
        let focus_gaming = gaming_mode.clone();
        if !hw_profiles.read().map(|m| m.is_empty()).unwrap_or(true) {
            info!("Per-app hardware profiles configured; focus-change application active");
        }
        tokio::spawn(async move {
            let mut current_class = String::new();
            // Time in front per app: Settings suggests keypad profiles by it.
            let mut usage = juhradiald::usage::AppUsage::load(
                juhradiald::config::Config::default_config_dir().map(|d| d.join("app_usage.json")),
            );
            // Class whose hardware profile is applied right now ("" = none).
            let mut active_profile = String::new();
            // True while the last applied profile overrode the thumb wheel,
            // so leaving its app restores the global divert/invert instead of
            // latching the profile's state everywhere (issue #127 review).
            let mut thumbwheel_overridden = false;
            // Classes already announced through NewAppSeen during this run.
            let mut seen_apps: HashSet<String> = HashSet::new();
            // Device state before the first profile applied: what leaving
            // profiled apps restores for settings config.json does not name.
            let mut baseline: Option<juhradiald::replay::DeviceState> = None;
            // App profiles "Try now" can stand in for the app in front.
            let mut focus = juhradiald::focus_trial::FocusSource::new(active_window_rx);
            while let Some(class) = focus.next().await {
                if class == current_class {
                    continue;
                }
                current_class = class.clone();
                juhradiald::keypad::set_focused_app(&class);
                if !focus.in_trial() {
                    usage.focus(&class, std::time::Instant::now());
                }

                // First focus of an application in this run: Settings decides
                // whether to offer a profile for it (suppress list, existing
                // profiles), the daemon only announces it once.
                if let Some(app) = first_sighting(&mut seen_apps, &class) {
                    if let Err(e) = profile_connection
                        .emit_signal(
                            None::<&str>,
                            DBUS_PATH,
                            "org.kde.juhradialmx.Daemon",
                            "NewAppSeen",
                            &(app,),
                        )
                        .await
                    {
                        warn!(error = %e, "Failed to emit NewAppSeen");
                    }
                }

                // Window-switch haptic fires on every app-class change,
                // regardless of whether a hardware profile matches below.
                // An app on the haptics mute list goes quiet first, so
                // switching into it does not pulse either.
                let (app_muted, auto_game) = hw_config
                    .read()
                    .map(|c| (c.haptics.app_muted(&class), c.gaming.auto_app(&class)))
                    .unwrap_or((false, false));
                // Settings > Gaming > "When these apps are in front".
                let gaming = focus_gaming.clone();
                let flipped = tokio::task::spawn_blocking(move || {
                    gaming.write().ok().and_then(|mut gm| gm.set_auto(AutoSource::App, auto_game))
                })
                .await
                .ok()
                .flatten();
                if let Some(on) = flipped {
                    info!(app = %class, on, "Gaming mode switched by the app in front");
                    let _ = profile_connection
                        .emit_signal(None::<&str>, DBUS_PATH, "org.kde.juhradialmx.Daemon", "GamingModeChanged", &(on,))
                        .await;
                }
                let mgr_ws = hw_manager.clone();
                let _ = tokio::task::spawn_blocking(move || {
                    if let Ok(mut m) = mgr_ws.lock() {
                        m.set_app_muted(app_muted);
                        if m.is_window_switch_enabled() {
                            let _ = m.emit(HapticEvent::WindowSwitch);
                        }
                    }
                })
                .await;

                // Lookup is case-insensitive: keys are lowercased at load, so
                // lowercase the incoming class (window-tracker sources vary).
                let hw = {
                    let map = match hw_profiles.read() {
                        Ok(map) => map,
                        Err(e) => {
                            error!(error = %e, "Failed to read shared hardware profiles");
                            continue;
                        }
                    };
                    map.get(&class.to_lowercase()).cloned()
                };

                // Restore the global thumb-wheel state when leaving profiled
                // coverage (no profile, or one that doesn't touch the wheel).
                let profile_sets_tw = hw.as_ref().is_some_and(|h| h.thumbwheel.is_some());
                if thumbwheel_overridden && !profile_sets_tw {
                    thumbwheel_overridden = false;
                    let tw = hw_config
                        .read()
                        .map(|c| c.thumbwheel.clone())
                        .unwrap_or_default();
                    let mgr_tw = hw_manager.clone();
                    let _ = tokio::task::spawn_blocking(move || {
                        if let Ok(mut m) = mgr_tw.lock() {
                            if m.thumbwheel_supported() {
                                let _ = m.set_thumbwheel_reporting(
                                    tw.is_diverted(),
                                    tw.hardware_invert(),
                                );
                            }
                        }
                    })
                    .await;
                }
                thumbwheel_overridden = thumbwheel_overridden || profile_sets_tw;

                // ActiveProfileChanged carries the app class whose profile is
                // now applied, or "" once the focus leaves profiled apps.
                let now_active = if hw.is_some() { class.to_lowercase() } else { String::new() };
                let entering = active_profile.is_empty() && !now_active.is_empty();
                let profile_changed = now_active != active_profile;
                if profile_changed {
                    active_profile = now_active.clone();
                    if let Ok(mut cell) = focus_replay.active_profile.write() {
                        *cell = (!now_active.is_empty()).then(|| now_active.clone());
                    }
                    if let Err(e) = profile_connection
                        .emit_signal(
                            None::<&str>,
                            DBUS_PATH,
                            "org.kde.juhradialmx.Daemon",
                            "ActiveProfileChanged",
                            &(now_active,),
                        )
                        .await
                    {
                        warn!(error = %e, "Failed to emit ActiveProfileChanged");
                    }
                }

                if !profile_changed {
                    continue;
                }
                apply_app_button_overrides(
                    &hw_config,
                    &hw_manager,
                    &focus_triggers,
                    (!active_profile.is_empty()).then(|| active_profile.clone()),
                    hw.as_ref(),
                )
                .await;
                // Entering, switching or leaving a profile: write the full
                // effective state, so a setting the previous profile changed
                // returns to the global value (config.json, else the device
                // state from before the first profile) instead of latching.
                match &hw {
                    Some(_) => info!(class = %class, "Applying per-app hardware profile"),
                    None => info!("Focus left profiled apps; restoring global pointer and scroll state"),
                }
                let mgr = hw_manager.clone();
                let (thumbwheel_invert, unit_key) = hw_config
                    .read()
                    .map(|c| (c.thumbwheel.invert, c.active_unit.clone()))
                    .unwrap_or((false, None));
                let gaming_dpi = focus_replay.gaming_dpi();
                let prior = baseline;
                let captured = tokio::task::spawn_blocking(move || {
                    let mut m = match mgr.lock() {
                        Ok(m) => m,
                        Err(e) => {
                            error!(error = %e, "Failed to lock haptic manager for hardware profile");
                            return prior;
                        }
                    };
                    let base = if entering {
                        Some(juhradiald::replay::read_device_state(&mut m))
                    } else {
                        prior
                    };
                    let globals = juhradiald::replay::with_session_dpi(
                        juhradiald::replay::globals_from_config(
                            &juhradiald::replay::load_raw_config(),
                            unit_key.as_deref(),
                        ),
                    )
                    .or(base.unwrap_or_default());
                    let state = juhradiald::replay::effective_state(globals, hw.as_ref(), gaming_dpi);
                    let (tried, failed) = juhradiald::replay::apply(&mut *m, &state);
                    debug!(tried, failed, "Profile pointer/scroll state written");
                    if let Some(hw) = &hw {
                        // Thumb-wheel override (the global restore is above).
                        let tw_only = juhradiald::profiles::HardwareProfile {
                            thumbwheel: hw.thumbwheel,
                            ..Default::default()
                        };
                        juhradiald::profiles::apply_hardware_profile(
                            &tw_only,
                            &mut m,
                            thumbwheel_invert,
                            globals.natural.unwrap_or(false),
                        );
                    }
                    base
                })
                .await
                .unwrap_or(prior);
                baseline = if active_profile.is_empty() { None } else { captured };
            }
        });
    }

    // Create channel for gesture events
    let (event_tx, mut event_rx) = mpsc::channel::<GestureEvent>(32);

    // Directional gestures: one tracker shared by the press owners (hidraw or
    // evdev) and the MX evdev loop that sees the mouse's relative motion.
    let gesture_tracker = juhradiald::gesture::GestureTracker::new_shared();

    // Spawn the HID++ hidraw handler (reads button events directly from mouse).
    // Button divert is volatile and is reset by Easy-Switch host changes, so
    // this loop owns re-applying diverts whenever the mouse hotplugs/reconnects.
    let hidraw_tx = event_tx.clone();
    let hidraw_config = shared_config.clone();
    let hidraw_hotplug = hotplug_notify.clone();
    let hidraw_kwin = kwin_context.clone();
    let hidraw_dbus_connection = dbus_connection.clone();
    let hidraw_device_name_state = device_name_state.clone();
    let hidraw_tracker = gesture_tracker.clone();
    let hidraw_replay = replay_ctx.clone();

    // Publish mouse reachability transitions (connected/asleep/away/offline).
    {
        let conn = dbus_connection.clone();
        let mut rx = juhradiald::link_state::subscribe();
        tokio::spawn(async move {
            let mut last = rx.borrow().0;
            while rx.changed().await.is_ok() {
                let (state, transport) = *rx.borrow_and_update();
                info!(state = state.as_str(), transport = transport.as_str(), "Mouse link changed");
                // Back from another computer (not a wake): the hand feels
                // which computer the mouse landed on.
                if last == juhradiald::link_state::LinkState::Away
                    && state == juhradiald::link_state::LinkState::Connected
                {
                    juhradiald::actions::pulse(HapticEvent::HostArrive);
                }
                last = state;
                if let Err(e) = conn
                    .emit_signal(
                        None::<&str>,
                        DBUS_PATH,
                        "org.kde.juhradialmx.Daemon",
                        "DeviceConnectionChanged",
                        &(state.as_str(), transport.as_str()),
                    )
                    .await
                {
                    warn!(error = %e, "Failed to emit DeviceConnectionChanged");
                }
            }
        });
    }
    // Low-battery pulse (the overlay shows the notice; the hand feels it).
    {
        let battery = battery_state_for_events.clone();
        let alert_config = shared_config.clone();
        tokio::spawn(async move {
            let mut latched = false;
            loop {
                sleep(Duration::from_secs(60)).await;
                let (pct, charging) = {
                    let b = battery.read().await;
                    (b.percentage, b.charging)
                };
                let alert = alert_config.read().map(|c| c.battery.alert_percent).unwrap_or(15);
                let (fire, next) = juhradiald::battery::low_battery_step(latched, pct, charging, alert);
                latched = next;
                if fire {
                    juhradiald::actions::pulse(HapticEvent::LowBattery);
                }
            }
        });
    }
    let hidraw_handle = tokio::spawn(async move {
        run_hidraw_loop(
            hidraw_tx,
            HidrawStartup {
                preferred_path: mx4_hidraw_path,
                gesture_tracker: hidraw_tracker,
                replay: hidraw_replay,
            },
            trigger_map_for_hidraw,
            hidraw_config,
            hidraw_hotplug,
            haptic_manager_for_hidraw,
            hidraw_kwin,
            hidraw_dbus_connection,
            hidraw_device_name_state,
        )
        .await
    });

    // Spawn evdev handlers:
    // - MX evdev loop: fallback for standard MX input events (when HID++ divert unavailable)
    // - Generic evdev loop: handles non-Logitech mice (e.g., SteelSeries)
    // Both run simultaneously so either mouse can trigger the radial wheel.
    let evdev_tx = event_tx.clone();
    // Always suppress gesture button (BTN_BACK = 0x116) on MX evdev path
    // so it doesn't leak to the OS as "browser back" / "open last file".
    // Also suppress any macro-bound buttons.
    let mut suppressed_for_mx = macro_evdev_codes.clone();
    for &code in juhradiald::evdev::GESTURE_BUTTON_CODES {
        suppressed_for_mx.insert(code);
    }
    let hotplug_for_mx = hotplug_notify.clone();
    let evdev_config = shared_config.clone();
    let evdev_kwin = kwin_context.clone();
    let evdev_tracker = gesture_tracker.clone();
    let evdev_handle = tokio::spawn(async move {
        run_evdev_loop(
            evdev_tx,
            suppressed_for_mx,
            hotplug_for_mx,
            evdev_config,
            evdev_kwin,
            evdev_tracker,
            trigger_map_for_evdev,
        )
        .await
    });

    let generic_evdev_tx = event_tx.clone();
    let suppressed_for_generic = macro_evdev_codes.clone();
    let hotplug_for_generic = hotplug_notify.clone();
    let generic_evdev_config = shared_config.clone();
    let generic_evdev_kwin = kwin_context;
    let generic_evdev_handle = tokio::spawn(async move {
        run_generic_evdev_loop(
            generic_evdev_tx,
            suppressed_for_generic,
            hotplug_for_generic,
            generic_evdev_config,
            generic_evdev_kwin,
        )
        .await
    });

    // Spawn the keyboard remap loop (BETA, opt-in). It idles unless the user
    // has enabled keyboard remapping AND defined remap entries, so a default
    // install never grabs the keyboard. Detached and designed to never return,
    // so it is intentionally NOT part of the shutdown select! below.
    let keyboard_config = shared_config.clone();
    let keyboard_hotplug = hotplug_notify.clone();
    let _keyboard_handle = tokio::spawn(async move {
        juhradiald::keyboard::run_keyboard_remap_loop(keyboard_config, keyboard_hotplug).await;
    });

    // MX Keys S link watcher (BETA, opt-in with keyboard.mx_keys.enabled):
    // pushes KeyboardBatteryChanged when a key press re-links the keyboard,
    // so Settings stops showing "asleep" the moment the user types.
    let link_config = shared_config.clone();
    let link_connection = dbus_connection.clone();
    let _keyboard_link_handle = tokio::spawn(async move {
        juhradiald::keyboard::run_keyboard_link_watcher(link_config, link_connection).await;
    });

    // Spawn event processing task with D-Bus connection
    let config_for_events = shared_config.clone();
    let hotplug_for_events = hotplug_notify.clone();
    let gaming_for_events = replay_ctx.gaming_mode.clone();
    let event_handle = tokio::spawn(async move {
        let actions = ActionContext {
            connection: dbus_connection.clone(),
            config: config_for_events,
            macro_engine: macro_engine_for_events,
            gaming_mode: gaming_for_events,
            shift_restore: None,
            held_custom: None,
        };
        process_gesture_events(
            &mut event_rx,
            &dbus_connection,
            trigger_map_for_events,
            battery_state_for_events,
            hotplug_for_events,
            actions,
        )
        .await
    });

    // TODO: Initialize remaining components
    // 4. Initialize HID++ haptic subsystem

    log_startup_phase(&startup_started_at, "ready");
    info!("JuhRadial MX Daemon ready");

    // Wait for shutdown signal
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            info!("Shutdown signal received, exiting...");
        }
        result = hidraw_handle => {
            if let Err(e) = result {
                error!("hidraw task panicked: {:?}", e);
            }
        }
        result = evdev_handle => {
            if let Err(e) = result {
                error!("evdev task panicked: {:?}", e);
            }
        }
        result = generic_evdev_handle => {
            if let Err(e) = result {
                error!("generic evdev task panicked: {:?}", e);
            }
        }
        result = event_handle => {
            if let Err(e) = result {
                error!("Event processing task panicked: {:?}", e);
            }
        }
        result = battery_handle => {
            if let Err(e) = result {
                error!("Battery updater task panicked: {:?}", e);
            }
        }
    }

    Ok(())
}

/// List all detected Logitech devices and generic mouse fallback
fn list_logitech_devices() {
    println!("Scanning for Logitech input devices...\n");

    let devices = EvdevHandler::list_logitech_devices();

    if devices.is_empty() {
        println!("No Logitech devices found.");
    } else {
        println!("Found {} Logitech device(s):\n", devices.len());

        for (i, device) in devices.iter().enumerate() {
            let mx_marker = if device.is_mx_master_4 {
                " [MX Master 4]"
            } else {
                ""
            };
            println!("{}. {}{}", i + 1, device.name, mx_marker);
            println!("   Path:    {:?}", device.path);
            println!("   Vendor:  0x{:04X}", device.vendor_id);
            println!("   Product: 0x{:04X}", device.product_id);
            println!();
        }
    }

    // Also try generic mouse detection
    println!("Scanning for generic mouse fallback...\n");
    match EvdevHandler::find_any_mouse() {
        Ok(info) => {
            println!("Generic mouse detected: {} [FALLBACK]", info.name);
            println!("   Path:    {:?}", info.path);
            println!("   Vendor:  0x{:04X}", info.vendor_id);
            println!("   Product: 0x{:04X}", info.product_id);
            println!("   Trigger: BTN_SIDE (0x113, button 8)");
            println!();
        }
        Err(_) => {
            println!("No generic mouse found.");
            println!();
        }
    }

    if devices.is_empty() {
        println!("Troubleshooting:");
        println!("  - Ensure your mouse is connected");
        println!("  - Check that udev rules are installed");
        println!("  - Verify user is in 'input' group");
    }
}

struct HidrawStartup {
    preferred_path: Option<PathBuf>,
    gesture_tracker: juhradiald::gesture::SharedGestureTracker,
    replay: juhradiald::replay::ReplayContext,
}

#[derive(Clone)]
struct KWinContext {
    availability: juhradiald::compositor::KWinAvailability,
    scripting: juhradiald::compositor::KWinScripting,
    gaming: juhradiald::gaming::SharedGamingMode,
}

/// Reconnect HID++ and re-apply volatile button diverts.
///
/// Easy-Switch host changes reset temporary REPROG_CONTROLS_V4 diverts, so the
/// daemon must apply them again after the mouse returns to this machine.
async fn refresh_hidpp_button_diverts(
    haptic_manager: SharedHapticManager,
    macro_cids: Vec<u16>,
    remapped_cids: Vec<u16>,
) -> (Option<PathBuf>, Option<String>, Option<u32>) {
    match tokio::task::spawn_blocking(move || {
        let mut manager = haptic_manager.lock().unwrap();
        let connected = match manager.connect() {
            Ok(connected) => connected,
            Err(e) => {
                warn!(error = %e, "HID++ reconnect failed while refreshing button divert");
                return (None, None, None);
            }
        };
        if !connected {
            debug!("No MX Master HID++ device available for button divert");
            return (None, None, None);
        }
        let name = manager.get_device_name_string();

        match manager.divert_buttons() {
            Ok(n) if n > 0 => info!(count = n, "HID++ gesture buttons diverted"),
            Ok(_) => warn!("No HID++ gesture buttons found to divert"),
            Err(e) => warn!(error = %e, "Failed to divert HID++ gesture buttons"),
        }

        // Macro and reassigned CIDs all use the same REPROG_CONTROLS_V4 table,
        // so enumerate it once rather than once per configured control.
        let requested_cids: Vec<u16> = macro_cids
            .iter()
            .chain(remapped_cids.iter())
            .copied()
            .collect();
        let diverted_cids: HashSet<u16> = match manager.divert_buttons_by_cid(&requested_cids) {
            Ok(cids) => cids.into_iter().collect(),
            Err(e) => {
                warn!(error = %e, "Failed to scan configured HID++ button diverts");
                HashSet::new()
            }
        };
        for cid in macro_cids {
            if diverted_cids.contains(&cid) {
                debug!(
                    cid = format!("0x{:04X}", cid),
                    "HID++ macro button diverted"
                );
            } else {
                debug!(
                    cid = format!("0x{:04X}", cid),
                    "HID++ macro button not divertable on this device"
                );
            }
        }
        for cid in remapped_cids {
            if diverted_cids.contains(&cid) {
                info!(
                    cid = format!("0x{:04X}", cid),
                    "HID++ reassigned button diverted"
                );
            } else {
                debug!(
                    cid = format!("0x{:04X}", cid),
                    "Reassigned button not divertable on this device"
                );
            }
        }

        (manager.device_path(), name, manager.unit_id())
    })
    .await
    {
        Ok(result) => result,
        Err(e) => {
            error!("HID++ button divert refresh task panicked: {:?}", e);
            (None, None, None)
        }
    }
}

/// Resolve only when the HID++ manager is connected on a DIFFERENT hidraw
/// node than the event listener opened, and stay pending otherwise.
///
/// This is the deaf-listener condition a second plugged-in receiver produces:
/// auto-detect ties both receivers on priority and can open the one the mouse
/// is not paired to. Diverted button notifications then never arrive, so
/// nothing on the listener's own path would ever end the session; this arm
/// gives the reconnect loop a reason to re-bind onto the manager's
/// ping-verified path (e.g. once the battery updater connects it).
async fn hidraw_listener_mismatch(
    haptic_manager: &SharedHapticManager,
    listener_path: Option<std::path::PathBuf>,
) {
    let Some(listener_path) = listener_path else {
        // No opened path to compare; leave the session to its other arms.
        std::future::pending::<()>().await;
        return;
    };
    loop {
        tokio::time::sleep(Duration::from_secs(5)).await;
        let manager_path = haptic_manager
            .lock()
            .ok()
            .and_then(|m| m.device_path());
        if let Some(manager_path) = manager_path {
            if manager_path != listener_path {
                return;
            }
        }
    }
}

/// Apply thumb-wheel divert from config and return the ThumbWheel feature index.
///
/// Like button divert, thumb-wheel reporting (HID++ 0x2150) is volatile and is
/// reset by Easy-Switch host changes, so it is re-applied on every (re)connect.
/// The returned feature index lets the hidraw reader disambiguate diverted
/// rotation notifications from diverted button events.
async fn apply_thumbwheel_reporting(
    haptic_manager: SharedHapticManager,
    shared_config: juhradiald::config::SharedConfig,
) -> Option<u8> {
    match tokio::task::spawn_blocking(move || {
        let tw = shared_config
            .read()
            .map(|c| c.thumbwheel.clone())
            .unwrap_or_default();
        let mut manager = haptic_manager.lock().unwrap();
        if !manager.thumbwheel_supported() {
            return None;
        }
        // Diverted modes (Volume/Zoom) invert in software in the hidraw
        // reader; native Horizontal Scroll inverts in hardware, so the invert
        // byte must survive every re-apply (issue #127).
        match manager.set_thumbwheel_reporting(tw.is_diverted(), tw.hardware_invert()) {
            Ok(()) => info!(
                diverted = tw.is_diverted(),
                invert = tw.hardware_invert(),
                "Thumb-wheel reporting applied"
            ),
            Err(e) => warn!(error = %e, "Failed to apply thumb-wheel reporting"),
        }
        manager.thumbwheel_feature_index()
    })
    .await
    {
        Ok(idx) => idx,
        Err(e) => {
            error!("Thumb-wheel reporting task panicked: {:?}", e);
            None
        }
    }
}

/// Read the discovered notification feature indices (battery/host/DPI/ratchet)
/// so the hidraw reader can decode live hardware-state events. Runs on a
/// blocking task because the haptic manager uses a std `Mutex`.
async fn fetch_notification_indices(
    haptic_manager: SharedHapticManager,
) -> juhradiald::hidpp::notifications::NotificationIndices {
    tokio::task::spawn_blocking(move || {
        haptic_manager
            .lock()
            .map(|m| m.notification_indices())
            .unwrap_or_default()
    })
    .await
    .unwrap_or_default()
}

/// Point the shared config at the focused app's button overrides (P1 #2)
/// and divert exactly the buttons whose effective action changed from or
/// to their native behaviour.
async fn apply_app_button_overrides(
    config: &juhradiald::config::SharedConfig,
    manager: &SharedHapticManager,
    triggers: &juhradiald::macros::SharedTriggerMap,
    app: Option<String>,
    profile: Option<&juhradiald::profiles::HardwareProfile>,
) {
    let (buttons, custom) = profile
        .map(|p| (p.buttons.clone(), p.custom.clone()))
        .unwrap_or_default();
    // Macro-bound buttons stay diverted whatever the app does.
    let macro_cids = triggers.read().map(|m| m.cids()).unwrap_or_default();
    let changed: Vec<(u16, bool)> = match config.write() {
        Ok(mut c) => {
            let before: HashSet<u16> = c.remapped_button_cids().into_iter().chain(macro_cids.iter().copied()).collect();
            c.set_app_overrides(app, buttons, custom);
            let after: HashSet<u16> = c.remapped_button_cids().into_iter().chain(macro_cids.iter().copied()).collect();
            before
                .symmetric_difference(&after)
                .map(|cid| (*cid, after.contains(cid)))
                .collect()
        }
        Err(e) => {
            error!(error = %e, "Failed to lock config for per-app buttons");
            return;
        }
    };
    if changed.is_empty() {
        return;
    }
    let manager = manager.clone();
    let _ = tokio::task::spawn_blocking(move || {
        if let Ok(mut m) = manager.lock() {
            for (cid, divert) in changed {
                match m.set_button_divert(cid, divert) {
                    Ok(_) => info!(cid = format!("0x{:04X}", cid), divert, "Per-app button divert"),
                    Err(e) => warn!(cid = format!("0x{:04X}", cid), error = %e, "Per-app button divert failed"),
                }
            }
        }
    })
    .await;
}

/// Runs button actions for the event loop. Custom, DPI and gaming-mode
/// actions need the slot or daemon state and run here; the rest go to
/// `execute_button_action`.
struct ActionContext {
    connection: zbus::Connection,
    config: juhradiald::config::SharedConfig,
    macro_engine: Arc<Mutex<juhradiald::macros::MacroEngine>>,
    gaming_mode: juhradiald::gaming::SharedGamingMode,
    /// DPI to put back when the held DPI-shift button is released.
    shift_restore: Option<u16>,
    /// A hold-while-pressed custom action whose keys are down (release
    /// events carry no source button, so the press remembers it).
    held_custom: Option<(Option<u16>, juhradiald::config::CustomAction)>,
}

/// What an MX Keypad key bound to the Actions Ring does on one edge. Like the
/// gesture button: KWin's cursor script on KDE, a cursor query elsewhere, the
/// menu hidden on release, nothing while gaming mode hides the ring.
#[derive(Debug, PartialEq, Eq)]
enum KeypadRing {
    Hide,
    Suppressed,
    KWinScript,
    CursorQuery,
}

fn keypad_ring_route(pressed: bool, suppressed: bool, kwin_owned: bool) -> KeypadRing {
    if !pressed {
        KeypadRing::Hide
    } else if suppressed {
        KeypadRing::Suppressed
    } else if juhradiald::compositor::cursor_backend(kwin_owned) == juhradiald::compositor::CursorBackend::KWin {
        KeypadRing::KWinScript
    } else {
        KeypadRing::CursorQuery
    }
}

impl ActionContext {
    async fn run(
        &mut self,
        action: juhradiald::config::ButtonAction,
        pressed: bool,
        source: Option<u16>,
        repeats: u8,
    ) {
        use juhradiald::config::ButtonAction as A;
        match (action, pressed) {
            (A::DpiShift, true) => self.dpi_shift(true).await,
            (A::DpiShift, false) => self.dpi_shift(false).await,
            (A::Custom, false) => {
                if let Some((_, held)) = self.held_custom.take() {
                    run_custom_action(&held, &self.macro_engine, false).await;
                }
            }
            (_, false) => debug!(%action, "Button action released (no-op)"),
            (A::Custom, true) => self.custom(source).await,
            (A::DpiCycle | A::DpiUp | A::DpiDown, true) => self.dpi_step(action).await,
            (A::GamingMode, true) => self.toggle_gaming().await,
            (_, true) => {
                info!(%action, "Button action triggered");
                match juhradiald::actions::execute_button_action_repeated(action, repeats).await {
                    Ok(true) => {}
                    // RadialMenu goes through the Pressed path.
                    Ok(false) => warn!(%action, "Button action wants the radial menu here; ignoring"),
                    Err(e) => error!(%action, error = %e, "Failed to execute button action"),
                }
            }
        }
    }

    async fn custom(&mut self, source: Option<u16>) {
        let slot = source.map(juhradiald::config::Config::slot_for_cid);
        let custom = slot
            .as_deref()
            .and_then(|slot| self.config.read().ok().and_then(|c| c.custom_action(slot).cloned()));
        match custom {
            Some(custom) => {
                info!(slot = ?slot, kind = %custom.kind, "Custom button action");
                if custom.hold {
                    match self.held_custom.take() {
                        // The held button again, listed ahead of another diverted one.
                        Some(held) if held.0 == source => {
                            self.held_custom = Some(held);
                            return;
                        }
                        // A second hold button: release the first one's keys.
                        Some((_, previous)) => run_custom_action(&previous, &self.macro_engine, false).await,
                        None => {}
                    }
                }
                run_custom_action(&custom, &self.macro_engine, true).await;
                if custom.hold {
                    self.held_custom = Some((source, custom));
                }
            }
            None => warn!(slot = ?slot, "Button set to custom but no custom action is saved for it"),
        }
    }

    /// DPI cycle / up / down. The new DPI outlives a wake (session DPI) and
    /// Settings follows it through DpiChanged.
    async fn dpi_step(&self, action: juhradiald::config::ButtonAction) {
        if action == juhradiald::config::ButtonAction::DpiCycle && self.gaming_cycle().await {
            return;
        }
        let Some((current, range)) = juhradiald::actions::read_dpi().await else {
            warn!(%action, "DPI action: the mouse's DPI is not readable");
            return;
        };
        let presets = pointer_setting("dpi_presets")
            .and_then(|v| v.as_array().cloned())
            .map(|a| a.iter().filter_map(|d| d.as_u64()).filter_map(|d| u16::try_from(d).ok()).collect::<Vec<_>>())
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| vec![800, 1600, 3200]);
        let Some(dpi) = juhradiald::actions::next_dpi(action, current, &presets, range) else {
            return;
        };
        if dpi == current {
            return;
        }
        match juhradiald::actions::write_dpi(dpi).await {
            Ok(()) => {
                info!(%action, from = current, to = dpi, "DPI changed by a button");
                juhradiald::actions::pulse(HapticEvent::DpiChange);
                juhradiald::replay::set_session_dpi(Some(dpi));
                let _ = self
                    .connection
                    .emit_signal(None::<&str>, DBUS_PATH, "org.kde.juhradialmx.Daemon", "DpiChanged", &(dpi,))
                    .await;
            }
            Err(e) => error!(%action, error = %e, "DPI action failed"),
        }
    }

    /// Hold for the precision DPI (`pointer.dpi_shift`, default 400), release
    /// to put the previous DPI back.
    async fn dpi_shift(&mut self, pressed: bool) {
        if !pressed {
            if let Some(dpi) = self.shift_restore.take() {
                if let Err(e) = juhradiald::actions::write_dpi(dpi).await {
                    error!(error = %e, dpi, "DPI shift: restoring the DPI failed");
                }
            }
            return;
        }
        if self.shift_restore.is_some() {
            return;
        }
        let Some((current, (lo, hi))) = juhradiald::actions::read_dpi().await else {
            warn!("DPI shift: the mouse's DPI is not readable");
            return;
        };
        let shift = pointer_setting("dpi_shift")
            .and_then(|v| v.as_u64())
            .and_then(|d| u16::try_from(d).ok())
            .unwrap_or(400)
            .clamp(lo, hi);
        match juhradiald::actions::write_dpi(shift).await {
            Ok(()) => self.shift_restore = Some(current),
            Err(e) => error!(error = %e, dpi = shift, "DPI shift failed"),
        }
    }

    /// DPI cycle while gaming mode is on: the next gaming preset, one pulse
    /// per stage. False when gaming mode is off (the normal cycle runs).
    async fn gaming_cycle(&self) -> bool {
        let gaming = self.gaming_mode.clone();
        let cycled = tokio::task::spawn_blocking(move || {
            let mut gm = gaming.write().ok()?;
            if !gm.is_enabled() {
                return None;
            }
            gm.cycle_dpi()?;
            Some((gm.active_dpi(), gm.stage().0 + 1, gm.dpi_pulse()))
        })
        .await
        .ok()
        .flatten();
        let Some((dpi, stage, pulse)) = cycled else { return false };
        if pulse {
            juhradiald::actions::pulse_times(HapticEvent::DpiChange, stage);
        }
        if let Some(dpi) = dpi {
            let _ = self
                .connection
                .emit_signal(None::<&str>, DBUS_PATH, "org.kde.juhradialmx.Daemon", "DpiChanged", &(dpi,))
                .await;
        }
        true
    }

    async fn toggle_gaming(&self) {
        let gaming = self.gaming_mode.clone();
        // enable()/disable() write the DPI over HID++ (blocking).
        let enabled = tokio::task::spawn_blocking(move || {
            let mut gm = gaming.write().ok()?;
            let on = !gm.is_enabled();
            if on {
                gm.enable();
            } else {
                gm.disable();
            }
            Some(on)
        })
        .await
        .ok()
        .flatten();
        if let Some(enabled) = enabled {
            info!(enabled, "Gaming mode toggled by a button");
            let _ = self
                .connection
                .emit_signal(None::<&str>, DBUS_PATH, "org.kde.juhradialmx.Daemon", "GamingModeChanged", &(enabled,))
                .await;
        }
    }
}

/// A `pointer.<key>` value from config.json.
fn pointer_setting(key: &str) -> Option<serde_json::Value> {
    juhradiald::replay::load_raw_config().get("pointer")?.get(key).cloned()
}

/// Tell Settings which physical button was pressed (it lights the pin).
/// Detached, so the press itself (ring, action) never waits on the bus.
fn emit_button_pressed(connection: &zbus::Connection, cid: u16) {
    let connection = connection.clone();
    tokio::spawn(async move {
        if let Err(e) = connection
            .emit_signal(None::<&str>, DBUS_PATH, "org.kde.juhradialmx.Daemon", "ButtonPressed", &(cid,))
            .await
        {
            tracing::trace!(error = %e, "Failed to emit ButtonPressed");
        }
    });
}

/// Run a button's custom action (Settings > Buttons > Custom): a recorded
/// shortcut, a command, a URL, a saved macro or a plugin action.
/// Run a custom action for one edge of its button or key: hold-while-pressed
/// shortcuts go down on press and up on release, everything else runs once on
/// press.
async fn run_custom_action(
    custom: &juhradiald::config::CustomAction,
    macro_engine: &Arc<Mutex<juhradiald::macros::MacroEngine>>,
    pressed: bool,
) {
    use juhradiald::actions::{Action, ActionExecutor, ActionType};
    let value = custom.value.trim();
    if value.is_empty() {
        if pressed {
            warn!(kind = %custom.kind, "Custom button action has no value");
        }
        return;
    }
    if custom.kind == "shortcut" && custom.hold {
        if let Err(e) = juhradiald::actions::shortcut_edge(value, pressed) {
            error!(error = %e, "Held shortcut failed");
        }
        return;
    }
    if !pressed {
        return;
    }
    let result = match custom.kind.as_str() {
        // Not trimmed: leading/trailing spaces are part of the text.
        // Off the button/keypad loop: a slow clipboard must not stall input.
        "text" => {
            let (text, with, enter) = (custom.value.clone(), custom.paste_with.clone(), custom.enter);
            tokio::spawn(async move {
                if let Err(e) = juhradiald::actions::paste_text(&text, &with, enter).await {
                    error!(kind = "text", error = %e, "Custom button action failed");
                }
            });
            Ok(())
        }
        "shortcut" => ActionExecutor::execute(&Action {
            action_type: ActionType::Shortcut(value.to_string()),
            label: None,
            icon: None,
        })
        .await
        .map_err(|e| e.to_string()),
        "command" => ActionExecutor::execute(&Action {
            action_type: ActionType::Command(value.to_string()),
            label: None,
            icon: None,
        })
        .await
        .map_err(|e| e.to_string()),
        "url" => juhradiald::actions::open_url(value).map_err(|e| e.to_string()),
        "macro" => match juhradiald::macros::storage::load_macro(value) {
            Ok(config) => match macro_engine.lock() {
                Ok(mut engine) => {
                    engine.execute(config);
                    Ok(())
                }
                Err(e) => Err(e.to_string()),
            },
            Err(e) => Err(e.to_string()),
        },
        "page" => {
            juhradiald::keypad::request_page(value);
            Ok(())
        }
        "plugin" => juhradiald::plugins::run(&juhradiald::plugins::plugins_dir(), value)
            .await
            .map_err(|e| e.to_string()),
        other => Err(format!("unknown custom action kind {other:?}")),
    };
    if let Err(e) = result {
        error!(kind = %custom.kind, error = %e, "Custom button action failed");
    }
}

/// Write the effective pointer/scroll state to the mouse. False when a write
/// failed (the next trigger retries).
async fn replay_pointer_state(
    manager: SharedHapticManager,
    ctx: juhradiald::replay::ReplayContext,
    unit_key: Option<String>,
) -> bool {
    let result = tokio::task::spawn_blocking(move || {
        let state = ctx.effective(unit_key.as_deref());
        if state == juhradiald::replay::DeviceState::default() {
            return (0, 0);
        }
        match manager.lock() {
            Ok(mut m) => juhradiald::replay::apply(&mut *m, &state),
            Err(_) => (0, 1),
        }
    })
    .await
    .unwrap_or((0, 1));
    let (tried, failed) = result;
    if tried > 0 || failed > 0 {
        info!(tried, failed, "Replayed pointer and scroll state");
    }
    // Mouse and keyboard move together needs the mouse's slots cached while
    // it is here (a device that has left cannot be read).
    if juhradiald::replay::load_raw_config()
        .pointer("/keyboard/mx_keys/move_together")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        if let Some(m) = juhradiald::actions::device_manager() {
            let _ = tokio::task::spawn_blocking(move || {
                if let Ok(mut m) = m.lock() {
                    let slots = m.host_slots();
                    let current = m.get_easy_switch_info().map(|(_, c)| c);
                    juhradiald::easy_switch::remember_mouse(slots, current);
                }
            })
            .await;
        }
    }
    failed == 0
}

async fn run_hidraw_loop(
    event_tx: mpsc::Sender<GestureEvent>,
    startup: HidrawStartup,
    trigger_map: juhradiald::macros::SharedTriggerMap,
    shared_config: juhradiald::config::SharedConfig,
    hotplug: Arc<tokio::sync::Notify>,
    haptic_manager: SharedHapticManager,
    kwin: KWinContext,
    dbus_connection: zbus::Connection,
    device_name_state: SharedDeviceName,
) {
    let HidrawStartup {
        mut preferred_path,
        gesture_tracker,
        replay,
    } = startup;
    let mut replay_gate = juhradiald::replay::ReplayGate::default();
    let mut handler = HidrawHandler::new(event_tx);
    let config_for_thumbwheel = shared_config.clone();
    let config_for_divert = shared_config.clone();
    // Macro-bound buttons, as bound right now (ReloadMacroTriggers).
    let macro_cids_now = {
        let map = trigger_map.clone();
        move || -> Vec<u16> { map.read().map(|m| m.cids().into_iter().collect()).unwrap_or_default() }
    };
    handler.set_trigger_map(trigger_map);
    handler.set_shared_config(shared_config);
    handler.set_kwin_availability(kwin.availability);
    handler.set_kwin_scripting(kwin.scripting);
    handler.set_gaming_mode(kwin.gaming);
    handler.set_gesture_tracker(gesture_tracker);

    loop {
        // Re-read the reassigned buttons each cycle so a config change is
        // picked up on the next reconnect (live changes go through ReloadConfig).
        let remapped_cids = config_for_divert
            .read()
            .map(|c| c.remapped_button_cids())
            .unwrap_or_default();
        let (path, name, unit) = refresh_hidpp_button_diverts(
            haptic_manager.clone(),
            macro_cids_now(),
            remapped_cids,
        )
        .await;
        let refreshed = path.is_some();
        if let Some(path) = path {
            preferred_path = Some(path);
        }
        {
            use juhradiald::link_state::{report, LinkState, Transport};
            let (transport, index, known) = haptic_manager
                .lock()
                .map(|m| (m.connection_type(), m.device_index(), m.device_path().is_some()))
                .unwrap_or((None, None, false));
            handler.set_mouse_device_index(index);
            if refreshed {
                report(LinkState::Connected, transport.map(Transport::from));
            } else if known {
                report(LinkState::Asleep, None);
            } else {
                report(LinkState::Offline, None);
            }
        }
        // A different mouse (or the first connect after startup without one)
        // selects its own `devices.<unit>` overrides; when they change the
        // button map, divert once more so the new map is live immediately.
        if let Some(unit) = unit {
            let key = juhradiald::config::Config::unit_key(unit);
            let is_new = config_for_divert
                .read()
                .map(|c| c.active_unit.as_deref() != Some(key.as_str()))
                .unwrap_or(false);
            if is_new {
                let applied = config_for_divert
                    .write()
                    .map(|mut c| c.apply_device_overrides(&key))
                    .unwrap_or(false);
                info!(unit = %key, applied, "Per-device overrides selected for the connected mouse");
                if applied {
                    let remapped = config_for_divert
                        .read()
                        .map(|c| c.remapped_button_cids())
                        .unwrap_or_default();
                    let _ = refresh_hidpp_button_diverts(
                        haptic_manager.clone(),
                        macro_cids_now(),
                        remapped,
                    )
                    .await;
                }
            }
        }
        if let Some(name) = name {
            let changed = {
                let current = device_name_state.read().await;
                *current != name
            };
            if changed {
                info!(name = %name, "HID++ device name updated");
                *device_name_state.write().await = name.clone();
                if let Err(e) = dbus_connection
                    .emit_signal(
                        None::<&str>,
                        DBUS_PATH,
                        "org.kde.juhradialmx.Daemon",
                        "DeviceNameRefreshed",
                        &(name,),
                    )
                    .await
                {
                    warn!(error = %e, "Failed to emit DeviceNameRefreshed signal");
                }
            }
        }

        // Re-apply thumb-wheel divert (volatile) and refresh the feature index
        // the reader uses to route rotation notifications.
        let tw_index =
            apply_thumbwheel_reporting(haptic_manager.clone(), config_for_thumbwheel.clone()).await;
        handler.set_thumbwheel_feature_index(tw_index);

        // Refresh notification feature indices for live hardware readback. Like
        // diverts, these are cheap to re-fetch on every (re)connect and keep the
        // reader correct across hotplug/host-switch re-enumeration.
        let note_indices = fetch_notification_indices(haptic_manager.clone()).await;
        handler.set_notification_indices(note_indices);

        // The mouse answered: re-apply DPI, SmartShift, hi-res and natural
        // scroll (they do not survive every wake/host return), once per wake.
        // Runs before the listener opens so replies never interleave with it.
        if refreshed && replay_gate.should_run(Instant::now()) {
            let unit_key = config_for_divert
                .read()
                .ok()
                .and_then(|c| c.active_unit.clone());
            if replay_pointer_state(haptic_manager.clone(), replay.clone(), unit_key).await {
                replay_gate.record_success(Instant::now());
            }
        }

        // The manager's device path is ping-verified: it is the receiver
        // interface where the mouse actually answered HID++, and therefore
        // where its diverted notifications arrive. With more than one
        // receiver plugged in, blind auto-detect ties on priority and can
        // open the other receiver, leaving the listener deaf. The manager
        // may also have been connected by the battery updater even when the
        // refresh above found nothing, so always prefer its live path.
        if let Some(path) = haptic_manager.lock().ok().and_then(|m| m.device_path()) {
            preferred_path = Some(path);
        }

        // Try to open - use preferred path from HidppDevice if available
        // This ensures we listen on the same Bolt receiver where buttons were diverted
        let open_result = if let Some(ref path) = preferred_path {
            match handler.open_path(path) {
                Ok(()) => Ok(()),
                Err(HidrawError::DeviceNotFound) => {
                    warn!(
                        path = %path.display(),
                        "Preferred hidraw path disappeared, falling back to auto-detect"
                    );
                    preferred_path = None;
                    handler.open()
                }
                Err(e) => Err(e),
            }
        } else {
            handler.open()
        };

        let mut retry_immediately = false;
        match open_result {
            Ok(()) => {
                if let Some(path) = handler.device_path() {
                    preferred_path = Some(path);
                }
                info!("HID++ hidraw handler connected");

                // Run the event loop until error, until input hotplug tells
                // us the mouse may have returned from another Easy-Switch
                // host, or until the HID++ manager turns out to be connected
                // on a different node than we opened (the deaf-listener state
                // a second plugged-in receiver can produce: no events arrive,
                // so nothing else would ever re-trigger this loop).
                let listener_path = handler.device_path();
                let start_result = tokio::select! {
                    result = handler.start() => Some(result),
                    _ = hotplug.notified() => None,
                    _ = hidraw_listener_mismatch(&haptic_manager, listener_path) => {
                        info!("HID++ manager connected on a different node; re-binding event listener");
                        None
                    }
                };
                handler.close();

                match start_result {
                    Some(Ok(())) => {
                        if handler.take_divert_refresh_needed() {
                            // The mouse announced it came back online (power
                            // switch / radio sleep); its volatile diverts are
                            // gone. Loop immediately so the refresh path above
                            // re-applies them (issue #102).
                            info!("Device back online, re-applying HID++ diverts");
                            retry_immediately = true;
                        } else {
                            info!("HID++ event loop ended normally");
                        }
                    }
                    Some(Err(HidrawError::DeviceNotFound)) => {
                        warn!("HID++ device disconnected, will poll for reconnection...");
                    }
                    Some(Err(HidrawError::PermissionDenied)) => {
                        error!(
                            "Permission denied for hidraw device. Ensure udev rules are installed."
                        );
                    }
                    Some(Err(HidrawError::IoError(e))) => {
                        error!("HID++ I/O error: {}. Will retry...", e);
                    }
                    None => {
                        info!("Device hotplug detected, refreshing HID++ button listener");
                        retry_immediately = true;
                    }
                }
            }
            Err(HidrawError::DeviceNotFound) => {
                // Device not found, this is expected during polling
                info!(
                    "Waiting for Bolt receiver hidraw device... (polling every {}s)",
                    HIDRAW_RECONNECT_POLL_INTERVAL_SECS
                );
            }
            Err(HidrawError::PermissionDenied) => {
                error!("Permission denied accessing hidraw devices.");
                error!("Ensure udev rules are installed.");
            }
            Err(HidrawError::IoError(e)) => {
                error!("I/O error during hidraw scan: {}", e);
            }
        }

        if retry_immediately {
            continue;
        }

        // Wait for either the shorter HID++ reconnect poll or device hotplug.
        tokio::select! {
            _ = sleep(Duration::from_secs(HIDRAW_RECONNECT_POLL_INTERVAL_SECS)) => {}
            _ = hotplug.notified() => {
                debug!("Device hotplug detected, re-scanning HID++ devices");
            }
        }
    }
}

/// Run the evdev device detection and event loop
///
/// This function handles:
/// - Initial device detection
/// - Polling for device when not found (2-second intervals)
/// - Reconnection after device disconnect
/// - Instant re-scan on device hotplug (via inotify)
async fn run_evdev_loop(
    event_tx: mpsc::Sender<GestureEvent>,
    suppressed_keys: HashSet<u16>,
    hotplug: Arc<tokio::sync::Notify>,
    shared_config: juhradiald::config::SharedConfig,
    kwin: KWinContext,
    gesture_tracker: juhradiald::gesture::SharedGestureTracker,
    trigger_map: juhradiald::macros::SharedTriggerMap,
) {
    let mut handler = EvdevHandler::new(event_tx.clone());
    handler.set_suppressed_keys(suppressed_keys);
    handler.set_live_suppression(trigger_map);
    handler.set_shared_config(shared_config);
    handler.set_kwin_availability(kwin.availability);
    handler.set_kwin_scripting(kwin.scripting);
    handler.set_gaming_mode(kwin.gaming);
    handler.set_gesture_tracker(gesture_tracker);

    let mut logged_waiting = false;

    loop {
        // Try to find and connect to the device
        match EvdevHandler::find_device() {
            Ok(device_info) => {
                logged_waiting = false;
                info!(
                    "Detected MX Master 4 at {:?} ({})",
                    device_info.path, device_info.name
                );

                // Run the event loop until device disconnect OR hotplug. The
                // grabbed fd lives inside start(); without the hotplug arm a
                // re-enumeration that leaves the old node present kept the
                // loop glued to a dead grab. Cancelling start() drops its
                // device handle, which closes the fd and releases the grab.
                let start_result = tokio::select! {
                    result = handler.start() => Some(result),
                    _ = hotplug.notified() => None,
                };
                match start_result {
                    Some(Ok(())) => {
                        info!("Event loop ended normally");
                    }
                    Some(Err(EvdevError::DeviceNotFound)) => {
                        warn!("Device disconnected, will poll for reconnection...");
                        logged_waiting = false;
                    }
                    Some(Err(EvdevError::PermissionDenied)) => {
                        error!("Permission denied. Ensure udev rules are installed.");
                        error!("Run: sudo usermod -aG input $USER && logout");
                        // Continue polling in case permissions are fixed
                    }
                    Some(Err(EvdevError::IoError(e))) => {
                        error!("I/O error: {}. Will retry...", e);
                    }
                    None => {
                        info!("Device hotplug detected, re-scanning MX devices");
                        logged_waiting = false;
                        continue;
                    }
                }
            }
            Err(EvdevError::DeviceNotFound) => {
                if !logged_waiting {
                    info!("MX Master 4 not found via evdev - polling in background");
                    logged_waiting = true;
                }
            }
            Err(EvdevError::PermissionDenied) => {
                error!("Permission denied accessing input devices.");
                error!("Ensure udev rules are installed and user is in 'input' group.");
            }
            Err(EvdevError::IoError(e)) => {
                error!("I/O error during device scan: {}", e);
            }
        }

        // Wait for either poll interval OR instant hotplug notification
        tokio::select! {
            _ = sleep(Duration::from_secs(DEVICE_POLL_INTERVAL_SECS)) => {}
            _ = hotplug.notified() => {
                debug!("Device hotplug detected, re-scanning MX devices");
                logged_waiting = false;
            }
        }
    }
}

/// Read generic_trigger_button from ~/.config/juhradial/config.json
fn read_trigger_button_from_config() -> Option<u16> {
    let home = std::env::var("HOME").ok()?;
    let path = std::path::PathBuf::from(home).join(".config/juhradial/config.json");
    let data = std::fs::read_to_string(&path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&data).ok()?;
    json.get("generic_trigger_button")?
        .as_u64()
        .map(|v| v as u16)
}

/// Read device_mode from ~/.config/juhradial/config.json
///
/// Returns "generic", "logitech", or "auto" (default).
/// When the user toggles "Generic" in settings, this is set to "generic".
fn read_device_mode_from_config() -> String {
    let home = match std::env::var("HOME") {
        Ok(h) => h,
        Err(_) => return "auto".to_string(),
    };
    let path = std::path::PathBuf::from(home).join(".config/juhradial/config.json");
    let data = match std::fs::read_to_string(&path) {
        Ok(d) => d,
        Err(_) => return "auto".to_string(),
    };
    let json: serde_json::Value = match serde_json::from_str(&data) {
        Ok(j) => j,
        Err(_) => return "auto".to_string(),
    };
    json.get("device_mode")
        .and_then(|v| v.as_str())
        .unwrap_or("auto")
        .to_string()
}

/// Run the generic mouse evdev detection and event loop
///
/// Same as run_evdev_loop but uses find_any_mouse() and configurable trigger button.
/// This is the fallback when no Logitech MX device is found.
async fn run_generic_evdev_loop(
    event_tx: mpsc::Sender<GestureEvent>,
    suppressed_keys: HashSet<u16>,
    hotplug: Arc<tokio::sync::Notify>,
    shared_config: juhradiald::config::SharedConfig,
    kwin: KWinContext,
) {
    let trigger = read_trigger_button_from_config();
    if let Some(code) = trigger {
        info!("Generic trigger button from config: {:#x}", code);
    }
    let mut handler = EvdevHandler::new_generic(event_tx.clone(), trigger);
    handler.set_suppressed_keys(suppressed_keys);
    handler.set_shared_config(shared_config);
    handler.set_kwin_availability(kwin.availability);
    handler.set_kwin_scripting(kwin.scripting);
    handler.set_gaming_mode(kwin.gaming);

    let mut logged_waiting = false;

    loop {
        // Re-read trigger button from config on each reconnect cycle
        // so rebinds in settings take effect without daemon restart
        if let Some(code) = read_trigger_button_from_config() {
            handler.set_trigger_button(code);
        }

        // Try to find any generic mouse
        match EvdevHandler::find_any_mouse() {
            Ok(device_info) => {
                logged_waiting = false;
                info!(
                    "Detected generic mouse at {:?} ({})",
                    device_info.path, device_info.name
                );

                // Run the event loop until device disconnects
                match handler.start().await {
                    Ok(()) => {
                        info!("Generic mouse event loop ended normally");
                    }
                    Err(EvdevError::DeviceNotFound) => {
                        warn!("Generic mouse disconnected, will poll for reconnection...");
                        logged_waiting = false;
                    }
                    Err(EvdevError::PermissionDenied) => {
                        error!("Permission denied. Ensure udev rules are installed.");
                        error!("Run: sudo usermod -aG input $USER && logout");
                    }
                    Err(EvdevError::IoError(e)) => {
                        error!("I/O error: {}. Will retry...", e);
                    }
                }
            }
            Err(EvdevError::DeviceNotFound) => {
                // Only log once to avoid spamming every 2s when no generic mouse exists
                if !logged_waiting {
                    info!("No generic mouse found - polling in background");
                    logged_waiting = true;
                }
            }
            Err(EvdevError::PermissionDenied) => {
                error!("Permission denied accessing input devices.");
                error!("Ensure udev rules are installed and user is in 'input' group.");
            }
            Err(EvdevError::IoError(e)) => {
                error!("I/O error during device scan: {}", e);
            }
        }

        // Wait for either poll interval OR instant hotplug notification
        tokio::select! {
            _ = sleep(Duration::from_secs(DEVICE_POLL_INTERVAL_SECS)) => {}
            _ = hotplug.notified() => {
                debug!("Device hotplug detected, re-scanning generic mice immediately");
                logged_waiting = false; // Re-log status after hotplug
            }
        }
    }
}

/// Forward one event, including its batch and source, to the stateful dispatcher.
/// Releases must still reach it to end held DPI-shift actions.
async fn dispatch_button_action_event_with<Executor, Execution>(event: GestureEvent, execute: Executor)
where
    Executor: FnOnce(juhradiald::config::ButtonAction, bool, Option<u16>, u8) -> Execution,
    Execution: std::future::Future<Output = ()>,
{
    if let GestureEvent::ButtonActionEvent { action, pressed, source, repeats } = event {
        execute(action, pressed, source, repeats).await;
    }
}

/// Process gesture events from the evdev handler
///
/// Press triggers ydotool injection -> cursor_grabber catches -> emits ShowMenu
/// Release emits HideMenu directly
/// MacroTriggered events are checked against the TriggerMap for macro execution
async fn process_gesture_events(
    event_rx: &mut mpsc::Receiver<GestureEvent>,
    dbus_connection: &zbus::Connection,
    trigger_map: Arc<std::sync::RwLock<juhradiald::macros::TriggerMap>>,
    battery_state: SharedBatteryState,
    hotplug: Arc<tokio::sync::Notify>,
    mut actions: ActionContext,
) {
    let shared_config = actions.config.clone();
    let macro_engine = actions.macro_engine.clone();
    // A gaming action the ring button started (its release ends it).
    let mut ring_action_held: Option<juhradiald::config::ButtonAction> = None;
    while let Some(event) = event_rx.recv().await {
        match event {
            GestureEvent::GestureReleased { dx, dy, duration_ms } => {
                // Directional gesture: classify the drag and run the configured
                // action. This path never touches ShowMenu/HideMenu.
                let resolved = shared_config.read().ok().map(|cfg| {
                    let direction = juhradiald::gesture::classify(
                        dx,
                        dy,
                        cfg.buttons.gesture_directions.threshold_px,
                    );
                    (direction, cfg.gesture_direction_action(direction))
                });
                match resolved {
                    Some((
                        direction,
                        action @ (juhradiald::config::ButtonAction::RadialMenu
                        | juhradiald::config::ButtonAction::DpiShift),
                    )) => {
                        // A drag has no hold to show the ring for or to keep
                        // the precision DPI during.
                        warn!(?direction, %action, "not a directional gesture action; ignoring");
                    }
                    Some((direction, action)) => {
                        info!(duration_ms, dx, dy, ?direction, %action, "Directional gesture");
                        actions.run(action, true, None, 1).await;
                    }
                    None => warn!("Directional gesture dropped: config lock poisoned"),
                }
            }
            GestureEvent::Pressed { x, y } => {
                // In a game the ring button can do a gaming job instead.
                let ring = actions.gaming_mode.read().ok().and_then(|gm| gm.ring_action());
                if let Some(action) = ring {
                    info!(%action, "Ring button in a game");
                    ring_action_held = Some(action);
                    actions.run(action, true, None, 1).await;
                    continue;
                }
                // HID++ hidraw handler provides cursor coordinates directly
                info!(x, y, "Gesture button pressed - showing radial menu");

                // Emit ShowMenu via D-Bus
                if let Err(e) = emit_menu_requested(dbus_connection, x, y).await {
                    error!("Failed to emit ShowMenu signal: {}", e);
                }
            }
            GestureEvent::Released { duration_ms } => {
                if let Some(action) = ring_action_held.take() {
                    actions.run(action, false, None, 1).await;
                    continue;
                }
                info!(duration_ms, "Gesture button released");

                // Emit HideMenu signal via D-Bus
                // Overlay tracks duration internally for tap-to-toggle detection
                if let Err(e) = emit_hide_menu(dbus_connection).await {
                    error!("Failed to emit HideMenu signal: {}", e);
                }
            }
            GestureEvent::CursorMoved { x, y } => {
                // Emit CursorMoved signal for overlay hover detection
                // x, y are relative to button press point (menu center)
                if let Err(e) = emit_cursor_moved(dbus_connection, x, y).await {
                    // Don't log errors for every cursor move - too noisy
                    tracing::trace!("Failed to emit CursorMoved: {}", e);
                }
            }
            GestureEvent::MacroTriggered { key_code, pressed } => {
                if pressed {
                    if let Some(cid) = juhradiald::hidraw::evdev_keycode_to_cid(key_code) {
                        emit_button_pressed(dbus_connection, cid);
                    }
                }
                // Look up TriggerMap for a macro bound to this button
                let macro_id = {
                    match trigger_map.read() {
                        Ok(map) => map.get(key_code).map(|s| s.to_string()),
                        Err(e) => {
                            error!("Failed to read trigger map: {}", e);
                            None
                        }
                    }
                };

                if let Some(id) = macro_id {
                    if pressed {
                        // Button pressed - load and execute the macro
                        match juhradiald::macros::storage::load_macro(&id) {
                            Ok(config) => {
                                info!(
                                    macro_id = %id,
                                    macro_name = %config.name,
                                    key_code = format!("0x{:03x}", key_code),
                                    mode = ?config.repeat_mode,
                                    "Macro triggered by button press"
                                );
                                match macro_engine.lock() {
                                    Ok(mut engine) => engine.execute(config),
                                    Err(e) => error!("Failed to lock macro engine: {}", e),
                                }
                            }
                            Err(e) => {
                                warn!(macro_id = %id, error = %e, "Failed to load triggered macro");
                            }
                        }
                    } else {
                        // Button released - stop if WhileHolding or Sequence mode
                        match macro_engine.lock() {
                            Ok(mut engine) => {
                                if engine.should_stop_on_release() {
                                    info!(macro_id = %id, "Macro stopped on button release");
                                    engine.stop();
                                }
                            }
                            Err(e) => error!("Failed to lock macro engine: {}", e),
                        }
                    }
                }
            }
            event @ GestureEvent::ButtonActionEvent { pressed, source, .. } => {
                if pressed {
                    if let Some(cid) = source {
                        emit_button_pressed(dbus_connection, cid);
                    }
                }
                dispatch_button_action_event_with(event, |action, pressed, source, repeats| {
                    actions.run(action, pressed, source, repeats)
                }).await;
            }
            GestureEvent::ButtonSeen { cid } => {
                emit_button_pressed(dbus_connection, cid);
            }
            GestureEvent::ThumbwheelScroll { clicks } => {
                tracing::debug!(clicks, "Thumb-wheel horizontal scroll");
                if let Err(e) = juhradiald::actions::execute_horizontal_scroll(clicks).await {
                    error!(clicks, error = %e, "Failed to inject horizontal scroll");
                }
            }
            GestureEvent::Hardware(note) => {
                if let Err(e) =
                    emit_hardware_notification(dbus_connection, &battery_state, &hotplug, note)
                        .await
                {
                    tracing::warn!(?note, error = %e, "Failed to emit hardware notification signal");
                }
            }
        }
    }
}

/// Emit the D-Bus change signal for a decoded live hardware notification.
///
/// Broadcast directly on the connection (empty destination) so any subscribed
/// client receives it, mirroring the HideMenu/CursorMoved emit pattern.
async fn emit_hardware_notification(
    connection: &zbus::Connection,
    battery_state: &SharedBatteryState,
    hotplug: &tokio::sync::Notify,
    note: juhradiald::hidpp::notifications::HardwareNotification,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use juhradiald::hidpp::notifications::HardwareNotification as HN;
    let iface = "org.kde.juhradialmx.Daemon";
    match note {
        HN::BatteryChanged { percent, status } => {
            info!(percent, status, "Battery changed (notification)");
            // Cache so GetBatteryStatus reports the live value even while the
            // active poll is failing (e.g. shared hidraw handle churning).
            {
                let mut s = battery_state.write().await;
                s.percentage = percent;
                s.charging = matches!(status, "charging" | "full");
                s.available = true;
                s.error = None;
            }
            connection
                .emit_signal(None::<&str>, DBUS_PATH, iface, "BatteryChanged", &(percent, status))
                .await?;
        }
        HN::RatchetChanged { ratchet } => {
            info!(ratchet, "Ratchet changed (notification)");
            connection
                .emit_signal(None::<&str>, DBUS_PATH, iface, "RatchetChanged", &(ratchet,))
                .await?;
        }
        HN::HostChanged { host, next } => {
            info!(host, ?next, "Easy-Switch host changed (notification)");
            // The mouse's own Easy-Switch button: take the keyboard along.
            let together = juhradiald::replay::load_raw_config()
                .pointer("/keyboard/mx_keys/move_together")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if let Some(slot) = next.filter(|_| together).and_then(|to| juhradiald::easy_switch::mouse_left(host, to)) {
                juhradiald::easy_switch::move_keyboard(slot);
            }
            // Volatile button diverts + thumb-wheel reporting are lost when the
            // mouse returns from another Easy-Switch host. Wake run_hidraw_loop
            // (the same path device hotplug uses) so it re-applies them.
            hotplug.notify_waiters();
            connection
                .emit_signal(None::<&str>, DBUS_PATH, iface, "HostChanged", &(host,))
                .await?;
        }
        HN::DpiChanged { dpi } => {
            info!(dpi, "DPI changed (notification)");
            connection
                .emit_signal(None::<&str>, DBUS_PATH, iface, "DpiChanged", &(dpi,))
                .await?;
        }
        HN::DeviceConnected => {
            // Handled inside the hidraw reader (divert refresh, issue #102);
            // nothing to surface on D-Bus.
            debug!("Device connected (notification)");
        }
    }
    Ok(())
}

/// Emit MenuRequested signal via D-Bus
///
/// Calls the ShowMenu method on our own D-Bus service, which triggers
/// the MenuRequested signal for the overlay.
///
/// Emit MenuRequested signal via D-Bus to show radial menu.
/// Called when gesture button is pressed (via HID++ hidraw handler).
async fn emit_menu_requested(
    connection: &zbus::Connection,
    x: i32,
    y: i32,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use zbus::proxy::Proxy;

    let proxy = Proxy::new(
        connection,
        DBUS_NAME,
        DBUS_PATH,
        "org.kde.juhradialmx.Daemon",
    )
    .await?;

    proxy.call_method("ShowMenu", &(x, y)).await?;

    Ok(())
}

/// Emit HideMenu signal via D-Bus (Story 2.7)
///
/// Emits HideMenu signal to dismiss the overlay.
/// Overlay tracks time internally for tap-to-toggle detection.
async fn emit_hide_menu(
    connection: &zbus::Connection,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Emit signal directly (no parameters)
    connection
        .emit_signal(
            None::<&str>, // destination (None = broadcast)
            DBUS_PATH,
            "org.kde.juhradialmx.Daemon",
            "HideMenu",
            &(),
        )
        .await?;

    info!("HideMenu signal emitted");
    Ok(())
}

/// Emit CursorMoved signal via D-Bus
///
/// Broadcasts cursor position updates for overlay hover detection.
/// x, y are relative offsets from the menu center (button press point).
async fn emit_cursor_moved(
    connection: &zbus::Connection,
    x: i32,
    y: i32,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Emit signal directly without going through a method
    connection
        .emit_signal(
            None::<&str>, // destination (None = broadcast)
            DBUS_PATH,
            "org.kde.juhradialmx.Daemon",
            "CursorMoved",
            &(x, y),
        )
        .await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use juhradiald::cursor::{CursorPosition, EDGE_MARGIN, MENU_RADIUS, ScreenBounds};

    #[test]
    fn test_device_poll_interval() {
        // Steady-state input scans stay infrequent; hidraw reconnects use the
        // shorter cadence after Easy-Switch or hotplug events.
        assert_eq!(DEVICE_POLL_INTERVAL_SECS, 60);
        assert_eq!(HIDRAW_RECONNECT_POLL_INTERVAL_SECS, 5);
    }

    // --- hotplug self-caused filter (issues #121/#125) ---

    use notify::event::{CreateKind, RemoveKind};
    use notify::EventKind;
    use std::collections::HashSet;
    use std::path::{Path, PathBuf};

    fn vdev_name_for<'a>(vdev_paths: &'a [&'a str]) -> impl Fn(&Path) -> Option<String> + 'a {
        move |p: &Path| {
            if vdev_paths.iter().any(|v| Path::new(v) == p) {
                Some(juhradiald::evdev::VIRTUAL_DEVICE_NAME.to_string())
            } else {
                Some("Logitech MX Master 4".to_string())
            }
        }
    }

    #[test]
    fn create_of_own_vdev_is_self_caused_and_recorded() {
        let mut own = HashSet::new();
        let paths = vec![PathBuf::from("/dev/input/event257")];
        assert!(hotplug_event_is_self_caused(
            &EventKind::Create(CreateKind::File),
            &paths,
            &mut own,
            vdev_name_for(&["/dev/input/event257"]),
        ));
        assert!(own.contains(Path::new("/dev/input/event257")));
    }

    #[test]
    fn create_of_unknown_device_is_real_hotplug() {
        let mut own = HashSet::new();
        let paths = vec![PathBuf::from("/dev/input/event256")];
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Create(CreateKind::File),
            &paths,
            &mut own,
            vdev_name_for(&[]),
        ));
        assert!(own.is_empty());
    }

    #[test]
    fn remove_of_recorded_vdev_is_self_caused_and_consumed() {
        let mut own = HashSet::new();
        own.insert(PathBuf::from("/dev/input/event257"));
        let paths = vec![PathBuf::from("/dev/input/event257")];
        // A removed node has no sysfs entry left; the name resolver must not
        // be consulted for Removes.
        assert!(hotplug_event_is_self_caused(
            &EventKind::Remove(RemoveKind::File),
            &paths,
            &mut own,
            |_: &Path| None,
        ));
        assert!(own.is_empty());
    }

    #[test]
    fn remove_of_unknown_device_is_real_hotplug() {
        let mut own = HashSet::new();
        let paths = vec![PathBuf::from("/dev/input/event29")];
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Remove(RemoveKind::File),
            &paths,
            &mut own,
            |_: &Path| None,
        ));
    }

    #[test]
    fn reused_event_number_after_vdev_removal_is_real_hotplug() {
        // The kernel reuses event numbers: after our vdev at event257 is
        // removed (and consumed above), a real device can appear at event257.
        let mut own = HashSet::new();
        own.insert(PathBuf::from("/dev/input/event257"));
        let remove = vec![PathBuf::from("/dev/input/event257")];
        assert!(hotplug_event_is_self_caused(
            &EventKind::Remove(RemoveKind::File),
            &remove,
            &mut own,
            |_: &Path| None,
        ));
        let create = vec![PathBuf::from("/dev/input/event257")];
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Create(CreateKind::File),
            &create,
            &mut own,
            vdev_name_for(&[]),
        ));
    }

    #[test]
    fn create_with_non_vdev_name_evicts_stale_entry() {
        // If the vdev's Remove was lost (queue overflow) and the kernel
        // reused the number for a real device, its Create must evict the
        // stale record so the real device's later Remove counts as real.
        let mut own = HashSet::new();
        own.insert(PathBuf::from("/dev/input/event257"));
        let create = vec![PathBuf::from("/dev/input/event257")];
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Create(CreateKind::File),
            &create,
            &mut own,
            vdev_name_for(&[]),
        ));
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Remove(RemoveKind::File),
            &create,
            &mut own,
            |_: &Path| None,
        ));
    }

    #[test]
    fn mixed_create_is_real_but_still_records_vdev_path() {
        let mut own = HashSet::new();
        let paths = vec![
            PathBuf::from("/dev/input/event256"),
            PathBuf::from("/dev/input/event257"),
        ];
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Create(CreateKind::File),
            &paths,
            &mut own,
            vdev_name_for(&["/dev/input/event257"]),
        ));
        // The vdev path must be recorded anyway, so its later Remove does not
        // count as a real unplug.
        assert!(own.contains(Path::new("/dev/input/event257")));
        assert!(hotplug_event_is_self_caused(
            &EventKind::Remove(RemoveKind::File),
            &[PathBuf::from("/dev/input/event257")],
            &mut own,
            |_: &Path| None,
        ));
    }

    #[test]
    fn access_events_are_never_self_caused() {
        // The watcher filters Access before this function runs (#15), but the
        // function itself must not misclassify them either.
        let mut own = HashSet::new();
        let paths = vec![PathBuf::from("/dev/input/event257")];
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Access(notify::event::AccessKind::Close(
                notify::event::AccessMode::Write
            )),
            &paths,
            &mut own,
            vdev_name_for(&["/dev/input/event257"]),
        ));
    }

    #[test]
    fn empty_path_list_is_not_self_caused() {
        let mut own = HashSet::new();
        assert!(!hotplug_event_is_self_caused(
            &EventKind::Create(CreateKind::File),
            &[],
            &mut own,
            |_: &Path| None,
        ));
    }

    #[test]
    fn test_args_default_config() {
        // Verify default config path
        let args = Args::parse_from(["juhradiald"]);
        assert_eq!(args.config, "~/.config/juhradial/config.json");
        assert!(!args.verbose);
        assert!(!args.list_devices);
    }

    #[test]
    fn test_args_verbose() {
        let args = Args::parse_from(["juhradiald", "--verbose"]);
        assert!(args.verbose);
    }

    #[test]
    fn test_args_list_devices() {
        let args = Args::parse_from(["juhradiald", "--list-devices"]);
        assert!(args.list_devices);
    }

    #[test]
    fn first_sighting_announces_each_app_once_case_insensitively() {
        let mut seen = HashSet::new();
        assert_eq!(first_sighting(&mut seen, "Firefox"), Some("firefox".to_string()));
        assert_eq!(first_sighting(&mut seen, "firefox"), None);
        assert_eq!(first_sighting(&mut seen, "FIREFOX "), None);
        assert_eq!(first_sighting(&mut seen, "org.kde.dolphin"), Some("org.kde.dolphin".to_string()));
        assert_eq!(first_sighting(&mut seen, ""), None);
        assert_eq!(first_sighting(&mut seen, "   "), None);
    }

    #[test]
    fn test_args_export_and_import_take_a_file_and_exclude_each_other() {
        let args = Args::parse_from(["juhradiald", "--export", "/tmp/backup.zip"]);
        assert_eq!(args.export.as_deref(), Some(Path::new("/tmp/backup.zip")));
        assert!(args.import.is_none());
        let args = Args::parse_from(["juhradiald", "--import", "b.zip"]);
        assert_eq!(args.import.as_deref(), Some(Path::new("b.zip")));
        assert!(Args::try_parse_from(["juhradiald", "--export", "a.zip", "--import", "b.zip"]).is_err());
        assert!(Args::try_parse_from(["juhradiald", "--export"]).is_err());
        let args = Args::parse_from(["juhradiald"]);
        assert!(args.export.is_none() && args.import.is_none());
    }

    #[tokio::test]
    async fn test_gesture_event_channel() {
        let (tx, mut rx) = mpsc::channel::<GestureEvent>(8);

        // Send press event
        tx.send(GestureEvent::Pressed { x: 100, y: 200 })
            .await
            .unwrap();

        // Receive and verify
        let event = rx.recv().await.unwrap();
        assert!(matches!(event, GestureEvent::Pressed { x: 100, y: 200 }));

        // Send release event
        tx.send(GestureEvent::Released { duration_ms: 500 })
            .await
            .unwrap();

        let event = rx.recv().await.unwrap();
        assert!(matches!(event, GestureEvent::Released { duration_ms: 500 }));
    }

    #[tokio::test]
    async fn test_rapid_press_handling() {
        // Test AC3: Rapid presses (5 in 1 second) should all be captured in order
        let (tx, mut rx) = mpsc::channel::<GestureEvent>(32);

        // Simulate 5 rapid press/release cycles
        for i in 0..5 {
            tx.send(GestureEvent::Pressed {
                x: i * 10,
                y: i * 10,
            })
            .await
            .unwrap();
            tx.send(GestureEvent::Released {
                duration_ms: 50 + (i as u64 * 10),
            })
            .await
            .unwrap();
        }

        // Verify all 10 events are received in order
        for i in 0..5 {
            let press = rx.recv().await.unwrap();
            assert!(matches!(press, GestureEvent::Pressed { x, y } if x == i * 10 && y == i * 10));

            let release = rx.recv().await.unwrap();
            assert!(
                matches!(release, GestureEvent::Released { duration_ms } if duration_ms == 50 + (i as u64 * 10))
            );
        }

        // Ensure no more events
        assert!(rx.try_recv().is_err());
    }

    // Story 2.3: Edge clamping tests
    #[test]
    fn test_edge_clamping_integration() {
        let bounds = ScreenBounds {
            width: 1920,
            height: 1080,
        };

        // Test near left edge
        let pos = CursorPosition::new(50, 540);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.x, EDGE_MARGIN + MENU_RADIUS); // 170

        // Test near top edge
        let pos = CursorPosition::new(960, 30);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.y, EDGE_MARGIN + MENU_RADIUS); // 170

        // Test bottom-right corner
        let pos = CursorPosition::new(1900, 1060);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.x, 1920 - EDGE_MARGIN - MENU_RADIUS); // 1750
        assert_eq!(clamped.y, 1080 - EDGE_MARGIN - MENU_RADIUS); // 910
    }

    #[test]
    fn test_cursor_position_within_bounds() {
        // Cursor in safe area should not be modified
        let bounds = ScreenBounds {
            width: 1920,
            height: 1080,
        };
        let pos = CursorPosition::new(500, 500);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.x, 500);
        assert_eq!(clamped.y, 500);
    }

    #[test]
    fn keypad_ring_opens_at_the_cursor_like_the_gesture_button() {
        use KeypadRing::*;
        for (pressed, suppressed, kwin, want) in [
            (true, false, true, KWinScript),
            (true, false, false, CursorQuery),
            (true, true, true, Suppressed),
            (true, true, false, Suppressed),
            (false, true, true, Hide), // a release always closes, even after a suppressed press
            (false, false, false, Hide),
        ] {
            assert_eq!(keypad_ring_route(pressed, suppressed, kwin), want, "{pressed} {suppressed} {kwin}");
        }
    }

    #[tokio::test]
    async fn button_action_dispatch_preserves_batch_source_and_release() {
        use juhradiald::config::ButtonAction;
        let mut calls = Vec::new();
        for pressed in [true, false] {
            dispatch_button_action_event_with(
                GestureEvent::ButtonActionEvent {
                    action: ButtonAction::VolumeUp,
                    pressed,
                    source: Some(0x56),
                    repeats: 8,
                },
                |action, pressed, source, repeats| {
                    calls.push((action, pressed, source, repeats));
                    std::future::ready(())
                },
            )
            .await;
        }
        assert_eq!(
            calls,
            [
                (ButtonAction::VolumeUp, true, Some(0x56), 8),
                (ButtonAction::VolumeUp, false, Some(0x56), 8),
            ]
        );
    }
}
