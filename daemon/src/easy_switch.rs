//! Mouse and keyboard move together (opt-in, `keyboard.mx_keys.move_together`).
//!
//! Logitech Options+ moves an MX Keys along with the mouse on Windows and
//! macOS only. Here: when the mouse leaves for another computer (its own
//! Easy-Switch button, or the ring and Settings through SetHost), the
//! keyboard is sent to the slot that holds the same computer, matched by the
//! host NAME in both devices' HOSTS_INFO tables (slot numbers differ between
//! devices). A device cannot be read once it has left, so both tables are
//! cached while they are here. A keyboard that is asleep gets the switch on
//! its next link-up (within PENDING_TTL).

use std::sync::Mutex;
use std::time::{Duration, Instant};

use crate::hidpp::device::HostSlot;

/// How long a keyboard switch waits for the keyboard to wake.
pub const PENDING_TTL: Duration = Duration::from_secs(300);

#[derive(Default)]
struct Cache {
    mouse: Vec<HostSlot>,
    mouse_current: Option<u8>,
    keyboard: Vec<HostSlot>,
    pending: Option<(u8, Instant)>,
}

static CACHE: Mutex<Cache> = Mutex::new(Cache {
    mouse: Vec::new(),
    mouse_current: None,
    keyboard: Vec::new(),
    pending: None,
});

pub fn remember_mouse(slots: Vec<HostSlot>, current: Option<u8>) {
    if let Ok(mut c) = CACHE.lock() {
        if !slots.is_empty() {
            c.mouse = slots;
        }
        if current.is_some() {
            c.mouse_current = current;
        }
    }
}

pub fn remember_keyboard(slots: Vec<HostSlot>) {
    if let Ok(mut c) = CACHE.lock() {
        if !slots.is_empty() {
            c.keyboard = slots;
        }
    }
}

/// The keyboard slot that holds the computer in mouse slot `to`: the paired
/// keyboard slot with the same (non-empty) host name.
pub fn keyboard_slot_for(mouse: &[HostSlot], keyboard: &[HostSlot], to: u8) -> Option<u8> {
    let name = mouse.get(usize::from(to)).filter(|s| s.paired()).map(|s| s.name.trim())?;
    if name.is_empty() {
        return None;
    }
    keyboard
        .iter()
        .position(|k| k.paired() && k.name.trim().eq_ignore_ascii_case(name))
        .and_then(|i| u8::try_from(i).ok())
}

/// A CHANGE_HOST event from the mouse, `[old, new]`. Trusted only when
/// `old` is this computer's slot (so a one-byte event can never send the
/// keyboard somewhere random). Returns the keyboard slot to switch to.
pub fn mouse_left(old: u8, new: u8) -> Option<u8> {
    let c = CACHE.lock().ok()?;
    if c.mouse_current != Some(old) || new == old {
        return None;
    }
    keyboard_slot_for(&c.mouse, &c.keyboard, new)
}

/// SetHost moved the mouse to `to` (the ring, Settings).
pub fn mouse_sent(to: u8) -> Option<u8> {
    let c = CACHE.lock().ok()?;
    if c.mouse_current == Some(to) {
        return None;
    }
    keyboard_slot_for(&c.mouse, &c.keyboard, to)
}

pub fn set_pending(slot: u8) {
    if let Ok(mut c) = CACHE.lock() {
        c.pending = Some((slot, Instant::now()));
    }
}

/// A switch still waiting for the keyboard (taken once).
pub fn take_pending() -> Option<u8> {
    let mut c = CACHE.lock().ok()?;
    c.pending.take().filter(|(_, at)| at.elapsed() < PENDING_TTL).map(|(s, _)| s)
}

/// Send the keyboard to `slot`; if it is asleep, keep it for its link-up.
pub fn move_keyboard(slot: u8) {
    std::thread::spawn(move || {
        let result = crate::keyboard::manager()
            .lock()
            .map_err(|_| "keyboard lock".to_string())
            .and_then(|mut m| m.set_current_host(slot));
        match result {
            Ok(()) => tracing::info!(slot, "Keyboard followed the mouse"),
            Err(e) => {
                tracing::info!(slot, error = %e, "Keyboard not reachable; switching when it wakes");
                set_pending(slot);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slot(status: u8, name: &str) -> HostSlot {
        HostSlot { status, bus: 1, name: name.into() }
    }

    #[test]
    fn slots_match_by_computer_name_not_number() {
        let mouse = [slot(1, "linux-box"), slot(1, "MacBook Pro"), slot(0, "")];
        let keyboard = [slot(1, "macbook pro"), slot(1, "linux-box"), slot(1, "iPad")];
        assert_eq!(keyboard_slot_for(&mouse, &keyboard, 1), Some(0));
        assert_eq!(keyboard_slot_for(&mouse, &keyboard, 0), Some(1));
        assert_eq!(keyboard_slot_for(&mouse, &keyboard, 2), None); // empty slot
        let unpaired = [slot(0, "MacBook Pro")];
        assert_eq!(keyboard_slot_for(&mouse, &unpaired, 1), None);
    }
}
