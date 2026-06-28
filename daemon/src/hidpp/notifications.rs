//! Decoders for device-originated HID++ notifications (live hardware readback)
//!
//! A HID++ report whose function/software-id byte has a low nibble of zero
//! (`data[3] & 0x0F == 0`) is a SPONTANEOUS device event, not a response to a
//! method we issued. These carry live hardware state changes (battery, host,
//! DPI, ratchet) that we surface as D-Bus change signals so the UI updates
//! without polling.
//!
//! Routing is by FEATURE INDEX: the same feature has a different index on each
//! device, so the indices are discovered at connect time (see
//! `HapticManager::notification_indices`) and matched here.
//!
//! SPDX-License-Identifier: GPL-3.0

/// A decoded live hardware-state change.
///
/// `status` is a `&'static str` (not `String`) so the whole enum stays `Copy`,
/// which lets it ride the existing `GestureEvent` channel without changing that
/// enum's `Copy` derive.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HardwareNotification {
    /// Battery state of charge changed (UNIFIED_BATTERY 0x1004).
    BatteryChanged { percent: u8, status: &'static str },
    /// Scroll-wheel ratchet engaged/disengaged (HiResWheel 0x2121).
    RatchetChanged { ratchet: bool },
    /// Active Easy-Switch host slot changed (CHANGE_HOST 0x1814).
    HostChanged { host: u8 },
    /// Pointer DPI changed (ADJUSTABLE_DPI 0x2201).
    DpiChanged { dpi: u16 },
}

/// Feature indices for the notification-bearing features on the connected
/// device. `None` means the feature is absent (or not yet discovered), in which
/// case it never matches an incoming report.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NotificationIndices {
    pub battery: Option<u8>,
    pub change_host: Option<u8>,
    pub dpi: Option<u8>,
    pub hires_wheel: Option<u8>,
}

impl NotificationIndices {
    /// Route a spontaneous report (already gated on `sw_id == 0`) to the decoder
    /// for whichever feature owns `feature_index`. Returns `None` if the index
    /// is not one of the tracked notification features.
    pub fn route(&self, feature_index: u8, data: &[u8]) -> Option<HardwareNotification> {
        if self.battery == Some(feature_index) {
            return decode_battery(data);
        }
        if self.change_host == Some(feature_index) {
            return decode_host(data);
        }
        if self.dpi == Some(feature_index) {
            return decode_dpi(data);
        }
        if self.hires_wheel == Some(feature_index) {
            return decode_ratchet(data);
        }
        None
    }
}

/// Map a UNIFIED_BATTERY charging-status byte to a stable string label.
///
/// Values match the Linux kernel hid-logitech-hidpp unified-battery driver:
/// 0 = discharging, 1 = charging, 2 = charging (slow), 3 = full (complete),
/// 4 = error/not charging.
fn battery_status_label(status: u8) -> &'static str {
    match status {
        0 => "discharging",
        1 | 2 => "charging",
        3 => "full",
        4 => "not_charging",
        _ => "unknown",
    }
}

/// UNIFIED_BATTERY 0x1004 event: `[percent, level, status, ...]` in the HID++
/// payload starting at byte 4.
fn decode_battery(data: &[u8]) -> Option<HardwareNotification> {
    if data.len() < 7 {
        return None;
    }
    let percent = data[4];
    let status = battery_status_label(data[6]);
    Some(HardwareNotification::BatteryChanged { percent, status })
}

/// CHANGE_HOST 0x1814 event: new active host slot in byte 4 (0-based).
fn decode_host(data: &[u8]) -> Option<HardwareNotification> {
    if data.len() < 5 {
        return None;
    }
    Some(HardwareNotification::HostChanged { host: data[4] })
}

/// ADJUSTABLE_DPI 0x2201 event: DPI as a big-endian u16 in bytes 4..5.
fn decode_dpi(data: &[u8]) -> Option<HardwareNotification> {
    if data.len() < 6 {
        return None;
    }
    let dpi = ((data[4] as u16) << 8) | (data[5] as u16);
    if dpi == 0 {
        return None;
    }
    Some(HardwareNotification::DpiChanged { dpi })
}

/// HiResWheel 0x2121 `ratchetSwitchChanged` event: byte 4 bit 0 = ratchet
/// engaged (1) vs free-spin (0).
fn decode_ratchet(data: &[u8]) -> Option<HardwareNotification> {
    if data.len() < 5 {
        return None;
    }
    Some(HardwareNotification::RatchetChanged {
        ratchet: (data[4] & 0x01) != 0,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(feature_index: u8, payload: &[u8]) -> Vec<u8> {
        // [report_type, device_index, feature_index, sw_id, payload...]
        let mut v = vec![0x11, 0x01, feature_index, 0x00];
        v.extend_from_slice(payload);
        v
    }

    #[test]
    fn routes_battery_by_index() {
        let idx = NotificationIndices { battery: Some(0x06), ..Default::default() };
        let r = report(0x06, &[55, 0, 1]);
        assert_eq!(
            idx.route(0x06, &r),
            Some(HardwareNotification::BatteryChanged { percent: 55, status: "charging" })
        );
    }

    #[test]
    fn routes_host_change() {
        let idx = NotificationIndices { change_host: Some(0x09), ..Default::default() };
        let r = report(0x09, &[2]);
        assert_eq!(idx.route(0x09, &r), Some(HardwareNotification::HostChanged { host: 2 }));
    }

    #[test]
    fn routes_dpi_big_endian() {
        let idx = NotificationIndices { dpi: Some(0x0a), ..Default::default() };
        let r = report(0x0a, &[0x03, 0xE8]); // 1000
        assert_eq!(idx.route(0x0a, &r), Some(HardwareNotification::DpiChanged { dpi: 1000 }));
    }

    #[test]
    fn routes_ratchet_bit() {
        let idx = NotificationIndices { hires_wheel: Some(0x05), ..Default::default() };
        assert_eq!(
            idx.route(0x05, &report(0x05, &[0x01])),
            Some(HardwareNotification::RatchetChanged { ratchet: true })
        );
        assert_eq!(
            idx.route(0x05, &report(0x05, &[0x00])),
            Some(HardwareNotification::RatchetChanged { ratchet: false })
        );
    }

    #[test]
    fn unknown_index_is_ignored() {
        let idx = NotificationIndices { battery: Some(0x06), ..Default::default() };
        assert_eq!(idx.route(0x07, &report(0x07, &[1, 2, 3])), None);
    }

    #[test]
    fn none_index_never_matches() {
        let idx = NotificationIndices::default();
        assert_eq!(idx.route(0x00, &report(0x00, &[1, 2, 3])), None);
    }

    #[test]
    fn battery_status_labels() {
        assert_eq!(battery_status_label(0), "discharging");
        assert_eq!(battery_status_label(1), "charging");
        assert_eq!(battery_status_label(2), "charging");
        assert_eq!(battery_status_label(3), "full");
        assert_eq!(battery_status_label(4), "not_charging");
        assert_eq!(battery_status_label(9), "unknown");
    }
}
