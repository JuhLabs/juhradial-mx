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
    battery::{new_shared_state, start_battery_updater},
    config::load_shared_config,
    cursor::{get_screen_bounds, ScreenBounds},
    dbus::{init_dbus_service, DBUS_PATH, DBUS_NAME},
    evdev::{EvdevHandler, EvdevError, GestureEvent, LogidHandler},
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

    // Try to connect to MX Master 4 for haptic feedback
    {
        let mut manager = haptic_manager.lock().unwrap();
        match manager.connect() {
            Ok(true) => info!("Haptic feedback connected to MX Master 4"),
            Ok(false) => info!("No MX Master 4 found for haptics (optional)"),
            Err(e) => warn!("Haptic connection error (non-fatal): {}", e),
        }
    }

    // Initialize D-Bus service with battery state, config, and haptic manager
    let dbus_connection = match init_dbus_service(
        battery_state.clone(),
        shared_config.clone(),
        haptic_manager,
    ).await {
        Ok(conn) => {
            info!("D-Bus service initialized successfully");
            conn
        }
        Err(e) => {
            error!("Failed to initialize D-Bus service: {}", e);
            return Err(e.into());
        }
    };

    // Spawn battery status updater
    let battery_handle = tokio::spawn(async move {
        start_battery_updater(battery_state).await
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

    // Check if logid is available - if so, use it exclusively to avoid duplicate events
    let logid_available = LogidHandler::find_logid_device().is_ok();

    if logid_available {
        info!("LogiOps (logid) detected - using logid handler exclusively");
    } else {
        info!("LogiOps not detected - using evdev/hidraw handlers");
    }

    // Spawn the HID++ hidraw handler (for diverted button events from Solaar)
    // Only if logid is NOT available
    let hidraw_handle = if !logid_available {
        let hidraw_tx = event_tx.clone();
        Some(tokio::spawn(async move {
            run_hidraw_loop(hidraw_tx).await
        }))
    } else {
        None
    };

    // Spawn the evdev handler as fallback (for non-diverted button events)
    // Only if logid is NOT available
    let evdev_handle = if !logid_available {
        let evdev_tx = event_tx.clone();
        Some(tokio::spawn(async move {
            run_evdev_loop(evdev_tx).await
        }))
    } else {
        None
    };

    // Spawn the logid handler (for F19/F20 keypresses from logid)
    // Only if logid IS available
    let logid_handle = if logid_available {
        Some(tokio::spawn(async move {
            run_logid_loop(event_tx).await
        }))
    } else {
        None
    };

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
    // Use async block to handle Option handles properly
    let wait_hidraw = async {
        if let Some(handle) = hidraw_handle {
            handle.await
        } else {
            std::future::pending().await
        }
    };
    let wait_evdev = async {
        if let Some(handle) = evdev_handle {
            handle.await
        } else {
            std::future::pending().await
        }
    };
    let wait_logid = async {
        if let Some(handle) = logid_handle {
            handle.await
        } else {
            std::future::pending().await
        }
    };

    tokio::select! {
        _ = tokio::signal::ctrl_c() => {
            info!("Shutdown signal received, exiting...");
        }
        result = wait_hidraw => {
            if let Err(e) = result {
                error!("hidraw task panicked: {:?}", e);
            }
        }
        result = wait_evdev => {
            if let Err(e) = result {
                error!("evdev task panicked: {:?}", e);
            }
        }
        result = wait_logid => {
            if let Err(e) = result {
                error!("logid task panicked: {:?}", e);
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

/// List all detected Logitech devices
fn list_logitech_devices() {
    println!("Scanning for Logitech input devices...\n");

    let devices = EvdevHandler::list_logitech_devices();

    if devices.is_empty() {
        println!("No Logitech devices found.");
        println!("\nTroubleshooting:");
        println!("  - Ensure your MX Master 4 is connected");
        println!("  - Check that udev rules are installed");
        println!("  - Verify user is in 'input' group");
        return;
    }

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

/// Run the HID++ hidraw event loop for diverted buttons
///
/// When buttons are diverted in Solaar, they send HID++ notifications
/// instead of evdev events. This handler reads from the hidraw device.
async fn run_hidraw_loop(event_tx: mpsc::Sender<GestureEvent>) {
    let mut handler = HidrawHandler::new(event_tx);

    loop {
        // Try to open and start listening
        match handler.open() {
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

/// Run the logid event loop for F19/F20 keypresses
///
/// This handler listens to the LogiOps Virtual Input device for:
/// - KEY_F19: Gesture button pressed
/// - KEY_F20: Gesture button released
async fn run_logid_loop(event_tx: mpsc::Sender<GestureEvent>) {
    let mut handler = LogidHandler::new(event_tx);

    loop {
        match LogidHandler::find_logid_device() {
            Ok(_) => {
                info!("LogiOps Virtual Input found, starting logid listener");

                match handler.start().await {
                    Ok(()) => {
                        info!("Logid event loop ended normally");
                    }
                    Err(EvdevError::DeviceNotFound) => {
                        warn!("LogiOps device disconnected, will poll for reconnection...");
                    }
                    Err(EvdevError::PermissionDenied) => {
                        error!("Permission denied for LogiOps device");
                    }
                    Err(EvdevError::IoError(e)) => {
                        error!("Logid I/O error: {}. Will retry...", e);
                    }
                }
            }
            Err(EvdevError::DeviceNotFound) => {
                // logid not running or device not created yet
                info!("Waiting for LogiOps Virtual Input... (logid must be running)");
            }
            Err(e) => {
                error!("Error finding LogiOps device: {:?}", e);
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
