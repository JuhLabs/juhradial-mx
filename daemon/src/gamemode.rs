//! Feral GameMode watcher: turns gaming mode on while a game is registered
//! with gamemoded (Settings > Gaming > Turn on automatically).
//!
//! gamemoded runs on the session bus as `com.feralinteractive.GameMode` and
//! counts registered games in its `ClientCount` property. It is D-Bus
//! activatable, so every query here carries NO_AUTO_START: watching must
//! never start it. The name-owner and property-change streams re-bind across
//! gamemoded restarts; each event re-queries the count (no cached values).

use tokio_stream::StreamExt;
use zbus::fdo::DBusProxy;
use zbus::proxy::{CacheProperties, MethodFlags};

use crate::dbus::DBUS_PATH;
use crate::gaming::{AutoSource, SharedGamingMode};

const NAME: &str = "com.feralinteractive.GameMode";
const PATH: &str = "/com/feralinteractive/GameMode";

/// A game counts as running while gamemoded owns its name and reports at
/// least one registered client.
pub fn is_active(owned: bool, client_count: Option<i32>) -> bool {
    owned && client_count.unwrap_or(0) > 0
}

async fn client_count(props: &zbus::Proxy<'_>) -> Option<i32> {
    let reply: Option<zbus::zvariant::OwnedValue> = props
        .call_with_flags("Get", MethodFlags::NoAutoStart.into(), &(NAME, "ClientCount"))
        .await
        .ok()?;
    i32::try_from(reply?).ok()
}

/// Watch gamemoded for the life of the daemon. Cheap when it is not
/// installed: one name lookup, then an idle owner stream.
pub async fn run_gamemode_watcher(conn: zbus::Connection, gaming: SharedGamingMode) {
    let Ok(dbus) = DBusProxy::new(&conn).await else { return };
    let Ok(name) = zbus::names::BusName::try_from(NAME) else { return };
    let activatable = dbus
        .list_activatable_names()
        .await
        .map(|names| names.iter().any(|n| n.as_str() == NAME))
        .unwrap_or(false);
    let owned = dbus.name_has_owner(name.clone()).await.unwrap_or(false);
    if let Ok(mut gm) = gaming.write() {
        gm.set_gamemode_installed(activatable || owned);
    }
    tracing::info!(installed = activatable || owned, "Feral GameMode");

    let Ok(mut owners) = dbus.receive_name_owner_changed_with_args(&[(0u8, NAME)]).await else { return };
    let props = match zbus::proxy::Builder::<zbus::Proxy<'_>>::new(&conn)
        .destination(NAME)
        .and_then(|b| b.path(PATH))
        .and_then(|b| b.interface("org.freedesktop.DBus.Properties"))
        .map(|b| b.cache_properties(CacheProperties::No))
    {
        Ok(b) => match b.build().await {
            Ok(p) => p,
            Err(_) => return,
        },
        Err(_) => return,
    };
    let Ok(mut changed) = props.receive_signal("PropertiesChanged").await else { return };

    let mut last: Option<bool> = None;
    loop {
        let owned = dbus.name_has_owner(name.clone()).await.unwrap_or(false);
        let count = if owned { client_count(&props).await } else { None };
        let active = is_active(owned, count);
        if owned {
            if let Ok(mut gm) = gaming.write() {
                gm.set_gamemode_installed(true);
            }
        }
        if last != Some(active) {
            last = Some(active);
            tracing::info!(active, "Feral GameMode game state");
            // enable()/disable() write the DPI over HID++ (blocking).
            let g = gaming.clone();
            let flipped = tokio::task::spawn_blocking(move || {
                g.write().ok().and_then(|mut gm| gm.set_auto(AutoSource::GameMode, active))
            })
            .await
            .ok()
            .flatten();
            if let Some(on) = flipped {
                let _ = conn
                    .emit_signal(None::<&str>, DBUS_PATH, "org.kde.juhradialmx.Daemon", "GamingModeChanged", &(on,))
                    .await;
            }
        }
        tokio::select! {
            o = owners.next() => if o.is_none() { return },
            c = changed.next() => if c.is_none() { return },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_game_counts_only_while_gamemoded_runs() {
        assert!(!is_active(false, Some(2)));
        assert!(!is_active(true, Some(0)));
        assert!(!is_active(true, None));
        assert!(is_active(true, Some(1)));
    }
}
