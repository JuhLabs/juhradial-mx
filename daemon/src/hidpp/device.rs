//! HID++ device communication
//!
//! Low-level HidppDevice for direct hidraw access to MX Master 4.
//! Handles device discovery, HID++ 2.0 protocol, feature enumeration,
//! button divert, haptics, DPI, SmartShift, battery, and Easy-Switch.

use std::collections::HashSet;

use super::controls::ControlInfo;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::io::AsRawFd;
use std::path::PathBuf;

use super::constants::{blocklisted_features, features, report_type};
use super::error::HapticError;
use super::messages::ConnectionType;
use super::patterns::Mx4HapticPattern;

/// Software ID for HID++ message tracking
const SOFTWARE_ID: u8 = 0x01;

/// Wait for `fd` to become readable, up to `deadline`.
///
/// Used by the HID++ request loops (here and in the battery module) instead of
/// fixed 10ms sleeps, so responses are picked up the moment they arrive.
/// Returns false on timeout or poll error; retries on EINTR with the remaining
/// budget.
pub(crate) fn wait_readable(fd: std::os::unix::io::RawFd, deadline: std::time::Instant) -> bool {
    loop {
        let remaining = deadline.saturating_duration_since(std::time::Instant::now());
        if remaining.is_zero() {
            return false;
        }
        let mut pfd = libc::pollfd {
            fd,
            events: libc::POLLIN,
            revents: 0,
        };
        // Round up so a sub-millisecond remainder does not busy-spin.
        let timeout_ms = remaining.as_millis().clamp(1, i32::MAX as u128) as libc::c_int;
        let ret = unsafe { libc::poll(&mut pfd, 1, timeout_ms) };
        if ret > 0 {
            return true;
        }
        if ret == 0 {
            return false;
        }
        if std::io::Error::last_os_error().kind() != std::io::ErrorKind::Interrupted {
            return false;
        }
    }
}

/// HID++ device wrapper for communication with MX Master 4
///
/// Uses direct hidraw device access for reliable HID++ communication.
/// This approach matches the battery module and avoids hidapi enumeration issues.
pub struct HidppDevice {
    /// The underlying hidraw file handle
    device: File,
    /// Device index for HID++ messages (0xFF for direct, 0x01-0x06 for receiver)
    device_index: u8,
    /// Connection type
    connection_type: ConnectionType,
    /// Cached feature table (feature_id -> feature_index)
    feature_table: std::collections::HashMap<u16, u8>,
    /// Whether haptic feature is available (legacy force feedback 0x8123)
    haptic_supported: bool,
    /// Haptic feature index for legacy force feedback (0x8123)
    haptic_feature_index: Option<u8>,
    /// Whether MX Master 4 haptic feature is available (0x19B0)
    mx4_haptic_supported: bool,
    /// MX Master 4 haptic feature index (0x19B0)
    mx4_haptic_feature_index: Option<u8>,
    /// Whether adjustable DPI feature is available (0x2201)
    dpi_supported: bool,
    /// Adjustable DPI feature index (0x2201)
    dpi_feature_index: Option<u8>,
    /// getSensorDpiList answer (connection-scoped; read on first use)
    dpi_caps: Option<DpiCaps>,
    /// Whether SmartShift feature is available (0x2111 or 0x2110)
    smartshift_supported: bool,
    /// SmartShift feature index (0x2111 Enhanced preferred, 0x2110 legacy fallback)
    smartshift_feature_index: Option<u8>,
    /// True when bound to SmartShift Enhanced (0x2111), which uses function IDs
    /// [1] getRatchetControlMode / [2] setRatchetControlMode (its [0] is
    /// getCapabilities). Legacy 0x2110 uses [0] get / [1] set.
    smartshift_is_enhanced: bool,
    /// Whether unified battery feature is available (0x1004)
    battery_supported: bool,
    /// Battery feature index (0x1004 or 0x1000)
    battery_feature_index: Option<u8>,
    /// Whether using UNIFIED_BATTERY (true) or BATTERY_STATUS (false)
    is_unified_battery: bool,
    /// Whether REPROG_CONTROLS_V4 feature is available (0x1B04)
    reprog_controls_supported: bool,
    /// REPROG_CONTROLS_V4 feature index (0x1B04) - for button divert
    reprog_controls_feature_index: Option<u8>,
    /// Whether ThumbWheel feature is available (0x2150)
    thumbwheel_supported: bool,
    /// ThumbWheel feature index (0x2150) - for thumb-wheel divert
    thumbwheel_feature_index: Option<u8>,
    /// Path to the hidraw device we connected to
    device_path: PathBuf,
    /// REPROG_CONTROLS_V4 inventory from the last `list_controls()` scan
    /// (connection-scoped; empty until scanned).
    controls: Vec<ControlInfo>,
    /// HID++ 1.0 error the receiver answered to our last request (`0x8F`),
    /// cleared by the next matched reply. 0x04 means the paired device's
    /// radio is parked (idle or on another host): see `link_parked()`.
    last_receiver_error: Option<u8>,
    /// Unit id from DEVICE_INFORMATION (0x0003): unique per physical device,
    /// the key for per-device config overrides (`devices.0xXXXXXXXX`).
    unit_id: Option<u32>,
    /// True once `divert_buttons` saw the gesture button (CID 0x00C3) in the
    /// REPROG_CONTROLS_V4 table (connection-scoped; read by GetCapabilities).
    gesture_button_seen: bool,
}

/// Unit id from a `getDeviceInfo` reply (bytes 5..9, big-endian); zero means
/// the device reports none.
fn parse_unit_id(resp: &[u8]) -> Option<u32> {
    if resp.len() < 9 {
        return None;
    }
    let id = u32::from_be_bytes([resp[5], resp[6], resp[7], resp[8]]);
    (id != 0).then_some(id)
}

/// What getSensorDpiList (0x2201 fn 1) reports for sensor 0: the settable
/// range and its step, or the discrete values of a list-form device.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DpiCaps {
    pub min: u16,
    pub max: u16,
    /// DPI between settable values; 0 when the device lists discrete values.
    pub step: u16,
    /// The settable values of a list-form device (empty for a range).
    pub values: Vec<u16>,
    /// The sensor's factory DPI (getSensorDpi defaultDpi; 0 = not reported).
    pub default: u16,
}

impl DpiCaps {
    /// Parse the DPI words of a getSensorDpiList reply (the payload after
    /// the sensor index): big-endian values, a hyphen word `0xE000 | step`
    /// between the two ends of a range, `0x0000` ends the list.
    pub fn parse(words: &[u8]) -> Option<Self> {
        let mut values = Vec::new();
        let mut step = 0;
        for w in words.chunks_exact(2) {
            let v = u16::from_be_bytes([w[0], w[1]]);
            if v == 0 {
                break;
            }
            if v >> 13 == 0b111 {
                step = v & 0x1FFF;
                continue;
            }
            values.push(v);
        }
        let (min, max) = (*values.iter().min()?, *values.iter().max()?);
        if step > 0 {
            values.clear();
        }
        Some(Self { min, max, step, values, default: 0 })
    }

    /// The settable DPI nearest to `dpi`.
    pub fn snap(&self, dpi: u16) -> u16 {
        let dpi = dpi.clamp(self.min, self.max);
        if self.step > 0 {
            let (min, step) = (u32::from(self.min), u32::from(self.step));
            let n = (u32::from(dpi) - min + step / 2) / step;
            let on_grid = (min + n * step).min(u32::from(self.max)) as u16;
            // the top of a range need not sit on the grid
            return if self.max - dpi < dpi.abs_diff(on_grid) { self.max } else { on_grid };
        }
        self.values.iter().copied().min_by_key(|v| v.abs_diff(dpi)).unwrap_or(dpi)
    }
}

/// The Haptic Sense Panel's press force (0x19C0 button 0): raw sensor units,
/// higher = firmer. `changeable` is capability bit 0.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ForceSense {
    pub changeable: bool,
    pub min: u16,
    pub max: u16,
    pub default: u16,
    pub current: u16,
}

impl ForceSense {
    /// From the getButtonInfo payload (caps, default, max, min) and the
    /// getButtonConfig payload (current), all big-endian u16.
    pub fn parse(info: &[u8], current: &[u8]) -> Option<Self> {
        let word = |b: &[u8], i: usize| Some(u16::from_be_bytes([*b.get(i)?, *b.get(i + 1)?]));
        let (min, max) = (word(info, 6)?, word(info, 4)?);
        if max <= min {
            return None;
        }
        Some(Self {
            changeable: word(info, 0)? & 0x0001 != 0,
            default: word(info, 2)?,
            max,
            min,
            current: word(current, 0)?,
        })
    }

    /// The raw value `pct` percent of the way from min to max.
    pub fn at_percent(&self, pct: u8) -> u16 {
        let span = u32::from(self.max - self.min);
        (u32::from(self.min) + span * u32::from(pct.min(100)) / 100) as u16
    }

    /// Where `raw` sits in the range, in percent.
    pub fn percent_of(&self, raw: u16) -> u8 {
        let span = u32::from(self.max - self.min);
        ((u32::from(raw.clamp(self.min, self.max) - self.min) * 100 + span / 2) / span) as u8
    }
}

/// Receiver error "connection request failed": the device is paired but not
/// linked right now (radio parked after idling, or switched to another host).
pub const RECEIVER_ERR_CONNECT_FAIL: u8 = 0x04;

/// HID++ 1.0 receiver error (`0x8F`) answering one of our requests. The
/// receiver speaks for a paired device that cannot answer; the code sits at
/// byte 5 (0x04 connection failed, 0x09 resource error, ...).
fn receiver_error_code(response: &[u8], device_index: u8) -> Option<u8> {
    if response.len() >= 6
        && (response[0] == report_type::SHORT || response[0] == report_type::LONG)
        && response[1] == device_index
        && response[2] == 0x8F
    {
        Some(response[5])
    } else {
        None
    }
}

/// UNIFIED_BATTERY (0x1004) percent: the reported state of charge, or an
/// estimate from the level flags (critical 0x01, low 0x02, good 0x04, full
/// 0x08) for firmware that reports levels only.
fn unified_battery_percent(state_of_charge: u8, level_flags: u8) -> u8 {
    if state_of_charge > 0 {
        return state_of_charge;
    }
    if level_flags & 0x08 != 0 {
        90
    } else if level_flags & 0x04 != 0 {
        55
    } else if level_flags & 0x02 != 0 {
        20
    } else if level_flags & 0x01 != 0 {
        5
    } else {
        0
    }
}

trait ButtonDivertIo {
    fn short_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>>;
    fn long_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>>;
}

impl ButtonDivertIo for HidppDevice {
    fn short_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>> {
        self.hidpp_request(feature_index, function, params)
    }

    fn long_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>> {
        self.hidpp_long_request(feature_index, function, params)
    }
}

fn set_button_diverts_with_io(
    io: &mut impl ButtonDivertIo,
    feature_index: u8,
    cids: &[u16],
    divert: bool,
) -> Vec<u16> {
    let requested: HashSet<u16> = cids.iter().copied().collect();
    if requested.is_empty() {
        return Vec::new();
    }

    let count = match io.short_request(feature_index, 0x00, &[]) {
        Some(resp) if resp.len() >= 5 => resp[4],
        _ => return Vec::new(),
    };
    let divert_flags: u8 = if divert { 0x03 } else { 0x02 };
    let mut diverted = Vec::new();

    for index in 0..count {
        let resp = match io.short_request(feature_index, 0x01, &[index, 0, 0]) {
            Some(response) if response.len() >= 9 => response,
            _ => continue,
        };
        let cid = ((resp[4] as u16) << 8) | (resp[5] as u16);
        let divertable = (resp[8] & 0x20) != 0;
        if !requested.contains(&cid) || !divertable {
            continue;
        }

        let params = [
            (cid >> 8) as u8,
            (cid & 0xFF) as u8,
            divert_flags,
            0x00,
            0x00,
        ];
        if let Some(resp) = io.long_request(feature_index, 0x03, &params) {
            tracing::info!(
                cid = format!("0x{:04X}", cid),
                divert,
                response = format!("{:02X?}", &resp[4..resp.len().min(9)]),
                "Button divert updated"
            );
            diverted.push(cid);
        }
    }

    diverted
}

/// Enumerate every control with one REPROG_CONTROLS_V4 scan (getCount, then
/// getCidInfo per index). Replies that fail to decode are skipped.
fn list_controls_with_io(io: &mut impl ButtonDivertIo, feature_index: u8) -> Vec<ControlInfo> {
    let count = match io.short_request(feature_index, 0x00, &[]) {
        Some(resp) if resp.len() >= 5 => resp[4],
        _ => return Vec::new(),
    };
    (0..count)
        .filter_map(|index| {
            io.short_request(feature_index, 0x01, &[index, 0, 0])
                .and_then(|resp| ControlInfo::from_report(&resp))
        })
        .collect()
}

impl HidppDevice {
    /// Find a Logitech hidraw device suitable for HID++ communication
    ///
    /// Scans /sys/class/hidraw/ for Logitech devices and returns ALL candidates
    /// for HID++ communication (prefers interface 2).
    fn find_all_devices() -> Vec<(PathBuf, ConnectionType)> {
        let hidraw_dir = PathBuf::from("/sys/class/hidraw");
        if !hidraw_dir.exists() {
            tracing::debug!("/sys/class/hidraw not found");
            return Vec::new();
        }

        let mut candidates: Vec<(PathBuf, String, ConnectionType)> = Vec::new();

        let entries = match std::fs::read_dir(&hidraw_dir) {
            Ok(e) => e,
            Err(e) => {
                tracing::debug!(error = %e, "Failed to read /sys/class/hidraw");
                return Vec::new();
            }
        };

        for entry in entries.flatten() {
            let path = entry.path();
            let uevent_path = path.join("device/uevent");

            if let Ok(uevent) = std::fs::read_to_string(&uevent_path) {
                // Check for Logitech vendor ID (046D)
                if !uevent.contains("046D") && !uevent.contains("046d") {
                    continue;
                }

                // HID++ lives on the vendor-specific HID interface (input2 on
                // both Bolt and Unifying receivers; sometimes input1 on direct
                // USB / Bluetooth). Receiver hidraw nodes for input0/input1 are
                // boot mouse / consumer interfaces, pinging them never works
                // and just stalls the receiver firmware for the timeout window
                // (200ms × 6 device indices = 1.2s wasted per non-HID++ node).
                let is_input2 = uevent.contains("input2");

                // Determine the HID bus type from the uevent's HID_ID field
                // BEFORE mapping the product ID to a connection type. The MX
                // Master 4 (0xB034) and MX Master 3S share their direct-mode PID
                // across BOTH USB and Bluetooth, so the PID alone cannot
                // disambiguate the transport: only the HID bus id can
                // (0003 = USB, 0005 = Bluetooth). Checking Bluetooth first
                // keeps a 0xB034 mouse on Bluetooth from misclassifying as USB.
                let is_bluetooth = uevent.contains("HID_ID=0005");

                let connection_type = if uevent.contains("C548") || uevent.contains("c548") {
                    if !is_input2 { continue; }
                    ConnectionType::Bolt
                } else if uevent.contains("C52B") || uevent.contains("c52b") {
                    if !is_input2 { continue; }
                    ConnectionType::Unifying
                } else if is_bluetooth {
                    // Direct Bluetooth: the kernel exposes a virtual uhid device
                    // whose uevent has no inputN interface marker. Any direct PID
                    // (B034/3S/B042/...) reports Bluetooth here, never USB.
                    ConnectionType::Bluetooth
                } else if uevent.contains("B034") || uevent.contains("b034") {
                    // Direct USB exposes HID++ on a single interface; accept any.
                    ConnectionType::Usb
                } else if is_input2 {
                    ConnectionType::Bluetooth
                } else {
                    continue;
                };

                let descriptor = crate::device_descriptor::lookup_from_uevent(&uevent);
                if let Some(name) = path.file_name() {
                    let dev_path = PathBuf::from("/dev").join(name);
                    tracing::debug!(
                        path = %dev_path.display(),
                        model = descriptor.model,
                        connection = %connection_type,
                        "Classified Logitech HID++ candidate"
                    );
                    candidates.push((dev_path, uevent, connection_type));
                }
            }
        }

        // Sort: interface 2 devices first (preferred for HID++)
        candidates.sort_by(|a, b| {
            let a_is_input2 = a.1.contains("input2");
            let b_is_input2 = b.1.contains("input2");
            b_is_input2.cmp(&a_is_input2)
        });

        // Log all candidates
        for (dev_path, uevent, conn_type) in &candidates {
            let is_input2 = uevent.contains("input2");
            tracing::debug!(
                path = %dev_path.display(),
                connection = %conn_type,
                is_input2,
                "Found Logitech HID++ candidate"
            );
        }

        candidates.into_iter().map(|(path, _, conn_type)| (path, conn_type)).collect()
    }

    /// Attempt to open and initialize an MX Master 4 device
    ///
    /// Returns None if no compatible device is found.
    /// This is NOT an error - haptics are optional.
    ///
    /// Uses direct hidraw access instead of hidapi for more reliable
    /// device communication (same approach as the battery module).
    ///
    /// Tries ALL candidate devices until one validates HID++ 2.0.
    /// This handles setups with multiple Logitech receivers (e.g., MX Master 4
    /// on one Bolt receiver, Keys S on another).
    pub fn open() -> Option<Self> {
        let candidates = Self::find_all_devices();

        if candidates.is_empty() {
            tracing::debug!("No Logitech HID++ devices found");
            return None;
        }

        tracing::debug!(count = candidates.len(), "Trying HID++ device candidates");

        'candidates: for (device_path, connection_type) in candidates {
            // Determine device indices to try based on connection type
            // Bolt receivers can have the mouse on any slot (1-6), so try them all
            let indices_to_try: Vec<u8> = match connection_type {
                ConnectionType::Usb => vec![0xFF],
                ConnectionType::Bolt => vec![0x01, 0x02, 0x03, 0x04, 0x05, 0x06],
                ConnectionType::Unifying => vec![0x01, 0x02, 0x03, 0x04, 0x05, 0x06],
                ConnectionType::Bluetooth => vec![0xFF],
            };

            // Open the device with read/write and non-blocking
            let device = match OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open(&device_path)
            {
                Ok(f) => f,
                Err(e) => {
                    if e.kind() == std::io::ErrorKind::PermissionDenied {
                        tracing::warn!(
                            path = %device_path.display(),
                            "Permission denied opening hidraw device. Node should be root:input \
                             mode 0660; this daemon's user must be in the 'input' group. Run \
                             'sudo usermod -aG input $USER' then REBOOT (or log out and back in) \
                             so the systemd --user manager inherits the group, a session that \
                             predates the group change cannot access the device (issue #52)."
                        );
                    } else {
                        tracing::debug!(
                            path = %device_path.display(),
                            error = %e,
                            "Failed to open hidraw device"
                        );
                    }
                    continue; // Try next candidate
                }
            };

            // First pass: short ping per slot. If nothing answers on this
            // candidate, the receiver may be in deep-sleep (post-suspend, or
            // mouse idle on its radio). Send a wake stimulus and retry once
            // before giving up, the previous "replug to make it work"
            // symptom was a sleeping receiver that never got woken.
            let mut woke_attempted = false;
            let mut pass = 0u8;

            'pass_loop: loop {
            for device_index in &indices_to_try {
                // Clone the file handle for each index attempt (reuse same fd)
                let device_clone = match device.try_clone() {
                    Ok(d) => d,
                    Err(_) => continue,
                };

                let mut hidpp = Self {
                    device: device_clone,
                    device_index: *device_index,
                    connection_type,
                    feature_table: std::collections::HashMap::new(),
                    haptic_supported: false,
                    haptic_feature_index: None,
                    mx4_haptic_supported: false,
                    mx4_haptic_feature_index: None,
                    dpi_supported: false,
                    dpi_feature_index: None,
                    dpi_caps: None,
                    smartshift_supported: false,
                    smartshift_feature_index: None,
                    smartshift_is_enhanced: false,
                    battery_supported: false,
                    battery_feature_index: None,
                    is_unified_battery: false,
                    reprog_controls_supported: false,
                    reprog_controls_feature_index: None,
                    thumbwheel_supported: false,
                    thumbwheel_feature_index: None,
                    controls: Vec::new(),
                    last_receiver_error: None,
                    unit_id: None,
                    gesture_button_seen: false,
                    device_path: device_path.clone(),
                };

                // Try HID++ validation, uses fast 200ms timeout per slot.
                // Responsive devices reply within ~20ms; empty slots never reply.
                // No retry/sleep: the first ping already wakes the radio, and a
                // second attempt just adds latency that can stall the receiver.
                let validated = hidpp.validate_hidpp20();

                if !validated {
                    tracing::debug!(
                        path = %device_path.display(),
                        device_index,
                        connection = %connection_type,
                        "Device index does not support HID++ 2.0"
                    );
                    continue; // Try next device index
                }

                // Enumerate features and check for haptic support
                hidpp.enumerate_features();

                // Skip devices that aren't a mouse
                // Use DPI support (0x2201) as the filter - only mice have DPI,
                // keyboards (e.g. Keys MX S) have reprog_controls but never DPI
                if !hidpp.dpi_supported {
                    tracing::debug!(
                        path = %device_path.display(),
                        device_index,
                        "Device is HID++ 2.0 but has no DPI (not a mouse), trying next"
                    );
                    continue;
                }

                hidpp.read_unit_id();
                tracing::info!(
                    path = %device_path.display(),
                    device_index,
                    connection = %connection_type,
                    unit_id = hidpp.unit_id.map(|u| format!("0x{:08X}", u)).unwrap_or_default(),
                    haptic_supported = hidpp.haptic_supported,
                    mx4_haptic_supported = hidpp.mx4_haptic_supported,
                    reprog_controls = hidpp.reprog_controls_supported,
                    pass,
                    "Connected to MX Master 4 via hidraw"
                );

                return Some(hidpp);
            }

            // No slot answered on this pass. If we haven't tried to wake the
            // receiver yet, send a long ping (which the radio firmware tends
            // to use as a wake-up signal) and retry the slot scan once.
            if !woke_attempted && matches!(connection_type, ConnectionType::Bolt | ConnectionType::Unifying) {
                woke_attempted = true;
                pass = 1;
                tracing::debug!(
                    path = %device_path.display(),
                    "No slots responded, sending wake ping and retrying once"
                );
                if let Ok(mut wake_fd) = device.try_clone() {
                    // Broadcast ping on slot 0xFF, receivers route this
                    // to all paired devices and start their radios.
                    let mut wake = [0u8; 7];
                    wake[0] = report_type::SHORT;
                    wake[1] = 0xFF;
                    wake[2] = 0x00; // IRoot
                    wake[3] = (0x01 << 4) | SOFTWARE_ID; // ping
                    wake[6] = 0xAA;
                    let _ = wake_fd.write_all(&wake);
                }
                std::thread::sleep(std::time::Duration::from_millis(250));
                continue 'pass_loop;
            }
            break 'pass_loop;
            }
            // Try next candidate device (path).
            let _ = (); // satisfy clippy on empty body when 'pass_loop breaks
            continue 'candidates;
        }

        tracing::debug!("No valid HID++ 2.0 device found among candidates");
        None
    }

    /// Device index of the first KEYBOARD paired to the receiver at
    /// `device_path`, read from the receiver's own pairing table.
    ///
    /// Sends the HID++ 1.0 "fake device arrival" sequence (enable wireless
    /// notifications on register 0x00, re-announce via register 0x02) and
    /// parses the 0x41 connection notifications it triggers. The receiver
    /// answers without a device radio round-trip, so this finds a keyboard
    /// even while it is deep-asleep - the state every ping-based scan misses.
    pub fn find_keyboard_index_on_receiver(device_path: &std::path::Path) -> Option<u8> {
        let mut device = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(device_path)
            .ok()?;

        device
            .write_all(&[0x10, 0xFF, 0x80, 0x00, 0x00, 0x01, 0x00])
            .ok()?;
        std::thread::sleep(std::time::Duration::from_millis(20));
        device
            .write_all(&[0x10, 0xFF, 0x80, 0x02, 0x02, 0x00, 0x00])
            .ok()?;

        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(500);
        let fd = device.as_raw_fd();
        let mut buf = [0u8; 32];
        while wait_readable(fd, deadline) {
            let n = match device.read(&mut buf) {
                Ok(n) => n,
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => continue,
                Err(_) => break,
            };
            // 0x41 connection notification: byte 1 = device index, byte 4 low
            // nibble = device kind (0x01 = keyboard).
            if n >= 5 && buf[0] == 0x10 && buf[2] == 0x41 {
                tracing::debug!(
                    path = %device_path.display(),
                    device_index = buf[1],
                    kind = buf[4] & 0x0F,
                    "Fake-arrival notification"
                );
                if buf[4] & 0x0F == 0x01 {
                    return Some(buf[1]);
                }
            }
        }
        tracing::debug!(path = %device_path.display(), "Fake-arrival: no keyboard announced");
        None
    }

    /// Whether any connected receiver has a keyboard in its pairing table.
    ///
    /// Presence, not reachability: stays true while the keyboard's radio
    /// sleeps, which is exactly when `open_keyboard` cannot validate it.
    /// Direct-Bluetooth keyboards are not covered (they validate normally).
    pub fn any_paired_keyboard() -> bool {
        Self::find_paired_keyboard().is_some()
    }

    /// The receiver hidraw node and slot holding a paired keyboard, from the
    /// receivers' pairing tables (answers while the keyboard sleeps).
    pub fn find_paired_keyboard() -> Option<(PathBuf, u8)> {
        Self::find_all_devices()
            .into_iter()
            .filter(|(_, ct)| matches!(ct, ConnectionType::Bolt | ConnectionType::Unifying))
            .find_map(|(path, _)| Self::find_keyboard_index_on_receiver(&path).map(|idx| (path, idx)))
    }

    /// Open the first HID++ 2.0 KEYBOARD (MX Keys S and friends).
    ///
    /// BETA / additive: this mirrors [`Self::open`] but accepts a keyboard
    /// instead of a mouse, and is the ONLY entry point that does so. The mouse
    /// `open()` path filters on DPI support (0x2201); keyboards never report
    /// DPI, so here a keyboard is a validated HID++ 2.0 device that has NO DPI
    /// but does expose a battery feature (every MX keyboard does). It is a
    /// completely separate function, so the existing mouse path is unchanged.
    ///
    /// Returns `None` when no compatible keyboard is found. Conservative by
    /// construction: it only READS during discovery (ping + feature enumerate).
    ///
    /// LIMITATION: HID++ validation needs the keyboard's radio awake, and an
    /// idle MX Keys parks its radio within seconds and ignores pings until a
    /// key press wakes it. Use [`Self::any_paired_keyboard`] for presence.
    pub fn open_keyboard() -> Option<Self> {
        let candidates = Self::find_all_devices();
        if candidates.is_empty() {
            tracing::debug!("No Logitech HID++ devices found (keyboard scan)");
            return None;
        }

        for (device_path, connection_type) in candidates {
            let mut designated: Option<u8> = None;
            let indices_to_try: Vec<u8> = match connection_type {
                ConnectionType::Usb => vec![0xFF],
                ConnectionType::Bluetooth => vec![0xFF],
                ConnectionType::Bolt | ConnectionType::Unifying => {
                    // Ask the receiver's pairing table which slot holds a
                    // keyboard (answers even while the keyboard sleeps) and
                    // probe that slot first; keep the exhaustive scan as
                    // fallback for receivers that ignore fake-arrival.
                    let mut order: Vec<u8> = vec![0x01, 0x02, 0x03, 0x04, 0x05, 0x06];
                    if let Some(kb) = Self::find_keyboard_index_on_receiver(&device_path) {
                        designated = Some(kb);
                        order.retain(|i| *i != kb);
                        order.insert(0, kb);
                    }
                    order
                }
            };

            let device = match OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NONBLOCK)
                .open(&device_path)
            {
                Ok(f) => f,
                Err(e) => {
                    tracing::debug!(path = %device_path.display(), error = %e, "Failed to open hidraw (keyboard scan)");
                    continue;
                }
            };

            for device_index in &indices_to_try {
                let device_clone = match device.try_clone() {
                    Ok(d) => d,
                    Err(_) => continue,
                };

                let mut hidpp = Self {
                    device: device_clone,
                    device_index: *device_index,
                    connection_type,
                    feature_table: std::collections::HashMap::new(),
                    haptic_supported: false,
                    haptic_feature_index: None,
                    mx4_haptic_supported: false,
                    mx4_haptic_feature_index: None,
                    dpi_supported: false,
                    dpi_feature_index: None,
                    dpi_caps: None,
                    smartshift_supported: false,
                    smartshift_feature_index: None,
                    smartshift_is_enhanced: false,
                    battery_supported: false,
                    battery_feature_index: None,
                    is_unified_battery: false,
                    reprog_controls_supported: false,
                    reprog_controls_feature_index: None,
                    thumbwheel_supported: false,
                    thumbwheel_feature_index: None,
                    controls: Vec::new(),
                    last_receiver_error: None,
                    unit_id: None,
                    gesture_button_seen: false,
                    device_path: device_path.clone(),
                };

                // The pairing-table-designated keyboard slot gets a 1s budget:
                // a dozing keyboard re-establishes its radio link before its
                // first answer (hundreds of ms), and concurrent receiver
                // traffic stretches that further. Speculative slots keep the
                // fast budget so empty receivers stay cheap to scan.
                let attempts = if designated == Some(*device_index) { 100 } else { 20 };
                if !hidpp.validate_hidpp20_with_attempts(attempts) {
                    continue;
                }

                hidpp.enumerate_features();

                // Keyboard signature: HID++ 2.0, battery present, NO DPI sensor.
                // (Mice report DPI 0x2201; keyboards never do, same heuristic the
                // mouse `open()` uses to skip keyboards, inverted here.)
                if hidpp.dpi_supported {
                    tracing::debug!(
                        path = %device_path.display(),
                        device_index,
                        "HID++ device has DPI (a mouse) - not a keyboard, skipping"
                    );
                    continue;
                }
                if !hidpp.battery_supported {
                    continue;
                }

                tracing::info!(
                    path = %device_path.display(),
                    device_index,
                    connection = %connection_type,
                    backlight = hidpp.feature_table.contains_key(&features::BACKLIGHT2),
                    reprog_controls = hidpp.reprog_controls_supported,
                    "Connected to HID++ keyboard (BETA)"
                );

                return Some(hidpp);
            }
        }

        tracing::debug!("No HID++ keyboard found among candidates");
        None
    }

    /// Drain any pending data from the device buffer
    ///
    /// This prevents reading stale responses from previous requests.
    fn drain_buffer(&mut self) {
        let mut drain_buf = [0u8; 64];
        loop {
            match self.device.read(&mut drain_buf) {
                Ok(_) => continue, // Discard stale data
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }
    }

    /// Send a HID++ request and wait for matching response
    ///
    /// Uses polling with timeout (same approach as battery module).
    fn hidpp_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>> {
        self.hidpp_request_with_timeout(feature_index, function, params, 100)
    }

    /// Send a HID++ request with a custom max attempt count.
    ///
    /// Each attempt is worth 10ms of timeout budget (the fd is waited on with
    /// poll(2), so responses are handled as soon as they arrive). Use a lower
    /// max_attempts for fast-fail scenarios (e.g., device discovery pings) to
    /// avoid hammering receivers with long blocking waits on empty slots.
    fn hidpp_request_with_timeout(&mut self, feature_index: u8, function: u8, params: &[u8], max_attempts: u32) -> Option<Vec<u8>> {
        // Bluetooth-connected devices do not expose the short (0x10) HID++
        // report, their HID descriptor only contains the long (0x11) report.
        // A short write there is dropped and never answered, so route every
        // request through the long path. Makes HID++ validation, feature
        // enumeration and haptics work over Bluetooth.
        if self.connection_type == ConnectionType::Bluetooth {
            return self.hidpp_long_request(feature_index, function, params);
        }

        // Drain any pending data first
        self.drain_buffer();

        // Build HID++ short report (7 bytes)
        let mut request = [0u8; 7];
        request[0] = report_type::SHORT;
        request[1] = self.device_index;
        request[2] = feature_index;
        request[3] = (function << 4) | SOFTWARE_ID;

        // Copy params (up to 3 bytes for short report)
        let param_len = params.len().min(3);
        request[4..4 + param_len].copy_from_slice(&params[..param_len]);

        tracing::debug!(
            feature_index,
            function,
            "Sending HID++ request: {:02X?}",
            &request
        );

        // Send request
        if let Err(e) = self.device.write_all(&request) {
            tracing::debug!(error = %e, "Failed to write HID++ message");
            return None;
        }

        // Read response with timeout: wait on poll(2) instead of sleeping in
        // fixed 10ms steps (same total budget, ~5ms less latency per round
        // trip, and shorter mutex hold windows upstream).
        let mut response = [0u8; 20];
        let deadline = std::time::Instant::now()
            + std::time::Duration::from_millis(max_attempts as u64 * 10);

        loop {
            match self.device.read(&mut response) {
                Ok(len) if len >= 7 => {
                    let resp_function = (response[3] >> 4) & 0x0F;
                    let resp_sw_id = response[3] & 0x0F;

                    tracing::debug!(
                        "HID++ response: {:02X?} (feat={}, fn={}, sw={})",
                        &response[..len],
                        response[2],
                        resp_function,
                        resp_sw_id
                    );

                    // Check if this is a response to our request
                    if response[0] == report_type::SHORT || response[0] == report_type::LONG {
                        // Must match: device index, feature index, function, AND software ID
                        if response[1] == self.device_index
                            && response[2] == feature_index
                            && resp_function == function
                            && resp_sw_id == SOFTWARE_ID
                        {
                            tracing::debug!("HID++ request matched! Returning response");
                            self.last_receiver_error = None;
                            return Some(response[..len].to_vec());
                        }
                        // Check for error response (0xFF feature_index indicates error)
                        // Format: [report_type, device_idx, 0xFF, orig_feature_idx, orig_fn_sw, error_code, ...]
                        if response[2] == 0xFF {
                            let error_code = response[5];
                            let error_msg = match error_code {
                                0x00 => "No error",
                                0x01 => "Unknown function",
                                0x02 => "Function not available",
                                0x03 => "Invalid argument",
                                0x04 => "Not supported",
                                0x05 => "Invalid argument/Out of range",
                                0x06 => "Device busy",
                                0x07 => "Connection failed",
                                0x08 => "Invalid address",
                                _ => "Unknown error",
                            };
                            tracing::warn!(
                                error_code,
                                error_msg,
                                feature_index = response[3],
                                "HID++ error response: {:02X?}",
                                &response[..len]
                            );
                            return None;
                        }
                        // HID++ 1.0 receiver error (0x8F): the paired device
                        // cannot answer (0x04 = radio parked). Remembered so
                        // callers can tell "asleep" from a real failure.
                        if response[2] == 0x8F {
                            if let Some(code) = receiver_error_code(&response[..len], self.device_index) {
                                self.last_receiver_error = Some(code);
                            }
                            tracing::debug!("HID++ legacy error response: {:02X?}", &response[..len]);
                            return None;
                        }
                        // Log non-matching responses for debugging
                        tracing::debug!(
                            expected_dev = self.device_index,
                            expected_feat = feature_index,
                            expected_fn = function,
                            expected_sw = SOFTWARE_ID,
                            got_dev = response[1],
                            got_feat = response[2],
                            got_fn = resp_function,
                            got_sw = resp_sw_id,
                            "HID++ response didn't match expected values"
                        );
                    }
                }
                Ok(_) => {
                    // Short read, continue
                }
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    // No data yet - block until readable or out of budget
                    if !wait_readable(self.device.as_raw_fd(), deadline) {
                        tracing::debug!(feature_index, function, max_attempts, "HID++ request timeout");
                        return None;
                    }
                    // Data ready: read it before re-checking the deadline
                    continue;
                }
                Err(e) => {
                    tracing::debug!(error = %e, "Error reading HID++ response");
                    return None;
                }
            }

            if std::time::Instant::now() >= deadline {
                tracing::debug!(feature_index, function, max_attempts, "HID++ request timeout");
                return None;
            }
        }
    }

    /// Send a long HID++ message (20 bytes) - fire and forget
    #[allow(dead_code)]
    fn hidpp_send_long(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Result<(), std::io::Error> {
        // Drain any pending data first
        self.drain_buffer();

        // Build HID++ long report (20 bytes)
        let mut request = [0u8; 20];
        request[0] = report_type::LONG;
        request[1] = self.device_index;
        request[2] = feature_index;
        request[3] = (function << 4) | SOFTWARE_ID;

        // Copy params (up to 16 bytes for long report)
        let param_len = params.len().min(16);
        request[4..4 + param_len].copy_from_slice(&params[..param_len]);

        tracing::trace!(
            feature_index,
            function,
            "Sending HID++ long message: {:02X?}",
            &request
        );

        self.device.write_all(&request)
    }

    /// Send a long HID++ request (20 bytes) and wait for response
    ///
    /// Used for commands that need more than 3 parameter bytes
    /// (e.g. setCidReporting which needs 5 bytes).
    fn hidpp_long_request(&mut self, feature_index: u8, function: u8, params: &[u8]) -> Option<Vec<u8>> {
        // Drain any pending data first
        self.drain_buffer();

        // Build HID++ long report (20 bytes)
        let mut request = [0u8; 20];
        request[0] = report_type::LONG;
        request[1] = self.device_index;
        request[2] = feature_index;
        request[3] = (function << 4) | SOFTWARE_ID;

        // Copy params (up to 16 bytes for long report)
        let param_len = params.len().min(16);
        request[4..4 + param_len].copy_from_slice(&params[..param_len]);

        tracing::debug!(
            feature_index,
            function,
            "Sending HID++ long request: {:02X?}",
            &request
        );

        // Send request
        if let Err(e) = self.device.write_all(&request) {
            tracing::debug!(error = %e, "Failed to write HID++ long message");
            return None;
        }

        // Read response with timeout (same poll(2) approach as hidpp_request,
        // 1000ms budget matching the previous 100 x 10ms attempts)
        let mut response = [0u8; 20];
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(1000);

        loop {
            match self.device.read(&mut response) {
                Ok(len) if len >= 7 => {
                    let resp_function = (response[3] >> 4) & 0x0F;
                    let resp_sw_id = response[3] & 0x0F;

                    // Check for matching response
                    if (response[0] == report_type::SHORT || response[0] == report_type::LONG)
                        && response[1] == self.device_index
                        && response[2] == feature_index
                        && resp_function == function
                        && resp_sw_id == SOFTWARE_ID
                    {
                        tracing::debug!("HID++ long request matched: {:02X?}", &response[..len]);
                        self.last_receiver_error = None;
                        return Some(response[..len].to_vec());
                    }

                    // Check for error response. Gate on the report type and
                    // device index first: on Bluetooth the same hidraw fd also
                    // carries 0x02 mouse-motion reports where byte 2 is
                    // coordinate data, an ungated 0xFF check misparses pointer
                    // motion as a HID++ error (feature enumeration then fails
                    // whenever the mouse is moving).
                    if (response[0] == report_type::SHORT || response[0] == report_type::LONG)
                        && response[1] == self.device_index
                        && response[2] == 0xFF
                    {
                        let error_code = response[5];
                        tracing::warn!(
                            error_code,
                            "HID++ error response to long request: {:02X?}",
                            &response[..len]
                        );
                        return None;
                    }
                    // Receiver error (0x8F) for our device: fail now instead
                    // of waiting out the 1 s deadline (a parked mouse made
                    // every setCidReporting call cost a full second).
                    if let Some(code) = receiver_error_code(&response[..len], self.device_index) {
                        self.last_receiver_error = Some(code);
                        tracing::debug!(code, "HID++ receiver error to long request: {:02X?}", &response[..len]);
                        return None;
                    }
                }
                Ok(_) => {}
                Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                    // No data yet - block until readable or out of budget
                    if !wait_readable(self.device.as_raw_fd(), deadline) {
                        tracing::debug!(feature_index, function, "HID++ long request timeout");
                        return None;
                    }
                    // Data ready: read it before re-checking the deadline
                    continue;
                }
                Err(e) => {
                    tracing::debug!(error = %e, "Error reading HID++ long response");
                    return None;
                }
            }

            if std::time::Instant::now() >= deadline {
                tracing::debug!(feature_index, function, "HID++ long request timeout");
                return None;
            }
        }
    }

    /// Validate that the device supports HID++ 2.0 protocol
    ///
    /// Uses a short timeout (200ms) since responsive devices reply within
    /// ~20ms. Empty receiver slots and non-HID++ devices won't respond at all,
    /// so waiting longer just hammers the receiver firmware for no benefit.
    fn validate_hidpp20(&mut self) -> bool {
        // Send IRoot ping (feature 0x00, function 0x01)
        // Ping echoes back the data byte and returns protocol version
        let params = [0x00, 0x00, 0xAA]; // 0xAA is ping data to echo

        if let Some(response) = self.hidpp_request_with_timeout(0x00, 0x01, &params, 20) {
            // Check if ping data was echoed (byte 6 should be 0xAA)
            if response.len() >= 7 && response[6] == 0xAA {
                tracing::debug!("HID++ 2.0 validated, ping echoed successfully");
                return true;
            }
        }

        false
    }

    /// [`Self::validate_hidpp20`] with a custom attempt budget (10ms each).
    ///
    /// A dozing wireless device needs its radio link re-established before it
    /// answers the first ping (hundreds of ms on Bolt), which the default
    /// 200ms budget misses; discovery paths that KNOW a slot holds a device
    /// pass a larger budget instead of failing on every scan.
    fn validate_hidpp20_with_attempts(&mut self, max_attempts: u32) -> bool {
        let params = [0x00, 0x00, 0xAA];
        if let Some(response) = self.hidpp_request_with_timeout(0x00, 0x01, &params, max_attempts) {
            if response.len() >= 7 && response[6] == 0xAA {
                return true;
            }
        }
        false
    }

    /// Enumerate device features and build feature table
    ///
    /// # SAFETY
    ///
    /// This method only READS feature information - it does NOT use
    /// any blocklisted features. Blocklisted features are logged for
    /// audit purposes but never stored for use.
    fn enumerate_features(&mut self) {
        // First, get the feature index for IFeatureSet (0x0001)
        let feature_set_index = match self.get_feature_index(features::I_FEATURE_SET) {
            Some(idx) => idx,
            None => {
                tracing::debug!("Device does not support IFeatureSet");
                return;
            }
        };

        // Get feature count (function 0x00 of IFeatureSet)
        let feature_count = match self.hidpp_request(feature_set_index, 0x00, &[]) {
            Some(resp) if resp.len() >= 5 => resp[4],
            _ => return,
        };

        tracing::debug!(count = feature_count, "Enumerating device features");

        // Enumerate each feature (function 0x01 of IFeatureSet)
        for i in 0..feature_count {
            if let Some(resp) = self.hidpp_request(feature_set_index, 0x01, &[i, 0, 0]) {
                if resp.len() < 6 {
                    continue;
                }

                let feature_id = ((resp[4] as u16) << 8) | (resp[5] as u16);
                let feature_index = i; // Feature indices are 0-based (slot = index)

                // SAFETY CHECK: Log blocklisted features but DO NOT store them
                if blocklisted_features::is_blocklisted(feature_id) {
                    let reason = blocklisted_features::blocklist_reason(feature_id)
                        .unwrap_or("Unknown");
                    tracing::debug!(
                        feature_id = format!("0x{:04X}", feature_id),
                        reason = reason,
                        "Device has blocklisted feature (will NOT be used)"
                    );
                    // Explicitly DO NOT add to feature_table
                    continue;
                }

                self.feature_table.insert(feature_id, feature_index);

                // Log all features for debugging
                tracing::debug!(
                    feature_id = format!("0x{:04X}", feature_id),
                    feature_index = feature_index,
                    "Found feature"
                );

                // Check for legacy force feedback feature (0x8123 - for racing wheels)
                if feature_id == features::FORCE_FEEDBACK {
                    self.haptic_supported = true;
                    self.haptic_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "Legacy haptic/force feedback feature found (0x8123)"
                    );
                }

                // Check for MX Master 4 haptic feature (0x19B0)
                if feature_id == features::MX_MASTER_4_HAPTIC {
                    self.mx4_haptic_supported = true;
                    self.mx4_haptic_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "MX Master 4 haptic feature found (0x19B0)"
                    );
                }

                // Check for alternative haptic feature (0x0B4E from mx4notifications)
                if feature_id == features::MX4_HAPTIC_ALT {
                    self.mx4_haptic_supported = true;
                    self.mx4_haptic_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "MX Master 4 haptic feature found (0x0B4E - mx4notifications)"
                    );
                }

                // Check for adjustable DPI feature (0x2201)
                if feature_id == features::ADJUSTABLE_DPI {
                    self.dpi_supported = true;
                    self.dpi_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "Adjustable DPI feature found (0x2201)"
                    );
                }

                // Check for SmartShift Enhanced (0x2111) - MX Master 3/4 SmartShift control
                if feature_id == features::HIRES_SCROLL {
                    self.smartshift_supported = true;
                    self.smartshift_feature_index = Some(feature_index);
                    self.smartshift_is_enhanced = true;
                    tracing::info!(
                        index = feature_index,
                        "SmartShift Enhanced feature found (0x2111) - SmartShift control available"
                    );
                }

                // Also check for legacy SmartShift feature (0x2110) for older mice
                if feature_id == features::SMARTSHIFT_LEGACY {
                    // Only set if not already detected via HiResScroll
                    if !self.smartshift_supported {
                        self.smartshift_supported = true;
                        self.smartshift_feature_index = Some(feature_index);
                        tracing::info!(
                            index = feature_index,
                            "Legacy SmartShift feature found (0x2110)"
                        );
                    }
                }

                // Check for UNIFIED_BATTERY feature (0x1004) - preferred for MX Master 4
                if feature_id == features::UNIFIED_BATTERY {
                    self.battery_supported = true;
                    self.battery_feature_index = Some(feature_index);
                    self.is_unified_battery = true;
                    tracing::info!(
                        index = feature_index,
                        "Unified Battery feature found (0x1004)"
                    );
                }

                // Check for BATTERY_STATUS feature (0x1000) - fallback for older devices
                if feature_id == features::BATTERY_STATUS && !self.battery_supported {
                    self.battery_supported = true;
                    self.battery_feature_index = Some(feature_index);
                    self.is_unified_battery = false;
                    tracing::info!(
                        index = feature_index,
                        "Battery Status feature found (0x1000)"
                    );
                }

                // Check for REPROG_CONTROLS_V4 feature (0x1B04) - button divert
                if feature_id == features::REPROG_CONTROLS_V4 {
                    self.reprog_controls_supported = true;
                    self.reprog_controls_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "REPROG_CONTROLS_V4 feature found (0x1B04) - button divert available"
                    );
                }

                // Check for ThumbWheel feature (0x2150) - thumb-wheel divert
                if feature_id == features::THUMB_WHEEL {
                    self.thumbwheel_supported = true;
                    self.thumbwheel_feature_index = Some(feature_index);
                    tracing::info!(
                        index = feature_index,
                        "ThumbWheel feature found (0x2150) - thumb-wheel divert available"
                    );
                }
            }
        }

        tracing::debug!(
            feature_count = self.feature_table.len(),
            legacy_haptic = self.haptic_supported,
            mx4_haptic = self.mx4_haptic_supported,
            dpi = self.dpi_supported,
            smartshift = self.smartshift_supported,
            battery = self.battery_supported,
            reprog_controls = self.reprog_controls_supported,
            "Feature enumeration complete (blocklisted features excluded)"
        );
    }

    /// Get the feature index for a given feature ID using IRoot
    fn get_feature_index(&mut self, feature_id: u16) -> Option<u8> {
        // IRoot function 0x00: getFeatureIndex
        let params = [(feature_id >> 8) as u8, (feature_id & 0xFF) as u8, 0];

        self.hidpp_request(0x00, 0x00, &params).and_then(|resp| {
            if resp.len() >= 5 {
                let index = resp[4];
                if index == 0 {
                    None // Feature not supported
                } else {
                    Some(index)
                }
            } else {
                None
            }
        })
    }

    // =========================================================================
    // Button Divert (REPROG_CONTROLS_V4)
    // =========================================================================

    /// Divert gesture buttons via REPROG_CONTROLS_V4 (0x1B04)
    ///
    /// Tells the mouse to send button presses as HID++ notifications
    /// instead of standard HID reports. This is how we receive the
    /// haptic/gesture thumb button press without logid.
    ///
    /// # SAFETY
    ///
    /// The divert command (setCidReporting function 3) is VOLATILE.
    /// It resets on mouse disconnect or host switch. It does NOT
    /// persist to onboard memory.
    ///
    /// # Target CIDs
    ///
    /// - 0x00C3 (195): Gesture button (thumb button on MX Master 4)
    /// - 0x01A0 (416): Haptic button (if present as separate control)
    pub fn divert_buttons(&mut self) -> Result<u8, HapticError> {
        let feature_index = match self.reprog_controls_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("REPROG_CONTROLS_V4 not available, cannot divert buttons");
                return Ok(0);
            }
        };

        tracing::info!(feature_index, "Diverting gesture buttons via REPROG_CONTROLS_V4");

        // Function 0: getCount() - get number of remappable controls
        let count = match self.hidpp_request(feature_index, 0x00, &[]) {
            Some(resp) if resp.len() >= 5 => resp[4],
            _ => {
                tracing::warn!("Failed to get control count from REPROG_CONTROLS_V4");
                return Ok(0);
            }
        };

        tracing::debug!(count, "Device has remappable controls");

        // Target CIDs to divert
        const GESTURE_BUTTON_CID: u16 = 0x00C3; // 195
        const HAPTIC_BUTTON_CID: u16 = 0x01A0;  // 416

        let mut diverted = 0u8;

        // Function 1: getCidInfo(index) - enumerate controls to find our targets
        for i in 0..count {
            let resp = match self.hidpp_request(feature_index, 0x01, &[i, 0, 0]) {
                Some(r) if r.len() >= 9 => r,
                _ => continue,
            };

            // getCidInfo response format (long report):
            // Byte 4-5: CID (big endian)
            // Byte 6-7: Task ID
            // Byte 8: flags (bit 0 = mouse btn, bit 1 = fKey, bit 2 = hotKey,
            //          bit 3 = fnToggle, bit 4 = reprogrammable, bit 5 = divertable)
            let cid = ((resp[4] as u16) << 8) | (resp[5] as u16);
            let flags = resp[8];
            let divertable = (flags & 0x20) != 0;
            if cid == GESTURE_BUTTON_CID {
                self.gesture_button_seen = true;
            }

            tracing::debug!(
                index = i,
                cid = format!("0x{:04X}", cid),
                flags = format!("0x{:02X}", flags),
                divertable,
                "Control info"
            );

            // Check if this is one of our target buttons AND it's divertable
            if (cid == GESTURE_BUTTON_CID || cid == HAPTIC_BUTTON_CID) && divertable {
                tracing::info!(
                    cid = format!("0x{:04X}", cid),
                    "Diverting button"
                );

                // Function 3: setCidReporting - MUST use long report (5 param bytes)
                //
                // Flag byte uses "change gate" pattern from HID++ 2.0 spec:
                //   bit 0: TemporaryDiverted     (0x01) - enable volatile divert
                //   bit 1: ChangeTemporaryDivert (0x02) - MUST set to apply bit 0
                //   bit 2: PersistentlyDiverted  (0x04) - DO NOT USE
                //   bit 3: ChangePersistentDivert(0x08) - DO NOT USE
                //   bit 4: RawXYDiverted         (0x10) - divert raw XY movement
                //   bit 5: ChangeRawXYDivert     (0x20) - MUST set to apply bit 4
                //
                // We set divert + change gate = 0x03. No persist, no rawXY.
                let divert_flags: u8 = 0x03; // TemporaryDiverted | ChangeTemporaryDivert
                let params: &[u8] = &[
                    (cid >> 8) as u8,   // CID high byte
                    (cid & 0xFF) as u8, // CID low byte
                    divert_flags,       // 0x03: divert=true with change gate
                    0x00,               // remap target CID high (0 = no remap)
                    0x00,               // remap target CID low  (0 = no remap)
                ];

                match self.hidpp_long_request(feature_index, 0x03, params) {
                    Some(resp) => {
                        tracing::info!(
                            cid = format!("0x{:04X}", cid),
                            response = format!("{:02X?}", &resp[4..resp.len().min(9)]),
                            "Button diverted successfully"
                        );
                        diverted += 1;
                    }
                    None => {
                        tracing::warn!(
                            cid = format!("0x{:04X}", cid),
                            "Failed to divert button (setCidReporting returned no response)"
                        );
                    }
                }
            }
        }

        if diverted > 0 {
            tracing::info!(count = diverted, "Gesture buttons diverted - HID++ notifications enabled");
        } else {
            tracing::warn!("No gesture buttons found to divert. Button detection may not work.");
        }

        Ok(diverted)
    }

    /// Divert a single button by CID for macro interception.
    ///
    /// This prevents the OS from seeing the button event. Instead, it arrives
    /// as a HID++ notification that the hidraw handler forwards as MacroTriggered.
    pub fn divert_single_button(&mut self, cid: u16) -> Result<bool, HapticError> {
        self.set_button_divert(cid, true)
    }

    /// Enable or disable the volatile HID++ divert for a single control by CID.
    ///
    /// With `divert` true the button's events arrive as HID++ notifications
    /// instead of normal input; with `divert` false the divert is cleared and
    /// the button returns to its native hardware behaviour. The divert is
    /// volatile and is reset by the device on disconnect / Easy-Switch host
    /// change. Returns `Ok(true)` when the control was found and the request
    /// succeeded, `Ok(false)` when the CID is absent or not divertable.
    pub fn set_button_divert(&mut self, cid: u16, divert: bool) -> Result<bool, HapticError> {
        let feature_index = match self.reprog_controls_feature_index {
            Some(idx) => idx,
            None => return Ok(false),
        };

        // Enumerate controls to verify the CID exists and is divertable
        let count = match self.hidpp_request(feature_index, 0x00, &[]) {
            Some(resp) if resp.len() >= 5 => resp[4],
            _ => return Ok(false),
        };

        for i in 0..count {
            let resp = match self.hidpp_request(feature_index, 0x01, &[i, 0, 0]) {
                Some(r) if r.len() >= 9 => r,
                _ => continue,
            };

            let found_cid = ((resp[4] as u16) << 8) | (resp[5] as u16);
            let flags = resp[8];
            let divertable = (flags & 0x20) != 0;

            if found_cid == cid && divertable {
                // ChangeTemporaryDivert (0x02) is the change gate; OR in
                // TemporaryDiverted (0x01) to enable, leave it clear to disable.
                let divert_flags: u8 = if divert { 0x03 } else { 0x02 };
                let params: &[u8] = &[
                    (cid >> 8) as u8,
                    (cid & 0xFF) as u8,
                    divert_flags,
                    0x00,
                    0x00,
                ];

                if let Some(resp) = self.hidpp_long_request(feature_index, 0x03, params) {
                    tracing::info!(
                        cid = format!("0x{:04X}", cid),
                        divert,
                        response = format!("{:02X?}", &resp[4..resp.len().min(9)]),
                        "Button divert updated"
                    );
                    return Ok(true);
                }
            }
        }

        Ok(false)
    }

    /// Enable or disable volatile diverts for multiple controls after one
    /// REPROG_CONTROLS_V4 control scan.
    ///
    /// This is equivalent to calling [`Self::set_button_divert`] for every CID,
    /// but avoids repeating `getCount` and `getCidInfo` for each macro during
    /// startup. The returned CIDs are exactly those successfully updated.
    pub fn set_button_diverts(
        &mut self,
        cids: &[u16],
        divert: bool,
    ) -> Result<Vec<u16>, HapticError> {
        let feature_index = match self.reprog_controls_feature_index {
            Some(idx) => idx,
            None => return Ok(Vec::new()),
        };
        Ok(set_button_diverts_with_io(
            self,
            feature_index,
            cids,
            divert,
        ))
    }

    /// Scan the REPROG_CONTROLS_V4 inventory and cache it for this connection.
    ///
    /// READ-ONLY on the device (getCount + getCidInfo). Empty when the feature
    /// is absent. `cached_controls()` returns the last result without I/O.
    pub fn list_controls(&mut self) -> Vec<ControlInfo> {
        let feature_index = match self.reprog_controls_feature_index {
            Some(idx) => idx,
            None => return Vec::new(),
        };
        if !self.controls.is_empty() {
            return self.controls.clone();
        }
        self.controls = list_controls_with_io(self, feature_index);
        tracing::debug!(count = self.controls.len(), "REPROG_CONTROLS_V4 inventory scanned");
        self.controls.clone()
    }

    /// The inventory from the last `list_controls()` scan (may be empty).
    pub fn cached_controls(&self) -> &[ControlInfo] {
        &self.controls
    }

    // =========================================================================
    // ThumbWheel (0x2150)
    // =========================================================================

    /// Check if the ThumbWheel feature (0x2150) is available.
    pub fn thumbwheel_supported(&self) -> bool {
        self.thumbwheel_supported
    }

    /// Feature index for the ThumbWheel feature, if present.
    ///
    /// The hidraw event reader uses this to disambiguate diverted thumb-wheel
    /// rotation notifications from diverted button events (both arrive as
    /// HID++ reports with function id 0).
    pub fn thumbwheel_feature_index(&self) -> Option<u8> {
        self.thumbwheel_feature_index
    }

    /// Look up the discovered feature index for an arbitrary feature id.
    ///
    /// Reads the table built during enumeration (blocklisted features are never
    /// inserted, so this can only return indices for safe features). Used by the
    /// hidraw reader to route device-originated notifications.
    pub fn feature_index(&self, feature_id: u16) -> Option<u8> {
        self.feature_table.get(&feature_id).copied()
    }

    /// Query ThumbWheel capabilities (function 0: getThumbwheelInfo).
    ///
    /// Returns `(native_resolution, diverted)` where `native_resolution` is the
    /// reported counts per revolution and `diverted` is the device's current
    /// divert state. Returns `None` if the feature is unavailable or the query
    /// fails. READ-ONLY.
    pub fn get_thumbwheel_capabilities(&mut self) -> Option<(u16, bool)> {
        let feature_index = self.thumbwheel_feature_index?;

        // Function 0: getThumbwheelInfo() -> nativeRes(2B), diverted(1B), ...
        let resp = self.hidpp_request(feature_index, 0x00, &[])?;
        if resp.len() < 7 {
            return None;
        }
        let native_res = ((resp[4] as u16) << 8) | (resp[5] as u16);
        let diverted = resp[6] != 0;
        tracing::debug!(native_res, diverted, "ThumbWheel capabilities");
        Some((native_res, diverted))
    }

    /// Enable or disable thumb-wheel divert (function 1: setThumbwheelReporting).
    ///
    /// # SAFETY
    ///
    /// This is a VOLATILE runtime command. It resets on mouse disconnect or host
    /// switch and does NOT persist to onboard memory.
    ///
    /// # Arguments
    ///
    /// * `divert` - true to route rotation to HID++ notifications, false for
    ///   native behaviour.
    /// * `invert` - request the device to invert reported direction.
    pub fn set_thumbwheel_reporting(&mut self, divert: bool, invert: bool) -> Result<(), HapticError> {
        let feature_index = match self.thumbwheel_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("ThumbWheel not supported, cannot set reporting");
                return Err(HapticError::NotSupported);
            }
        };

        // Function 2: setThumbwheelReporting(reporting, invertDirection)
        //   reporting:       0 = native, 1 = diverted (HID++ notifications)
        //   invertDirection: 0 = normal, 1 = inverted
        // (Function 1 is getThumbwheelStatus: calling it never diverted the
        // wheel, and its status response got misread as a phantom rotation.)
        let params = [if divert { 0x01 } else { 0x00 }, if invert { 0x01 } else { 0x00 }];

        tracing::info!(feature_index, divert, invert, "Setting ThumbWheel reporting");

        match self.hidpp_request(feature_index, 0x02, &params) {
            Some(_) => {
                tracing::info!(divert, invert, "ThumbWheel reporting set");
                Ok(())
            }
            None => {
                tracing::warn!("Failed to set ThumbWheel reporting (no response)");
                Err(HapticError::CommunicationError)
            }
        }
    }

    // =========================================================================
    // Public Accessors
    // =========================================================================

    /// Check if REPROG_CONTROLS_V4 is available for button divert
    pub fn reprog_controls_supported(&self) -> bool {
        self.reprog_controls_supported
    }

    /// Get the hidraw device path this device is connected to
    pub fn device_path(&self) -> &std::path::Path {
        &self.device_path
    }

    /// HID++ device index: the receiver slot, or 0xFF for a direct link.
    pub fn device_index(&self) -> u8 {
        self.device_index
    }

    /// Check if any haptic feedback is supported (MX4 or legacy)
    pub fn haptic_supported(&self) -> bool {
        self.mx4_haptic_supported || self.haptic_supported
    }

    /// Check if MX Master 4 specific haptic is supported (feature 0x19B0)
    pub fn mx4_haptic_supported(&self) -> bool {
        self.mx4_haptic_supported
    }

    /// Check if legacy force feedback haptic is supported (feature 0x8123)
    pub fn legacy_haptic_supported(&self) -> bool {
        self.haptic_supported
    }

    /// Get connection type
    /// Read the unit id from DEVICE_INFORMATION (0x0003, function 0). READ-ONLY.
    fn read_unit_id(&mut self) {
        if let Some(idx) = self.get_feature_index(features::DEVICE_INFORMATION) {
            if let Some(resp) = self.hidpp_request(idx, 0x00, &[]) {
                self.unit_id = parse_unit_id(&resp);
            }
        }
    }

    /// The device's unit id, when DEVICE_INFORMATION reported one.
    pub fn unit_id(&self) -> Option<u32> {
        self.unit_id
    }

    /// True when the receiver last answered "connection request failed" for
    /// this device: paired, but its radio is parked (idle or on another
    /// Easy-Switch host). Callers should wait rather than rescan.
    pub fn link_parked(&self) -> bool {
        self.last_receiver_error == Some(RECEIVER_ERR_CONNECT_FAIL)
    }

    /// True when the last `divert_buttons` scan found the gesture button
    /// (CID 0x00C3). No I/O.
    pub fn gesture_button_seen(&self) -> bool {
        self.gesture_button_seen
    }

    /// Capability flags from the cached feature table (no I/O).
    pub fn capabilities(&self) -> std::collections::HashMap<String, bool> {
        crate::hidpp::capabilities::capability_map(
            |id| self.feature_table.contains_key(&id),
            self.gesture_button_seen,
        )
    }

    pub fn connection_type(&self) -> ConnectionType {
        self.connection_type
    }

    /// Get the device name via HID++ DEVICE_NAME feature (0x0005)
    ///
    /// Queries the device for its actual name string (e.g. "MX Master 4",
    /// "MX Master 4 for Business", "MX Master 3S"). Returns None if
    /// the feature is not available or the query fails.
    pub fn get_device_name(&mut self) -> Option<String> {
        let feat_idx = *self.feature_table.get(&features::DEVICE_NAME)?;

        // Function 0: getDeviceNameCount - returns name length
        let resp = self.hidpp_request(feat_idx, 0x00, &[])?;
        if resp.len() < 5 {
            return None;
        }
        let name_len = resp[4] as usize;
        if name_len == 0 || name_len > 64 {
            return None;
        }

        // Function 1: getDeviceName - read name in chunks
        let mut name_bytes = Vec::with_capacity(name_len);
        let mut offset = 0usize;
        while offset < name_len {
            let resp = self.hidpp_request(feat_idx, 0x01, &[offset as u8])?;
            // Payload starts at byte 4
            let available = resp.len().saturating_sub(4);
            let needed = name_len - offset;
            let chunk_len = available.min(needed);
            if chunk_len == 0 {
                break;
            }
            name_bytes.extend_from_slice(&resp[4..4 + chunk_len]);
            offset += chunk_len;
        }

        // Convert to string, trimming null bytes
        let name = String::from_utf8_lossy(&name_bytes)
            .trim_end_matches('\0')
            .trim()
            .to_string();

        if name.is_empty() {
            None
        } else {
            tracing::info!(name = %name, "Device name from HID++");
            Some(name)
        }
    }

    // =========================================================================
    // Haptic Methods
    // =========================================================================

    /// The motor as the mouse has it (0x19B0 getConfig): enabled, and the
    /// strength in percent.
    pub fn get_haptic_level(&mut self) -> Option<(bool, u8)> {
        let idx = self.mx4_haptic_feature_index?;
        let r = self.hidpp_request(idx, 0x01, &[0x00, 0x00, 0x00])?;
        (r.len() >= 6).then(|| (r[4] & 0x01 != 0, r[5]))
    }

    /// Motor strength in percent (0x19B0 setConfig `[enabled, pct, 0]`,
    /// hardware-verified). The play command has no amplitude byte, so this
    /// device-wide value is the only strength there is.
    pub fn set_haptic_level(&mut self, pct: u8) -> Result<(), HapticError> {
        let idx = self.mx4_haptic_feature_index.ok_or(HapticError::NotSupported)?;
        self.hidpp_request(idx, 0x02, &[0x01, pct.clamp(1, 100), 0x00])
            .map(|_| ())
            .ok_or(HapticError::CommunicationError)
    }

    /// The Haptic Sense Panel press force (0x19C0 button 0).
    pub fn force_sense(&mut self) -> Option<ForceSense> {
        let idx = *self.feature_table.get(&features::FORCE_SENSING_BUTTON)?;
        let info = self.hidpp_request(idx, 0x01, &[0x00, 0x00, 0x00])?;
        let current = self.hidpp_request(idx, 0x02, &[0x00, 0x00, 0x00])?;
        ForceSense::parse(info.get(4..)?, current.get(4..)?)
    }

    /// Set the Haptic Sense Panel press force (raw, within the reported range).
    pub fn set_force_sense(&mut self, raw: u16) -> Result<(), HapticError> {
        let idx = *self
            .feature_table
            .get(&features::FORCE_SENSING_BUTTON)
            .ok_or(HapticError::NotSupported)?;
        let [hi, lo] = raw.to_be_bytes();
        self.hidpp_request(idx, 0x03, &[0x00, hi, lo])
            .map(|_| ())
            .ok_or(HapticError::CommunicationError)
    }

    /// Send an MX Master 4 haptic pattern
    ///
    /// # SAFETY
    ///
    /// This method ONLY sends volatile/runtime commands.
    /// It does NOT write to onboard memory.
    ///
    /// # Arguments
    ///
    /// * `pattern` - The MX4 haptic pattern to play (0-14)
    pub fn send_haptic_pattern(&mut self, pattern: Mx4HapticPattern) -> Result<(), HapticError> {
        if !self.mx4_haptic_supported {
            tracing::trace!("MX4 haptic not supported, skipping pattern");
            return Ok(());
        }

        tracing::debug!(
            pattern = %pattern,
            waveform_id = pattern.to_id(),
            "Sending MX4 haptic pattern"
        );

        // Use the exact packet format from mx4notifications that we verified works:
        // Packet: [0x10, 0x02, 0x0B, 0x4E, waveform, 0x00, 0x00]
        // - 0x10: SHORT report type
        // - 0x02: device index (Bolt receiver)
        // - 0x0B: feature index 11 (hardcoded, matches mx4notifications)
        // - 0x4E: (function 0x04 << 4) | sw_id 0x0E
        // - waveform: the haptic pattern ID

        const MX4_HAPTIC_FEATURE_INDEX: u8 = 0x0B;  // Feature index 11
        const MX4_HAPTIC_FUNCTION: u8 = 0x04;       // Function ID for haptic play
        const MX4_HAPTIC_SW_ID: u8 = 0x0E;          // Software ID used by mx4notifications

        self.drain_buffer();

        // Bluetooth devices only expose the long (0x11) report, so send the
        // haptic command as a 20-byte long report there. The short-report
        // path below is left untouched for USB/Bolt where it is verified.
        // On Bluetooth the haptic feature index can differ from 0x0B, so
        // prefer the index discovered during feature enumeration.
        if self.connection_type == ConnectionType::Bluetooth {
            let feature_index = self
                .mx4_haptic_feature_index
                .unwrap_or(MX4_HAPTIC_FEATURE_INDEX);

            let mut request = [0u8; 20];
            request[0] = report_type::LONG;
            request[1] = self.device_index;
            request[2] = feature_index;
            request[3] = (MX4_HAPTIC_FUNCTION << 4) | MX4_HAPTIC_SW_ID;
            request[4] = pattern.to_id();

            tracing::debug!("Sending MX4 haptic packet (long/BT): {:02X?}", &request);

            self.device
                .write_all(&request)
                .map_err(HapticError::IoError)?;

            return Ok(());
        }

        let mut request = [0u8; 7];
        request[0] = report_type::SHORT;
        request[1] = self.device_index;
        request[2] = MX4_HAPTIC_FEATURE_INDEX;
        request[3] = (MX4_HAPTIC_FUNCTION << 4) | MX4_HAPTIC_SW_ID;
        request[4] = pattern.to_id();
        // request[5] and request[6] remain 0

        tracing::debug!(
            "Sending MX4 haptic packet: {:02X?}",
            &request
        );

        self.device.write_all(&request).map_err(HapticError::IoError)?;

        Ok(())
    }

    /// Send a haptic pulse command (legacy method for force feedback devices)
    ///
    /// # SAFETY
    ///
    /// This method ONLY sends volatile/runtime commands.
    /// It does NOT write to onboard memory.
    pub fn send_haptic_pulse(&mut self, intensity: u8, duration_ms: u16) -> Result<(), HapticError> {
        let feature_index = match self.haptic_feature_index {
            Some(idx) => idx,
            None => {
                // Legacy haptics not supported, succeed silently
                return Ok(());
            }
        };

        // Construct haptic pulse command for legacy force feedback
        // Note: This is for racing wheels and similar devices with 0x8123 feature
        let params = [
            intensity,
            (duration_ms >> 8) as u8,
            (duration_ms & 0xFF) as u8,
        ];

        // Use hidpp_request for short messages (will drain buffer and send)
        if self.hidpp_request(feature_index, 0x00, &params).is_none() {
            tracing::debug!("Legacy haptic pulse - no response (may be expected)");
        }

        Ok(())
    }

    // =========================================================================
    // DPI Methods (0x2201 - Adjustable DPI)
    // =========================================================================

    /// Check if DPI adjustment is supported
    pub fn dpi_supported(&self) -> bool {
        self.dpi_supported
    }

    /// Get current sensor DPI
    ///
    /// # Returns
    /// Current DPI value (typically 400-8000) or None if not supported
    pub fn get_dpi(&mut self) -> Option<u16> {
        let feature_index = self.dpi_feature_index?;

        tracing::debug!(feature_index, "Getting DPI from device");

        // Function [2] getSensorDpi(sensorIdx) -> sensorIdx, dpi, defaultDpi
        // sensorIdx = 0 for the primary (and usually only) sensor
        let params = [0x00, 0x00, 0x00]; // sensorIdx = 0

        self.hidpp_request(feature_index, 0x02, &params).and_then(|resp| {
            if resp.len() >= 7 {
                // Response: [report_type, device_idx, feature_idx, fn_sw_id, sensor_idx, dpi_msb, dpi_lsb, default_msb, default_lsb, ...]
                let mut dpi = ((resp[5] as u16) << 8) | (resp[6] as u16);
                if dpi == 0 && resp.len() >= 9 {
                    // Some firmware reads 0 until set: fall back to defaultDpi (Solaar).
                    dpi = ((resp[7] as u16) << 8) | (resp[8] as u16);
                }
                tracing::debug!(dpi, "Got current DPI");
                (dpi != 0).then_some(dpi)
            } else {
                tracing::warn!("Invalid getSensorDpi response length: {}", resp.len());
                None
            }
        })
    }

    /// Set sensor DPI
    ///
    /// # Arguments
    /// * `dpi` - DPI value to set (typically 400-8000, device-dependent)
    ///
    /// # Returns
    /// Ok(()) on success, error on failure
    pub fn set_dpi(&mut self, dpi: u16) -> Result<(), HapticError> {
        let feature_index = match self.dpi_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("DPI adjustment not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        // Every writer (Settings, app profiles, gaming mode, DPI buttons)
        // lands on a value the sensor accepts.
        let requested = dpi;
        let dpi = self.dpi_caps().map_or(dpi, |c| c.snap(dpi));
        tracing::info!(feature_index, requested, dpi, "Setting DPI");

        // Function [3] setSensorDpi(sensorIdx, dpi) -> sensorIdx, dpi
        // sensorIdx = 0 for the primary sensor
        let params = [
            0x00,                    // sensorIdx = 0
            (dpi >> 8) as u8,        // dpi MSB
            (dpi & 0xFF) as u8,      // dpi LSB
        ];

        match self.hidpp_request(feature_index, 0x03, &params) {
            Some(resp) => {
                if resp.len() >= 7 {
                    let confirmed_dpi = ((resp[5] as u16) << 8) | (resp[6] as u16);
                    tracing::info!(requested_dpi = dpi, confirmed_dpi, "DPI set successfully");
                    Ok(())
                } else {
                    tracing::warn!("Short setSensorDpi response, but command may have succeeded");
                    Ok(())
                }
            }
            None => {
                tracing::error!("Failed to set DPI - no response from device");
                Err(HapticError::CommunicationError)
            }
        }
    }

    /// The sensor's settable DPI range and step (getSensorDpiList), read once
    /// per connection.
    pub fn dpi_caps(&mut self) -> Option<DpiCaps> {
        if self.dpi_caps.is_none() {
            let feature_index = self.dpi_feature_index?;
            // Function [1] getSensorDpiList(sensorIdx) -> sensorIdx, dpiList
            let resp = self.hidpp_request(feature_index, 0x01, &[0x00, 0x00, 0x00])?;
            // [report_type, device_idx, feature_idx, fn_sw_id, sensor_idx, words...]
            let mut caps = resp.get(5..).and_then(DpiCaps::parse);
            // Function [2] getSensorDpi -> sensorIdx, dpi, defaultDpi
            if let (Some(c), Some(r)) = (caps.as_mut(), self.hidpp_request(feature_index, 0x02, &[0x00, 0x00, 0x00])) {
                if r.len() >= 9 {
                    c.default = u16::from_be_bytes([r[7], r[8]]);
                }
            }
            self.dpi_caps = caps;
            tracing::info!(caps = ?self.dpi_caps, "DPI range");
        }
        self.dpi_caps.clone()
    }

    // =========================================================================
    // SmartShift Methods (0x2110/0x2111)
    // =========================================================================

    /// Check if SmartShift is supported
    pub fn smartshift_supported(&self) -> bool {
        self.smartshift_supported
    }

    /// Get SmartShift configuration
    ///
    /// Returns the current SmartShift wheel mode and auto-disengage threshold.
    ///
    /// # Returns
    /// Some((wheel_mode, auto_disengage, third)) where:
    /// - wheel_mode: 1 = Freespin, 2 = Ratchet
    /// - auto_disengage: Threshold for automatic ratchet disengagement (1-254 = N/4 turns/sec, 255 = always engaged)
    /// - third: autoDisengageDefault on legacy 0x2110, torque % on Enhanced 0x2111
    ///
    /// None if SmartShift is not supported
    pub fn get_smartshift(&mut self) -> Option<(u8, u8, u8)> {
        let feature_index = self.smartshift_feature_index?;

        tracing::debug!(feature_index, "Getting SmartShift config from device");

        // Legacy 0x2110: function [0] getRatchetControlMode.
        // Enhanced 0x2111: function [1] getRatchetControlMode ([0] is getCapabilities).
        let read_fn = if self.smartshift_is_enhanced { 0x01 } else { 0x00 };
        let params = [0x00, 0x00, 0x00];

        self.hidpp_request(feature_index, read_fn, &params).and_then(|resp| {
            if resp.len() >= 7 {
                // Response: [report_type, device_idx, feature_idx, fn_sw_id, wheel_mode, auto_disengage, auto_disengage_default, ...]
                let wheel_mode = resp[4];
                let auto_disengage = resp[5];
                let auto_disengage_default = resp[6];

                tracing::debug!(
                    wheel_mode,
                    auto_disengage,
                    auto_disengage_default,
                    "Got SmartShift config"
                );
                Some((wheel_mode, auto_disengage, auto_disengage_default))
            } else {
                tracing::warn!("Invalid getRatchetControlMode response length: {}", resp.len());
                None
            }
        })
    }

    /// Set SmartShift configuration
    ///
    /// Configures the wheel mode and auto-disengage threshold.
    ///
    /// # Arguments
    /// * `wheel_mode` - 0 = no change, 1 = Freespin, 2 = Ratchet
    /// * `auto_disengage` - 0 = no change, 1-254 = N/4 turns/sec threshold, 255 = always engaged
    /// * `auto_disengage_default` - 0 = no change, 1-254 = default threshold, 255 = always
    ///   engaged. Legacy 0x2110 only: on Enhanced 0x2111 the third byte is torque %, so this
    ///   parameter is ignored and 0 (= leave unchanged) is sent instead.
    ///
    /// # Returns
    /// Ok(()) on success, error on failure
    pub fn set_smartshift(
        &mut self,
        wheel_mode: u8,
        auto_disengage: u8,
        auto_disengage_default: u8,
    ) -> Result<(), HapticError> {
        let feature_index = match self.smartshift_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("SmartShift not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        tracing::info!(
            feature_index,
            wheel_mode,
            auto_disengage,
            auto_disengage_default,
            "Setting SmartShift config"
        );

        // Legacy 0x2110: function [1] setRatchetControlMode(wheelMode, autoDisengage,
        // autoDisengageDefault). Enhanced 0x2111: function [2] setRatchetControlMode,
        // whose third byte is torque % - send 0 (= leave unchanged) there.
        let (write_fn, third_byte) = if self.smartshift_is_enhanced {
            (0x02, 0x00)
        } else {
            (0x01, auto_disengage_default)
        };
        let params = [wheel_mode, auto_disengage, third_byte];

        match self.hidpp_request(feature_index, write_fn, &params) {
            Some(resp) if resp.len() >= 7 => {
                // Response echoes the parameters
                let returned_wheel_mode = resp[4];
                let returned_auto_disengage = resp[5];
                let returned_auto_disengage_default = resp[6];

                tracing::debug!(
                    returned_wheel_mode,
                    returned_auto_disengage,
                    returned_auto_disengage_default,
                    "SmartShift config set successfully"
                );
                Ok(())
            }
            Some(resp) => {
                tracing::warn!("Invalid setRatchetControlMode response length: {}", resp.len());
                Err(HapticError::IoError(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "Invalid SmartShift response",
                )))
            }
            None => {
                tracing::warn!("Failed to set SmartShift config");
                Err(HapticError::IoError(std::io::Error::other(
                    "Failed to set SmartShift",
                )))
            }
        }
    }

    /// Get HiResScroll mode configuration (HiRes Wheel 0x2121)
    pub fn get_hiresscroll_mode(&mut self) -> Option<(bool, bool, bool)> {
        let feature_index = self.feature_index(features::HIRES_WHEEL)?;

        tracing::debug!(feature_index, "Getting HiResScroll mode from device");

        // Function [1] getWheelMode() -> mode byte
        let params = [0x00, 0x00, 0x00];

        self.hidpp_request(feature_index, 0x01, &params).and_then(|resp| {
            if resp.len() >= 5 {
                let mode = resp[4];
                let target = (mode & 0x01) != 0;
                let hires = (mode & 0x02) != 0;
                let invert = (mode & 0x04) != 0;

                tracing::debug!(
                    mode,
                    hires,
                    invert,
                    target,
                    "Got HiResScroll mode"
                );
                Some((hires, invert, target))
            } else {
                tracing::warn!("Invalid getMode response length: {}", resp.len());
                None
            }
        })
    }

    /// Set HiResScroll mode configuration (HiRes Wheel 0x2121)
    pub fn set_hiresscroll_mode(
        &mut self,
        hires: bool,
        invert: bool,
        target: bool,
    ) -> Result<(), HapticError> {
        let feature_index = match self.feature_index(features::HIRES_WHEEL) {
            Some(idx) => idx,
            None => {
                tracing::debug!("HiResScroll not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        // Build mode byte
        let mut mode: u8 = 0;
        if target {
            mode |= 0x01;
        }
        if hires {
            mode |= 0x02;
        }
        if invert {
            mode |= 0x04;
        }

        tracing::info!(
            feature_index,
            mode,
            hires,
            invert,
            target,
            "Setting HiResScroll mode"
        );

        // Function [2] setWheelMode(mode)
        let params = [mode, 0x00, 0x00];

        match self.hidpp_request(feature_index, 0x02, &params) {
            Some(resp) if resp.len() >= 5 => {
                let returned_mode = resp[4];
                tracing::debug!(
                    returned_mode,
                    "HiResScroll mode set successfully"
                );
                Ok(())
            }
            Some(resp) => {
                tracing::warn!("Invalid setMode response length: {}", resp.len());
                Err(HapticError::IoError(std::io::Error::new(
                    std::io::ErrorKind::InvalidData,
                    "Invalid HiResScroll response",
                )))
            }
            None => {
                tracing::warn!("Failed to set HiResScroll mode");
                Err(HapticError::IoError(std::io::Error::other(
                    "Failed to set HiResScroll",
                )))
            }
        }
    }

    // =========================================================================
    // Battery Methods
    // =========================================================================

    /// Query battery status from the device
    pub fn query_battery(&mut self) -> Result<(u8, bool), HapticError> {
        let feature_index = match self.battery_feature_index {
            Some(idx) => idx,
            None => {
                tracing::debug!("Battery feature not supported on this device");
                return Err(HapticError::NotSupported);
            }
        };

        // Query battery status
        let function = if self.is_unified_battery { 0x01 } else { 0x00 };

        match self.hidpp_request(feature_index, function, &[]) {
            Some(resp) => {
                tracing::debug!(
                    response_len = resp.len(),
                    is_unified = self.is_unified_battery,
                    "Battery response: {:02X?}",
                    &resp[..resp.len().min(12)]
                );

                if self.is_unified_battery && resp.len() >= 8 {
                    let percentage = unified_battery_percent(resp[4], resp[5]);
                    let charging_status = resp[7];
                    let charging = (1..=3).contains(&charging_status);

                    tracing::debug!(
                        percentage,
                        charging_status,
                        charging,
                        "Battery query result (UNIFIED_BATTERY)"
                    );

                    Ok((percentage, charging))
                } else if resp.len() >= 7 {
                    let percentage = resp[4];
                    let charging_status = resp[6];
                    let charging = (1..=4).contains(&charging_status);

                    tracing::debug!(
                        percentage,
                        charging_status,
                        charging,
                        "Battery query result (BATTERY_STATUS)"
                    );

                    Ok((percentage, charging))
                } else {
                    Err(HapticError::ProtocolError("Invalid battery response".into()))
                }
            }
            None => {
                tracing::warn!("No response from battery query");
                Err(HapticError::CommunicationError)
            }
        }
    }

    /// Check if battery feature is supported
    pub fn battery_supported(&self) -> bool {
        self.battery_supported
    }

    // =========================================================================
    // Keyboard Backlight (BACKLIGHT2 0x1982) - BETA, verified on an MX Keys S
    //
    // Only reached for keyboards opened via `open_keyboard()`. The feature index
    // is read from the table populated during `enumerate_features` (0x1982 is on
    // the safelist, never blocklisted), so no extra struct field or change to
    // the mouse enumerate path is needed.
    // =========================================================================

    /// Whether the device advertises the BACKLIGHT2 feature (0x1982).
    pub fn backlight_supported(&self) -> bool {
        self.feature_table.contains_key(&features::BACKLIGHT2)
    }

    /// Discovered BACKLIGHT2 feature index, if present.
    pub fn backlight_feature_index(&self) -> Option<u8> {
        self.feature_table.get(&features::BACKLIGHT2).copied()
    }

    /// Read the current backlight configuration (function 0, READ-ONLY).
    ///
    /// Returns the raw payload bytes starting at HID++ byte 4. Per Solaar's
    /// BACKLIGHT2 V3 decoder the layout is:
    ///   `[enabled, options, supported, effects(2B), level, dho(2B), dhi(2B), dpow(2B)]`
    /// Layout from Solaar; the write path that preserves these fields is
    /// verified on an MX Keys S over Bolt (2026-09-23).
    pub fn query_backlight_config(&mut self) -> Option<Vec<u8>> {
        let feature_index = self.backlight_feature_index()?;
        let resp = self.hidpp_request(feature_index, 0x00, &[])?;
        if resp.len() < 6 {
            return None;
        }
        Some(resp[4..].to_vec())
    }

    /// Raw getBacklightInfo payload (fn 2): `[numberOfLevel, currentLevel, ..]`.
    ///
    /// `None` when the feature version lacks the function (older BACKLIGHT2
    /// revisions only implement get/set config).
    pub fn query_backlight_info(&mut self) -> Option<Vec<u8>> {
        let feature_index = self.backlight_feature_index()?;
        let resp = self.hidpp_long_request(feature_index, 0x02, &[])?;
        if resp.len() < 6 {
            return None;
        }
        Some(resp[4..].to_vec())
    }

    /// Set keyboard backlight brightness (function 1: setBacklightConfig). BETA.
    ///
    /// Packet reconstructed from Solaar's BACKLIGHT2 (0x1982) implementation
    /// and verified on an MX Keys S over Bolt (2026-09-23: levels 0..7 set
    /// from Settings, acknowledged and visibly applied). Solaar hit a
    /// `FeatureCallError` (error 2 = invalid argument) on some MX Keys
    /// firmware (pwr-Solaar/Solaar PR #2230), hence the read-then-preserve
    /// below. The write payload is:
    ///   `[enabled, options, 0xFF, level, dho(2B LE), dhi(2B LE), dpow(2B LE)]`
    /// where `(options >> 3) & 0x03` selects the mode; mode `0x3` is
    /// manual/permanent brightness, in which `level` is honoured.
    ///
    /// To minimise the chance of an invalid-argument rejection we READ the
    /// current config first and PRESERVE the device-reported `options` bits and
    /// dim durations, only forcing: enabled + manual mode + the requested level.
    ///
    /// Unlike the mouse HID++ paths, this WRITES a stored keyboard setting (the
    /// backlight level persists, like DPI). It only runs when a caller has opted
    /// into MX Keys S support and issues an explicit request. Returns
    /// `Err(NotSupported)` when the feature is absent.
    ///
    /// `brightness` is a percent (clamped `0..=100`) mapped onto the device's
    /// discrete level range from getBacklightInfo. Packet layout and level
    /// mapping hardware-verified on MX Keys S (BACKLIGHT2 v3, 8 levels).
    pub fn set_backlight(&mut self, brightness: u8) -> Result<(), HapticError> {
        let feature_index = match self.backlight_feature_index() {
            Some(idx) => idx,
            None => {
                tracing::debug!("BACKLIGHT2 not available, cannot set backlight");
                return Err(HapticError::NotSupported);
            }
        };

        // Device levels are DISCRETE: getBacklightInfo reports numberOfLevel
        // (8 on MX Keys S, hardware-verified). Sending a raw percent as the
        // level is rejected with INVALID_ARGUMENT, so map percent onto
        // 0..=n-1. Older feature versions without getBacklightInfo fall back
        // to the MX Keys' 8 levels.
        let pct = brightness.min(100) as u32;
        let n_levels = self
            .query_backlight_info()
            .and_then(|info| info.first().copied())
            .filter(|&n| (2..=16).contains(&n))
            .unwrap_or(8) as u32;
        let level = ((pct * (n_levels - 1) + 50) / 100) as u8;

        // Preserve device-reported options + dim durations from a fresh read so
        // only brightness + mode change. Falls back to zeros if the read fails.
        let current = self.query_backlight_config();
        let mut options = current.as_ref().and_then(|c| c.get(1).copied()).unwrap_or(0);
        // Force the mode bits (3-4) to manual (0x3): clear then set.
        options = (options & !0x18) | (0x3 << 3);
        let (dho, dhi, dpow) = match current.as_ref() {
            // Payload offsets (Solaar V3 get layout): level=5, dho=6..8,
            // dhi=8..10, dpow=10..12.
            Some(c) if c.len() >= 12 => (
                u16::from_le_bytes([c[6], c[7]]),
                u16::from_le_bytes([c[8], c[9]]),
                u16::from_le_bytes([c[10], c[11]]),
            ),
            _ => (0u16, 0u16, 0u16),
        };

        // Always enabled=1: level 0 in manual mode turns the glow off, while
        // enabled=0 disables the whole backlight feature (hardware-verified
        // write sequence on MX Keys S).
        let enabled: u8 = 1;
        let params: [u8; 10] = [
            enabled,
            options,
            0xFF,
            level,
            (dho & 0xFF) as u8,
            (dho >> 8) as u8,
            (dhi & 0xFF) as u8,
            (dhi >> 8) as u8,
            (dpow & 0xFF) as u8,
            (dpow >> 8) as u8,
        ];

        tracing::info!(
            feature_index,
            brightness = level,
            options = format!("0x{:02X}", options),
            "Setting keyboard backlight"
        );

        match self.hidpp_long_request(feature_index, 0x01, &params) {
            Some(_) => Ok(()),
            None => {
                tracing::warn!("Backlight set returned no response (firmware may reject this layout)");
                Err(HapticError::CommunicationError)
            }
        }
    }

    // =========================================================================
    // Easy-Switch Methods
    // =========================================================================

    /// Get host names for Easy-Switch slots using HID++ 0x1815 (HOSTS_INFO)
    ///
    /// This is a READ-ONLY operation that retrieves the friendly names of
    /// paired hosts. It does NOT write to device memory.
    pub fn get_host_names(&mut self) -> Vec<String> {
        // Query HOSTS_INFO feature (0x1815) directly using IRoot
        // This bypasses the blocklist check since we only READ, never WRITE
        let hosts_info_index = match self.get_feature_index(features::HOSTS_INFO) {
            Some(idx) => idx,
            None => {
                tracing::debug!("HOSTS_INFO feature (0x1815) not supported on this device");
                return Vec::new();
            }
        };

        tracing::debug!(index = hosts_info_index, "Found HOSTS_INFO feature");

        // Function 0x00: getHostInfo - get number of hosts and capabilities
        let resp = match self.hidpp_request(hosts_info_index, 0x00, &[]) {
            Some(r) => r,
            None => {
                tracing::debug!("Failed to get host info");
                return Vec::new();
            }
        };

        if resp.len() < 6 {
            return Vec::new();
        }

        // Response: [4]=capability_flags, [5]=numHosts, [6]=currentHost
        let num_hosts = resp[5];
        let _current_host = resp[6];
        tracing::debug!(num_hosts, "Got host count from device");

        let mut host_names = Vec::new();

        // Get name for each host slot.
        // Device may report max capacity (e.g. 8) but only 3 slots are real.
        // Break on first failed slot to avoid noisy HID++ error log spam.
        for host_idx in 0..num_hosts {
            // Function 0x01: getHostDescriptor - get status and name length
            let resp = match self.hidpp_request(hosts_info_index, 0x01, &[host_idx, 0, 0]) {
                Some(r) => r,
                None => {
                    // Non-existent slot - no more valid hosts
                    break;
                }
            };

            if resp.len() < 9 {
                host_names.push(String::new());
                continue;
            }

            // Response: [4]=host, [5]=busType, [6]=flags, [7]=status, [8]=nameLen, [9]=maxNameLen
            let name_len = resp[8] as usize;
            if name_len == 0 {
                host_names.push(String::new());
                continue;
            }

            // Function 0x03: getHostFriendlyName - get actual name (chunked, 14 bytes per call)
            let mut name_bytes = Vec::new();
            let mut offset = 0u8;

            while (offset as usize) < name_len {
                let resp = match self.hidpp_request(hosts_info_index, 0x03, &[host_idx, offset, 0]) {
                    Some(r) => r,
                    None => break,
                };

                if resp.len() < 6 {
                    break;
                }

                // Response: [4]=host, [5]=offset, [6..20]=name (up to 14 bytes)
                let chunk_start = 6;
                let chunk_len = std::cmp::min(14, name_len - offset as usize);
                if resp.len() >= chunk_start + chunk_len {
                    name_bytes.extend_from_slice(&resp[chunk_start..chunk_start + chunk_len]);
                }

                offset += 14;
            }

            // Convert to string, trimming null bytes
            let name = String::from_utf8_lossy(&name_bytes)
                .trim_end_matches('\0')
                .to_string();

            tracing::debug!(host = host_idx, name = %name, "Got host name");
            host_names.push(name);
        }

        host_names
    }

    /// Get Easy-Switch info: (num_hosts, current_host)
    pub fn get_easy_switch_info(&mut self) -> Option<(u8, u8)> {
        // Query CHANGE_HOST feature (0x1814)
        let change_host_index = self.get_feature_index(features::CHANGE_HOST)?;

        // Function 0: getHostInfo
        let resp = self.hidpp_request(change_host_index, 0x00, &[])?;

        if resp.len() < 6 {
            return None;
        }

        // Response: [4]=numHosts, [5]=currentHost
        let num_hosts = resp[4];
        let current_host = resp[5];

        Some((num_hosts, current_host))
    }

    /// Switch to a different paired host (Easy-Switch)
    pub fn set_current_host(&mut self, host_index: u8) -> Result<(), String> {
        // Query CHANGE_HOST feature (0x1814)
        let change_host_index = self.get_feature_index(features::CHANGE_HOST)
            .ok_or_else(|| "CHANGE_HOST feature (0x1814) not supported".to_string())?;

        // Validate host_index (typically 0, 1, or 2)
        if host_index > 2 {
            return Err(format!("Invalid host_index: {}. Must be 0, 1, or 2", host_index));
        }

        tracing::info!(host_index, "Switching to Easy-Switch host slot");

        // Function 0x01: setCurrentHost with param = host_index
        let resp = self.hidpp_request(change_host_index, 0x01, &[host_index]);

        match resp {
            Some(_) => {
                tracing::info!(host_index, "Successfully sent host switch command");
                Ok(())
            }
            None => {
                // Note: The device may disconnect before sending a response
                // when switching hosts, so a missing response might still mean success
                tracing::warn!(host_index, "No response from host switch command (device may have disconnected)");
                Ok(())
            }
        }
    }
}

#[cfg(test)]
mod button_divert_tests {
    use std::collections::VecDeque;

    use super::*;

    #[derive(Debug, PartialEq)]
    struct Request {
        feature_index: u8,
        function: u8,
        params: Vec<u8>,
    }

    #[derive(Default)]
    struct MockButtonDivertIo {
        short_responses: VecDeque<Option<Vec<u8>>>,
        long_responses: VecDeque<Option<Vec<u8>>>,
        short_requests: Vec<Request>,
        long_requests: Vec<Request>,
    }

    impl ButtonDivertIo for MockButtonDivertIo {
        fn short_request(
            &mut self,
            feature_index: u8,
            function: u8,
            params: &[u8],
        ) -> Option<Vec<u8>> {
            self.short_requests.push(Request {
                feature_index,
                function,
                params: params.to_vec(),
            });
            self.short_responses.pop_front().flatten()
        }

        fn long_request(
            &mut self,
            feature_index: u8,
            function: u8,
            params: &[u8],
        ) -> Option<Vec<u8>> {
            self.long_requests.push(Request {
                feature_index,
                function,
                params: params.to_vec(),
            });
            self.long_responses.pop_front().flatten()
        }
    }

    fn count_response(count: u8) -> Vec<u8> {
        let mut response = vec![0; 5];
        response[4] = count;
        response
    }

    fn control_response(cid: u16, flags: u8) -> Vec<u8> {
        let mut response = vec![0; 9];
        response[4] = (cid >> 8) as u8;
        response[5] = (cid & 0xFF) as u8;
        response[8] = flags;
        response
    }

    #[test]
    fn list_controls_decodes_every_index_and_skips_bad_replies() {
        let mut io = MockButtonDivertIo {
            short_responses: VecDeque::from(vec![
                Some(count_response(3)),
                Some(control_response(0x00C3, 0x31)),
                None,
                Some(control_response(0x01A0, 0x20)),
            ]),
            ..Default::default()
        };
        let controls = list_controls_with_io(&mut io, 0x0B);
        assert_eq!(controls.iter().map(|c| c.cid).collect::<Vec<_>>(), vec![0x00C3, 0x01A0]);
        assert!(controls[0].divertable() && controls[0].mouse_button());
        assert_eq!(io.short_requests.len(), 4);
        assert_eq!(io.short_requests[1].params, vec![0, 0, 0]);
        assert_eq!(io.short_requests[3].params, vec![2, 0, 0]);
        assert!(io.long_requests.is_empty(), "the inventory scan must never write");
    }

    #[test]
    fn receiver_errors_are_recognised_only_for_our_device() {
        // 10 01 8F 00 0D 04 00: receiver says device 1 is paired but not linked
        let parked = [0x10, 0x01, 0x8F, 0x00, 0x0D, 0x04, 0x00];
        assert_eq!(receiver_error_code(&parked, 1), Some(RECEIVER_ERR_CONNECT_FAIL));
        assert_eq!(receiver_error_code(&parked, 2), None);
        let mouse_motion = [0x02, 0x01, 0x8F, 0x00, 0x0D, 0x04, 0x00];
        assert_eq!(receiver_error_code(&mouse_motion, 1), None);
        assert_eq!(receiver_error_code(&parked[..5], 1), None);
    }

    #[test]
    fn unit_id_is_read_big_endian_and_zero_means_none() {
        let reply = [0x11, 0x02, 0x03, 0x01, 0x03, 0x12, 0x34, 0xAB, 0xCD, 0x00, 0x03];
        assert_eq!(parse_unit_id(&reply), Some(0x1234ABCD));
        assert_eq!(parse_unit_id(&[0x11, 0x02, 0x03, 0x01, 0x03, 0, 0, 0, 0]), None);
        assert_eq!(parse_unit_id(&reply[..8]), None);
    }

    #[test]
    fn unified_battery_percent_falls_back_to_level_flags() {
        assert_eq!(unified_battery_percent(73, 0x04), 73);
        assert_eq!(unified_battery_percent(0, 0x08), 90);
        assert_eq!(unified_battery_percent(0, 0x04), 55);
        assert_eq!(unified_battery_percent(0, 0x02), 20);
        assert_eq!(unified_battery_percent(0, 0x01), 5);
        assert_eq!(unified_battery_percent(0, 0x00), 0);
    }

    #[test]
    fn list_controls_without_count_is_empty() {
        let mut io = MockButtonDivertIo::default();
        assert!(list_controls_with_io(&mut io, 0x0B).is_empty());
    }

    #[test]
    fn batch_divert_scans_controls_once_and_returns_only_successful_cids() {
        let mut io = MockButtonDivertIo {
            short_responses: VecDeque::from([
                Some(count_response(4)),
                Some(control_response(0x0050, 0x20)),
                Some(control_response(0x0051, 0x20)),
                Some(control_response(0x0052, 0x00)),
                None,
            ]),
            long_responses: VecDeque::from([Some(vec![0; 9]), None]),
            ..Default::default()
        };

        let diverted =
            set_button_diverts_with_io(&mut io, 0x0A, &[0x0050, 0x0051, 0x0052, 0x0050], true);

        assert_eq!(diverted, vec![0x0050]);
        assert_eq!(io.short_requests.len(), 5);
        assert_eq!(io.short_requests[0].function, 0x00);
        assert_eq!(
            io.short_requests[1..]
                .iter()
                .map(|request| request.params.clone())
                .collect::<Vec<_>>(),
            vec![vec![0, 0, 0], vec![1, 0, 0], vec![2, 0, 0], vec![3, 0, 0]]
        );
        assert_eq!(
            io.long_requests,
            vec![
                Request {
                    feature_index: 0x0A,
                    function: 0x03,
                    params: vec![0x00, 0x50, 0x03, 0x00, 0x00],
                },
                Request {
                    feature_index: 0x0A,
                    function: 0x03,
                    params: vec![0x00, 0x51, 0x03, 0x00, 0x00],
                },
            ]
        );
    }

    #[test]
    fn batch_divert_stops_when_control_count_is_unavailable() {
        let mut io = MockButtonDivertIo {
            short_responses: VecDeque::from([None]),
            ..Default::default()
        };

        let diverted = set_button_diverts_with_io(&mut io, 0x0A, &[0x0050], true);

        assert!(diverted.is_empty());
        assert_eq!(io.short_requests.len(), 1);
        assert!(io.long_requests.is_empty());
    }

    #[test]
    fn batch_divert_skips_io_for_an_empty_request() {
        let mut io = MockButtonDivertIo::default();

        let diverted = set_button_diverts_with_io(&mut io, 0x0A, &[], true);

        assert!(diverted.is_empty());
        assert!(io.short_requests.is_empty());
        assert!(io.long_requests.is_empty());
    }
}
