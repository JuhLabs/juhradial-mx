//! D-Bus method handlers in `src/dbus/interface.rs` run on the zbus executor
//! thread, which is not a tokio context: `tokio::spawn` and
//! `tokio::task::spawn_blocking` panic there with "there is no reactor
//! running" and the call silently fails (the recorder's `ListReceivers` and
//! `ModifiersHeld` did). Work that must leave the executor goes to its own
//! thread (`on_thread`, or a dedicated current-thread runtime as
//! `ExecutePreset` does).

#[test]
fn dbus_handlers_do_not_spawn_on_the_tokio_runtime() {
    let source = include_str!("../src/dbus/interface.rs");
    for needle in ["tokio::task::spawn_blocking(", "tokio::spawn("] {
        assert!(
            !source.contains(needle),
            "{needle} in src/dbus/interface.rs runs on the zbus executor, which has no tokio runtime; use on_thread"
        );
    }
}
