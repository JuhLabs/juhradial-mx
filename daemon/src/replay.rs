//! Re-apply pointer and scroll state after the mouse (re)connects.
//!
//! DPI, SmartShift and the hi-res/invert bits are volatile on a wake or an
//! Easy-Switch return on some firmware, and the Settings app writes them only
//! once, so a mouse that came back could silently run with other values than
//! the ones Settings shows. The hidraw loop calls
//! [`replay_effective_state`] after every successful refresh; [`ReplayGate`]
//! collapses the burst of triggers one wake produces into one replay.
//!
//! Only keys present in config.json are replayed, so a user who never touched
//! a setting keeps the device's own value. Precedence: global settings (with
//! the connected mouse's `devices.<unit>` overrides), then the focused app's
//! hardware profile, then the gaming-mode DPI. Natural scroll is always the
//! global setting (profiles never own it).

use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::profiles::HardwareProfile;

/// One wake fires a HostChanged, a 0x41 link-up and a 0x1D4B in a row.
pub const REPLAY_DEBOUNCE: Duration = Duration::from_secs(2);

/// The class whose hardware profile is applied right now (None = globals).
pub type SharedActiveProfile = Arc<RwLock<Option<String>>>;

/// DPI chosen with a DPI button action (cycle, up, down) this session. It
/// replaces `pointer.dpi` in replay so a wake does not undo the button;
/// `SetDpi` from Settings clears it.
static SESSION_DPI: RwLock<Option<u16>> = RwLock::new(None);

pub fn set_session_dpi(dpi: Option<u16>) {
    if let Ok(mut cell) = SESSION_DPI.write() {
        *cell = dpi;
    }
}

/// Global state with the session DPI on top.
pub fn with_session_dpi(mut globals: DeviceState) -> DeviceState {
    if let Some(dpi) = SESSION_DPI.read().ok().and_then(|cell| *cell) {
        globals.dpi = Some(dpi);
    }
    globals
}

pub fn new_shared_active_profile() -> SharedActiveProfile {
    Arc::new(RwLock::new(None))
}

/// Pointer and scroll state to write; `None` = leave the device alone.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DeviceState {
    pub dpi: Option<u16>,
    /// (auto_disengage enabled, device threshold) as `SetSmartShift` takes it.
    pub smartshift: Option<(bool, u8)>,
    pub hires: Option<bool>,
    pub natural: Option<bool>,
}

/// Settings Easy 1 % .. Hard 100 % -> HID++ threshold 1..49 (PR #123).
pub fn ui_to_device_threshold(ui: i64) -> u8 {
    let ui = ui.clamp(1, 100);
    (1 + ((ui - 1) * 48 + 49) / 99) as u8
}

fn section<'a>(raw: &'a Value, unit_key: Option<&str>, name: &str, key: &str) -> Option<&'a Value> {
    let over = unit_key.and_then(|unit| {
        raw.get("devices")?
            .as_object()?
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(unit))
            .and_then(|(_, v)| v.get(name)?.get(key))
    });
    over.or_else(|| raw.get(name)?.get(key))
}

/// The global state config.json asks for (with `devices.<unit>` overrides).
pub fn globals_from_config(raw: &Value, unit_key: Option<&str>) -> DeviceState {
    let get = |name: &str, key: &str| section(raw, unit_key, name, key);
    let dpi = get("pointer", "dpi")
        .and_then(Value::as_u64)
        .filter(|d| (100..=25_600).contains(d))
        .map(|d| d as u16);
    let threshold = get("scroll", "smartshift_threshold")
        .and_then(Value::as_i64)
        .unwrap_or(50);
    let smartshift = match get("scroll", "mode").and_then(Value::as_str) {
        Some("smartshift") => Some((true, ui_to_device_threshold(threshold))),
        Some("ratchet") => Some((false, 0)),
        Some("freespin") => Some((true, 0)),
        _ => None,
    };
    DeviceState {
        dpi,
        smartshift,
        hires: get("scroll", "smooth").and_then(Value::as_bool),
        natural: get("scroll", "natural").and_then(Value::as_bool),
    }
}

/// Globals, then the app profile, then the gaming-mode DPI.
pub fn effective_state(
    globals: DeviceState,
    profile: Option<&HardwareProfile>,
    gaming_dpi: Option<u16>,
) -> DeviceState {
    let mut s = globals;
    if let Some(p) = profile {
        s.dpi = p.dpi.or(s.dpi);
        s.smartshift = p.smartshift.map(|ss| (ss.enabled, ss.threshold)).or(s.smartshift);
        s.hires = p.hires.or(s.hires);
    }
    s.dpi = gaming_dpi.or(s.dpi);
    s
}

/// The three volatile setters replay needs (implemented by the manager).
pub trait ReplayTarget {
    fn replay_smartshift(&mut self, enabled: bool, threshold: u8) -> bool;
    fn replay_hires(&mut self, hires: bool, invert: bool) -> bool;
    fn replay_dpi(&mut self, dpi: u16) -> bool;
}

impl ReplayTarget for crate::hidpp::HapticManager {
    fn replay_smartshift(&mut self, enabled: bool, threshold: u8) -> bool {
        self.set_smart_shift(enabled, threshold).is_ok()
    }
    fn replay_hires(&mut self, hires: bool, invert: bool) -> bool {
        self.set_hiresscroll_mode(hires, invert, false).is_ok()
    }
    fn replay_dpi(&mut self, dpi: u16) -> bool {
        self.set_dpi(dpi).is_ok()
    }
}

/// (writes attempted, writes that failed)
pub fn apply(target: &mut impl ReplayTarget, s: &DeviceState) -> (u8, u8) {
    let (mut tried, mut failed) = (0u8, 0u8);
    let mut count = |ok: bool| {
        tried += 1;
        if !ok {
            failed += 1;
        }
    };
    if let Some((enabled, threshold)) = s.smartshift {
        count(target.replay_smartshift(enabled, threshold));
    }
    // The hi-res write carries both bits; defaults match Settings (smooth on,
    // natural off) for whichever one config.json does not name.
    if s.hires.is_some() || s.natural.is_some() {
        count(target.replay_hires(s.hires.unwrap_or(true), s.natural.unwrap_or(false)));
    }
    if let Some(dpi) = s.dpi {
        count(target.replay_dpi(dpi));
    }
    (tried, failed)
}

/// Lets one replay through per [`REPLAY_DEBOUNCE`]; a failed replay does not
/// count, so the next trigger retries.
#[derive(Debug, Default)]
pub struct ReplayGate {
    last_ok: Option<Instant>,
}

impl ReplayGate {
    pub fn should_run(&self, now: Instant) -> bool {
        self.last_ok
            .is_none_or(|t| now.saturating_duration_since(t) >= REPLAY_DEBOUNCE)
    }
    pub fn record_success(&mut self, now: Instant) {
        self.last_ok = Some(now);
    }
}

impl DeviceState {
    /// Field-wise: self where set, else `other`.
    pub fn or(self, other: DeviceState) -> DeviceState {
        DeviceState {
            dpi: self.dpi.or(other.dpi),
            smartshift: self.smartshift.or(other.smartshift),
            hires: self.hires.or(other.hires),
            natural: self.natural.or(other.natural),
        }
    }
}

/// What the device runs right now (used as the baseline to restore when the
/// focus leaves a profiled app and config.json names no global value).
pub fn read_device_state(m: &mut crate::hidpp::HapticManager) -> DeviceState {
    let hires = m.get_hiresscroll_mode();
    DeviceState {
        dpi: m.get_dpi(),
        smartshift: m.get_smart_shift(),
        hires: hires.map(|(h, _, _)| h),
        natural: hires.map(|(_, i, _)| i),
    }
}

/// Shared state replay needs besides config.json.
#[derive(Clone)]
pub struct ReplayContext {
    pub gaming_mode: crate::gaming::SharedGamingMode,
    pub hardware_profiles: crate::profiles::SharedHardwareProfiles,
    pub active_profile: SharedActiveProfile,
}

impl ReplayContext {
    pub fn gaming_dpi(&self) -> Option<u16> {
        self.gaming_mode.read().ok().and_then(|g| g.active_dpi())
    }

    pub fn active_hardware_profile(&self) -> Option<HardwareProfile> {
        let class = self.active_profile.read().ok()?.clone()?;
        self.hardware_profiles.read().ok()?.get(&class).cloned()
    }

    /// The state to replay now for the given unit key.
    pub fn effective(&self, unit_key: Option<&str>) -> DeviceState {
        let globals = with_session_dpi(globals_from_config(&load_raw_config(), unit_key));
        effective_state(globals, self.active_hardware_profile().as_ref(), self.gaming_dpi())
    }
}

/// config.json as JSON (empty object when missing or unreadable).
pub fn load_raw_config() -> Value {
    crate::config::Config::default_config_path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or(Value::Object(Default::default()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::profiles::SmartshiftSetting;
    use serde_json::json;

    #[derive(Default)]
    struct Fake {
        calls: Vec<String>,
        fail_dpi: bool,
    }
    impl ReplayTarget for Fake {
        fn replay_smartshift(&mut self, e: bool, t: u8) -> bool {
            self.calls.push(format!("ss {e} {t}"));
            true
        }
        fn replay_hires(&mut self, h: bool, i: bool) -> bool {
            self.calls.push(format!("hires {h} {i}"));
            true
        }
        fn replay_dpi(&mut self, d: u16) -> bool {
            self.calls.push(format!("dpi {d}"));
            !self.fail_dpi
        }
    }

    #[test]
    fn threshold_mapping_matches_settings() {
        assert_eq!(ui_to_device_threshold(1), 1);
        assert_eq!(ui_to_device_threshold(50), 25);
        assert_eq!(ui_to_device_threshold(100), 49);
        assert_eq!(ui_to_device_threshold(0), 1);
        assert_eq!(ui_to_device_threshold(500), 49);
    }

    #[test]
    fn absent_keys_are_never_replayed() {
        let s = globals_from_config(&json!({"radial": {}}), None);
        assert_eq!(s, DeviceState::default());
        let mut f = Fake::default();
        assert_eq!(apply(&mut f, &s), (0, 0));
        assert!(f.calls.is_empty());
    }

    #[test]
    fn globals_map_modes_and_unit_overrides() {
        let raw = json!({
            "pointer": {"dpi": 1600},
            "scroll": {"mode": "smartshift", "smartshift_threshold": 50, "natural": true},
            "devices": {"0x1234ABCD": {"pointer": {"dpi": 800}}}
        });
        let s = globals_from_config(&raw, None);
        assert_eq!(s.dpi, Some(1600));
        assert_eq!(s.smartshift, Some((true, 25)));
        assert_eq!(s.natural, Some(true));
        assert_eq!(s.hires, None);
        assert_eq!(globals_from_config(&raw, Some("0x1234abcd")).dpi, Some(800));
        let ratchet = globals_from_config(&json!({"scroll": {"mode": "ratchet"}}), None);
        assert_eq!(ratchet.smartshift, Some((false, 0)));
        let free = globals_from_config(&json!({"scroll": {"mode": "freespin"}}), None);
        assert_eq!(free.smartshift, Some((true, 0)));
        let junk = globals_from_config(&json!({"pointer": {"dpi": 5}}), None);
        assert_eq!(junk.dpi, None);
    }

    #[test]
    fn profile_then_gaming_win_but_natural_stays_global() {
        let globals = DeviceState { dpi: Some(1600), smartshift: Some((true, 25)), hires: Some(true), natural: Some(true) };
        let profile = HardwareProfile {
            dpi: Some(800),
            smartshift: Some(SmartshiftSetting { enabled: false, threshold: 0 }),
            hires: Some(false),
            ..Default::default()
        };
        let s = effective_state(globals, Some(&profile), None);
        assert_eq!(s, DeviceState { dpi: Some(800), smartshift: Some((false, 0)), hires: Some(false), natural: Some(true) });
        assert_eq!(effective_state(globals, Some(&profile), Some(3200)).dpi, Some(3200));
        assert_eq!(effective_state(globals, None, None), globals);
    }

    #[test]
    fn apply_writes_smartshift_then_hires_then_dpi_and_counts_failures() {
        let s = DeviceState { dpi: Some(1000), smartshift: Some((true, 10)), hires: None, natural: Some(true) };
        let mut f = Fake { fail_dpi: true, ..Default::default() };
        assert_eq!(apply(&mut f, &s), (3, 1));
        assert_eq!(f.calls, vec!["ss true 10", "hires true true", "dpi 1000"]);
    }

    #[test]
    fn baseline_fills_only_what_config_leaves_out() {
        let config = DeviceState { dpi: Some(1600), ..Default::default() };
        let baseline = DeviceState { dpi: Some(1000), smartshift: Some((true, 30)), hires: Some(true), natural: Some(false) };
        assert_eq!(
            config.or(baseline),
            DeviceState { dpi: Some(1600), smartshift: Some((true, 30)), hires: Some(true), natural: Some(false) }
        );
    }

    #[test]
    fn gate_collapses_a_burst_and_retries_after_failure() {
        let t0 = Instant::now();
        let mut g = ReplayGate::default();
        assert!(g.should_run(t0));
        // A failed replay records nothing, so the next trigger runs.
        assert!(g.should_run(t0 + Duration::from_millis(300)));
        g.record_success(t0);
        assert!(!g.should_run(t0 + Duration::from_millis(1500)));
        assert!(g.should_run(t0 + REPLAY_DEBOUNCE));
    }
}
