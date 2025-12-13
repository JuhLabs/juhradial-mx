//! Window focus tracking via KWin D-Bus
//!
//! Story 3.2: Detect Focused Window via KWin/Plasma APIs
//!
//! Monitors active window changes on KDE Plasma to enable
//! per-application profile switching.

use std::sync::Arc;
use tokio::sync::RwLock;
use zbus::{proxy, Connection, Result as ZbusResult};

/// KWin D-Bus service name (for future KWin integration)
#[allow(dead_code)]
const KWIN_SERVICE: &str = "org.kde.KWin";

/// KWin D-Bus object path (for future KWin integration)
#[allow(dead_code)]
const KWIN_PATH: &str = "/KWin";

/// Scripting interface path (for future KWin integration)
#[allow(dead_code)]
const KWIN_SCRIPTING_PATH: &str = "/Scripting";

/// Window tracker state
#[derive(Debug, Clone)]
pub struct WindowInfo {
    /// Window resource class (e.g., "firefox", "konsole")
    pub resource_class: String,
    /// Window caption/title (optional)
    pub caption: Option<String>,
}

impl Default for WindowInfo {
    fn default() -> Self {
        Self {
            resource_class: String::new(),
            caption: None,
        }
    }
}

/// Tracks the currently focused window via KWin D-Bus
///
/// Story 3.2: Implements window focus detection for per-app profiles.
pub struct WindowTracker {
    /// D-Bus connection to session bus
    connection: Option<Connection>,
    /// Last known active window info (cached)
    active_window: Arc<RwLock<WindowInfo>>,
    /// Whether KWin is available
    kwin_available: bool,
}

impl WindowTracker {
    /// Create a new WindowTracker
    ///
    /// Attempts to connect to KWin D-Bus service. If KWin is not available
    /// (e.g., not running on KDE Plasma), the tracker will be in fallback mode.
    pub async fn new() -> Self {
        let connection = match Connection::session().await {
            Ok(conn) => Some(conn),
            Err(e) => {
                tracing::warn!("Failed to connect to session bus: {}", e);
                None
            }
        };

        let kwin_available = if let Some(ref conn) = connection {
            Self::check_kwin_available(conn).await
        } else {
            false
        };

        if kwin_available {
            tracing::info!("WindowTracker connected to KWin D-Bus");
        } else {
            tracing::warn!("KWin not available - window tracking disabled");
        }

        Self {
            connection,
            active_window: Arc::new(RwLock::new(WindowInfo::default())),
            kwin_available,
        }
    }

    /// Check if KWin D-Bus service is available
    async fn check_kwin_available(connection: &Connection) -> bool {
        // Try to get the active window to verify KWin is responding
        let proxy = match KWinProxy::new(connection).await {
            Ok(p) => p,
            Err(_) => return false,
        };

        // Try to call a simple method to verify the service is alive
        proxy.active_client_id().await.is_ok()
    }

    /// Get the current active window's resource class
    ///
    /// Returns the cached value or queries KWin if cache is stale.
    /// Performance: This should complete in <5ms (NFR-004).
    pub async fn get_active_window_class(&self) -> Option<String> {
        if !self.kwin_available {
            return None;
        }

        let info = self.active_window.read().await;
        if !info.resource_class.is_empty() {
            return Some(info.resource_class.clone());
        }
        drop(info);

        // Query KWin for current active window
        self.refresh_active_window().await
    }

    /// Refresh the active window info from KWin
    ///
    /// Queries KWin D-Bus for the currently focused window's resource class.
    pub async fn refresh_active_window(&self) -> Option<String> {
        let connection = self.connection.as_ref()?;

        let start = std::time::Instant::now();

        // Get active client info via KWin proxy
        let proxy = match KWinProxy::new(connection).await {
            Ok(p) => p,
            Err(e) => {
                tracing::debug!("Failed to create KWin proxy: {}", e);
                return None;
            }
        };

        // Get active client ID first
        let client_id = match proxy.active_client_id().await {
            Ok(id) => id,
            Err(e) => {
                tracing::debug!("Failed to get active client ID: {}", e);
                return None;
            }
        };

        if client_id.is_empty() {
            // No active window (e.g., desktop focused)
            let mut info = self.active_window.write().await;
            info.resource_class.clear();
            info.caption = None;
            return None;
        }

        // Query the window's resource class
        let resource_class = match self.query_window_resource_class(connection, &client_id).await {
            Some(class) => class,
            None => {
                tracing::debug!("Failed to get resource class for client {}", client_id);
                return None;
            }
        };

        let elapsed = start.elapsed();
        if elapsed.as_millis() > 5 {
            tracing::warn!(
                latency_ms = elapsed.as_millis(),
                "Window class detection exceeded 5ms target (NFR-004)"
            );
        } else {
            tracing::debug!(
                resource_class = %resource_class,
                latency_us = elapsed.as_micros(),
                "Active window detected"
            );
        }

        // Update cache
        let mut info = self.active_window.write().await;
        info.resource_class = resource_class.clone();

        Some(resource_class)
    }

    /// Query a window's resource class by client ID
    async fn query_window_resource_class(
        &self,
        connection: &Connection,
        client_id: &str,
    ) -> Option<String> {
        // Use KWin scripting interface to get window properties
        // The client_id is typically a UUID or internal ID
        let script_proxy = match KWinScriptingProxy::new(connection).await {
            Ok(p) => p,
            Err(_) => return None,
        };

        // Try to get the resource class via scripting
        match script_proxy.get_window_resource_class(client_id).await {
            Ok(class) => Some(class.to_lowercase()),
            Err(e) => {
                tracing::debug!("Scripting query failed: {}, trying fallback", e);
                // Fallback: try parsing the client_id if it contains app info
                self.parse_client_id_fallback(client_id)
            }
        }
    }

    /// Fallback method to extract window class from client ID
    ///
    /// Some KWin versions encode app info in the client ID format.
    fn parse_client_id_fallback(&self, client_id: &str) -> Option<String> {
        // Client IDs sometimes contain the app name
        // Format varies: "{uuid}" or "appname-uuid" or just "uuid"
        if client_id.contains('-') {
            let parts: Vec<&str> = client_id.split('-').collect();
            if parts.len() > 1 {
                let potential_app = parts[0].to_lowercase();
                // Filter out UUID-like prefixes
                if !potential_app.chars().all(|c| c.is_ascii_hexdigit()) {
                    return Some(potential_app);
                }
            }
        }
        None
    }

    /// Check if window tracking is available
    pub fn is_available(&self) -> bool {
        self.kwin_available
    }

    /// Clear the cached window info
    pub async fn clear_cache(&self) {
        let mut info = self.active_window.write().await;
        info.resource_class.clear();
        info.caption = None;
    }
}

impl Default for WindowTracker {
    fn default() -> Self {
        // Synchronous default - creates without connection
        Self {
            connection: None,
            active_window: Arc::new(RwLock::new(WindowInfo::default())),
            kwin_available: false,
        }
    }
}

/// KWin D-Bus proxy for window management
#[proxy(
    interface = "org.kde.KWin",
    default_service = "org.kde.KWin",
    default_path = "/KWin"
)]
trait KWin {
    /// Get the active client (window) ID
    #[zbus(name = "activeClient")]
    fn active_client_id(&self) -> ZbusResult<String>;
}

/// KWin Scripting D-Bus proxy
#[proxy(
    interface = "org.kde.KWin.Scripting",
    default_service = "org.kde.KWin",
    default_path = "/Scripting"
)]
trait KWinScripting {
    /// Get window resource class by ID
    fn get_window_resource_class(&self, window_id: &str) -> ZbusResult<String>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_window_info_default() {
        let info = WindowInfo::default();
        assert!(info.resource_class.is_empty());
        assert!(info.caption.is_none());
    }

    #[test]
    fn test_window_tracker_default() {
        let tracker = WindowTracker::default();
        assert!(!tracker.is_available());
        assert!(tracker.connection.is_none());
    }

    #[test]
    fn test_parse_client_id_fallback() {
        let tracker = WindowTracker::default();

        // Test app name prefix extraction
        let result = tracker.parse_client_id_fallback("firefox-12345");
        assert_eq!(result, Some("firefox".to_string()));

        // Test konsole
        let result = tracker.parse_client_id_fallback("konsole-abc-123");
        assert_eq!(result, Some("konsole".to_string()));

        // Test UUID-only (should return None)
        let result = tracker.parse_client_id_fallback("a1b2c3d4-5678-90ab-cdef-1234567890ab");
        assert!(result.is_none());

        // Test no hyphen (should return None)
        let result = tracker.parse_client_id_fallback("randomstring");
        assert!(result.is_none());
    }

    #[test]
    fn test_window_info_clone() {
        let info = WindowInfo {
            resource_class: "firefox".to_string(),
            caption: Some("Mozilla Firefox".to_string()),
        };

        let cloned = info.clone();
        assert_eq!(cloned.resource_class, "firefox");
        assert_eq!(cloned.caption, Some("Mozilla Firefox".to_string()));
    }

    #[tokio::test]
    async fn test_window_tracker_no_dbus() {
        // This test will pass even without D-Bus connection
        // The tracker should gracefully handle missing KWin
        let tracker = WindowTracker::default();

        let result = tracker.get_active_window_class().await;
        assert!(result.is_none());
    }

    #[tokio::test]
    async fn test_clear_cache() {
        let tracker = WindowTracker::default();

        // Set some cached data
        {
            let mut info = tracker.active_window.write().await;
            info.resource_class = "test".to_string();
        }

        // Clear cache
        tracker.clear_cache().await;

        // Verify cleared
        let info = tracker.active_window.read().await;
        assert!(info.resource_class.is_empty());
    }
}
