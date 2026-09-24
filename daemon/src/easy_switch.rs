//! Mouse and keyboard move together (opt-in, `keyboard.mx_keys.move_together`).
//!
//! Logitech Options+ moves an MX Keys along with the mouse on Windows and
//! macOS only. Here: when the mouse leaves for another computer (its own
//! Easy-Switch button, or the ring and Settings through SetHost), the
//! keyboard is sent to the slot that holds the same computer, matched by the
//! host NAME in both devices' HOSTS_INFO tables (slot numbers differ between
//! devices). A device cannot be read once it has left, so both tables are
//! cached while they are here. A keyboard that is asleep gets the switch on
//! its next link-up (within PENDING_TTL). The other way round, the keyboard's
//! own Easy-Switch key (its CHANGE_HOST event, sent to the computer it
//! leaves) takes the mouse along.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use crate::hidpp::device::HostSlot;

/// How long a keyboard switch waits for the keyboard to wake.
pub const PENDING_TTL: Duration = Duration::from_secs(300);
/// After the keyboard took the mouse along, the mouse's own CHANGE_HOST
/// event must not send the keyboard anywhere (it has left already).
const FOLLOW_ECHO: Duration = Duration::from_secs(10);

#[derive(Default)]
struct Cache {
    mouse: Vec<HostSlot>,
    mouse_current: Option<u8>,
    keyboard: Vec<HostSlot>,
    pending: Option<(u8, Instant)>,
    keyboard_led: Option<Instant>,
}

static CACHE: Mutex<Cache> = Mutex::new(Cache {
    mouse: Vec::new(),
    mouse_current: None,
    keyboard: Vec::new(),
    pending: None,
    keyboard_led: None,
});

fn keyboard_led_recently(c: &Cache) -> bool {
    c.keyboard_led.is_some_and(|t| t.elapsed() < FOLLOW_ECHO)
}

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
    if c.mouse_current != Some(old) || new == old || keyboard_led_recently(&c) {
        return None;
    }
    keyboard_slot_for(&c.mouse, &c.keyboard, new)
}

/// SetHost moved the mouse to `to` (the ring, Settings).
pub fn mouse_sent(to: u8) -> Option<u8> {
    let c = CACHE.lock().ok()?;
    if c.mouse_current == Some(to) || keyboard_led_recently(&c) {
        return None;
    }
    keyboard_slot_for(&c.mouse, &c.keyboard, to)
}

/// The mouse slot to follow a keyboard that switched from keyboard slot
/// `old` to `new`: only when `old` is this computer (the keyboard slot named
/// like the mouse's current one) and the mouse is here, never to where it is.
pub fn follow_slot(mouse: &[HostSlot], mouse_current: Option<u8>, keyboard: &[HostSlot], old: u8, new: u8) -> Option<u8> {
    let here = mouse_current?;
    if new == old || keyboard_slot_for(mouse, keyboard, here) != Some(old) {
        return None;
    }
    keyboard_slot_for(keyboard, mouse, new).filter(|&to| to != here)
}

/// The keyboard's own Easy-Switch key sent it from slot `old` to `new`.
/// Returns the mouse slot to send the mouse to, if it should follow. A
/// keyboard switch still waiting for the keyboard is void either way.
pub fn keyboard_left(old: u8, new: u8) -> Option<u8> {
    let mut c = CACHE.lock().ok()?;
    c.pending = None;
    let to = follow_slot(&c.mouse, c.mouse_current, &c.keyboard, old, new)?;
    c.keyboard_led = Some(Instant::now());
    Some(to)
}

/// Send the mouse to `slot` (the keyboard left for that computer).
pub fn move_mouse(slot: u8) {
    let Some(manager) = crate::actions::device_manager() else { return };
    std::thread::spawn(move || {
        let result = manager.lock().map_err(|_| "mouse lock".to_string()).and_then(|mut m| m.set_current_host(slot));
        match result {
            Ok(()) => {
                tracing::info!(slot, "Mouse followed the keyboard");
                crate::link_state::report(crate::link_state::LinkState::Away, None);
            }
            Err(e) => tracing::info!(slot, error = %e, "Mouse could not follow the keyboard"),
        }
    });
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

    #[test]
    fn the_mouse_follows_the_keyboard_only_from_this_computer() {
        // Mouse: 0 linux-box (here), 1 MacBook Pro. Keyboard: 0 MacBook Pro, 1 linux-box.
        let mouse = [slot(1, "linux-box"), slot(1, "MacBook Pro"), slot(0, "")];
        let keyboard = [slot(1, "macbook pro"), slot(1, "linux-box"), slot(1, "iPad")];
        // Keyboard key 1 (MacBook) pressed here (keyboard slot 1 -> 0): mouse to 1.
        assert_eq!(follow_slot(&mouse, Some(0), &keyboard, 1, 0), Some(1));
        // An event claiming another computer as "old" is ignored.
        assert_eq!(follow_slot(&mouse, Some(0), &keyboard, 0, 1), None);
        // No mouse slot holds the iPad; the mouse is not here; no switch.
        assert_eq!(follow_slot(&mouse, Some(0), &keyboard, 1, 2), None);
        assert_eq!(follow_slot(&mouse, None, &keyboard, 1, 0), None);
        assert_eq!(follow_slot(&mouse, Some(0), &keyboard, 1, 1), None);
    }
}
