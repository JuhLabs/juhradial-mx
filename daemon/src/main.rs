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
    dbus::{DBUS_NAME, DBUS_PATH, init_dbus_service_with_device},
    evdev::{EvdevError, EvdevHandler, GestureEvent},
    gaming::new_shared_gaming_mode,
    hidpp::SharedHapticManager,
    hidraw::{HidrawError, HidrawHandler},
    macros::{MacroEngine, MacroRecorder, TriggerMap},
    new_shared_haptic_manager,
    profiles::{ProfileManager, SharedHardwareProfiles},
    window_tracker::WindowTracker,
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
/// matches the cost of a missed hotplug — barely perceptible — without
/// generating periodic contention on active input devices.
const DEVICE_POLL_INTERVAL_SECS: u64 = 60;

/// Poll interval while the HID++ listener is disconnected.
///
/// This path only runs after the listener has lost the mouse or before it has
/// found one, so a shorter cadence does not reintroduce the steady-state evdev
/// scanning stutter that `DEVICE_POLL_INTERVAL_SECS` avoids.
const HIDRAW_RECONNECT_POLL_INTERVAL_SECS: u64 = 5;

/// Emit monotonic checkpoints so cold-start latency can be attributed to a
/// concrete phase instead of inferring it from process activation.
fn log_startup_phase(started_at: &Instant, phase: &'static str) {
    info!(
        phase,
        elapsed_ms = started_at.elapsed().as_millis() as u64,
        "Startup phase completed"
    );
}

/// Spawn a background thread that watches /dev/input/ for device hotplug events
/// using inotify. Returns a Notify that fires when event* devices appear or disappear.
/// This allows evdev loops to re-scan immediately instead of waiting for the 2s poll.
///
/// Only reacts to Create/Remove events (actual device plug/unplug). Access events
/// (e.g. Close(Write)) are filtered out to prevent a feedback loop where our own
/// device scanning triggers inotify events that cause more scanning. A 500ms
/// debounce window coalesces rapid events from USB hubs into a single notification.
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
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();

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
    // HID++ probing does blocking hidraw I/O with std::thread::sleep — running it
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
            (connect_result, divert_result, path, name)
        })
        .await
        .expect("HID++ probe task panicked");

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

    // Initialize gaming mode and macro subsystem
    let gaming_mode = new_shared_gaming_mode(haptic_manager.clone());
    let macro_engine = Arc::new(Mutex::new(MacroEngine::new()));
    let macro_recorder = Arc::new(Mutex::new(MacroRecorder::new()));
    let trigger_map = Arc::new(std::sync::RwLock::new(TriggerMap::default()));

    // Load existing macro triggers from disk at startup
    let macro_cids: Vec<u16>;
    let macro_evdev_codes: HashSet<u16>;
    {
        // Pull what we need out of the trigger map, then drop the write lock
        // before we await on the blocking divert task — clippy's
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

        macro_cids = if pending_cids.is_empty() && initial_remapped_cids.is_empty() {
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
    let macro_engine_for_events = macro_engine.clone();

    // Active-window channel for per-app hardware profiles. The D-Bus service
    // (KWin script path) and the WindowTracker (Hyprland/X11 paths) both push
    // resource classes here; a single consumer applies matching profiles.
    let (active_window_tx, active_window_rx) =
        tokio::sync::mpsc::unbounded_channel::<String>();
    // Clone the haptic manager for the profile consumer before it is moved into
    // the D-Bus service below.
    let haptic_manager_for_profiles = haptic_manager_for_battery.clone();

    // Shared per-app hardware profile map. Created empty here, populated once
    // profiles.json is loaded below, and refreshed by `ReloadConfig` whenever
    // the settings UI saves. Both the D-Bus service and the focus-change
    // consumer hold a clone, so a UI save reaches the consumer without restart.
    let hardware_profiles: SharedHardwareProfiles = Arc::new(RwLock::new(HashMap::new()));

    // Initialize D-Bus service with battery state, config, haptic manager, device info, and macro state
    let dbus_connection = match init_dbus_service_with_device(
        battery_state.clone(),
        shared_config.clone(),
        haptic_manager,
        device_mode.clone(),
        device_name.clone(),
        gaming_mode,
        macro_engine,
        macro_recorder,
        trigger_map,
        active_window_tx.clone(),
        hardware_profiles.clone(),
    )
    .await
    {
        Ok(conn) => {
            info!(
                "D-Bus service initialized successfully (mode={}, device={})",
                device_mode, device_name
            );
            conn
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
    {
        let conn = dbus_connection.clone();
        let kwin = kwin_availability.clone();
        tokio::spawn(async move { juhradiald::compositor::run_kwin_watcher(conn, kwin).await });
    }

    let haptic_manager_for_hidraw = haptic_manager_for_battery.clone();

    // Live battery notifications update the same shared state the active poller
    // writes, so GetBatteryStatus reflects them even when the active query fails.
    let battery_state_for_events = battery_state.clone();

    // Spawn battery status updater (shares HidppDevice with haptic via SharedHapticManager)
    let battery_handle = tokio::spawn(async move {
        start_battery_updater_shared(battery_state, haptic_manager_for_battery).await
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

    // Initialize window tracker for per-app HARDWARE profiles (Story 3.2/3.3).
    // The tracker pushes focused-window resource classes; the consumer below
    // applies any matching HardwareProfile via volatile HID++ setters.
    let window_tracker = WindowTracker::new();
    if window_tracker.is_available() {
        info!(desktop = window_tracker.desktop(), "Window tracking enabled for per-app hardware profiles");
        let watch_tx = active_window_tx.clone();
        tokio::spawn(async move { window_tracker.watch(watch_tx).await });
    } else {
        warn!("Window tracking unavailable - per-app hardware profiles inactive");
    }

    // Consumer: on each focus change, look up and apply the per-app hardware
    // profile (volatile only). No-op when no profile matches, so the default
    // (empty hardware map) leaves device state untouched.
    {
        let mut active_window_rx = active_window_rx;
        let hw_manager = haptic_manager_for_profiles;
        // Read the live shared map (refreshed by ReloadConfig) instead of a
        // one-time snapshot, so UI saves take effect without a daemon restart.
        let hw_profiles = hardware_profiles.clone();
        if !hw_profiles.read().map(|m| m.is_empty()).unwrap_or(true) {
            info!("Per-app hardware profiles configured; focus-change application active");
        }
        tokio::spawn(async move {
            let mut current_class = String::new();
            while let Some(class) = active_window_rx.recv().await {
                if class == current_class {
                    continue;
                }
                current_class = class.clone();
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
                    match map.get(&class.to_lowercase()) {
                        Some(hw) => hw.clone(),
                        None => continue,
                    }
                };
                info!(class = %class, "Applying per-app hardware profile");
                let mgr = hw_manager.clone();
                let _ = tokio::task::spawn_blocking(move || {
                    match mgr.lock() {
                        Ok(mut m) => {
                            juhradiald::profiles::apply_hardware_profile(&hw, &mut m)
                        }
                        Err(e) => error!(error = %e, "Failed to lock haptic manager for hardware profile"),
                    }
                })
                .await;
            }
        });
    }

    // Start inotify watcher on /dev/input/ for instant device hotplug detection.
    // Shared across both evdev loops so they re-scan immediately on device changes.
    let hotplug_notify = spawn_device_hotplug_watcher();

    // Create channel for gesture events
    let (event_tx, mut event_rx) = mpsc::channel::<GestureEvent>(32);

    // Spawn the HID++ hidraw handler (reads button events directly from mouse).
    // Button divert is volatile and is reset by Easy-Switch host changes, so
    // this loop owns re-applying diverts whenever the mouse hotplugs/reconnects.
    let hidraw_tx = event_tx.clone();
    let hidraw_config = shared_config.clone();
    let hidraw_hotplug = hotplug_notify.clone();
    let hidraw_kwin = kwin_availability.clone();
    let hidraw_handle = tokio::spawn(async move {
        run_hidraw_loop(
            hidraw_tx,
            HidrawStartup {
                preferred_path: mx4_hidraw_path,
            },
            macro_cids,
            hidraw_config,
            hidraw_hotplug,
            haptic_manager_for_hidraw,
            hidraw_kwin,
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
    let evdev_kwin = kwin_availability.clone();
    let evdev_handle = tokio::spawn(async move {
        run_evdev_loop(evdev_tx, suppressed_for_mx, hotplug_for_mx, evdev_config, evdev_kwin).await
    });

    let generic_evdev_tx = event_tx.clone();
    let suppressed_for_generic = macro_evdev_codes.clone();
    let hotplug_for_generic = hotplug_notify.clone();
    let generic_evdev_config = shared_config.clone();
    let generic_evdev_kwin = kwin_availability.clone();
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

    // Spawn event processing task with D-Bus connection
    let event_handle = tokio::spawn(async move {
        process_gesture_events(
            &mut event_rx,
            &dbus_connection,
            trigger_map_for_events,
            macro_engine_for_events,
            battery_state_for_events,
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
}

/// Reconnect HID++ and re-apply volatile button diverts.
///
/// Easy-Switch host changes reset temporary REPROG_CONTROLS_V4 diverts, so the
/// daemon must apply them again after the mouse returns to this machine.
async fn refresh_hidpp_button_diverts(
    haptic_manager: SharedHapticManager,
    macro_cids: Vec<u16>,
    remapped_cids: Vec<u16>,
) -> Option<PathBuf> {
    match tokio::task::spawn_blocking(move || {
        let mut manager = haptic_manager.lock().unwrap();
        let connected = match manager.connect() {
            Ok(connected) => connected,
            Err(e) => {
                warn!(error = %e, "HID++ reconnect failed while refreshing button divert");
                return None;
            }
        };
        if !connected {
            debug!("No MX Master HID++ device available for button divert");
            return None;
        }

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
                debug!(cid = format!("0x{:04X}", cid), "HID++ macro button diverted");
            } else {
                debug!(cid = format!("0x{:04X}", cid), "HID++ macro button not divertable on this device");
            }
        }
        for cid in remapped_cids {
            if diverted_cids.contains(&cid) {
                info!(cid = format!("0x{:04X}", cid), "HID++ reassigned button diverted");
            } else {
                debug!(cid = format!("0x{:04X}", cid), "Reassigned button not divertable on this device");
            }
        }

        manager.device_path()
    })
    .await
    {
        Ok(path) => path,
        Err(e) => {
            error!("HID++ button divert refresh task panicked: {:?}", e);
            None
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
        // Direction inversion is applied in software by the hidraw reader, so
        // the device divert is enabled with hardware inversion off.
        match manager.set_thumbwheel_reporting(tw.is_diverted(), false) {
            Ok(()) => info!(diverted = tw.is_diverted(), "Thumb-wheel reporting applied"),
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

async fn run_hidraw_loop(
    event_tx: mpsc::Sender<GestureEvent>,
    startup: HidrawStartup,
    macro_cids: Vec<u16>,
    shared_config: juhradiald::config::SharedConfig,
    hotplug: Arc<tokio::sync::Notify>,
    haptic_manager: SharedHapticManager,
    kwin_availability: juhradiald::compositor::KWinAvailability,
) {
    let HidrawStartup {
        mut preferred_path,
    } = startup;
    let mut handler = HidrawHandler::new(event_tx);
    let macro_cids_for_divert = macro_cids.clone();
    let config_for_thumbwheel = shared_config.clone();
    let config_for_divert = shared_config.clone();
    handler.set_macro_cids(macro_cids);
    handler.set_shared_config(shared_config);
    handler.set_kwin_availability(kwin_availability);

    loop {
        // Re-read the reassigned buttons each cycle so a config change is
        // picked up on the next reconnect (live changes go through ReloadConfig).
        let remapped_cids = config_for_divert
            .read()
            .map(|c| c.remapped_button_cids())
            .unwrap_or_default();
        if let Some(path) = refresh_hidpp_button_diverts(
            haptic_manager.clone(),
            macro_cids_for_divert.clone(),
            remapped_cids,
        )
        .await
        {
            preferred_path = Some(path);
        }

        // Re-apply thumb-wheel divert (volatile) and refresh the feature index
        // the reader uses to route rotation notifications.
        let tw_index = apply_thumbwheel_reporting(
            haptic_manager.clone(),
            config_for_thumbwheel.clone(),
        )
        .await;
        handler.set_thumbwheel_feature_index(tw_index);

        // Refresh notification feature indices for live hardware readback. Like
        // diverts, these are cheap to re-fetch on every (re)connect and keep the
        // reader correct across hotplug/host-switch re-enumeration.
        let note_indices = fetch_notification_indices(haptic_manager.clone()).await;
        handler.set_notification_indices(note_indices);

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

                // Run the event loop until error, or until input hotplug tells
                // us the mouse may have returned from another Easy-Switch host.
                let start_result = tokio::select! {
                    result = handler.start() => Some(result),
                    _ = hotplug.notified() => None,
                };
                handler.close();

                match start_result {
                    Some(Ok(())) => {
                        info!("HID++ event loop ended normally");
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
    kwin_availability: juhradiald::compositor::KWinAvailability,
) {
    let mut handler = EvdevHandler::new(event_tx.clone());
    handler.set_suppressed_keys(suppressed_keys);
    handler.set_shared_config(shared_config);
    handler.set_kwin_availability(kwin_availability);

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

                // Run the event loop until device disconnects
                match handler.start().await {
                    Ok(()) => {
                        info!("Event loop ended normally");
                    }
                    Err(EvdevError::DeviceNotFound) => {
                        warn!("Device disconnected, will poll for reconnection...");
                        logged_waiting = false;
                    }
                    Err(EvdevError::PermissionDenied) => {
                        error!("Permission denied. Ensure udev rules are installed.");
                        error!("Run: sudo usermod -aG input $USER && logout");
                        // Continue polling in case permissions are fixed
                    }
                    Err(EvdevError::IoError(e)) => {
                        error!("I/O error: {}. Will retry...", e);
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
    kwin_availability: juhradiald::compositor::KWinAvailability,
) {
    let trigger = read_trigger_button_from_config();
    if let Some(code) = trigger {
        info!("Generic trigger button from config: {:#x}", code);
    }
    let mut handler = EvdevHandler::new_generic(event_tx.clone(), trigger);
    handler.set_suppressed_keys(suppressed_keys);
    handler.set_shared_config(shared_config);
    handler.set_kwin_availability(kwin_availability);

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

/// Process gesture events from the evdev handler
///
/// Press triggers ydotool injection -> cursor_grabber catches -> emits ShowMenu
/// Release emits HideMenu directly
/// MacroTriggered events are checked against the TriggerMap for macro execution
async fn process_gesture_events(
    event_rx: &mut mpsc::Receiver<GestureEvent>,
    dbus_connection: &zbus::Connection,
    trigger_map: Arc<std::sync::RwLock<juhradiald::macros::TriggerMap>>,
    macro_engine: Arc<Mutex<juhradiald::macros::MacroEngine>>,
    battery_state: SharedBatteryState,
) {
    while let Some(event) = event_rx.recv().await {
        match event {
            GestureEvent::Pressed { x, y } => {
                // HID++ hidraw handler provides cursor coordinates directly
                info!(x, y, "Gesture button pressed - showing radial menu");

                // Emit ShowMenu via D-Bus
                if let Err(e) = emit_menu_requested(dbus_connection, x, y).await {
                    error!("Failed to emit ShowMenu signal: {}", e);
                }
            }
            GestureEvent::Released { duration_ms } => {
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
            GestureEvent::ButtonActionEvent { action, pressed } => {
                if pressed {
                    info!(%action, "Button action triggered");
                    match juhradiald::actions::execute_button_action(action).await {
                        Ok(true) => {
                            // Action was handled directly
                        }
                        Ok(false) => {
                            // Should not happen (RadialMenu goes through Pressed path)
                            warn!("ButtonActionEvent with radial_menu - unexpected");
                        }
                        Err(e) => {
                            error!(%action, error = %e, "Failed to execute button action");
                        }
                    }
                } else {
                    // Button released for non-radial action - no HideMenu needed
                    tracing::debug!(%action, "Button action released (no-op)");
                }
            }
            GestureEvent::ThumbwheelScroll { clicks } => {
                tracing::debug!(clicks, "Thumb-wheel horizontal scroll");
                if let Err(e) = juhradiald::actions::execute_horizontal_scroll(clicks).await {
                    error!(clicks, error = %e, "Failed to inject horizontal scroll");
                }
            }
            GestureEvent::Hardware(note) => {
                if let Err(e) = emit_hardware_notification(dbus_connection, &battery_state, note).await {
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
        HN::HostChanged { host } => {
            info!(host, "Easy-Switch host changed (notification)");
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
}
