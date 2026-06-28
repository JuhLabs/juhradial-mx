//! Static device descriptor table for known Logitech HID++ mice.
//!
//! Maps a USB/Bluetooth product ID to a human-readable model name and a hint
//! about which transports the PID is used on. This is a clean-room data table
//! built from publicly known Logitech product IDs; it is intentionally minimal
//! and falls back to a generic descriptor for unknown devices so discovery
//! never fails on an unrecognized PID.

use crate::hidpp::constants::product_ids;

/// Transport hint for a known product ID.
///
/// Some PIDs are shared across transports (the MX Master 4 and 3S report the
/// same direct-mode PID on both USB and Bluetooth), so the hint records every
/// transport the PID can legitimately appear on. The actual transport is still
/// decided from the HID bus id at discovery time; this is only metadata.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConnectionHint {
    /// Direct cable only (PID seen exclusively on the USB bus).
    UsbOnly,
    /// Direct cable or Bluetooth (PID shared across both buses).
    UsbOrBluetooth,
    /// A receiver dongle (Bolt/Unifying); paired devices sit behind it.
    Receiver,
    /// Transport unknown (fallback descriptor).
    Unknown,
}

/// A single device descriptor entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeviceDescriptor {
    /// USB/Bluetooth product ID.
    pub product_id: u16,
    /// Human-readable model name.
    pub model: &'static str,
    /// Which transports this PID is used on.
    pub connection_hint: ConnectionHint,
}

/// Fallback descriptor for product IDs not present in [`TABLE`].
pub const FALLBACK: DeviceDescriptor = DeviceDescriptor {
    product_id: 0x0000,
    model: "Logitech HID++ device",
    connection_hint: ConnectionHint::Unknown,
};

/// Known Logitech mice and receivers relevant to this daemon.
pub const TABLE: &[DeviceDescriptor] = &[
    DeviceDescriptor {
        product_id: product_ids::MX_MASTER_4_USB,
        model: "MX Master 4",
        connection_hint: ConnectionHint::UsbOrBluetooth,
    },
    DeviceDescriptor {
        product_id: product_ids::MX_MASTER_4_BOLT,
        model: "Logitech Bolt receiver",
        connection_hint: ConnectionHint::Receiver,
    },
    DeviceDescriptor {
        product_id: product_ids::UNIFYING_RECEIVER,
        model: "Logitech Unifying receiver",
        connection_hint: ConnectionHint::Receiver,
    },
    // MX Master 3S direct mode (USB cable or Bluetooth), shares behaviour with
    // the MX Master 4 over HID++ 2.0.
    DeviceDescriptor {
        product_id: 0xB023,
        model: "MX Master 3S",
        connection_hint: ConnectionHint::UsbOrBluetooth,
    },
    // MX Master 3 direct mode.
    DeviceDescriptor {
        product_id: 0xB022,
        model: "MX Master 3",
        connection_hint: ConnectionHint::UsbOrBluetooth,
    },
];

/// Look up the descriptor for a product ID, returning the fallback when unknown.
pub fn lookup(product_id: u16) -> DeviceDescriptor {
    TABLE
        .iter()
        .find(|d| d.product_id == product_id)
        .copied()
        .unwrap_or(FALLBACK)
}

/// Parse the product ID out of a sysfs `uevent` string.
///
/// The relevant line looks like `HID_ID=0005:0000046D:0000B034`, where the
/// final field is the product ID in uppercase hex. Returns `None` if the field
/// is missing or unparseable.
pub fn product_id_from_uevent(uevent: &str) -> Option<u16> {
    let line = uevent.lines().find(|l| l.starts_with("HID_ID="))?;
    let last = line.rsplit(':').next()?;
    u16::from_str_radix(last.trim().get(last.trim().len().saturating_sub(4)..)?, 16).ok()
}

/// Look up the descriptor implied by a sysfs `uevent` string.
pub fn lookup_from_uevent(uevent: &str) -> DeviceDescriptor {
    match product_id_from_uevent(uevent) {
        Some(pid) => lookup(pid),
        None => FALLBACK,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_known_pid_lookup() {
        let mx4 = lookup(product_ids::MX_MASTER_4_USB);
        assert_eq!(mx4.model, "MX Master 4");
        assert_eq!(mx4.connection_hint, ConnectionHint::UsbOrBluetooth);
    }

    #[test]
    fn test_unknown_pid_falls_back() {
        let d = lookup(0x1234);
        assert_eq!(d.model, FALLBACK.model);
        assert_eq!(d.connection_hint, ConnectionHint::Unknown);
    }

    #[test]
    fn test_product_id_from_uevent() {
        let uevent = "DRIVER=hid-logitech\nHID_ID=0005:0000046D:0000B034\nMODALIAS=hid:...";
        assert_eq!(product_id_from_uevent(uevent), Some(0xB034));
        assert_eq!(lookup_from_uevent(uevent).model, "MX Master 4");
    }

    #[test]
    fn test_uevent_without_hid_id() {
        let uevent = "DRIVER=hid-logitech\nMODALIAS=hid:...";
        assert_eq!(product_id_from_uevent(uevent), None);
        assert_eq!(lookup_from_uevent(uevent).model, FALLBACK.model);
    }

    #[test]
    fn test_mx3s_distinct_from_mx4() {
        assert_eq!(lookup(0xB023).model, "MX Master 3S");
        assert_eq!(lookup(0xB022).model, "MX Master 3");
    }
}
