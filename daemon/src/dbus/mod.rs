//! D-Bus IPC server for JuhRadial MX
//!
//! Implements the org.kde.juhradialmx.Daemon interface for communication
//! with the overlay, settings UI, and Plasma widget.
//!
//! ## Module Layout
//!
//! - `service` - JuhRadialService struct and constructors
//! - `interface` - #[interface] impl with all D-Bus methods/signals/properties
//! - `init` - Service initialization and bus registration

mod init;
mod interface;
mod service;

/// D-Bus interface name
pub const DBUS_INTERFACE: &str = "org.kde.juhradialmx.Daemon";

/// D-Bus object path
pub const DBUS_PATH: &str = "/org/kde/juhradialmx/Daemon";

/// D-Bus bus name
pub const DBUS_NAME: &str = "org.kde.juhradialmx";

// Re-export public API
pub use init::{init_dbus_service, init_dbus_service_with_device};
pub use service::JuhRadialService;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dbus_constants() {
        assert_eq!(DBUS_INTERFACE, "org.kde.juhradialmx.Daemon");
        assert_eq!(DBUS_PATH, "/org/kde/juhradialmx/Daemon");
        assert_eq!(DBUS_NAME, "org.kde.juhradialmx");
    }
}
