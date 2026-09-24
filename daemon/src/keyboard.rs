//! Keyboard support (BETA, opt-in): generic evdev remap + MX Keys S HID++.
//!
//! This module is entirely ADDITIVE and gated off by default. It is separate
//! from the mouse paths (`evdev.rs`, `hidraw.rs`, `hidpp/`) and never modifies
//! them. Two independent capabilities live here:
//!
//! 1. **Generic keyboard remap** (`run_keyboard_remap_loop`): grabs the first
//!    physical keyboard and rewrites source evdev key codes to targets via a
//!    virtual keyboard. This is the testable part and works with ANY keyboard.
//!    It only grabs when the user has set `keyboard.enabled = true` AND defined
//!    at least one remap entry, so a default install never touches the keyboard.
//!
//! 2. **MX Keys S HID++ scaffold** (`KeyboardManager`): battery readback via
//!    UNIFIED_BATTERY (0x1004) and a backlight set via BACKLIGHT2 (0x1982). It
//!    reuses the existing `HidppDevice` abstraction through the keyboard-only
//!    `HidppDevice::open_keyboard()` constructor, connects lazily, and never
//!    panics when no keyboard is present. The backlight write is verified on
//!    an MX Keys S over Bolt (see `HidppDevice::set_backlight`).
//!
//! SPDX-License-Identifier: GPL-3.0

use std::sync::{Mutex, OnceLock};

use crate::hidpp::device::HidppDevice;

#[cfg(target_os = "linux")]
use std::collections::HashMap;
#[cfg(target_os = "linux")]
use std::path::{Path, PathBuf};
#[cfg(target_os = "linux")]
use std::sync::Arc;
#[cfg(target_os = "linux")]
use std::time::Duration;
#[cfg(target_os = "linux")]
use tokio::sync::Notify;

use crate::config::SharedConfig;

// ============================================================================
// MX Keys S HID++ manager (battery + backlight)
// ============================================================================

/// Lazily-created process-global MX Keys S manager.
///
/// A keyboard is naturally a singleton for this daemon, and the manager only
/// acts on explicit D-Bus calls, so a global avoids threading a new field
/// through the D-Bus service constructors (keeping the mouse wiring untouched).
static KEYBOARD_MANAGER: OnceLock<Mutex<KeyboardManager>> = OnceLock::new();

/// Access the shared MX Keys S keyboard manager (created on first use).
pub fn manager() -> &'static Mutex<KeyboardManager> {
    KEYBOARD_MANAGER.get_or_init(|| Mutex::new(KeyboardManager::new()))
}

/// HID++ wrapper for an MX Keys S keyboard (battery + backlight). BETA.
///
/// Holds its own hidraw connection, separate from the mouse `HapticManager`,
/// and connects lazily on first use. Every method returns a safe default when
/// no keyboard is present, so nothing here can panic on a mouse-only system.
pub struct KeyboardManager {
    device: Option<HidppDevice>,
    /// Cached receiver pairing-table presence (see [`keyboard_paired`]): each
    /// probe costs a ~0.5s receiver exchange, and the settings UI may poll.
    paired_cache: Option<(bool, std::time::Instant)>,
    /// Last failed connect scan. Scans cost ~1s of receiver traffic, run on
    /// the D-Bus executor (blocking other calls = UI lag spikes), and the
    /// settings UI polls on every page open, so failures are rate-limited.
    last_connect_fail: Option<std::time::Instant>,
    /// Until when the keyboard counts as asleep after the receiver reported
    /// its radio parked, so repeated UI polls cost no receiver traffic.
    asleep_until: Option<std::time::Instant>,
    /// Receiver hidraw node and slot of the paired keyboard, learned from the
    /// pairing-table probe; the link watcher listens there.
    slot: Option<(std::path::PathBuf, u8)>,
}

/// How long a POSITIVE pairing-table presence probe stays valid.
const PAIRED_CACHE_TTL: std::time::Duration = std::time::Duration::from_secs(15);
/// How long a NEGATIVE presence probe stays valid: long enough to stop UI
/// polls from hammering the receiver, short enough that a newly-paired
/// keyboard appears on the next page open.
const PAIRED_NEG_CACHE_TTL: std::time::Duration = std::time::Duration::from_secs(5);
/// Minimum spacing between failed connect scans.
const CONNECT_RETRY_BACKOFF: std::time::Duration = std::time::Duration::from_secs(3);
/// How long a "radio parked" answer stays valid before the next battery probe.
const ASLEEP_CACHE_TTL: std::time::Duration = std::time::Duration::from_secs(2);

impl KeyboardManager {
    /// Create an unconnected manager.
    pub fn new() -> Self {
        Self {
            device: None,
            paired_cache: None,
            last_connect_fail: None,
            asleep_until: None,
            slot: None,
        }
    }

    /// Whether a keyboard is PAIRED to a connected receiver.
    ///
    /// Answered from the receiver's pairing table, so it stays true while the
    /// keyboard's radio deep-sleeps - the state where `query_battery` fails
    /// because the keyboard ignores pings until a key press wakes it. This is
    /// what "present" means for the UI; battery/backlight need it awake.
    pub fn keyboard_paired(&mut self) -> bool {
        self.paired(true)
    }

    /// Presence from the receivers' pairing registers only (no fake-arrival,
    /// so no 0x41 notices reach the mouse path). Safe while MX Keys S support
    /// is off, which is when Settings offers to turn it on.
    pub fn keyboard_detected(&mut self) -> bool {
        self.paired(false)
    }

    fn paired(&mut self, announce: bool) -> bool {
        if self.device.is_some() {
            return true;
        }
        if let Some((paired, at)) = self.paired_cache {
            let ttl = if paired { PAIRED_CACHE_TTL } else { PAIRED_NEG_CACHE_TTL };
            if at.elapsed() < ttl {
                return paired;
            }
        }
        // Passive register read first. Fake-arrival (only with `announce`)
        // covers receivers that ignore it, with two attempts: a single false
        // can be a collision with a concurrent mouse discovery scan holding
        // the receiver busy (seen live after a restart with every device
        // asleep). Negatives get only a short TTL so a newly-paired keyboard
        // still shows up quickly.
        let found = HidppDevice::find_paired_keyboard_passive().or_else(|| {
            if announce {
                (0..2).find_map(|_| HidppDevice::find_paired_keyboard())
            } else {
                None
            }
        });
        let paired = found.is_some();
        if found.is_some() {
            self.slot = found;
        }
        self.paired_cache = Some((paired, std::time::Instant::now()));
        paired
    }

    /// Receiver hidraw node and slot of the paired keyboard, probing the
    /// pairing tables when nothing is known yet. `None` for a keyboard on a
    /// direct link (USB cable, Bluetooth), which sends no receiver notices.
    pub fn receiver_slot(&mut self) -> Option<(std::path::PathBuf, u8)> {
        if let Some(device) = self.device.as_ref() {
            if device.device_index() == 0xFF {
                return None;
            }
            return Some((device.device_path().to_path_buf(), device.device_index()));
        }
        if self.slot.is_none() {
            self.keyboard_paired();
        }
        self.slot.clone()
    }

    /// The receiver just reported the keyboard's link up: forget the cached
    /// "asleep" answer and the connect back-off so the next query runs now.
    pub fn mark_awake(&mut self) {
        self.asleep_until = None;
        self.last_connect_fail = None;
    }

    /// Connect to a keyboard if not already connected. Returns whether a device
    /// is now available.
    fn ensure_connected(&mut self) -> bool {
        if self.device.is_none() {
            if let Some(at) = self.last_connect_fail {
                if at.elapsed() < CONNECT_RETRY_BACKOFF {
                    return false;
                }
            }
            self.device = HidppDevice::open_keyboard();
            self.last_connect_fail = if self.device.is_none() {
                Some(std::time::Instant::now())
            } else {
                None
            };
        }
        self.device.is_some()
    }

    /// Query battery as `(percent, charging)`. Returns `None` when no keyboard
    /// is present or the query fails. Drops the connection on IO error so the
    /// next call reconnects.
    /// The keyboard's Easy-Switch slots (HOSTS_INFO), for matching the
    /// mouse's slots by computer name.
    pub fn hosts_table(&mut self) -> Vec<crate::hidpp::device::HostSlot> {
        if !self.ensure_connected() {
            return Vec::new();
        }
        self.device.as_mut().map(|d| d.hosts_table()).unwrap_or_default()
    }

    /// The keyboard's BACKLIGHT2 feature index (its backlight-key events).
    pub fn backlight_index(&mut self) -> Option<u8> {
        if !self.ensure_connected() {
            return None;
        }
        self.device.as_ref()?.backlight_feature_index()
    }

    /// The keyboard's CHANGE_HOST feature index (its Easy-Switch events).
    pub fn change_host_index(&mut self) -> Option<u8> {
        if !self.ensure_connected() {
            return None;
        }
        self.device.as_mut()?.change_host_index()
    }

    /// Send the keyboard to another computer (CHANGE_HOST).
    pub fn set_current_host(&mut self, slot: u8) -> Result<(), String> {
        if !self.ensure_connected() {
            return Err("keyboard not connected".to_string());
        }
        self.device
            .as_mut()
            .ok_or_else(|| "keyboard not connected".to_string())?
            .set_current_host(slot)
    }

    pub fn query_battery(&mut self) -> Option<(u8, bool)> {
        if let Some(until) = self.asleep_until {
            if std::time::Instant::now() < until {
                return None;
            }
        }
        if !self.ensure_connected() {
            return None;
        }
        match self.device.as_mut()?.query_battery() {
            Ok(v) => {
                self.asleep_until = None;
                Some(v)
            }
            Err(e) => {
                if self.device.as_ref().is_some_and(|d| d.link_parked()) {
                    // Paired but its radio is parked (idle, or on another
                    // Easy-Switch host). Keep the connection: dropping it made
                    // every Settings open rescan two receivers for seconds.
                    tracing::debug!("Keyboard radio parked; keeping the connection, reporting asleep");
                    self.asleep_until = Some(std::time::Instant::now() + ASLEEP_CACHE_TTL);
                    return None;
                }
                tracing::debug!(error = %e, "Keyboard battery query failed; dropping connection");
                self.device = None;
                None
            }
        }
    }

    /// Whether the connected keyboard exposes the BACKLIGHT2 feature.
    pub fn backlight_supported(&mut self) -> bool {
        if !self.ensure_connected() {
            return false;
        }
        self.device
            .as_ref()
            .map(|d| d.backlight_supported())
            .unwrap_or(false)
    }

    /// Current backlight state, `None` when the keyboard is absent, asleep
    /// or has no BACKLIGHT2. READ-ONLY.
    pub fn backlight_state(&mut self) -> Option<crate::hidpp::device::BacklightState> {
        if !self.ensure_connected() {
            return None;
        }
        self.device.as_mut()?.query_backlight_state()
    }

    /// Set backlight brightness (0..=100). BETA (see
    /// `HidppDevice::set_backlight`). Returns whether the command was sent.
    pub fn set_backlight(&mut self, brightness: u8) -> bool {
        self.backlight_write("level", |d| d.set_backlight(brightness))
    }

    /// Automatic (light sensor) or Manual backlight.
    pub fn set_backlight_mode(&mut self, automatic: bool) -> bool {
        self.backlight_write("mode", |d| d.set_backlight_mode(automatic))
    }

    /// Stay-on durations in seconds (0 = keep): hands away, near, on a cable.
    pub fn set_backlight_durations(&mut self, away_s: u16, near_s: u16, powered_s: u16) -> bool {
        self.backlight_write("durations", |d| d.set_backlight_durations(away_s, near_s, powered_s))
    }

    fn backlight_write(
        &mut self,
        what: &str,
        write: impl FnOnce(&mut HidppDevice) -> Result<(), crate::hidpp::HapticError>,
    ) -> bool {
        if !self.ensure_connected() {
            return false;
        }
        let Some(device) = self.device.as_mut() else {
            return false;
        };
        match write(device) {
            Ok(()) => true,
            Err(e) => {
                tracing::warn!(error = %e, what, "Keyboard backlight write failed");
                // Drop the connection on a hard IO failure so the next call
                // reconnects with a fresh fd.
                if matches!(e, crate::hidpp::HapticError::IoError(_)) {
                    self.device = None;
                }
                false
            }
        }
    }
}

impl Default for KeyboardManager {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// Generic keyboard remap (evdev) - the testable part
// ============================================================================

/// List the evdev key codes supported by the first physical keyboard, as
/// decimal strings (sorted, deduped). Empty when no keyboard is found.
///
/// READ-ONLY: it opens the device only to read its capabilities and never
/// grabs it. Intended for the settings UI to populate a remap picker. Safe to
/// call with no keyboard attached (returns an empty list).
pub fn list_keyboard_key_codes() -> Vec<String> {
    #[cfg(not(target_os = "linux"))]
    {
        Vec::new()
    }

    #[cfg(target_os = "linux")]
    {
        let path = match find_keyboard() {
            Some((p, _name)) => p,
            None => return Vec::new(),
        };
        let dev = match evdev::Device::open(&path) {
            Ok(d) => d,
            Err(_) => return Vec::new(),
        };
        let mut codes: Vec<u16> = match dev.supported_keys() {
            Some(keys) => keys.iter().map(|k| k.code()).collect(),
            None => Vec::new(),
        };
        codes.sort_unstable();
        codes.dedup();
        codes.into_iter().map(|c| c.to_string()).collect()
    }
}

/// Find the first physical keyboard: a device with EV_KEY that supports a
/// spread of typing keys (A, Z, Space, Enter), has a real physical path (skips
/// virtual/uinput devices, including the virtual keyboard we create), and is
/// returned as `(path, name)`.
#[cfg(target_os = "linux")]
fn find_keyboard() -> Option<(PathBuf, String)> {
    use evdev::{Device, KeyCode};

    let input_dir = PathBuf::from("/dev/input");
    let mut entries: Vec<_> = std::fs::read_dir(&input_dir).ok()?.flatten().collect();
    // Lower event numbers first (physical devices precede virtual ones).
    entries.sort_by_key(|e| {
        e.file_name()
            .to_str()
            .and_then(|n| n.strip_prefix("event").and_then(|x| x.parse::<u32>().ok()))
            .unwrap_or(u32::MAX)
    });

    for entry in entries {
        let path = entry.path();
        let fname = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if !fname.starts_with("event") {
            continue;
        }
        let dev = match Device::open(&path) {
            Ok(d) => d,
            Err(_) => continue,
        };
        // Skip virtual devices (no physical path), including our own vdev.
        if dev.physical_path().unwrap_or("").is_empty() {
            continue;
        }
        let keys = match dev.supported_keys() {
            Some(k) => k,
            None => continue,
        };
        // Require a spread of letter/whitespace keys to identify a real typing
        // keyboard (filters mice, consumer-control, and power-button nodes that
        // also expose EV_KEY).
        let is_keyboard = keys.contains(KeyCode::KEY_A)
            && keys.contains(KeyCode::KEY_Z)
            && keys.contains(KeyCode::KEY_SPACE)
            && keys.contains(KeyCode::KEY_ENTER);
        if !is_keyboard {
            continue;
        }
        let name = dev.name().unwrap_or("Keyboard").to_string();
        return Some((path, name));
    }
    None
}

// ============================================================================
// Keyboard link watcher (live battery and awake state for Settings)
// ============================================================================

/// True when `report` is the receiver's device-connection notice (HID++ 1.0
/// sub-id 0x41, short report) for slot `index` with the link-down bit clear.
///
/// An MX Keys S parks its radio seconds after the last key press and the
/// receiver sends no notice for that; the next key press re-links it and the
/// receiver announces the link, which is the moment the keyboard answers.
pub fn link_up_in_report(report: &[u8], index: u8) -> bool {
    report.len() >= 5
        && report[0] == 0x10
        && report[1] == index
        && report[2] == 0x41
        && report[4] & 0x40 == 0
}

/// The keyboard's Easy-Switch key: the CHANGE_HOST event `[old, new]` it
/// sends the computer it is leaving (long report, function 0, software id 0;
/// verified on MX Keys S, Solaar #3228). `feature` 0 = not known yet.
pub fn host_switch_in_report(report: &[u8], index: u8, feature: u8) -> Option<(u8, u8)> {
    (feature != 0
        && report.len() >= 6
        && report[0] == 0x11
        && report[1] == index
        && report[2] == feature
        && report[3] == 0
        && report[4] != report[5]
        && report[4] < 8
        && report[5] < 8)
        .then(|| (report[4], report[5]))
}

/// The keyboard's backlight keys (or its light sensor) changed the level:
/// the BACKLIGHT2 event `[levels, level, status, effect]` (OpenLogi, Solaar).
/// Returns `(level, levels, status)`.
pub fn backlight_in_report(report: &[u8], index: u8, feature: u8) -> Option<(u8, u8, u8)> {
    (feature != 0
        && report.len() >= 8
        && report[0] == 0x11
        && report[1] == index
        && report[2] == feature
        && report[3] == 0
        && (2..=32).contains(&report[4])
        && report[5] < report[4])
        .then(|| (report[5], report[4], report[6]))
}

/// What the keyboard's receiver reported.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LinkEvent {
    Up,
    HostSwitch(u8, u8),
    Backlight(u8, u8, u8),
}

/// Feature indices the reader matches events with (0 = not known yet).
#[derive(Default)]
struct EventIndices {
    change_host: std::sync::atomic::AtomicU8,
    backlight: std::sync::atomic::AtomicU8,
}

/// Quiet period after a link-up notice before the next one counts.
const LINK_UP_DEBOUNCE: std::time::Duration = std::time::Duration::from_secs(2);
/// Pause between the link-up notice and the battery read (the first request
/// after a re-link is answered late).
const LINK_SETTLE: std::time::Duration = std::time::Duration::from_millis(300);

/// Watch the paired keyboard's receiver and push `KeyboardBatteryChanged
/// (y percent, b charging)` each time the keyboard links up, so Settings flips
/// from "asleep" to the live battery as soon as a key is pressed. Idle while
/// `keyboard.mx_keys.enabled` is off. Listens on its own read-only handle:
/// hidraw delivers every report to every open handle, so request/reply
/// traffic on the manager's handle is untouched.
pub async fn run_keyboard_link_watcher(config: SharedConfig, connection: zbus::Connection) {
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (config, connection);
        std::future::pending::<()>().await
    }

    #[cfg(target_os = "linux")]
    {
        run_link_watcher_linux(config, connection).await
    }
}

#[cfg(target_os = "linux")]
fn mx_keys_enabled(config: &SharedConfig) -> bool {
    config.read().map(|c| c.keyboard.mx_keys.enabled).unwrap_or(false)
}

#[cfg(target_os = "linux")]
async fn run_link_watcher_linux(config: SharedConfig, connection: zbus::Connection) {
    use std::sync::atomic::{AtomicBool, Ordering};
    loop {
        if !mx_keys_enabled(&config) {
            tokio::time::sleep(Duration::from_secs(5)).await;
            continue;
        }
        let slot = tokio::task::spawn_blocking(|| manager().lock().ok().and_then(|mut m| m.receiver_slot()))
            .await
            .ok()
            .flatten();
        let Some((path, index)) = slot else {
            tokio::time::sleep(Duration::from_secs(30)).await;
            continue;
        };
        tracing::info!(path = %path.display(), index, "Watching the keyboard's receiver for link-up");

        let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<LinkEvent>();
        let stop = Arc::new(AtomicBool::new(false));
        let indices = Arc::new(EventIndices::default());
        learn_keyboard(&indices).await;
        let reader_stop = stop.clone();
        let reader_indices = indices.clone();
        let reader = tokio::task::spawn_blocking(move || watch_for_link_up(&path, index, &tx, &reader_stop, &reader_indices));
        loop {
            tokio::select! {
                event = rx.recv() => match event {
                    Some(LinkEvent::Up) => {
                        announce_keyboard_battery(&connection).await;
                        learn_keyboard(&indices).await;
                        // Link-ups that queued while this read ran (a first
                        // connect can take seconds) are answered by it.
                        while matches!(rx.try_recv(), Ok(LinkEvent::Up)) {}
                    }
                    Some(LinkEvent::Backlight(level, levels, status)) => {
                        tracing::debug!(level, levels, status, "Keyboard backlight changed");
                        if let Err(e) = connection
                            .emit_signal(None::<&str>, crate::dbus::DBUS_PATH, crate::dbus::DBUS_INTERFACE,
                                "KeyboardBacklightChanged", &(level, levels, status))
                            .await
                        {
                            tracing::warn!(error = %e, "Failed to emit KeyboardBacklightChanged");
                        }
                    }
                    Some(LinkEvent::HostSwitch(old, new)) => {
                        tracing::info!(old, new, "Keyboard Easy-Switch key");
                        if move_together() {
                            if let Some(slot) = crate::easy_switch::keyboard_left(old, new) {
                                crate::easy_switch::move_mouse(slot);
                            }
                        }
                    }
                    None => break,
                },
                _ = tokio::time::sleep(Duration::from_secs(5)) => {
                    if !mx_keys_enabled(&config) {
                        stop.store(true, Ordering::Relaxed);
                    }
                }
            }
        }
        let _ = reader.await;
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

#[cfg(target_os = "linux")]
fn move_together() -> bool {
    crate::replay::load_raw_config()
        .pointer("/keyboard/mx_keys/move_together")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
}

/// While the keyboard is here: the indices of its backlight and CHANGE_HOST
/// events and, for moving together, its slots (it cannot be read once it has
/// left). An index stays 0 while the keyboard sleeps and is learned later.
#[cfg(target_os = "linux")]
async fn learn_keyboard(indices: &Arc<EventIndices>) {
    use std::sync::atomic::Ordering;
    let together = move_together();
    let need_backlight = indices.backlight.load(Ordering::Relaxed) == 0;
    let need_host = together && indices.change_host.load(Ordering::Relaxed) == 0;
    if !need_backlight && !together {
        return;
    }
    let learned = tokio::task::spawn_blocking(move || {
        let mut m = manager().lock().ok()?;
        let backlight = if need_backlight { m.backlight_index() } else { None };
        let host = if need_host { m.change_host_index() } else { None };
        let slots = if together { m.hosts_table() } else { Vec::new() };
        Some((backlight, host, slots))
    })
    .await
    .ok()
    .flatten();
    if let Some((backlight, host, slots)) = learned {
        if let Some(i) = backlight {
            indices.backlight.store(i, Ordering::Relaxed);
        }
        if let Some(i) = host {
            indices.change_host.store(i, Ordering::Relaxed);
        }
        crate::easy_switch::remember_keyboard(slots);
    }
}

/// Blocking reader: one event per (debounced) link-up of slot `index`, and
/// one per Easy-Switch key press of the keyboard (CHANGE_HOST `feature`).
/// Returns when `stop` is set, the channel closes, or the receiver goes away.
#[cfg(target_os = "linux")]
fn watch_for_link_up(
    path: &Path,
    index: u8,
    tx: &tokio::sync::mpsc::UnboundedSender<LinkEvent>,
    stop: &std::sync::atomic::AtomicBool,
    indices: &EventIndices,
) {
    use std::io::Read;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::io::AsRawFd;
    use std::sync::atomic::Ordering;

    let mut file = match std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK)
        .open(path)
    {
        Ok(f) => f,
        Err(e) => {
            tracing::debug!(path = %path.display(), error = %e, "Keyboard link watcher cannot open the receiver");
            return;
        }
    };
    let mut buf = [0u8; 64];
    let mut last_sent: Option<std::time::Instant> = None;
    while !stop.load(Ordering::Relaxed) {
        let deadline = std::time::Instant::now() + Duration::from_secs(1);
        if !crate::hidpp::device::wait_readable(file.as_raw_fd(), deadline) {
            continue;
        }
        match file.read(&mut buf) {
            Ok(n) if link_up_in_report(&buf[..n], index) => {
                if last_sent.is_some_and(|t| t.elapsed() < LINK_UP_DEBOUNCE) {
                    continue;
                }
                last_sent = Some(std::time::Instant::now());
                tracing::debug!(index, "Keyboard linked up");
                if tx.send(LinkEvent::Up).is_err() {
                    return;
                }
            }
            Ok(0) => return,
            Ok(n) => {
                let report = &buf[..n];
                let event = host_switch_in_report(report, index, indices.change_host.load(Ordering::Relaxed))
                    .map(|(old, new)| LinkEvent::HostSwitch(old, new))
                    .or_else(|| {
                        backlight_in_report(report, index, indices.backlight.load(Ordering::Relaxed))
                            .map(|(level, levels, status)| LinkEvent::Backlight(level, levels, status))
                    });
                if let Some(event) = event {
                    if tx.send(event).is_err() {
                        return;
                    }
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
            Err(e) => {
                tracing::debug!(error = %e, "Keyboard link watcher lost the receiver");
                return;
            }
        }
    }
}

/// Read the keyboard's battery right after a link-up and broadcast it.
#[cfg(target_os = "linux")]
async fn announce_keyboard_battery(connection: &zbus::Connection) {
    tokio::time::sleep(LINK_SETTLE).await;
    let battery = tokio::task::spawn_blocking(|| {
        manager().lock().ok().and_then(|mut m| {
            m.mark_awake();
            m.query_battery()
        })
    })
    .await
    .ok()
    .flatten();
    let Some((percent, charging)) = battery else {
        return;
    };
    tracing::info!(percent, charging, "Keyboard awake; battery read");
    // Mouse and keyboard move together: learn the keyboard's slots while it
    // is here, and deliver a switch that waited for it to wake.
    if move_together() {
        let _ = tokio::task::spawn_blocking(|| {
            let slots = manager().lock().map(|mut m| m.hosts_table()).unwrap_or_default();
            crate::easy_switch::remember_keyboard(slots);
            if let Some(slot) = crate::easy_switch::take_pending() {
                crate::easy_switch::move_keyboard(slot);
            }
        })
        .await;
    }
    if let Err(e) = connection
        .emit_signal(
            None::<&str>,
            crate::dbus::DBUS_PATH,
            crate::dbus::DBUS_INTERFACE,
            "KeyboardBatteryChanged",
            &(percent, charging),
        )
        .await
    {
        tracing::warn!(error = %e, "Failed to emit KeyboardBatteryChanged");
    }
}

/// BETA generic keyboard remap loop. Runs forever; never returns under normal
/// operation, so it must NOT be joined in the daemon's shutdown `select!`.
///
/// # SAFETY
///
/// A keyboard is only grabbed (EVIOCGRAB) when the user has BOTH set
/// `keyboard.enabled = true` AND defined at least one remap entry. With the
/// default config this loop just idles, so a mouse-only / unconfigured install
/// never has its keyboard touched. While grabbed, every event is forwarded
/// through a virtual keyboard with the configured source codes rewritten to
/// their targets; unmapped keys pass through unchanged. The grab is released
/// (Device dropped) whenever the config is disabled, the table changes, or the
/// device hotplugs, so changes apply live via `ReloadConfig`.
pub async fn run_keyboard_remap_loop(config: SharedConfig, hotplug: std::sync::Arc<tokio::sync::Notify>) {
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (config, hotplug);
        std::future::pending::<()>().await
    }

    #[cfg(target_os = "linux")]
    {
        run_remap_loop_linux(config, hotplug).await
    }
}

#[cfg(target_os = "linux")]
async fn run_remap_loop_linux(config: SharedConfig, hotplug: Arc<Notify>) {
    loop {
        // Snapshot the live config each outer iteration so enabling/disabling
        // or editing the table via ReloadConfig is picked up.
        let (active, remap) = match config.read() {
            Ok(c) => (c.keyboard.remap_active(), c.keyboard.remap.clone()),
            Err(_) => (false, HashMap::new()),
        };

        if !active {
            tokio::time::sleep(Duration::from_secs(2)).await;
            continue;
        }

        let (path, name) = match find_keyboard() {
            Some(p) => p,
            None => {
                tokio::time::sleep(Duration::from_secs(2)).await;
                continue;
            }
        };

        tracing::info!(
            path = %path.display(),
            name = %name,
            entries = remap.len(),
            "Keyboard remap: grabbing keyboard (BETA)"
        );

        if let Err(e) = run_grabbed(&path, &remap, &config, &hotplug).await {
            tracing::warn!(error = %e, "Keyboard remap grab ended; will retry");
        }

        // Small delay before re-attempting (avoids a hot loop on errors).
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

/// Grab `path`, forward events through a virtual keyboard with `remap` applied,
/// and return when the config is disabled/changed, the device hotplugs, or an
/// IO error occurs. The grabbed `Device` is auto-released on drop.
#[cfg(target_os = "linux")]
async fn run_grabbed(
    path: &Path,
    remap: &HashMap<u16, u16>,
    config: &SharedConfig,
    hotplug: &Notify,
) -> std::io::Result<()> {
    use evdev::{uinput::VirtualDevice, Device, EventType, InputEvent};

    let mut device = Device::open(path)?;

    // Build the virtual keyboard mirroring the real device's key set, THEN grab.
    // The immutable borrow from `supported_keys()` ends before `grab()`.
    let mut vdev = {
        let mut builder = VirtualDevice::builder()?.name("JuhRadial Virtual Keyboard");
        if let Some(keys) = device.supported_keys() {
            builder = builder.with_keys(keys)?;
        }
        let v = builder.build()?;
        device.grab()?;
        v
    };

    let mut events = device.into_event_stream()?;
    // Batch events between SYN_REPORT frames (emit auto-appends SYN_REPORT),
    // matching the mouse forwarding path to preserve report grouping.
    let mut batch: Vec<InputEvent> = Vec::with_capacity(8);
    let mut recheck = tokio::time::interval(Duration::from_secs(1));

    loop {
        tokio::select! {
            _ = recheck.tick() => {
                // Release the grab if disabled or the table changed, so the
                // outer loop re-grabs with the new mapping. (`next_event` is
                // cancel-safe: its state lives in the stream, not the future.)
                let still = config
                    .read()
                    .ok()
                    .map(|c| c.keyboard.remap_active() && &c.keyboard.remap == remap)
                    .unwrap_or(false);
                if !still {
                    tracing::info!("Keyboard remap: releasing grab (config changed/disabled)");
                    return Ok(());
                }
            }
            _ = hotplug.notified() => {
                tracing::info!("Keyboard remap: device hotplug, releasing grab");
                return Ok(());
            }
            ev = events.next_event() => {
                let event = ev?;
                match event.event_type() {
                    EventType::SYNCHRONIZATION => {
                        if !batch.is_empty() {
                            let _ = vdev.emit(&batch);
                            batch.clear();
                        }
                    }
                    EventType::KEY => {
                        // Rewrite the key code if remapped; forward value as-is
                        // (covers press=1, release=0, autorepeat=2).
                        let out_code = remap.get(&event.code()).copied().unwrap_or(event.code());
                        batch.push(InputEvent::new(EventType::KEY.0, out_code, event.value()));
                    }
                    _ => {
                        batch.push(event);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backlight_keys_are_the_backlight2_event_of_our_keyboard() {
        // OpenLogi's event vector [8, 5, 5, 2]: 8 levels, level 5, manual, breathing.
        let mut event = [0u8; 20];
        event[..8].copy_from_slice(&[0x11, 0x02, 0x0C, 0x00, 8, 5, 5, 2]);
        assert_eq!(backlight_in_report(&event, 2, 0x0C), Some((5, 8, 5)));
        assert_eq!(backlight_in_report(&event, 1, 0x0C), None, "another slot");
        assert_eq!(backlight_in_report(&event, 2, 0), None, "index not learned yet");
        let mut reply = event;
        reply[3] = 0x21; // our own getBacklightInfo reply
        assert_eq!(backlight_in_report(&reply, 2, 0x0C), None);
        let mut bad = event;
        bad[5] = 8; // level beyond the count
        assert_eq!(backlight_in_report(&bad, 2, 0x0C), None);
    }

    #[test]
    fn easy_switch_key_is_the_change_host_event_of_our_keyboard() {
        // MX Keys S (Solaar #3228): r[11 01 0A 00 00 01 ...] = host 0 -> 1.
        let mut event = [0u8; 20];
        event[..6].copy_from_slice(&[0x11, 0x01, 0x0A, 0x00, 0x00, 0x01]);
        assert_eq!(host_switch_in_report(&event, 1, 0x0A), Some((0, 1)));
        assert_eq!(host_switch_in_report(&event, 2, 0x0A), None, "another slot");
        assert_eq!(host_switch_in_report(&event, 1, 0x0B), None, "another feature");
        assert_eq!(host_switch_in_report(&event, 1, 0), None, "index not learned yet");
        let mut reply = event;
        reply[3] = 0x01; // our own getHostInfo reply (software id 1)
        assert_eq!(host_switch_in_report(&reply, 1, 0x0A), None);
        let mut same = event;
        same[5] = 0;
        assert_eq!(host_switch_in_report(&same, 1, 0x0A), None);
        assert_eq!(host_switch_in_report(&event[..5], 1, 0x0A), None, "truncated");
        let mut short = event;
        short[0] = 0x10;
        assert_eq!(host_switch_in_report(&short, 1, 0x0A), None, "short reports are receiver traffic");
    }

    #[test]
    fn link_up_is_the_short_0x41_notice_for_our_slot_with_link_bit_clear() {
        // Captured on an MX Keys S (Bolt slot 1, WPID B378) when a key was pressed.
        let up = [0x10, 0x01, 0x41, 0x10, 0x01, 0x78, 0xB3];
        assert!(link_up_in_report(&up, 1));
        assert!(!link_up_in_report(&up, 2), "another slot");
        let down = [0x10, 0x01, 0x41, 0x10, 0x41, 0x78, 0xB3];
        assert!(!link_up_in_report(&down, 1), "link-down bit set");
        let long = [0x11, 0x01, 0x41, 0x10, 0x01, 0x78, 0xB3];
        assert!(!link_up_in_report(&long, 1), "a long report with feature index 0x41 is device traffic");
        let parked = [0x10, 0x01, 0x8F, 0x00, 0x0D, 0x04, 0x00];
        assert!(!link_up_in_report(&parked, 1));
        assert!(!link_up_in_report(&up[..4], 1), "truncated");
    }

    #[test]
    fn manager_safe_without_hardware() {
        // On a machine with no MX Keys S, every method must return a safe
        // default and never panic.
        let mut mgr = KeyboardManager::new();
        // query_battery may attempt a connection but must not panic; it returns
        // None when no keyboard answers.
        let _ = mgr.query_battery();
        // set_backlight returns false when no keyboard is present.
        let _ = mgr.set_backlight(50);
    }

    #[test]
    fn list_keys_never_panics() {
        // Returns a (possibly empty) list without panicking, regardless of
        // whether a keyboard is attached in the test environment.
        let _ = list_keyboard_key_codes();
    }

    #[test]
    fn global_manager_is_singleton() {
        let a = manager() as *const _;
        let b = manager() as *const _;
        assert_eq!(a, b);
    }
}
