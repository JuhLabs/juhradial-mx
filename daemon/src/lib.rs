//! JuhRadial MX Daemon Library
//!
//! Public API for testing and integration.

pub mod accessibility;
pub mod actions;
pub mod battery;
pub mod bundled_themes;
pub mod config;
pub mod cursor;
pub mod dbus;
pub mod evdev;
pub mod hidpp;
pub mod hidraw;
pub mod performance_monitor;
pub mod profiles;
pub mod theme;
pub mod theme_watcher;
pub mod window_tracker;

/// Re-export commonly used types
pub use accessibility::{AccessibilitySettings, EffectiveAnimationTimings};
pub use actions::{Action, ActionType};
pub use battery::{BatteryState, SharedBatteryState, new_shared_state as new_battery_state, start_battery_updater};
pub use bundled_themes::{get_bundled_theme, get_default_theme, list_bundled_themes, DEFAULT_THEME_NAME};
pub use config::{Config, SharedConfig, new_shared_config, load_shared_config};
pub use cursor::{get_cursor_position, get_screen_bounds, CursorPosition, ScreenBounds, EDGE_MARGIN, MENU_DIAMETER, MENU_RADIUS};
pub use dbus::{init_dbus_service, JuhRadialService, DBUS_INTERFACE, DBUS_NAME, DBUS_PATH};
pub use evdev::{DeviceInfo, EvdevError, EvdevHandler, GestureEvent, LogidHandler, LOGITECH_VENDOR_ID};
pub use performance_monitor::{BlurMode, PerformanceMonitor};
pub use profiles::{Profile, ProfileManager};
pub use theme::{Theme, ThemeManager};
pub use theme_watcher::{ThemeEvent, ThemeHotReloader, ThemeWatcher};
pub use window_tracker::{WindowInfo, WindowTracker};
pub use hidpp::{HapticManager, HapticEvent, SharedHapticManager, new_shared_haptic_manager};
