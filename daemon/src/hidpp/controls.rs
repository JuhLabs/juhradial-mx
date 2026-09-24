//! REPROG_CONTROLS_V4 (0x1B04) control inventory.
//!
//! `getCidInfo` describes every remappable control the device exposes: its
//! control id (CID), task id, and capability flags. The daemon keeps that list
//! per connection so Settings can build the button page from what the mouse
//! actually has (side buttons on an MX Anywhere, the DPI switch on an MX
//! Vertical) instead of a fixed MX Master table, and so any divertable control
//! can carry a configured action (`buttons.controls` in config.json).

use serde::Serialize;

/// One control as reported by `getCidInfo`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ControlInfo {
    pub cid: u16,
    pub task_id: u16,
    /// bit 0 mouse button, 1 F-key, 2 hot key, 3 Fn toggle, 4 reprogrammable,
    /// 5 divertable, 6 persistently divertable, 7 virtual.
    pub flags: u8,
    pub position: u8,
    pub group: u8,
    pub group_mask: u8,
    /// bit 0 raw XY, 1 force raw XY, 2 analytics key events.
    pub additional: u8,
}

impl ControlInfo {
    /// Decode a `getCidInfo` reply (the whole report, CID at bytes 4-5).
    /// Older firmware answers with a short report that stops at the flags
    /// byte; the position, group and additional bytes are then zero.
    pub fn from_report(resp: &[u8]) -> Option<Self> {
        if resp.len() < 9 {
            return None;
        }
        let at = |i: usize| resp.get(i).copied().unwrap_or(0);
        Some(Self {
            cid: ((resp[4] as u16) << 8) | resp[5] as u16,
            task_id: ((resp[6] as u16) << 8) | resp[7] as u16,
            flags: resp[8],
            position: at(9),
            group: at(10),
            group_mask: at(11),
            additional: at(12),
        })
    }

    pub fn mouse_button(&self) -> bool { self.flags & 0x01 != 0 }
    pub fn f_key(&self) -> bool { self.flags & 0x02 != 0 }
    pub fn hot_key(&self) -> bool { self.flags & 0x04 != 0 }
    pub fn fn_toggle(&self) -> bool { self.flags & 0x08 != 0 }
    pub fn reprogrammable(&self) -> bool { self.flags & 0x10 != 0 }
    pub fn divertable(&self) -> bool { self.flags & 0x20 != 0 }
    pub fn persistently_divertable(&self) -> bool { self.flags & 0x40 != 0 }
    pub fn is_virtual(&self) -> bool { self.flags & 0x80 != 0 }
    pub fn raw_xy(&self) -> bool { self.additional & 0x01 != 0 }

    /// Human name for well-known CIDs, else `Control 0xNNNN`.
    pub fn name(&self) -> String {
        control_name(self.cid)
            .map(str::to_string)
            .unwrap_or_else(|| format!("Control 0x{:04X}", self.cid))
    }
}

/// Names for the CIDs Logitech reuses across the MX line (the HID++ 2.0
/// control id table as documented by Solaar and logiops). Unknown ids keep
/// their hex form so nothing is mislabelled.
pub fn control_name(cid: u16) -> Option<&'static str> {
    Some(match cid {
        0x0050 => "Left Click",
        0x0051 => "Right Click",
        0x0052 => "Middle Button",
        0x0053 => "Back",
        0x0056 => "Forward",
        0x005B => "Left Scroll",
        0x005D => "Right Scroll",
        0x00C3 => "Gesture Button",
        0x00C4 => "SmartShift",
        0x00D7 => "Virtual Gesture Button",
        0x00FD => "DPI Switch",
        0x01A0 => "Actions Ring Button",
        _ => return None,
    })
}

/// JSON document for the D-Bus `ListControls` reply: one object per control
/// with the decoded capability bits, so clients need no HID++ knowledge.
pub fn controls_to_json(controls: &[ControlInfo]) -> String {
    let items: Vec<serde_json::Value> = controls
        .iter()
        .map(|c| {
            serde_json::json!({
                "cid": c.cid,
                "hex": format!("0x{:04X}", c.cid),
                "name": c.name(),
                "task_id": c.task_id,
                "mouse_button": c.mouse_button(),
                "f_key": c.f_key(),
                "hot_key": c.hot_key(),
                "reprogrammable": c.reprogrammable(),
                "divertable": c.divertable(),
                "persistently_divertable": c.persistently_divertable(),
                "virtual": c.is_virtual(),
                "raw_xy": c.raw_xy(),
                "group": c.group,
                "group_mask": c.group_mask,
            })
        })
        .collect();
    serde_json::Value::Array(items).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(cid: u16, tid: u16, flags: u8, extra: &[u8]) -> Vec<u8> {
        let mut r = vec![0x11, 0x01, 0x05, 0x10, (cid >> 8) as u8, cid as u8, (tid >> 8) as u8, tid as u8, flags];
        r.extend_from_slice(extra);
        r
    }

    #[test]
    fn decodes_a_long_get_cid_info_reply() {
        let c = ControlInfo::from_report(&report(0x00C3, 0x00B4, 0x31, &[3, 2, 0x03, 0x01])).unwrap();
        assert_eq!((c.cid, c.task_id, c.flags), (0x00C3, 0x00B4, 0x31));
        assert_eq!((c.position, c.group, c.group_mask, c.additional), (3, 2, 0x03, 0x01));
        assert!(c.mouse_button() && c.reprogrammable() && c.divertable() && c.raw_xy());
        assert!(!c.is_virtual() && !c.f_key());
        assert_eq!(c.name(), "Gesture Button");
    }

    #[test]
    fn short_replies_and_unknown_ids_still_decode() {
        let c = ControlInfo::from_report(&report(0x0123, 0, 0xA0, &[])).unwrap();
        assert!(c.is_virtual() && c.divertable());
        assert_eq!((c.position, c.additional), (0, 0));
        assert_eq!(c.name(), "Control 0x0123");
        assert!(ControlInfo::from_report(&[0; 8]).is_none());
    }

    #[test]
    fn json_carries_decoded_bits_and_hex_ids() {
        let c = ControlInfo::from_report(&report(0x01A0, 1, 0x20, &[0, 0, 0, 0])).unwrap();
        let v: serde_json::Value = serde_json::from_str(&controls_to_json(&[c])).unwrap();
        assert_eq!(v[0]["hex"], "0x01A0");
        assert_eq!(v[0]["name"], "Actions Ring Button");
        assert_eq!(v[0]["divertable"], true);
        assert_eq!(v[0]["mouse_button"], false);
        assert_eq!(controls_to_json(&[]), "[]");
    }
}
