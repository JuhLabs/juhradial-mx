//! JuhRadial MX Daemon
//!
//! A daemon for Linux that provides radial menu functionality for the
//! Logitech MX Master 4 mouse via evdev input and KWin overlay.

use clap::Parser;
use tokio::sync::mpsc;
use tokio::time::{sleep, Duration};
use tracing::{info, warn, error, Level};
use tracing_subscriber::FmtSubscriber;

use juhradiald::{
    battery::{new_shared_state, start_battery_updater_shared},
    config::load_shared_config,
    cursor::{get_screen_bounds, ScreenBounds},
    dbus::{init_dbus_service_with_device, DBUS_PATH, DBUS_NAME},
    evdev::{EvdevHandler, EvdevError, GestureEvent},
    hidraw::{HidrawHandler, HidrawError},
    new_shared_haptic_manager,
    profiles::ProfileManager,
    window_tracker::WindowTracker,
};

/// Device polling interval when device is not found (2 seconds)
const DEVICE_POLL_INTERVAL_SECS: u64 = 2;

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
    let level = if args.verbose { Level::DEBUG } else { Level::INFO };
    let subscriber = FmtSubscriber::builder()
        .with_max_level(level)
        .finish();
    tracing::subscriber::set_global_default(subscriber)?;

    info!("JuhRadial MX Daemon starting...");

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

    // Initialize haptic manager for MX4 haptic feedback
    let haptic_config = shared_config.read().unwrap().haptics.clone();
    let haptic_manager = new_shared_haptic_manager(&haptic_config);

    // Try to connect to MX Master 4 for haptic feedback and divert gesture buttons
    // Also capture the device path so HidrawHandler uses the same Bolt receiver
    let mx4_hidraw_path;
    {
        let mut manager = haptic_manager.lock().unwrap();
        match manager.connect() {
            Ok(true) => {
                info!("Haptic feedback connected to MX Master 4");
                // Divert gesture buttons so we receive HID++ notifications
                // This replaces what logid (LogiOps) was doing with "divert: true"
                match manager.divert_buttons() {
                    Ok(n) if n > 0 => info!(count = n, "Gesture buttons diverted via HID++"),
                    Ok(_) => warn!("No gesture buttons found to divert - thumb button may not work"),
                    Err(e) => warn!("Button divert failed (non-fatal): {}", e),
                }
            }
            Ok(false) => info!("No MX Master 4 found for haptics (optional)"),
            Err(e) => warn!("Haptic connection error (non-fatal): {}", e),
        }
        mx4_hidraw_path = manager.device_path();
        if let Some(ref path) = mx4_hidraw_path {
            info!(path = %path.display(), "MX Master 4 hidraw path for event listener");
        }
    }

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
        // HID++ found a Logitech device
        info!("Device mode: logitech (HID++ connected)");
        ("logitech".to_string(), "Logitech MX Master 4".to_string())
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


    // Initialize D-Bus service with battery state, config, haptic manager, and device info
    let dbus_connection = match init_dbus_service_with_device(
        battery_state.clone(),
        shared_config.clone(),
        haptic_manager,
        device_mode.clone(),
        device_name.clone(),
    ).await {
        Ok(conn) => {
            info!("D-Bus service initialized successfully (mode={}, device={})", device_mode, device_name);
            conn
        }
        Err(e) => {
            error!("Failed to initialize D-Bus service: {}", e);
            return Err(e.into());
        }
    };

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
    info!(
        profile = current.name,
        "Active profile loaded"
    );

    // Initialize window tracker for per-app profiles (Story 3.2)
    let window_tracker = WindowTracker::new().await;
    if window_tracker.is_available() {
        info!("Window tracking enabled for per-app profiles");
    } else {
        warn!("Window tracking unavailable - using default profile only");
    }

    // Store for later use in Story 3.3 (window-based profile switching)
    let _window_tracker = window_tracker;
    let _profile_manager = profile_manager;

    // Create channel for gesture events
    let (event_tx, mut event_rx) = mpsc::channel::<GestureEvent>(32);

    // Spawn the HID++ hidraw handler (reads button events directly from mouse)
    // Pass the MX Master 4's hidraw path so it uses the correct Bolt receiver
    let hidraw_tx = event_tx.clone();
    let hidraw_handle = tokio::spawn(async move {
        run_hidraw_loop(hidraw_tx, mx4_hidraw_path).await
    });

    // Spawn evdev handlers:
    // - MX evdev loop: fallback for standard MX input events (when HID++ divert unavailable)
    // - Generic evdev loop: handles non-Logitech mice (e.g., SteelSeries)
    // Both run simultaneously so either mouse can trigger the radial wheel.
    let evdev_tx = event_tx.clone();
    let evdev_handle = tokio::spawn(async move {
        run_evdev_loop(evdev_tx).await
    });

    let generic_evdev_tx = event_tx.clone();
    let generic_evdev_handle = tokio::spawn(async move {
        run_generic_evdev_loop(generic_evdev_tx).await
    });

    // Get screen bounds for edge clamping (query once at startup)
    let screen_bounds = get_screen_bounds();
    info!("Screen bounds: {}x{}", screen_bounds.width, screen_bounds.height);

    // Spawn event processing task with D-Bus connection
    let event_handle = tokio::spawn(async move {
        process_gesture_events(&mut event_rx, &dbus_connection, &screen_bounds).await
    });

    // TODO: Initialize remaining components
    // 4. Initialize HID++ haptic subsystem

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
            let mx_marker = if device.is_mx_master_4 { " [MX Master 4]" } else { "" };
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

/// Run the HID++ hidraw event loop for diverted buttons
///
/// When buttons are diverted via HID++ configuration, they send HID++ notifications
/// instead of evdev events. This handler reads from the hidraw device.
async fn run_hidraw_loop(event_tx: mpsc::Sender<GestureEvent>, preferred_path: Option<std::path::PathBuf>) {
    let mut handler = HidrawHandler::new(event_tx);

    loop {
        // Try to open - use preferred path from HidppDevice if available
        // This ensures we listen on the same Bolt receiver where buttons were diverted
        let open_result = if let Some(ref path) = preferred_path {
            handler.open_path(path)
        } else {
            handler.open()
        };
        match open_result {
            Ok(()) => {
                info!("HID++ hidraw handler connected");

                // Run the event loop until error
                match handler.start().await {
                    Ok(()) => {
                        info!("HID++ event loop ended normally");
                    }
                    Err(HidrawError::DeviceNotFound) => {
                        warn!("HID++ device disconnected, will poll for reconnection...");
                    }
                    Err(HidrawError::PermissionDenied) => {
                        error!("Permission denied for hidraw device. Ensure udev rules are installed.");
                    }
                    Err(HidrawError::IoError(e)) => {
                        error!("HID++ I/O error: {}. Will retry...", e);
                    }
                }
            }
            Err(HidrawError::DeviceNotFound) => {
                // Device not found, this is expected during polling
                info!("Waiting for Bolt receiver hidraw device... (polling every {}s)", DEVICE_POLL_INTERVAL_SECS);
            }
            Err(HidrawError::PermissionDenied) => {
                error!("Permission denied accessing hidraw devices.");
                error!("Ensure udev rules are installed.");
            }
            Err(HidrawError::IoError(e)) => {
                error!("I/O error during hidraw scan: {}", e);
            }
        }

        // Wait before polling again
        sleep(Duration::from_secs(DEVICE_POLL_INTERVAL_SECS)).await;
    }
}

/// Run the evdev device detection and event loop
///
/// This function handles:
/// - Initial device detection
/// - Polling for device when not found (2-second intervals)
/// - Reconnection after device disconnect
async fn run_evdev_loop(event_tx: mpsc::Sender<GestureEvent>) {
    let mut handler = EvdevHandler::new(event_tx.clone());

    loop {
        // Try to find and connect to the device
        match EvdevHandler::find_device() {
            Ok(device_info) => {
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
                // Device not found, this is expected during polling
                info!("Waiting for MX Master 4... (polling every {}s)", DEVICE_POLL_INTERVAL_SECS);
            }
            Err(EvdevError::PermissionDenied) => {
                error!("Permission denied accessing input devices.");
                error!("Ensure udev rules are installed and user is in 'input' group.");
            }
            Err(EvdevError::IoError(e)) => {
                error!("I/O error during device scan: {}", e);
            }
        }

        // Wait before polling again
        sleep(Duration::from_secs(DEVICE_POLL_INTERVAL_SECS)).await;
    }
}

/// Read generic_trigger_button from ~/.config/juhradial/config.json
fn read_trigger_button_from_config() -> Option<u16> {
    let home = std::env::var("HOME").ok()?;
    let path = std::path::PathBuf::from(home)
        .join(".config/juhradial/config.json");
    let data = std::fs::read_to_string(&path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&data).ok()?;
    json.get("generic_trigger_button")?.as_u64().map(|v| v as u16)
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
    let path = std::path::PathBuf::from(home)
        .join(".config/juhradial/config.json");
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
async fn run_generic_evdev_loop(event_tx: mpsc::Sender<GestureEvent>) {
    let trigger = read_trigger_button_from_config();
    if let Some(code) = trigger {
        info!("Generic trigger button from config: {:#x}", code);
    }
    let mut handler = EvdevHandler::new_generic(event_tx.clone(), trigger);

    loop {
        // Try to find any generic mouse
        match EvdevHandler::find_any_mouse() {
            Ok(device_info) => {
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
                info!("Waiting for generic mouse... (polling every {}s)", DEVICE_POLL_INTERVAL_SECS);
            }
            Err(EvdevError::PermissionDenied) => {
                error!("Permission denied accessing input devices.");
                error!("Ensure udev rules are installed and user is in 'input' group.");
            }
            Err(EvdevError::IoError(e)) => {
                error!("I/O error during device scan: {}", e);
            }
        }

        // Wait before polling again
        sleep(Duration::from_secs(DEVICE_POLL_INTERVAL_SECS)).await;
    }
}

/// Process gesture events from the evdev handler
///
/// Press triggers ydotool injection -> cursor_grabber catches -> emits ShowMenu
/// Release emits HideMenu directly
async fn process_gesture_events(
    event_rx: &mut mpsc::Receiver<GestureEvent>,
    dbus_connection: &zbus::Connection,
    _screen_bounds: &ScreenBounds,
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
        }
    }
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
    connection.emit_signal(
        None::<&str>,  // destination (None = broadcast)
        DBUS_PATH,
        "org.kde.juhradialmx.Daemon",
        "HideMenu",
        &(),
    ).await?;

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
    connection.emit_signal(
        None::<&str>,  // destination (None = broadcast)
        DBUS_PATH,
        "org.kde.juhradialmx.Daemon",
        "CursorMoved",
        &(x, y),
    ).await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use juhradiald::cursor::{ScreenBounds, CursorPosition, EDGE_MARGIN, MENU_RADIUS};

    #[test]
    fn test_device_poll_interval() {
        // Verify poll interval is 2 seconds as specified in AC2
        assert_eq!(DEVICE_POLL_INTERVAL_SECS, 2);
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
        tx.send(GestureEvent::Pressed { x: 100, y: 200 }).await.unwrap();

        // Receive and verify
        let event = rx.recv().await.unwrap();
        assert!(matches!(event, GestureEvent::Pressed { x: 100, y: 200 }));

        // Send release event
        tx.send(GestureEvent::Released { duration_ms: 500 }).await.unwrap();

        let event = rx.recv().await.unwrap();
        assert!(matches!(event, GestureEvent::Released { duration_ms: 500 }));
    }

    #[tokio::test]
    async fn test_rapid_press_handling() {
        // Test AC3: Rapid presses (5 in 1 second) should all be captured in order
        let (tx, mut rx) = mpsc::channel::<GestureEvent>(32);

        // Simulate 5 rapid press/release cycles
        for i in 0..5 {
            tx.send(GestureEvent::Pressed { x: i * 10, y: i * 10 }).await.unwrap();
            tx.send(GestureEvent::Released { duration_ms: 50 + (i as u64 * 10) }).await.unwrap();
        }

        // Verify all 10 events are received in order
        for i in 0..5 {
            let press = rx.recv().await.unwrap();
            assert!(matches!(press, GestureEvent::Pressed { x, y } if x == i * 10 && y == i * 10));

            let release = rx.recv().await.unwrap();
            assert!(matches!(release, GestureEvent::Released { duration_ms } if duration_ms == 50 + (i as u64 * 10)));
        }

        // Ensure no more events
        assert!(rx.try_recv().is_err());
    }

    // Story 2.3: Edge clamping tests
    #[test]
    fn test_edge_clamping_integration() {
        let bounds = ScreenBounds { width: 1920, height: 1080 };

        // Test near left edge
        let pos = CursorPosition::new(50, 540);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.x, EDGE_MARGIN + MENU_RADIUS); // 160

        // Test near top edge
        let pos = CursorPosition::new(960, 30);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.y, EDGE_MARGIN + MENU_RADIUS); // 160

        // Test bottom-right corner
        let pos = CursorPosition::new(1900, 1060);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.x, 1920 - EDGE_MARGIN - MENU_RADIUS); // 1760
        assert_eq!(clamped.y, 1080 - EDGE_MARGIN - MENU_RADIUS); // 920
    }

    #[test]
    fn test_cursor_position_within_bounds() {
        // Cursor in safe area should not be modified
        let bounds = ScreenBounds { width: 1920, height: 1080 };
        let pos = CursorPosition::new(500, 500);
        let clamped = pos.clamp_to_screen(&bounds);
        assert_eq!(clamped.x, 500);
        assert_eq!(clamped.y, 500);
    }
}
