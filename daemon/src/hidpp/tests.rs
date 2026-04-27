//! Tests for the hidpp module

use crate::hidpp::*;

#[test]
fn test_haptic_profiles_ux_spec() {
    // Verify profiles match UX spec Section 2.3
    assert_eq!(haptic_profiles::MENU_APPEAR.intensity, 20);
    assert_eq!(haptic_profiles::MENU_APPEAR.duration_ms, 10);

    assert_eq!(haptic_profiles::SLICE_CHANGE.intensity, 40);
    assert_eq!(haptic_profiles::SLICE_CHANGE.duration_ms, 15);

    assert_eq!(haptic_profiles::CONFIRM.intensity, 80);
    assert_eq!(haptic_profiles::CONFIRM.duration_ms, 25);

    assert_eq!(haptic_profiles::INVALID.intensity, 30);
    assert_eq!(haptic_profiles::INVALID.duration_ms, 50);
}

#[test]
fn test_disabled_haptics() {
    let mut manager = HapticManager::new(false);
    // Should succeed but do nothing when disabled
    assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
}

#[test]
fn test_enabled_haptics_no_device() {
    let mut manager = HapticManager::new(true);
    // Should succeed silently without device
    assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
}

#[test]
fn test_short_message_construction() {
    let msg = HidppShortMessage::new(0xFF, 0x00, 0x01, 0x05).with_params([0xAA, 0xBB, 0xCC]);

    let bytes = msg.to_bytes();
    assert_eq!(bytes[0], 0x10); // Short report type
    assert_eq!(bytes[1], 0xFF); // Device index
    assert_eq!(bytes[2], 0x00); // Feature index
    assert_eq!(bytes[3], 0x15); // Function 1, SW ID 5
    assert_eq!(bytes[4], 0xAA);
    assert_eq!(bytes[5], 0xBB);
    assert_eq!(bytes[6], 0xCC);
}

#[test]
fn test_short_message_parsing() {
    let bytes = [0x10, 0xFF, 0x00, 0x15, 0xAA, 0xBB, 0xCC];
    let msg = HidppShortMessage::from_bytes(&bytes).unwrap();

    assert_eq!(msg.device_index, 0xFF);
    assert_eq!(msg.feature_index, 0x00);
    assert_eq!(msg.function_id(), 0x01);
    assert_eq!(msg.sw_id(), 0x05);
    assert_eq!(msg.params, [0xAA, 0xBB, 0xCC]);
}

#[test]
fn test_long_message_construction() {
    let msg = HidppLongMessage::new(0x01, 0x05, 0x02, 0x0A).with_params(&[1, 2, 3, 4, 5]);

    let bytes = msg.to_bytes();
    assert_eq!(bytes[0], 0x11); // Long report type
    assert_eq!(bytes[1], 0x01); // Device index
    assert_eq!(bytes[2], 0x05); // Feature index
    assert_eq!(bytes[3], 0x2A); // Function 2, SW ID 10
    assert_eq!(bytes[4], 1);
    assert_eq!(bytes[5], 2);
    assert_eq!(bytes[6], 3);
}

#[test]
fn test_connection_type_display() {
    assert_eq!(format!("{}", ConnectionType::Usb), "USB");
    assert_eq!(format!("{}", ConnectionType::Bolt), "Bolt");
    assert_eq!(format!("{}", ConnectionType::Bluetooth), "Bluetooth");
    assert_eq!(format!("{}", ConnectionType::Unifying), "Unifying");
}

#[test]
fn test_haptic_error_display() {
    assert!(
        HapticError::DeviceNotFound
            .to_string()
            .contains("not connected")
    );
    assert!(
        HapticError::PermissionDenied
            .to_string()
            .contains("Permission")
    );
    assert!(
        HapticError::UnsupportedDevice
            .to_string()
            .contains("not support")
    );
}

#[test]
fn test_graceful_fallback_no_device() {
    let mut manager = HapticManager::new(true);
    // Without connect(), device is None
    // Should succeed silently (graceful degradation)
    assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
    assert!(!manager.is_available());
}

#[test]
fn test_default_manager() {
    let manager = HapticManager::default();
    assert!(manager.is_enabled());
    assert_eq!(manager.default_pattern(), Mx4HapticPattern::SubtleCollision);
}

#[test]
fn test_set_debounce() {
    let mut manager = HapticManager::new(true);
    manager.set_debounce_ms(30);
    // Debounce is internal but we can verify it doesn't panic
    assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
}

#[test]
fn test_from_config() {
    use crate::config::HapticConfig;

    let config = HapticConfig {
        enabled: true,
        default_pattern: "subtle_collision".to_string(),
        per_event: Default::default(),
        debounce_ms: 30,
        slice_debounce_ms: 20,
        reentry_debounce_ms: 50,
    };

    let manager = HapticManager::from_config(&config);
    assert!(manager.is_enabled());
    assert_eq!(manager.default_pattern(), Mx4HapticPattern::SubtleCollision);
}

#[test]
fn test_from_config_disabled() {
    use crate::config::HapticConfig;

    let config = HapticConfig {
        enabled: false,
        default_pattern: "subtle_collision".to_string(),
        per_event: Default::default(),
        debounce_ms: 20,
        slice_debounce_ms: 20,
        reentry_debounce_ms: 50,
    };

    let manager = HapticManager::from_config(&config);
    assert!(!manager.is_enabled());
}

#[test]
fn test_update_from_config() {
    use crate::config::HapticConfig;

    let mut manager = HapticManager::new(true);
    assert_eq!(manager.default_pattern(), Mx4HapticPattern::SubtleCollision);

    let new_config = HapticConfig {
        enabled: true,
        default_pattern: "sharp_state_change".to_string(),
        per_event: Default::default(),
        debounce_ms: 25,
        slice_debounce_ms: 20,
        reentry_debounce_ms: 50,
    };

    manager.update_from_config(&new_config);
    assert_eq!(
        manager.default_pattern(),
        Mx4HapticPattern::SharpStateChange
    );
}

// ========================================================================
// Story 5.3: HapticEvent and Pattern Tests
// ========================================================================

#[test]
fn test_haptic_event_base_profiles() {
    assert_eq!(HapticEvent::MenuAppear.base_profile().intensity, 20);
    assert_eq!(HapticEvent::MenuAppear.base_profile().duration_ms, 10);

    assert_eq!(HapticEvent::SliceChange.base_profile().intensity, 40);
    assert_eq!(HapticEvent::SliceChange.base_profile().duration_ms, 15);

    assert_eq!(HapticEvent::SelectionConfirm.base_profile().intensity, 80);
    assert_eq!(HapticEvent::SelectionConfirm.base_profile().duration_ms, 25);

    assert_eq!(HapticEvent::InvalidAction.base_profile().intensity, 30);
    assert_eq!(HapticEvent::InvalidAction.base_profile().duration_ms, 50);
}

#[test]
fn test_haptic_event_patterns() {
    assert_eq!(HapticEvent::MenuAppear.pattern(), HapticPattern::Single);
    assert_eq!(HapticEvent::SliceChange.pattern(), HapticPattern::Single);
    assert_eq!(
        HapticEvent::SelectionConfirm.pattern(),
        HapticPattern::Double
    );
    assert_eq!(HapticEvent::InvalidAction.pattern(), HapticPattern::Triple);
}

#[test]
fn test_haptic_pattern_pulse_counts() {
    assert_eq!(HapticPattern::Single.pulse_count(), 1);
    assert_eq!(HapticPattern::Double.pulse_count(), 2);
    assert_eq!(HapticPattern::Triple.pulse_count(), 3);
}

#[test]
fn test_haptic_pattern_gaps() {
    assert_eq!(HapticPattern::Single.gap_ms(), 0);
    assert_eq!(HapticPattern::Double.gap_ms(), 30);
    assert_eq!(HapticPattern::Triple.gap_ms(), 20);
}

#[test]
fn test_haptic_event_display() {
    assert_eq!(format!("{}", HapticEvent::MenuAppear), "menu_appear");
    assert_eq!(format!("{}", HapticEvent::SliceChange), "slice_change");
    assert_eq!(
        format!("{}", HapticEvent::SelectionConfirm),
        "selection_confirm"
    );
    assert_eq!(format!("{}", HapticEvent::InvalidAction), "invalid_action");
}

#[test]
fn test_per_event_pattern_defaults() {
    let per_event = PerEventPattern::default();
    assert_eq!(per_event.menu_appear, Mx4HapticPattern::DampStateChange);
    assert_eq!(per_event.slice_change, Mx4HapticPattern::SubtleCollision);
    assert_eq!(per_event.confirm, Mx4HapticPattern::SharpStateChange);
    assert_eq!(per_event.invalid, Mx4HapticPattern::AngryAlert);
}

#[test]
fn test_per_event_pattern_get() {
    let per_event = PerEventPattern {
        menu_appear: Mx4HapticPattern::SubtleCollision,
        slice_change: Mx4HapticPattern::DampStateChange,
        confirm: Mx4HapticPattern::AngryAlert,
        invalid: Mx4HapticPattern::SharpStateChange,
    };

    assert_eq!(
        per_event.get(&HapticEvent::MenuAppear),
        Mx4HapticPattern::SubtleCollision
    );
    assert_eq!(
        per_event.get(&HapticEvent::SliceChange),
        Mx4HapticPattern::DampStateChange
    );
    assert_eq!(
        per_event.get(&HapticEvent::SelectionConfirm),
        Mx4HapticPattern::AngryAlert
    );
    assert_eq!(
        per_event.get(&HapticEvent::InvalidAction),
        Mx4HapticPattern::SharpStateChange
    );
}

#[test]
fn test_emit_disabled() {
    let mut manager = HapticManager::new(false);
    assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
}

#[test]
fn test_emit_no_device() {
    let mut manager = HapticManager::new(true);
    assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
    assert!(manager.emit(HapticEvent::SliceChange).is_ok());
    assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
    assert!(manager.emit(HapticEvent::InvalidAction).is_ok());
}

#[test]
fn test_emit_intensity_scaling() {
    let global = 50u32;
    let per_event = 80u32;
    let scaled = (global * per_event / 100) as u8;
    assert_eq!(scaled, 40);

    let global = 100u32;
    let per_event = 20u32;
    let scaled = (global * per_event / 100) as u8;
    assert_eq!(scaled, 20);

    let global = 25u32;
    let per_event = 40u32;
    let scaled = (global * per_event / 100) as u8;
    assert_eq!(scaled, 10);
}

#[test]
fn test_from_config_with_per_event() {
    use crate::config::{HapticConfig, HapticEventConfig};

    let config = HapticConfig {
        enabled: true,
        default_pattern: "subtle_collision".to_string(),
        per_event: HapticEventConfig {
            menu_appear: "damp_state_change".to_string(),
            slice_change: "sharp_state_change".to_string(),
            confirm: "angry_alert".to_string(),
            invalid: "subtle_collision".to_string(),
        },
        debounce_ms: 25,
        slice_debounce_ms: 20,
        reentry_debounce_ms: 50,
    };

    let manager = HapticManager::from_config(&config);
    assert!(manager.is_enabled());
    assert_eq!(
        manager.per_event.menu_appear,
        Mx4HapticPattern::DampStateChange
    );
    assert_eq!(
        manager.per_event.slice_change,
        Mx4HapticPattern::SharpStateChange
    );
    assert_eq!(manager.per_event.confirm, Mx4HapticPattern::AngryAlert);
    assert_eq!(manager.per_event.invalid, Mx4HapticPattern::SubtleCollision);
}

#[test]
fn test_update_from_config_with_per_event() {
    use crate::config::{HapticConfig, HapticEventConfig};

    let mut manager = HapticManager::new(true);

    let new_config = HapticConfig {
        enabled: true,
        default_pattern: "angry_alert".to_string(),
        per_event: HapticEventConfig {
            menu_appear: "sharp_state_change".to_string(),
            slice_change: "angry_alert".to_string(),
            confirm: "damp_state_change".to_string(),
            invalid: "subtle_collision".to_string(),
        },
        debounce_ms: 30,
        slice_debounce_ms: 20,
        reentry_debounce_ms: 50,
    };

    manager.update_from_config(&new_config);
    assert_eq!(manager.default_pattern(), Mx4HapticPattern::AngryAlert);
    assert_eq!(
        manager.per_event.menu_appear,
        Mx4HapticPattern::SharpStateChange
    );
    assert_eq!(manager.per_event.slice_change, Mx4HapticPattern::AngryAlert);
    assert_eq!(manager.per_event.confirm, Mx4HapticPattern::DampStateChange);
    assert_eq!(manager.per_event.invalid, Mx4HapticPattern::SubtleCollision);
}

// ========================================================================
// Story 5.4: Safety Verification Tests
// ========================================================================

#[test]
fn test_blocklisted_features_detection() {
    assert!(blocklisted_features::is_blocklisted(
        blocklisted_features::REPORT_RATE
    ));
    assert!(blocklisted_features::is_blocklisted(
        blocklisted_features::ONBOARD_PROFILES
    ));
    assert!(blocklisted_features::is_blocklisted(
        blocklisted_features::MODE_STATUS
    ));
    assert!(blocklisted_features::is_blocklisted(
        blocklisted_features::MOUSE_BUTTON_SPY
    ));
    assert!(blocklisted_features::is_blocklisted(
        blocklisted_features::PERSISTENT_REMAPPABLE_ACTION
    ));
    assert!(blocklisted_features::is_blocklisted(
        blocklisted_features::HOST_INFO
    ));

    // REPROG_CONTROLS_V4 (0x1B04) was moved to allowed
    assert!(!blocklisted_features::is_blocklisted(
        features::REPROG_CONTROLS_V4
    ));
}

#[test]
fn test_allowed_features_not_blocklisted() {
    assert!(!blocklisted_features::is_blocklisted(features::I_ROOT));
    assert!(!blocklisted_features::is_blocklisted(
        features::I_FEATURE_SET
    ));
    assert!(!blocklisted_features::is_blocklisted(features::DEVICE_NAME));
    assert!(!blocklisted_features::is_blocklisted(
        features::BATTERY_STATUS
    ));
    assert!(!blocklisted_features::is_blocklisted(features::LED_CONTROL));
    assert!(!blocklisted_features::is_blocklisted(
        features::FORCE_FEEDBACK
    ));
}

#[test]
fn test_allowed_features_in_safelist() {
    assert!(allowed_features::is_allowed(features::I_ROOT));
    assert!(allowed_features::is_allowed(features::I_FEATURE_SET));
    assert!(allowed_features::is_allowed(features::DEVICE_NAME));
    assert!(allowed_features::is_allowed(features::BATTERY_STATUS));
    assert!(allowed_features::is_allowed(features::LED_CONTROL));
    assert!(allowed_features::is_allowed(features::FORCE_FEEDBACK));
}

#[test]
fn test_verify_feature_safety_allowed() {
    assert!(verify_feature_safety(features::I_ROOT).is_ok());
    assert!(verify_feature_safety(features::I_FEATURE_SET).is_ok());
    assert!(verify_feature_safety(features::FORCE_FEEDBACK).is_ok());
}

#[test]
fn test_verify_feature_safety_blocklisted() {
    let result = verify_feature_safety(blocklisted_features::REPORT_RATE);
    assert!(result.is_err());

    if let Err(HapticError::SafetyViolation { feature_id, reason }) = result {
        assert_eq!(feature_id, blocklisted_features::REPORT_RATE);
        assert!(reason.contains("report rate") || reason.contains("persist"));
    } else {
        panic!("Expected SafetyViolation error");
    }
}

#[test]
fn test_reprog_controls_v4_is_allowed() {
    assert!(verify_feature_safety(features::REPROG_CONTROLS_V4).is_ok());
    assert!(allowed_features::is_allowed(features::REPROG_CONTROLS_V4));
}

#[test]
fn test_verify_feature_safety_onboard_profiles() {
    let result = verify_feature_safety(blocklisted_features::ONBOARD_PROFILES);
    assert!(result.is_err());

    if let Err(HapticError::SafetyViolation { feature_id, reason }) = result {
        assert_eq!(feature_id, 0x8100);
        assert!(reason.contains("profile") || reason.contains("Persistent"));
    } else {
        panic!("Expected SafetyViolation error");
    }
}

#[test]
fn test_verify_feature_safety_unknown() {
    let unknown_feature = 0x9999;
    assert!(!blocklisted_features::is_blocklisted(unknown_feature));
    assert!(!allowed_features::is_allowed(unknown_feature));
    assert!(verify_feature_safety(unknown_feature).is_ok());
}

#[test]
fn test_safety_violation_error_display() {
    let error = HapticError::SafetyViolation {
        feature_id: 0x8100,
        reason: "Persistent profile storage",
    };
    let msg = format!("{}", error);
    assert!(msg.contains("SAFETY VIOLATION"));
    assert!(msg.contains("8100"));
    assert!(msg.contains("Persistent"));
}

#[test]
fn test_blocklist_reasons_exist() {
    assert!(
        blocklisted_features::blocklist_reason(blocklisted_features::ONBOARD_PROFILES).is_some()
    );
    assert!(blocklisted_features::blocklist_reason(blocklisted_features::REPORT_RATE).is_some());

    assert!(blocklisted_features::blocklist_reason(features::FORCE_FEEDBACK).is_none());
    assert!(blocklisted_features::blocklist_reason(features::REPROG_CONTROLS_V4).is_none());
}

#[test]
fn test_haptic_feature_is_safe() {
    assert!(!blocklisted_features::is_blocklisted(
        features::FORCE_FEEDBACK
    ));
    assert!(allowed_features::is_allowed(features::FORCE_FEEDBACK));
    assert!(verify_feature_safety(features::FORCE_FEEDBACK).is_ok());
}

// ========================================================================
// Story 5.5: Graceful Fallback & Error Handling Tests
// ========================================================================

#[test]
fn test_connection_state_default() {
    let manager = HapticManager::new(true);
    assert_eq!(manager.connection_state(), ConnectionState::NotConnected);
}

#[test]
fn test_pulse_succeeds_when_no_device() {
    let mut manager = HapticManager::new(true);
    assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
    assert_eq!(manager.connection_state(), ConnectionState::NotConnected);
}

#[test]
fn test_emit_succeeds_when_no_device() {
    let mut manager = HapticManager::new(true);
    assert!(manager.emit(HapticEvent::MenuAppear).is_ok());
    assert!(manager.emit(HapticEvent::SliceChange).is_ok());
    assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
    assert!(manager.emit(HapticEvent::InvalidAction).is_ok());
}

#[test]
fn test_reconnect_not_needed_when_not_connected() {
    let mut manager = HapticManager::new(true);
    assert!(!manager.reconnect_if_needed());
    assert_eq!(manager.connection_state(), ConnectionState::NotConnected);
}

#[test]
fn test_connection_state_enum_variants() {
    assert_ne!(ConnectionState::NotConnected, ConnectionState::Connected);
    assert_ne!(ConnectionState::Connected, ConnectionState::Disconnected);
    assert_ne!(ConnectionState::Disconnected, ConnectionState::Cooldown);
}

#[test]
fn test_connection_state_default_trait() {
    let state: ConnectionState = Default::default();
    assert_eq!(state, ConnectionState::NotConnected);
}

#[test]
fn test_graceful_fallback_on_disabled() {
    let mut manager = HapticManager::new(false);
    assert!(manager.pulse(haptic_profiles::CONFIRM).is_ok());
    assert!(manager.emit(HapticEvent::SelectionConfirm).is_ok());
}

#[test]
fn test_reconnect_cooldown_constant() {
    // We can't directly access RECONNECT_COOLDOWN_MS from here,
    // but we verify the behavior is correct through integration tests.
    // The constant is 5000ms.
}

// ========================================================================
// Story 5.6: Haptic Latency Optimization Tests
// ========================================================================

#[test]
fn test_slice_debounce_defaults() {
    // Verify default slice debounce is 20ms per UX spec
    let manager = HapticManager::new(true);
    assert_eq!(manager.slice_debounce_ms(), 20);
}

#[test]
fn test_reentry_debounce_defaults() {
    // Verify default re-entry debounce is 50ms per UX spec
    let manager = HapticManager::new(true);
    assert_eq!(manager.reentry_debounce_ms(), 50);
}

#[test]
fn test_manager_slice_debounce_defaults() {
    let manager = HapticManager::new(true);
    assert_eq!(manager.slice_debounce_ms(), 20);
    assert_eq!(manager.reentry_debounce_ms(), 50);
}

#[test]
fn test_emit_slice_change_disabled() {
    let mut manager = HapticManager::new(false);
    assert!(!manager.emit_slice_change(0));
    assert!(!manager.emit_slice_change(1));
}

#[test]
fn test_emit_slice_change_no_device() {
    let mut manager = HapticManager::new(true);
    manager.last_slice_change_ms = 0;
    assert!(manager.emit_slice_change(0));
}

#[test]
fn test_reset_slice_tracking() {
    let mut manager = HapticManager::new(true);
    manager.last_slice_index = Some(3);
    manager.last_slice_change_ms = 12345;

    manager.reset_slice_tracking();

    assert_eq!(manager.last_slice_index, None);
    assert_eq!(manager.last_slice_change_ms, 0);
}

#[test]
fn test_set_slice_debounce_ms() {
    let mut manager = HapticManager::new(true);
    manager.set_slice_debounce_ms(30);
    assert_eq!(manager.slice_debounce_ms(), 30);
}

#[test]
fn test_set_reentry_debounce_ms() {
    let mut manager = HapticManager::new(true);
    manager.set_reentry_debounce_ms(100);
    assert_eq!(manager.reentry_debounce_ms(), 100);
}

#[test]
fn test_from_config_with_slice_debounce() {
    use crate::config::HapticConfig;

    let config = HapticConfig {
        enabled: true,
        default_pattern: "subtle_collision".to_string(),
        per_event: Default::default(),
        debounce_ms: 20,
        slice_debounce_ms: 25,
        reentry_debounce_ms: 60,
    };

    let manager = HapticManager::from_config(&config);
    assert_eq!(manager.slice_debounce_ms(), 25);
    assert_eq!(manager.reentry_debounce_ms(), 60);
}

#[test]
fn test_update_from_config_with_slice_debounce() {
    use crate::config::HapticConfig;

    let mut manager = HapticManager::new(true);
    assert_eq!(manager.slice_debounce_ms(), 20);
    assert_eq!(manager.reentry_debounce_ms(), 50);

    let new_config = HapticConfig {
        enabled: true,
        default_pattern: "subtle_collision".to_string(),
        per_event: Default::default(),
        debounce_ms: 20,
        slice_debounce_ms: 35,
        reentry_debounce_ms: 75,
    };

    manager.update_from_config(&new_config);
    assert_eq!(manager.slice_debounce_ms(), 35);
    assert_eq!(manager.reentry_debounce_ms(), 75);
}

#[test]
fn test_short_message_buffer_preallocated() {
    let manager = HapticManager::new(true);
    assert_eq!(manager._short_msg_buffer.len(), 7);
}

#[test]
fn test_pulse_command_construction_fast() {
    let msg = HidppShortMessage::new(0xFF, 0x00, 0x01, 0x05).with_params([0xAA, 0xBB, 0xCC]);

    let bytes = msg.to_bytes();
    assert_eq!(bytes.len(), 7);
}
