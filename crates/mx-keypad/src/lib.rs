//! Logitech MX Keypad protocol and Linux hidraw transport.
// SPDX-License-Identifier: MIT OR Apache-2.0
// Protocol informed by Julusian's @logitech-mx-creative-console/core (MIT),
// imageWriter and mx-creative-keypad input/model, and the owner's measurements.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub const PACKET_SIZE: usize = 4095;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KeyWindow {
    pub x: u16,
    pub y: u16,
    pub w: u16,
    pub h: u16,
}

impl KeyWindow {
    pub fn new(key: u8) -> Option<Self> {
        (1..=9).contains(&key).then(|| Self {
            x: 23 + u16::from((key - 1) % 3) * 158,
            y: 6 + u16::from((key - 1) / 3) * 158,
            w: 118,
            h: 118,
        })
    }
}

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

pub fn image_packets(x: u16, y: u16, w: u16, h: u16, jpeg: &[u8]) -> io::Result<Vec<[u8; PACKET_SIZE]>> {
    if jpeg.is_empty() || jpeg.len() > u16::MAX as usize {
        return Err(invalid("JPEG length must be 1..65535 bytes"));
    }
    if w == 0 || h == 0 || u32::from(x) + u32::from(w) > 480 || u32::from(y) + u32::from(h) > 480 {
        return Err(invalid("Image window must fit the 480x480 panel"));
    }
    let mut packets = Vec::new();
    let mut offset = 0;
    while offset < jpeg.len() {
        let first = packets.is_empty();
        let header = if first { 20 } else { 5 };
        let count = (PACKET_SIZE - header).min(jpeg.len() - offset);
        let last = offset + count == jpeg.len();
        let flags = (packets.len() + 1) as u8 | 0x20
            | if first { 0x80 } else { 0 } | if last { 0x40 } else { 0 };
        let mut packet = [0; PACKET_SIZE];
        packet[..5].copy_from_slice(&[0x14, 0xff, 2, 0x2b, flags]);
        if first {
            packet[5..9].copy_from_slice(&[1, 0, 1, 0]);
            for (at, value) in [(9, x), (11, y), (13, w), (15, h), (18, jpeg.len() as u16)] {
                packet[at..at + 2].copy_from_slice(&value.to_be_bytes());
            }
        }
        packet[header..header + count].copy_from_slice(&jpeg[offset..offset + count]);
        packets.push(packet);
        offset += count;
    }
    Ok(packets)
}

pub fn init_report() -> [u8; 20] {
    let mut report = [0; 20];
    report[..7].copy_from_slice(&[0x11, 0xff, 0x0b, 0x3b, 1, 0xa1, 3]);
    report
}

pub fn reset_to_logo_report() -> [u8; 32] {
    let mut report = [0; 32];
    report[..2].copy_from_slice(&[3, 2]);
    report
}

/// Bytes only. Persistence is unmeasured; the daemon and probe never send this.
/// Zero is deliberately rejected because it resets the device.
pub fn brightness_report(percent: u8) -> io::Result<[u8; 20]> {
    if !(1..=100).contains(&percent) {
        return Err(invalid("Brightness must be 1..100"));
    }
    let mut report = [0; 20];
    report[..6].copy_from_slice(&[0x11, 0xff, 0x0f, 0x2b, 0, percent]);
    Ok(report)
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct KeySet(u16);

#[derive(Debug, PartialEq, Eq)]
pub struct KeyDiff {
    pub down: Vec<u8>,
    pub up: Vec<u8>,
}

impl KeySet {
    pub fn iter(self) -> impl Iterator<Item = u8> {
        (1..=9).filter(move |key| self.0 & (1 << key) != 0)
    }

    pub fn diff(self, previous: Self) -> KeyDiff {
        KeyDiff {
            down: Self(self.0 & !previous.0).iter().collect(),
            up: Self(previous.0 & !self.0).iter().collect(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PageButton { Left, Right }

#[derive(Debug, PartialEq, Eq)]
pub enum Input {
    Keys(KeySet),
    Pages(Vec<PageButton>),
}

pub fn parse_input(data: &[u8]) -> Option<Input> {
    if data.get(2) == Some(&0x2b) {
        return None;
    }
    if data.starts_with(&[0x13, 0xff, 2, 0]) && data.get(5) == Some(&1) {
        let mut keys = KeySet::default();
        for &key in &data[6..] {
            if key == 0 { return Some(Input::Keys(keys)); }
            if !(1..=9).contains(&key) { return None; }
            keys.0 |= 1 << key;
        }
    } else if data.starts_with(&[0x11, 0xff, 0x0b, 0]) {
        let mut buttons = Vec::new();
        for pair in data[4..].chunks_exact(2) {
            let button = match u16::from_be_bytes([pair[0], pair[1]]) {
                0 => return Some(Input::Pages(buttons)),
                0x01a1 => PageButton::Left,
                0x01a2 => PageButton::Right,
                _ => continue,
            };
            if !buttons.contains(&button) { buttons.push(button); }
        }
    }
    None
}

/// Parse HID items so bytes inside unrelated values cannot match a usage page.
pub fn has_vendor_usage_page(mut descriptor: &[u8]) -> bool {
    while let Some((&prefix, rest)) = descriptor.split_first() {
        let (header, len) = if prefix == 0xfe {
            let Some(&len) = rest.first() else { return false };
            (2, len as usize)
        } else {
            (0, match prefix & 3 { 3 => 4, n => n as usize })
        };
        let Some(value) = rest.get(header..header + len) else { return false };
        if prefix != 0xfe && prefix & 0xfc == 0x04 {
            let page = value.iter().enumerate().fold(0u32, |n, (i, b)| n | (u32::from(*b) << (i * 8)));
            if page == 0xff43 { return true; }
        }
        descriptor = &rest[header + len..];
    }
    false
}

#[derive(Debug, Clone)]
pub struct DeviceInfo {
    pub path: PathBuf,
    pub name: String,
}

pub fn discover() -> io::Result<Vec<DeviceInfo>> {
    discover_in(Path::new("/sys/class/hidraw"), Path::new("/dev"))
}

/// Identify the device separately so other Logitech workers can leave it alone.
pub fn matches_device(uevent: &str) -> bool {
    uevent.lines().filter_map(|line| line.strip_prefix("HID_ID=")).any(|id| {
        let parts: Vec<_> = id.split(':').collect();
        parts.len() == 3 && u32::from_str_radix(parts[1], 16) == Ok(0x046d)
            && u32::from_str_radix(parts[2], 16) == Ok(0xc354)
    })
}

/// Alternate roots make discovery testable without a device or privileges.
pub fn discover_in(sysfs: &Path, dev: &Path) -> io::Result<Vec<DeviceInfo>> {
    let mut devices = Vec::new();
    for entry in fs::read_dir(sysfs)? {
        let entry = entry?;
        let device = entry.path().join("device");
        let Ok(uevent) = fs::read_to_string(device.join("uevent")) else { continue };
        if !matches_device(&uevent) { continue; }
        let Ok(descriptor) = fs::read(device.join("report_descriptor")) else { continue };
        if !has_vendor_usage_page(&descriptor) { continue; }
        devices.push(DeviceInfo {
            path: dev.join(entry.file_name()),
            name: uevent.lines().find_map(|s| s.strip_prefix("HID_NAME="))
                .unwrap_or("Logitech MX Keypad").to_string(),
        });
    }
    devices.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(devices)
}

/// One owner per hidraw fd. No writes occur until a method is called.
pub struct Keypad(File);

impl Keypad {
    pub fn open(path: &Path) -> io::Result<Self> {
        OpenOptions::new().read(true).write(true)
            .custom_flags(libc::O_NONBLOCK | libc::O_CLOEXEC).open(path).map(Self)
    }

    fn ready(&self, events: libc::c_short, timeout: Duration) -> io::Result<bool> {
        let deadline = Instant::now() + timeout;
        loop {
            let mut fd = libc::pollfd { fd: self.0.as_raw_fd(), events, revents: 0 };
            let ms = deadline.saturating_duration_since(Instant::now()).as_millis().min(i32::MAX as u128) as i32;
            // SAFETY: fd points to one valid pollfd for the duration of poll.
            let result = unsafe { libc::poll(&mut fd, 1, ms) };
            if result < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted { continue; }
                return Err(error);
            }
            if fd.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
                return Err(io::Error::new(io::ErrorKind::NotConnected, "Keypad disconnected"));
            }
            return Ok(result > 0 && fd.revents & events != 0);
        }
    }

    fn write_report(&mut self, report: &[u8]) -> io::Result<()> {
        if !self.ready(libc::POLLOUT, Duration::from_millis(500))? {
            return Err(io::Error::new(io::ErrorKind::TimedOut, "Keypad write timed out"));
        }
        let n = self.0.write(report)?;
        if n != report.len() {
            return Err(io::Error::new(io::ErrorKind::WriteZero, "Short HID report write"));
        }
        Ok(())
    }

    pub fn init(&mut self) -> io::Result<()> { self.write_report(&init_report()) }

    pub fn write_image(&mut self, window: KeyWindow, jpeg: &[u8]) -> io::Result<()> {
        for packet in image_packets(window.x, window.y, window.w, window.h, jpeg)? {
            self.write_report(&packet)?;
        }
        Ok(())
    }

    pub fn read_report(&mut self, timeout: Duration) -> io::Result<Option<Vec<u8>>> {
        if !self.ready(libc::POLLIN, timeout)? { return Ok(None); }
        let mut data = vec![0; PACKET_SIZE];
        match self.0.read(&mut data) {
            Ok(0) => Err(io::Error::new(io::ErrorKind::UnexpectedEof, "Keypad closed")),
            Ok(n) => { data.truncate(n); Ok(Some(data)) }
            Err(e) if matches!(e.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted) => Ok(None),
            Err(e) => Err(e),
        }
    }

    pub fn reset_to_logo(&mut self) -> io::Result<()> {
        let mut report = reset_to_logo_report();
        // Linux HIDIOCSFEATURE(len): _IOC(READ | WRITE, 'H', 0x06, len).
        let request = ((3u32 << 30) | (32 << 16) | (u32::from(b'H') << 8) | 6) as libc::c_ulong;
        // SAFETY: the request describes this writable 32-byte report buffer.
        if unsafe { libc::ioctl(self.0.as_raw_fd(), request, report.as_mut_ptr()) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}
