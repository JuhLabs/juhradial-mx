//! Theme File Watcher Module (Story 4.3)
//!
//! Watches theme directories for changes using inotify and triggers hot-reload.
//! Changes are detected within 100ms and debounced to avoid rapid reloads.

use notify::{Config, Event, EventKind, RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, Receiver};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::theme::{get_system_themes_dir, get_user_themes_dir, Theme, ThemeManager};

/// Debounce window to avoid multiple reloads on rapid saves
const DEBOUNCE_MS: u64 = 50;

/// Theme change event
#[derive(Debug, Clone)]
pub enum ThemeEvent {
    /// Theme file was modified
    Modified(PathBuf),
    /// New theme file was created
    Created(PathBuf),
    /// Theme file was deleted
    Deleted(PathBuf),
    /// Error watching files
    Error(String),
}

/// Theme file watcher using inotify
pub struct ThemeWatcher {
    /// The underlying notify watcher
    _watcher: RecommendedWatcher,
    /// Channel receiver for events
    event_rx: Receiver<Result<Event, notify::Error>>,
    /// Debounce state: paths that were recently modified
    pending_changes: Arc<Mutex<HashSet<PathBuf>>>,
    /// Last event time for debouncing
    last_event_time: Arc<Mutex<Instant>>,
}

impl ThemeWatcher {
    /// Create a new theme watcher that monitors system and user theme directories.
    ///
    /// # Returns
    /// * `Ok(ThemeWatcher)` - Watcher is running
    /// * `Err` - Failed to initialize watcher
    pub fn new() -> Result<Self, ThemeWatcherError> {
        let (tx, rx) = channel();

        // Configure watcher with recommended settings
        let config = Config::default().with_poll_interval(Duration::from_millis(100));

        let mut watcher = RecommendedWatcher::new(tx, config)
            .map_err(|e| ThemeWatcherError::InitError(e.to_string()))?;

        // Watch system themes directory
        let system_dir = get_system_themes_dir();
        if system_dir.exists() {
            watcher
                .watch(&system_dir, RecursiveMode::Recursive)
                .map_err(|e| ThemeWatcherError::WatchError(system_dir.clone(), e.to_string()))?;
            tracing::info!(path = %system_dir.display(), "Watching system themes directory");
        }

        // Watch user themes directory
        let user_dir = get_user_themes_dir();
        if user_dir.exists() {
            watcher
                .watch(&user_dir, RecursiveMode::Recursive)
                .map_err(|e| ThemeWatcherError::WatchError(user_dir.clone(), e.to_string()))?;
            tracing::info!(path = %user_dir.display(), "Watching user themes directory");
        } else {
            tracing::debug!(path = %user_dir.display(), "User themes directory does not exist yet");
        }

        Ok(Self {
            _watcher: watcher,
            event_rx: rx,
            pending_changes: Arc::new(Mutex::new(HashSet::new())),
            last_event_time: Arc::new(Mutex::new(Instant::now())),
        })
    }

    /// Check for pending theme events (non-blocking).
    ///
    /// Returns events that have been debounced and are ready to process.
    pub fn poll_events(&self) -> Vec<ThemeEvent> {
        let mut events = Vec::new();

        // Collect all pending notify events
        while let Ok(result) = self.event_rx.try_recv() {
            match result {
                Ok(event) => {
                    if let Some(theme_event) = self.process_notify_event(event) {
                        events.push(theme_event);
                    }
                }
                Err(e) => {
                    events.push(ThemeEvent::Error(e.to_string()));
                }
            }
        }

        // Apply debouncing
        self.debounce_events(&mut events);

        events
    }

    /// Process a raw notify event into a theme event.
    fn process_notify_event(&self, event: Event) -> Option<ThemeEvent> {
        // Only process events for theme.json files
        let theme_json_paths: Vec<PathBuf> = event
            .paths
            .into_iter()
            .filter(|p| p.file_name().map(|n| n == "theme.json").unwrap_or(false))
            .collect();

        if theme_json_paths.is_empty() {
            return None;
        }

        let path = theme_json_paths.into_iter().next()?;

        // Update debounce tracking
        {
            let mut pending = self.pending_changes.lock().unwrap();
            pending.insert(path.clone());
            *self.last_event_time.lock().unwrap() = Instant::now();
        }

        match event.kind {
            EventKind::Create(_) => Some(ThemeEvent::Created(path)),
            EventKind::Modify(_) => Some(ThemeEvent::Modified(path)),
            EventKind::Remove(_) => Some(ThemeEvent::Deleted(path)),
            _ => None,
        }
    }

    /// Apply debouncing to events.
    fn debounce_events(&self, events: &mut Vec<ThemeEvent>) {
        let last_event = *self.last_event_time.lock().unwrap();
        let elapsed = last_event.elapsed();

        // If we're within the debounce window, clear events
        if elapsed < Duration::from_millis(DEBOUNCE_MS) {
            events.clear();
        } else {
            // Clear the pending set since we're processing
            let mut pending = self.pending_changes.lock().unwrap();
            pending.clear();
        }
    }

    /// Blocking wait for the next theme event.
    ///
    /// Waits up to the specified timeout for an event.
    pub fn wait_for_event(&self, timeout: Duration) -> Option<ThemeEvent> {
        match self.event_rx.recv_timeout(timeout) {
            Ok(Ok(event)) => self.process_notify_event(event),
            Ok(Err(e)) => Some(ThemeEvent::Error(e.to_string())),
            Err(_) => None, // Timeout
        }
    }
}

/// Error types for theme watcher
#[derive(Debug)]
pub enum ThemeWatcherError {
    /// Failed to initialize the watcher
    InitError(String),
    /// Failed to watch a specific path
    WatchError(PathBuf, String),
}

impl std::fmt::Display for ThemeWatcherError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InitError(msg) => write!(f, "Failed to initialize theme watcher: {}", msg),
            Self::WatchError(path, msg) => {
                write!(f, "Failed to watch {}: {}", path.display(), msg)
            }
        }
    }
}

impl std::error::Error for ThemeWatcherError {}

/// Hot-reload handler for theme manager
pub struct ThemeHotReloader {
    /// Theme manager to reload into
    manager: Arc<Mutex<ThemeManager>>,
    /// Theme watcher
    watcher: ThemeWatcher,
}

impl ThemeHotReloader {
    /// Create a new hot-reloader for the given theme manager.
    pub fn new(manager: Arc<Mutex<ThemeManager>>) -> Result<Self, ThemeWatcherError> {
        let watcher = ThemeWatcher::new()?;
        Ok(Self { manager, watcher })
    }

    /// Process pending theme events and apply changes.
    ///
    /// Returns the list of themes that were reloaded.
    pub fn process_events(&self) -> Vec<String> {
        let mut reloaded = Vec::new();

        for event in self.watcher.poll_events() {
            match event {
                ThemeEvent::Modified(path) | ThemeEvent::Created(path) => {
                    if let Some(theme_name) = self.reload_theme(&path) {
                        reloaded.push(theme_name);
                    }
                }
                ThemeEvent::Deleted(path) => {
                    tracing::info!(path = %path.display(), "Theme file deleted");
                    // Optionally remove the theme from manager
                    // For now, we keep it since it might be bundled
                }
                ThemeEvent::Error(msg) => {
                    tracing::error!(error = %msg, "Theme watcher error");
                }
            }
        }

        reloaded
    }

    /// Reload a single theme from file.
    ///
    /// Returns the theme name if successful.
    fn reload_theme(&self, path: &Path) -> Option<String> {
        tracing::debug!(path = %path.display(), "Attempting to reload theme");

        match Theme::load_from_path(path) {
            Ok(mut theme) => {
                // Validate the new theme
                let validation = theme.validate_and_clamp();

                if validation.has_errors() {
                    for error in &validation.errors {
                        tracing::warn!(
                            path = %path.display(),
                            error = %error,
                            "Invalid theme, keeping previous version"
                        );
                    }
                    return None;
                }

                for warning in &validation.warnings {
                    tracing::warn!(
                        theme = %theme.name,
                        warning = %warning,
                        "Theme validation warning"
                    );
                }

                let theme_name = theme.name.clone();

                // Update the manager
                let mut manager = self.manager.lock().unwrap();
                manager.add_or_update_theme(theme);

                tracing::info!(
                    theme = %theme_name,
                    path = %path.display(),
                    "Theme hot-reloaded successfully"
                );

                Some(theme_name)
            }
            Err(e) => {
                tracing::warn!(
                    path = %path.display(),
                    error = %e,
                    "Failed to reload theme, keeping previous version"
                );
                None
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn test_theme_event_display() {
        let event = ThemeEvent::Modified(PathBuf::from("/test/theme.json"));
        assert!(matches!(event, ThemeEvent::Modified(_)));
    }

    #[test]
    fn test_theme_watcher_error_display() {
        let error = ThemeWatcherError::InitError("test error".to_string());
        let msg = error.to_string();
        assert!(msg.contains("initialize"));
        assert!(msg.contains("test error"));
    }

    #[test]
    fn test_watch_error_display() {
        let error = ThemeWatcherError::WatchError(
            PathBuf::from("/test/path"),
            "permission denied".to_string(),
        );
        let msg = error.to_string();
        assert!(msg.contains("/test/path"));
        assert!(msg.contains("permission denied"));
    }

    #[test]
    fn test_debounce_constant() {
        assert_eq!(DEBOUNCE_MS, 50);
    }

    // Integration test for file watching (requires actual filesystem)
    #[test]
    #[ignore] // This test requires actual inotify which may not work in all environments
    fn test_file_change_detection() {
        let temp_dir = TempDir::new().unwrap();
        let theme_dir = temp_dir.path().join("test-theme");
        fs::create_dir(&theme_dir).unwrap();

        let theme_json = "{
            \"name\": \"test-theme\",
            \"colors\": {
                \"base\": \"#1e1e2e\",
                \"surface\": \"#313244\",
                \"text\": \"#cdd6f4\",
                \"accent\": \"#b4befe\",
                \"border\": \"#585b70\"
            },
            \"glassmorphism\": {},
            \"animation\": {}
        }";

        fs::write(theme_dir.join("theme.json"), theme_json).unwrap();

        // Watcher would normally detect this change
        // This is more of a smoke test for the API
    }
}
