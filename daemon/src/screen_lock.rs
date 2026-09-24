// SPDX-License-Identifier: GPL-3.0
//! Screen lock watcher: follows logind's `LockedHint` on the user's graphical
//! session (KDE Plasma and GNOME set it while their lock screen is up) so the
//! MX Keypad can go blank and ignore presses while the screen is locked.
//! Desktops that never set the hint leave the keypad as it is.

use tokio_stream::StreamExt;
use zbus::zvariant::OwnedObjectPath;

const LOGIN1: &str = "org.freedesktop.login1";

async fn login1_proxy<'a>(conn: &zbus::Connection, path: &'a str, interface: &'a str) -> zbus::Result<zbus::Proxy<'a>> {
    zbus::proxy::Builder::new(conn).destination(LOGIN1)?.path(path)?.interface(interface)?.build().await
}

/// Watch for the life of the daemon; `on_change` gets the lock state once at
/// start and on every change.
pub async fn run(on_change: impl Fn(bool)) {
    let Ok(conn) = zbus::Connection::system().await else { return };
    // The daemon is a user service outside any session: ask for the user's
    // graphical ("display") session instead of the caller's own.
    let Ok(user) = login1_proxy(&conn, "/org/freedesktop/login1/user/self", "org.freedesktop.login1.User").await else { return };
    let Ok((id, path)) = user.get_property::<(String, OwnedObjectPath)>("Display").await else { return };
    if id.is_empty() {
        return;
    }
    let Ok(session) = login1_proxy(&conn, path.as_str(), "org.freedesktop.login1.Session").await else { return };
    let mut changes = session.receive_property_changed::<bool>("LockedHint").await;
    let mut locked = session.get_property::<bool>("LockedHint").await.unwrap_or(false);
    tracing::info!(session = %id, locked, "Screen lock watcher");
    on_change(locked);
    while let Some(change) = changes.next().await {
        let Ok(now) = change.get().await else { continue };
        if now != locked {
            locked = now;
            tracing::info!(locked, "Screen lock");
            on_change(locked);
        }
    }
}
