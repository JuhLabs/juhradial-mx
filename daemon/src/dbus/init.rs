//! D-Bus service initialization

use std::sync::{Arc, Mutex};

use crate::battery::SharedBatteryState;
use crate::config::SharedConfig;
use crate::gaming::SharedGamingMode;
use crate::hidpp::SharedHapticManager;
use crate::macros::{MacroEngine, MacroRecorder, SharedTriggerMap, TriggerMap};
use crate::profiles::SharedHardwareProfiles;

use super::service::JuhRadialService;
use super::DBUS_PATH;

/// Atomically claim a well-known bus name, or report that another connection
/// already owns it.
///
/// Returns `Ok(true)` when this connection now owns the name and `Ok(false)`
/// when a different connection does. This must NOT use zbus's default request
/// flags: those are `AllowReplacement | ReplaceExisting | DoNotQueue`, which
/// let a second daemon silently STEAL the name from a running one. The loser
/// only gets a `NameLost` signal nobody handles, so both daemons stay alive
/// and double-handle every button event (issue #60). `DoNotQueue` alone means
/// first claimer wins, every later claimer is refused, and nobody can be
/// replaced.
pub async fn claim_name(connection: &zbus::Connection, name: &str) -> zbus::Result<bool> {
    let well_known = zbus::names::WellKnownName::try_from(name)?;
    match connection
        .request_name_with_flags(well_known, zbus::fdo::RequestNameFlags::DoNotQueue.into())
        .await
    {
        Ok(_) => Ok(true),
        Err(zbus::Error::NameTaken) => Ok(false),
        Err(e) => Err(e),
    }
}

/// Initialize and run the D-Bus service
///
/// Exports the interface at the specified object path on an existing session
/// bus connection. The caller owns the connection and is expected to have
/// already claimed [`super::DBUS_NAME`] via [`claim_name`] before doing any
/// device work.
pub async fn init_dbus_service(
    connection: &zbus::Connection,
    battery_state: SharedBatteryState,
    config: SharedConfig,
    haptic_manager: SharedHapticManager,
) -> zbus::Result<()> {
    let gaming_mode = crate::gaming::new_shared_gaming_mode(haptic_manager.clone());
    let macro_engine = Arc::new(Mutex::new(MacroEngine::new()));
    let macro_recorder = Arc::new(Mutex::new(MacroRecorder::new()));
    let trigger_map = Arc::new(std::sync::RwLock::new(TriggerMap::default()));
    let (active_window_tx, _aw_rx) = tokio::sync::mpsc::unbounded_channel();
    let hardware_profiles = Arc::new(std::sync::RwLock::new(std::collections::HashMap::new()));
    init_dbus_service_with_device(
        connection,
        battery_state,
        config,
        haptic_manager,
        "logitech".to_string(),
        "Unknown".to_string(),
        gaming_mode,
        macro_engine,
        macro_recorder,
        trigger_map,
        active_window_tx,
        hardware_profiles,
    )
    .await
}

/// Initialize and run the D-Bus service with device mode information
#[allow(clippy::too_many_arguments)]
pub async fn init_dbus_service_with_device(
    connection: &zbus::Connection,
    battery_state: SharedBatteryState,
    config: SharedConfig,
    haptic_manager: SharedHapticManager,
    device_mode: String,
    device_name: String,
    gaming_mode: SharedGamingMode,
    macro_engine: Arc<Mutex<MacroEngine>>,
    macro_recorder: Arc<Mutex<MacroRecorder>>,
    trigger_map: SharedTriggerMap,
    active_window_tx: tokio::sync::mpsc::UnboundedSender<String>,
    hardware_profiles: SharedHardwareProfiles,
) -> zbus::Result<()> {
    let service = JuhRadialService::new_with_device(
        battery_state,
        config,
        haptic_manager,
        device_mode,
        device_name,
        gaming_mode,
        macro_engine,
        macro_recorder,
        trigger_map,
        active_window_tx,
        hardware_profiles,
    );

    connection.object_server().at(DBUS_PATH, service).await?;

    tracing::info!(
        name = super::DBUS_NAME,
        path = DBUS_PATH,
        "D-Bus service registered"
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Issue #60: the second daemon must be REFUSED the name, not silently
    /// replace the first owner (zbus's default flags do the latter, leaving
    /// two daemons alive that both handle every button event).
    #[tokio::test]
    async fn second_name_claim_is_refused_not_replaced() {
        let Ok(first) = zbus::Connection::session().await else {
            eprintln!("skipping: no session D-Bus available");
            return;
        };
        // Unique throwaway name so the test never collides with a live daemon.
        let name = format!("org.kde.juhradialmx.claimtest.pid{}", std::process::id());

        assert!(claim_name(&first, &name).await.unwrap(), "first claim must win");
        let second = zbus::Connection::session().await.unwrap();
        assert!(
            !claim_name(&second, &name).await.unwrap(),
            "second claim must be refused"
        );

        // The first connection must still be the owner afterwards.
        let dbus = zbus::fdo::DBusProxy::new(&second).await.unwrap();
        let owner = dbus
            .get_name_owner(zbus::names::BusName::try_from(name.as_str()).unwrap())
            .await
            .unwrap();
        assert_eq!(&owner, first.unique_name().unwrap());
    }
}
