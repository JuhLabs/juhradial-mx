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

use std::fmt;
use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

use tokio_stream::StreamExt;

/// The well-known bus name KWin owns while it is running.
const KWIN_BUS_NAME: &str = "org.kde.KWin";
const KWIN_SCRIPTING_PATH: &str = "/Scripting";
const KWIN_SCRIPTING_INTERFACE: &str = "org.kde.kwin.Scripting";
const KWIN_SCRIPT_INTERFACE: &str = "org.kde.kwin.Script";

/// Error returned when KWin cannot load or run a cursor-position script.
#[derive(Debug)]
pub enum KWinScriptError {
    Io {
        operation: &'static str,
        source: io::Error,
    },
    Dbus(zbus::Error),
    LoadRejected(i32),
}

/// Result after the `Script.run` call has been attempted.
///
/// A D-Bus call error cannot prove that KWin did not receive and execute the
/// method. Callers must therefore suppress their cursor fallback for both
/// variants: only an outer [`KWinScriptError`] is definitely pre-dispatch.
#[derive(Debug)]
pub enum KWinScriptRunOutcome {
    Confirmed { script_id: i32 },
    Unconfirmed { script_id: i32, error: zbus::Error },
}

impl KWinScriptRunOutcome {
    pub fn script_id(&self) -> i32 {
        match self {
            Self::Confirmed { script_id } | Self::Unconfirmed { script_id, .. } => *script_id,
        }
    }
}

impl fmt::Display for KWinScriptError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io { operation, source } => {
                write!(f, "failed to {operation} KWin script: {source}")
            }
            Self::Dbus(error) => write!(f, "KWin D-Bus call failed: {error}"),
            Self::LoadRejected(script_id) => {
                write!(f, "KWin rejected script load with id {script_id}")
            }
        }
    }
}

impl std::error::Error for KWinScriptError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io { source, .. } => Some(source),
            Self::Dbus(error) => Some(error),
            Self::LoadRejected(_) => None,
        }
    }
}

impl From<zbus::Error> for KWinScriptError {
    fn from(error: zbus::Error) -> Self {
        Self::Dbus(error)
    }
}

/// Native client for KWin's scripting API.
///
/// Clones share the daemon's existing session-bus connection and serialize
/// one-shot scripts. This removes the two `dbus-send` process launches that
/// previously ran on every radial-menu open in both input backends.
#[derive(Clone)]
pub struct KWinScripting {
    connection: zbus::Connection,
    sequence: Arc<AtomicU64>,
    one_shot_lock: Arc<tokio::sync::Mutex<()>>,
}

impl KWinScripting {
    pub fn new(connection: zbus::Connection) -> Self {
        Self {
            connection,
            sequence: Arc::new(AtomicU64::new(0)),
            one_shot_lock: Arc::new(tokio::sync::Mutex::new(())),
        }
    }

    /// Run the one-shot cursor script.
    ///
    /// `Err` means the call definitely failed before `Script.run` dispatch and
    /// handlers may use their cursor fallback. An unconfirmed `Ok` means the run
    /// call may have executed, so falling back could open the menu twice.
    pub async fn run_cursor_script(&self) -> Result<KWinScriptRunOutcome, KWinScriptError> {
        let _guard = self.one_shot_lock.lock().await;
        let sequence = self.sequence.fetch_add(1, Ordering::Relaxed);
        let plugin_name = format!("juhradial-cursor-{}-{sequence}", std::process::id());

        self.run_one_shot_script(crate::cursor::KWIN_CURSOR_SCRIPT, &plugin_name)
            .await
    }

    async fn run_one_shot_script(
        &self,
        script: &str,
        plugin_name: &str,
    ) -> Result<KWinScriptRunOutcome, KWinScriptError> {
        let mut temp_file =
            tempfile::Builder::new()
                .suffix(".js")
                .tempfile()
                .map_err(|source| KWinScriptError::Io {
                    operation: "create temporary file for",
                    source,
                })?;
        temp_file
            .write_all(script.as_bytes())
            .map_err(|source| KWinScriptError::Io {
                operation: "write",
                source,
            })?;
        let script_path = temp_file.path().to_string_lossy().into_owned();

        let scripting = zbus::Proxy::new(
            &self.connection,
            KWIN_BUS_NAME,
            KWIN_SCRIPTING_PATH,
            KWIN_SCRIPTING_INTERFACE,
        )
        .await?;
        let script_id: i32 = scripting
            .call("loadScript", &(script_path.as_str(), plugin_name))
            .await?;
        if script_id < 0 {
            return Err(KWinScriptError::LoadRejected(script_id));
        }

        let object_path = format!("/Scripting/Script{script_id}");
        let script_proxy = zbus::Proxy::new(
            &self.connection,
            KWIN_BUS_NAME,
            object_path.as_str(),
            KWIN_SCRIPT_INTERFACE,
        )
        .await?;
        let run_result: zbus::Result<()> = script_proxy.call("run", &()).await;

        // Attempt cleanup even when the void run reply is an error: KWin may
        // already have evaluated the script and dispatched ShowMenuAtCursor.
        // Cleanup failure must likewise not trigger the handler fallback.
        match scripting
            .call::<_, _, bool>("unloadScript", &(plugin_name))
            .await
        {
            Ok(true) => {}
            Ok(false) => tracing::warn!(
                script_id,
                plugin_name,
                "KWin did not unload completed cursor script"
            ),
            Err(error) => tracing::warn!(
                script_id,
                plugin_name,
                error = %error,
                "Failed to unload completed KWin cursor script"
            ),
        }

        Ok(match run_result {
            Ok(()) => KWinScriptRunOutcome::Confirmed { script_id },
            Err(error) => KWinScriptRunOutcome::Unconfirmed { script_id, error },
        })
    }
}

/// Run the shared KWin cursor trigger and invoke `fallback` only when dispatch
/// definitely did not happen.
///
/// Both input handlers use this consumer so the outcome policy cannot drift:
/// a confirmed or unconfirmed `Script.run` suppresses fallback, while a
/// pre-dispatch error (or an unavailable scripting client) invokes it exactly
/// once.
pub async fn trigger_kwin_cursor_script<F, Fut>(scripting: Option<&KWinScripting>, fallback: F)
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = ()>,
{
    let should_fallback = match scripting {
        Some(scripting) => match scripting.run_cursor_script().await {
            Ok(KWinScriptRunOutcome::Confirmed { script_id }) => {
                tracing::debug!(script_id, "KWin cursor script run confirmed");
                false
            }
            Ok(KWinScriptRunOutcome::Unconfirmed { script_id, error }) => {
                tracing::warn!(
                    script_id,
                    error = %error,
                    "KWin cursor script run is unconfirmed; suppressing fallback"
                );
                false
            }
            Err(error) => {
                tracing::warn!(
                    error = %error,
                    "KWin cursor script failed before run dispatch"
                );
                true
            }
        },
        None => {
            tracing::warn!("KWin scripting client is not configured");
            true
        }
    };

    if should_fallback {
        fallback().await;
    }
}

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
