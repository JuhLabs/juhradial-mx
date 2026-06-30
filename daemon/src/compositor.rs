//! Compositor capability detection.
//!
//! Whether to query KWin for the cursor position is decided by whether the
//! well-known `org.kde.KWin` name is owned on the session bus, NOT by the
//! `XDG_CURRENT_DESKTOP` environment string. At cold boot the daemon is started
//! by systemd without that variable in its environment, so the env check
//! classified a live KDE session as non-KDE and the cursor query fell back to
//! the screen centre, opening the menu in the wrong place until the app was
//! restarted from the graphical session (issue #32). The bus name is present
//! whenever KWin is running, and the watcher updates the flag live so a KWin
//! restart is reflected without restarting the daemon.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use tokio_stream::StreamExt;

/// The well-known bus name KWin owns while it is running.
const KWIN_BUS_NAME: &str = "org.kde.KWin";

/// Shared, live "is KWin available?" flag. Cheap to clone (an `Arc`) and
/// lock-free to read on the input hot path.
#[derive(Clone, Default)]
pub struct KWinAvailability(Arc<AtomicBool>);

impl KWinAvailability {
    pub fn new() -> Self {
        Self(Arc::new(AtomicBool::new(false)))
    }

    pub fn set_owned(&self, owned: bool) {
        self.0.store(owned, Ordering::Release);
    }

    pub fn is_owned(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}

/// Cursor backend chosen for a gesture press.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CursorBackend {
    /// Query KWin (accurate multi-monitor Wayland cursor) via its D-Bus script.
    KWin,
    /// Direct cursor-query cascade (GNOME/Hyprland/Sway/COSMIC/X11/fallback).
    Fallback,
}

/// Pure routing decision, kept out of the D-Bus code so it is unit-testable.
pub fn cursor_backend(kwin_owned: bool) -> CursorBackend {
    if kwin_owned {
        CursorBackend::KWin
    } else {
        CursorBackend::Fallback
    }
}

/// Keep `availability` in sync with `org.kde.KWin` ownership for the life of the
/// connection. Initializes from `NameHasOwner`, then follows `NameOwnerChanged`
/// (filtered to KWin) and re-queries on each change so a KWin restart is
/// reflected. Best-effort: on a D-Bus error it logs and keeps the last known
/// state rather than forcing the flag to false.
pub async fn run_kwin_watcher(connection: zbus::Connection, availability: KWinAvailability) {
    let proxy = match zbus::fdo::DBusProxy::new(&connection).await {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!(error = %e, "KWin watcher: could not create DBusProxy; KWin detection disabled");
            return;
        }
    };

    let kwin = match zbus::names::BusName::try_from(KWIN_BUS_NAME) {
        Ok(n) => n,
        Err(e) => {
            tracing::warn!(error = %e, "KWin watcher: invalid bus name");
            return;
        }
    };

    match proxy.name_has_owner(kwin.clone()).await {
        Ok(owned) => {
            availability.set_owned(owned);
            tracing::info!(
                kwin_owned = owned,
                "Initial KWin availability (D-Bus capability)"
            );
        }
        Err(e) => tracing::warn!(error = %e, "KWin watcher: initial NameHasOwner failed"),
    }

    // Server-side filter to NameOwnerChanged where arg0 (the name) is KWin.
    let mut stream = match proxy
        .receive_name_owner_changed_with_args(&[(0u8, KWIN_BUS_NAME)])
        .await
    {
        Ok(s) => s,
        Err(e) => {
            tracing::warn!(error = %e, "KWin watcher: could not watch NameOwnerChanged; KWin state is point-in-time only");
            return;
        }
    };

    while stream.next().await.is_some() {
        match proxy.name_has_owner(kwin.clone()).await {
            Ok(owned) => {
                availability.set_owned(owned);
                tracing::info!(kwin_owned = owned, "KWin availability changed");
            }
            Err(e) => tracing::warn!(error = %e, "KWin watcher: NameHasOwner re-query failed"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kwin_owner_selects_kwin_backend() {
        assert_eq!(cursor_backend(true), CursorBackend::KWin);
    }

    #[test]
    fn no_owner_uses_fallback() {
        assert_eq!(cursor_backend(false), CursorBackend::Fallback);
    }

    #[test]
    fn availability_defaults_to_not_owned() {
        assert!(!KWinAvailability::new().is_owned());
    }

    #[test]
    fn owner_loss_and_recovery_update_state() {
        let a = KWinAvailability::new();
        a.set_owned(true);
        assert!(a.is_owned());
        a.set_owned(false);
        assert!(!a.is_owned());
        a.set_owned(true);
        assert!(a.is_owned());
    }

    #[test]
    fn clones_share_one_flag() {
        let a = KWinAvailability::new();
        let b = a.clone();
        a.set_owned(true);
        assert!(b.is_owned());
    }
}
