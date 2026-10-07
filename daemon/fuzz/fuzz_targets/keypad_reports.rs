//! What the MX Keypad sends (key and page-button reports), the HID report
//! descriptor read from sysfs during discovery, and the image packets built
//! for it.
#![no_main]

use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = mx_keypad::parse_input(data);
    let _ = mx_keypad::has_vendor_usage_page(data);
    if let [x, y, w, h, jpeg @ ..] = data {
        // Whatever the window, a packet is one full report and never empty-handed.
        if let Ok(packets) = mx_keypad::image_packets((*x).into(), (*y).into(), (*w).into(), (*h).into(), jpeg) {
            assert!(!packets.is_empty());
        }
    }
});
