//! Whether the mouse is reachable right now, for the settings app.
//!
//! connected: the mouse answered HID++. asleep: it answered earlier in this
//! run and the receiver now reports the link as parked (0x8F / 0x04).
//! away: the receiver reported its link down (0x41, bit 6), or we sent it to
//! another Easy-Switch host; this also covers a switched-off mouse, the
//! protocol does not tell the two apart. offline: no mouse answered yet, or
//! its node is gone. One process-wide watch channel; subscribers see real
//! transitions only.

use std::sync::OnceLock;

use tokio::sync::watch;

use crate::hidpp::ConnectionType;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkState {
    Connected,
    Asleep,
    Away,
    Offline,
}

impl LinkState {
    pub fn as_str(self) -> &'static str {
        match self {
            LinkState::Connected => "connected",
            LinkState::Asleep => "asleep",
            LinkState::Away => "away",
            LinkState::Offline => "offline",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transport {
    Bolt,
    Unifying,
    Bluetooth,
    Usb,
    Unknown,
}

impl Transport {
    pub fn as_str(self) -> &'static str {
        match self {
            Transport::Bolt => "bolt",
            Transport::Unifying => "unifying",
            Transport::Bluetooth => "bluetooth",
            Transport::Usb => "usb",
            Transport::Unknown => "unknown",
        }
    }
}

impl From<ConnectionType> for Transport {
    fn from(c: ConnectionType) -> Self {
        match c {
            ConnectionType::Bolt => Transport::Bolt,
            ConnectionType::Unifying => Transport::Unifying,
            ConnectionType::Bluetooth => Transport::Bluetooth,
            ConnectionType::Usb => Transport::Usb,
        }
    }
}

pub type LinkSnapshot = (LinkState, Transport);

/// The next snapshot for a report, or None when nothing changes.
///
/// A mouse that never answered stays offline on "asleep" reports (a failed
/// poll proves nothing about a mouse we never saw), and "away" is not
/// downgraded to "asleep" by the failed polls that follow a host switch.
pub fn next_snapshot(
    current: LinkSnapshot,
    state: LinkState,
    transport: Option<Transport>,
) -> Option<LinkSnapshot> {
    let (cur_state, cur_transport) = current;
    let new_state = match (cur_state, state) {
        (LinkState::Offline, LinkState::Asleep) => LinkState::Offline,
        (LinkState::Away, LinkState::Asleep) => LinkState::Away,
        _ => state,
    };
    let new_transport = match (new_state, transport) {
        (LinkState::Offline, _) => Transport::Unknown,
        (_, Some(t)) => t,
        (_, None) => cur_transport,
    };
    let next = (new_state, new_transport);
    (next != current).then_some(next)
}

fn channel() -> &'static watch::Sender<LinkSnapshot> {
    static TX: OnceLock<watch::Sender<LinkSnapshot>> = OnceLock::new();
    TX.get_or_init(|| watch::channel((LinkState::Offline, Transport::Unknown)).0)
}

/// Report an observation; true when it changed the published state.
pub fn report(state: LinkState, transport: Option<Transport>) -> bool {
    let tx = channel();
    let mut changed = false;
    tx.send_if_modified(|snap| match next_snapshot(*snap, state, transport) {
        Some(next) => {
            *snap = next;
            changed = true;
            true
        }
        None => false,
    });
    changed
}

pub fn current() -> LinkSnapshot {
    *channel().borrow()
}

pub fn subscribe() -> watch::Receiver<LinkSnapshot> {
    channel().subscribe()
}

#[cfg(test)]
mod tests {
    use super::*;
    use LinkState::*;

    #[test]
    fn transitions() {
        let off = (Offline, Transport::Unknown);
        // Never answered: an asleep report proves nothing.
        assert_eq!(next_snapshot(off, Asleep, None), None);
        let up = next_snapshot(off, Connected, Some(Transport::Bolt)).unwrap();
        assert_eq!(up, (Connected, Transport::Bolt));
        // Repeats are not transitions.
        assert_eq!(next_snapshot(up, Connected, Some(Transport::Bolt)), None);
        assert_eq!(next_snapshot(up, Connected, None), None);
        // Transport is kept while asleep or away.
        assert_eq!(next_snapshot(up, Asleep, None), Some((Asleep, Transport::Bolt)));
        let away = next_snapshot(up, Away, None).unwrap();
        assert_eq!(away, (Away, Transport::Bolt));
        // Failed polls after a host switch do not turn away into asleep.
        assert_eq!(next_snapshot(away, Asleep, None), None);
        assert_eq!(next_snapshot(away, Connected, None), Some((Connected, Transport::Bolt)));
        assert_eq!(next_snapshot(up, Offline, None), Some(off));
    }
}
