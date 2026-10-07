//! Every parser that reads bytes a mouse, a keyboard or a receiver sent.
//! A device (or whatever answers on its hidraw node) chooses these bytes, so
//! none of them may panic, whatever arrives.
#![no_main]

use juhradiald::hidpp::controls::ControlInfo;
use juhradiald::hidpp::notifications::NotificationIndices;
use juhradiald::hidpp::{device, HidppLongMessage, HidppShortMessage};
use juhradiald::keyboard;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = HidppShortMessage::from_bytes(data);
    let _ = HidppLongMessage::from_bytes(data);
    let _ = ControlInfo::from_report(data);
    let _ = device::parse_firmware_entity(data);
    for bolt in [false, true] {
        let _ = device::parse_pairing_kind(bolt, data);
        let _ = device::parse_pairing_info(bolt, data);
        let _ = device::parse_codename(bolt, data);
    }
    let _ = device::parse_hosts_info(data);
    let _ = device::parse_host_descriptor(data);
    let _ = device::decode_unified_status(data);
    let _ = device::DpiCaps::parse(data);

    // The first byte picks a slot, a feature index and where a reply pair splits.
    let Some((&pick, rest)) = data.split_first() else { return };
    let (first, second) = rest.split_at(usize::from(pick).min(rest.len()));
    let _ = device::parse_backlight(rest, None);
    let _ = device::parse_backlight(first, Some(second));
    let _ = device::ForceSense::parse(first, second);
    let _ = keyboard::link_up_in_report(rest, pick);
    let _ = keyboard::host_switch_in_report(rest, pick & 0x0f, pick >> 4);
    let _ = keyboard::backlight_in_report(rest, pick & 0x0f, pick >> 4);

    // A notification of one of the features the mouse reports unprompted.
    let mut indices = NotificationIndices::default();
    match pick % 5 {
        0 => indices.battery = Some(pick),
        1 => indices.change_host = Some(pick),
        2 => indices.dpi = Some(pick),
        3 => indices.hires_wheel = Some(pick),
        _ => indices.wireless_status = Some(pick),
    }
    let _ = indices.route(pick, rest);
});
