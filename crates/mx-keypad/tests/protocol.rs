use mx_keypad::*;

#[test]
fn geometry_and_single_packet_exact_bytes() {
    assert_eq!(KeyWindow::new(1), Some(KeyWindow { x: 23, y: 6, w: 118, h: 118 }));
    assert_eq!(KeyWindow::new(9), Some(KeyWindow { x: 339, y: 322, w: 118, h: 118 }));
    assert!(KeyWindow::new(0).is_none());
    assert!(KeyWindow::new(10).is_none());
    let p = image_packets(339, 322, 118, 118, &[0xff, 0xd8, 0xff, 0xd9]).unwrap();
    assert_eq!(p.len(), 1);
    assert_eq!(p[0].len(), 4095);
    assert_eq!(&p[0][..24], &[0x14, 0xff, 2, 0x2b, 0xe1, 1, 0, 1, 0,
        1, 0x53, 1, 0x42, 0, 118, 0, 118, 0, 0, 4, 0xff, 0xd8, 0xff, 0xd9]);
    assert!(p[0][24..].iter().all(|b| *b == 0));
}

#[test]
fn splitting_flags_and_lengths() {
    for len in [4075, 4076, 8165, 8166, 65535] {
        let jpeg: Vec<u8> = (0..len).map(|n| (n % 251) as u8).collect();
        let p = image_packets(0, 0, 480, 480, &jpeg).unwrap();
        let mut joined = Vec::new();
        for (i, packet) in p.iter().enumerate() {
            let flags = (i + 1) as u8 | 0x20 | if i == 0 { 0x80 } else { 0 }
                | if i == p.len() - 1 { 0x40 } else { 0 };
            assert_eq!(&packet[..5], &[0x14, 0xff, 2, 0x2b, flags]);
            joined.extend_from_slice(&packet[if i == 0 { 20 } else { 5 }..]);
        }
        assert_eq!(&p[0][18..20], &(len as u16).to_be_bytes());
        assert_eq!(&joined[..len], jpeg);
        assert!(joined[len..].iter().all(|b| *b == 0));
    }
    assert!(image_packets(0, 0, 118, 118, &[]).is_err());
    assert!(image_packets(0, 0, 118, 118, &vec![1; 65536]).is_err());
    assert!(image_packets(470, 0, 118, 118, &[1]).is_err());
}

#[test]
fn input_sets_diff_and_page_reports() {
    let Some(Input::Keys(keys)) = parse_input(&[0x13, 0xff, 2, 0, 7, 1, 1, 3, 9, 0]) else { panic!() };
    assert_eq!(keys.iter().collect::<Vec<_>>(), [1, 3, 9]);
    assert_eq!(keys.diff(KeySet::default()).down, [1, 3, 9]);
    let Some(Input::Keys(next)) = parse_input(&[0x13, 0xff, 2, 0, 0, 1, 3, 0]) else { panic!() };
    assert_eq!(next.diff(keys).up, [1, 9]);
    assert!(next.diff(keys).down.is_empty());
    assert_eq!(parse_input(&[0x11, 0xff, 0x0b, 0, 1, 0xa1, 1, 0xa2, 0, 0]),
        Some(Input::Pages(vec![PageButton::Left, PageButton::Right])));
    assert_eq!(parse_input(&[0x11, 0xff, 0x0b, 0, 0, 0]), Some(Input::Pages(vec![])));
    // An image ack as the device sends it (captured on hardware): a burst of
    // animation frames must never read as "every key released".
    for bad in [&[0x13, 0xff, 0x2b][..], &[0x13, 0xff, 2, 0x2b, 0xc1, 0, 0, 0], &[],
        &[0x13, 0xff, 2, 0, 0, 1, 10, 0], &[0x13, 0xff, 2, 0, 0, 1, 1], &[0x11, 0xff, 0x0b, 0, 1]] {
        assert_eq!(parse_input(bad), None);
    }
}

#[test]
fn allowed_control_vectors_and_brightness_builder() {
    // Both page buttons are diverted (left 0x01a1, right 0x01a2), as in the
    // reference driver's two active init writes.
    let mut left = [0; 20];
    left[..7].copy_from_slice(&[0x11, 0xff, 0x0b, 0x3b, 1, 0xa1, 3]);
    let mut right = left;
    right[5] = 0xa2;
    assert_eq!(init_reports(), [left, right]);
    let mut reset = [0; 32];
    reset[..2].copy_from_slice(&[3, 2]);
    assert_eq!(reset_to_logo_report(), reset);
    let mut brightness = [0; 20];
    brightness[..6].copy_from_slice(&[0x11, 0xff, 0x0f, 0x2b, 0, 42]);
    assert_eq!(brightness_report(42).unwrap(), brightness);
    assert!(brightness_report(0).is_err());
    assert!(brightness_report(101).is_err());
}

#[test]
fn descriptor_matches_usage_items_not_embedded_bytes() {
    assert!(has_vendor_usage_page(&[0x06, 0x43, 0xff, 0x09, 1]));
    assert!(has_vendor_usage_page(&[0x07, 0x43, 0xff, 0, 0]));
    assert!(!has_vendor_usage_page(&[0x75, 8, 0x09, 6, 0x09, 0x43, 0x09, 0xff]));
    assert!(!has_vendor_usage_page(&[0xfe, 3, 1, 0x06, 0x43, 0xff]));
    assert!(!has_vendor_usage_page(&[0x06, 0x43]));
}

#[test]
fn discovery_requires_identity_and_vendor_interface_for_usb_and_bluetooth() {
    let root = std::env::temp_dir().join(format!("keypad-discovery-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    for (node, id, descriptor) in [
        ("hidraw1", "0003:0000046D:0000C354", &[6, 0x43, 0xff][..]),
        ("hidraw2", "0005:0000046d:0000c354", &[6, 0x43, 0xff][..]),
        ("hidraw3", "0003:0000046D:0000C354", &[5, 1][..]),
        ("hidraw4", "0003:0000046D:0000C548", &[6, 0x43, 0xff][..]),
    ] {
        let device = root.join(node).join("device");
        std::fs::create_dir_all(&device).unwrap();
        std::fs::write(device.join("uevent"), format!("HID_ID={id}\nHID_NAME=MX Keypad\n")).unwrap();
        std::fs::write(device.join("report_descriptor"), descriptor).unwrap();
    }
    let devices = discover_in(&root, std::path::Path::new("/fixture/dev")).unwrap();
    assert_eq!(devices.iter().map(|d| d.path.to_str().unwrap()).collect::<Vec<_>>(),
               ["/fixture/dev/hidraw1", "/fixture/dev/hidraw2"]);
    assert!(matches_device("HID_ID=0005:0000046D:0000C354\n"));
    assert!(!matches_device("HID_ID=0003:0000046D:0000C548\nHID_NAME=C354\n"));
    std::fs::remove_dir_all(root).unwrap();
}
