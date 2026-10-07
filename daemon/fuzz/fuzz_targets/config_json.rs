//! config.json is written by two Settings apps, by hand and by imported
//! backups: whatever it holds, loading it and asking it the questions every
//! button press asks must not panic.
#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    if let Ok(config) = serde_json::from_slice::<juhradiald::Config>(data) {
        let _ = config.remapped_button_cids();
        let _ = config.directional_gestures_enabled();
        let _ = config.classify_gesture(120, -40, Some(1000));
        let _ = config.classify_gesture(i32::MIN, i32::MAX, None);
        let _ = serde_json::to_string(&config);
    }
    if let Ok(text) = std::str::from_utf8(data) {
        let _ = juhradiald::config::parse_control_cid(text);
        let _ = juhradiald::macros::triggers::parse_trigger(text);
    }
});
