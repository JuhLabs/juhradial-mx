//! JuhRadial MX D-Bus service struct and constructors

use std::sync::{Arc, Mutex};

use crate::battery::SharedBatteryState;
use crate::config::SharedConfig;
use crate::gaming::SharedGamingMode;
use crate::hidpp::SharedHapticManager;
use crate::macros::{MacroEngine, MacroRecorder, SharedTriggerMap, TriggerMap};

/// JuhRadial MX D-Bus service
///
/// Implements the D-Bus interface for IPC between daemon, KWin overlay, and Plasma widget.
pub struct JuhRadialService {
    /// Current profile name
    pub(crate) current_profile: String,
    /// Daemon version
    pub(crate) version: String,
    /// Shared battery state
    pub(crate) battery_state: SharedBatteryState,
    /// Shared configuration for hot-reload
    pub(crate) config: SharedConfig,
    /// Shared haptic manager for triggering haptic feedback
    pub(crate) haptic_manager: SharedHapticManager,
    /// Device mode: "logitech" or "generic"
    pub(crate) device_mode: String,
    /// Detected device name (e.g., "MX Master 4" or "SteelSeries Rival 3")
    pub(crate) device_name: String,
    /// Gaming mode state
    pub(crate) gaming_mode: SharedGamingMode,
    /// Macro playback engine
    pub(crate) macro_engine: Arc<Mutex<MacroEngine>>,
    /// Macro event recorder
    pub(crate) macro_recorder: Arc<Mutex<MacroRecorder>>,
    /// Macro trigger map (evdev button code -> macro ID)
    pub(crate) trigger_map: SharedTriggerMap,
}

impl JuhRadialService {
    /// Create a new D-Bus service instance with battery state, config, and haptic manager
    pub fn new(
        battery_state: SharedBatteryState,
        config: SharedConfig,
        haptic_manager: SharedHapticManager,
    ) -> Self {
        let gaming_mode = crate::gaming::new_shared_gaming_mode(haptic_manager.clone());
        Self {
            current_profile: "default".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            battery_state,
            config,
            haptic_manager,
            device_mode: "logitech".to_string(),
            device_name: "Unknown".to_string(),
            gaming_mode,
            macro_engine: Arc::new(Mutex::new(MacroEngine::new())),
            macro_recorder: Arc::new(Mutex::new(MacroRecorder::new())),
            trigger_map: Arc::new(std::sync::RwLock::new(TriggerMap::default())),
        }
    }

    /// Create a new D-Bus service instance with device mode info
    pub fn new_with_device(
        battery_state: SharedBatteryState,
        config: SharedConfig,
        haptic_manager: SharedHapticManager,
        device_mode: String,
        device_name: String,
        gaming_mode: SharedGamingMode,
        macro_engine: Arc<Mutex<MacroEngine>>,
        macro_recorder: Arc<Mutex<MacroRecorder>>,
        trigger_map: SharedTriggerMap,
    ) -> Self {
        Self {
            current_profile: "default".to_string(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            battery_state,
            config,
            haptic_manager,
            device_mode,
            device_name,
            gaming_mode,
            macro_engine,
            macro_recorder,
            trigger_map,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use crate::battery::new_shared_state;
    use crate::config::new_shared_config;
    use crate::hidpp::new_shared_haptic_manager;

    #[test]
    fn test_service_creation() {
        let battery_state = new_shared_state();
        let config = new_shared_config();
        let haptic_config = config.read().unwrap().haptics.clone();
        let haptic_manager = new_shared_haptic_manager(&haptic_config);
        let service = JuhRadialService::new(battery_state, config, haptic_manager);
        assert_eq!(service.current_profile, "default");
        assert_eq!(service.device_mode, "logitech");
        assert_eq!(service.device_name, "Unknown");
        let haptics = service.config.read().unwrap().haptics.enabled;
        assert!(haptics);
        assert!(!service.version.is_empty());
    }

    #[test]
    fn test_service_creation_with_device() {
        let battery_state = new_shared_state();
        let config = new_shared_config();
        let haptic_config = config.read().unwrap().haptics.clone();
        let haptic_manager = new_shared_haptic_manager(&haptic_config);
        let gaming_mode = crate::gaming::new_shared_gaming_mode(haptic_manager.clone());
        let macro_engine = Arc::new(Mutex::new(MacroEngine::new()));
        let macro_recorder = Arc::new(Mutex::new(MacroRecorder::new()));
        let trigger_map = Arc::new(std::sync::RwLock::new(TriggerMap::default()));
        let service = JuhRadialService::new_with_device(
            battery_state, config, haptic_manager,
            "generic".to_string(),
            "SteelSeries Rival 3".to_string(),
            gaming_mode, macro_engine, macro_recorder, trigger_map,
        );
        assert_eq!(service.device_mode, "generic");
        assert_eq!(service.device_name, "SteelSeries Rival 3");
    }
}
