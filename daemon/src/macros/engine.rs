//! Macro playback engine
//!
//! Executes macro action sequences with precise timing using a dedicated thread.
//! Supports all five repeat modes and a "no delay" mode for fastest execution.
//! Communicates with the calling code via Arc<AtomicBool> stop signals.

use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use super::types::{MacroAction, MacroConfig, PlaybackState, RepeatMode, mouse_button_to_number};

// Re-export for main.rs convenience
pub use super::triggers::SharedTriggerMap;

// ============================================================================
// Key Synthesis
// ============================================================================

/// Synthesize a key press via xdotool or ydotool
///
/// Reuses the same fallback pattern from actions.rs:
/// try xdotool first (X11), then ydotool (Wayland).
fn synthesize_key(action: &str, key: &str) {
    // Try xdotool first
    let result = Command::new("xdotool")
        .args([action, key])
        .spawn();

    match result {
        Ok(_) => {}
        Err(_) => {
            // Fallback to ydotool
            let _ = Command::new("ydotool")
                .args([action, key])
                .spawn();
        }
    }
}

/// Synthesize a mouse button event
fn synthesize_mouse(action: &str, button: u8) {
    let button_str = button.to_string();
    let result = Command::new("xdotool")
        .args([action, &button_str])
        .spawn();

    if result.is_err() {
        let _ = Command::new("ydotool")
            .args([action, &button_str])
            .spawn();
    }
}

/// Type a text string by synthesizing key events
fn synthesize_text(text: &str) {
    let result = Command::new("xdotool")
        .args(["type", "--", text])
        .spawn();

    if result.is_err() {
        let _ = Command::new("ydotool")
            .args(["type", "--", text])
            .spawn();
    }
}

/// Synthesize a scroll event
fn synthesize_scroll(amount: i32) {
    let direction = if amount > 0 { "4" } else { "5" }; // 4=up, 5=down
    let clicks = amount.unsigned_abs().to_string();

    let result = Command::new("xdotool")
        .args(["click", "--repeat", &clicks, direction])
        .spawn();

    if result.is_err() {
        // ydotool uses different scroll interface
        let _ = Command::new("ydotool")
            .args(["click", direction])
            .spawn();
    }
}

// ============================================================================
// Action Execution
// ============================================================================

/// Execute a single macro action
///
/// Returns immediately after spawning the subprocess (non-blocking).
fn execute_action(action: &MacroAction) {
    match action {
        MacroAction::KeyDown(key) => synthesize_key("keydown", key),
        MacroAction::KeyUp(key) => synthesize_key("keyup", key),
        MacroAction::MouseDown(btn) => synthesize_mouse("mousedown", mouse_button_to_number(btn)),
        MacroAction::MouseUp(btn) => synthesize_mouse("mouseup", mouse_button_to_number(btn)),
        MacroAction::MouseClick(btn) => {
            let n = mouse_button_to_number(btn);
            synthesize_mouse("mousedown", n);
            synthesize_mouse("mouseup", n);
        }
        MacroAction::Delay(_) => {} // Handled by the timing loop
        MacroAction::Text(text) => synthesize_text(text),
        MacroAction::Scroll { direction, amount } => {
            let sign = if direction == "down" || direction == "left" { -1 } else { 1 };
            synthesize_scroll(sign * amount);
        }
    }
}

/// Get the effective delay for an action, respecting standard_delay override
fn effective_delay(action: &MacroAction, config: &MacroConfig) -> Duration {
    match action {
        MacroAction::Delay(ms) => {
            if config.use_standard_delay {
                Duration::from_millis(config.standard_delay_ms)
            } else if *ms == 0 {
                Duration::ZERO
            } else {
                Duration::from_millis(*ms)
            }
        }
        _ => Duration::ZERO,
    }
}

/// Execute a list of actions once, checking the stop signal between each
fn execute_actions_once(
    actions: &[MacroAction],
    config: &MacroConfig,
    stop_signal: &AtomicBool,
) {
    for action in actions {
        if stop_signal.load(Ordering::Relaxed) {
            return;
        }

        match action {
            MacroAction::Delay(_) => {
                let delay = effective_delay(action, config);
                if !delay.is_zero() {
                    // Sleep in small increments to check stop signal frequently
                    let mut remaining = delay;
                    let check_interval = Duration::from_millis(5);
                    while remaining > Duration::ZERO {
                        if stop_signal.load(Ordering::Relaxed) {
                            return;
                        }
                        let sleep_time = remaining.min(check_interval);
                        thread::sleep(sleep_time);
                        remaining = remaining.saturating_sub(sleep_time);
                    }
                }
            }
            _ => execute_action(action),
        }
    }
}

// ============================================================================
// Macro Engine
// ============================================================================

/// Macro playback engine
///
/// Manages macro execution in a separate thread with stop signal support.
pub struct MacroEngine {
    /// Stop signal shared with the playback thread
    stop_signal: Arc<AtomicBool>,

    /// Current playback state
    state: PlaybackState,

    /// Handle to the playback thread (if running)
    thread_handle: Option<thread::JoinHandle<()>>,

    /// Repeat mode of the currently running macro (for release detection)
    current_mode: Option<RepeatMode>,
}

impl MacroEngine {
    /// Create a new macro engine
    pub fn new() -> Self {
        Self {
            stop_signal: Arc::new(AtomicBool::new(false)),
            state: PlaybackState::Idle,
            thread_handle: None,
            current_mode: None,
        }
    }

    /// Execute a macro configuration
    ///
    /// Spawns a dedicated thread for playback. If a macro is already playing,
    /// the behavior depends on the repeat mode:
    /// - Toggle mode: stops the current playback
    /// - Other modes: stops current and starts new
    pub fn execute(&mut self, config: MacroConfig) {
        // Handle toggle mode: second call stops playback
        if self.state == PlaybackState::ToggledOn && config.repeat_mode == RepeatMode::Toggle {
            tracing::info!(id = %config.id, "Toggle macro off");
            self.stop();
            return;
        }

        // Stop any currently running macro
        if self.state != PlaybackState::Idle {
            self.stop();
        }

        // Reset stop signal
        self.stop_signal = Arc::new(AtomicBool::new(false));
        let stop = self.stop_signal.clone();

        // Set state and track current mode for release detection
        self.current_mode = Some(config.repeat_mode.clone());
        self.state = match config.repeat_mode {
            RepeatMode::Toggle => PlaybackState::ToggledOn,
            _ => PlaybackState::Playing,
        };

        let macro_id = config.id.clone();
        tracing::info!(id = %macro_id, mode = ?config.repeat_mode, "Starting macro playback");

        // Spawn playback thread
        self.thread_handle = Some(thread::spawn(move || {
            run_playback(config, stop);
        }));
    }

    /// Stop the currently playing macro
    pub fn stop(&mut self) {
        if self.state == PlaybackState::Idle {
            return;
        }

        tracing::info!("Stopping macro playback");
        self.stop_signal.store(true, Ordering::Relaxed);

        // Wait for thread to finish with a timeout to avoid deadlocks
        if let Some(handle) = self.thread_handle.take() {
            // Give the thread up to 2 seconds to finish
            let start = std::time::Instant::now();
            let timeout = Duration::from_secs(2);
            while !handle.is_finished() {
                if start.elapsed() >= timeout {
                    tracing::warn!("Macro playback thread did not stop within 2s, abandoning");
                    break;
                }
                thread::sleep(Duration::from_millis(10));
            }
            if handle.is_finished() {
                let _ = handle.join();
            }
        }

        self.state = PlaybackState::Idle;
        self.current_mode = None;
    }

    /// Whether the current macro should stop when the trigger button is released
    ///
    /// Only WhileHolding and Sequence modes stop on release.
    /// Once/RepeatN complete on their own; Toggle uses press-to-toggle.
    pub fn should_stop_on_release(&self) -> bool {
        matches!(
            self.current_mode,
            Some(RepeatMode::WhileHolding) | Some(RepeatMode::Sequence)
        )
    }

    /// Check if a macro is currently running
    pub fn is_running(&self) -> bool {
        self.state != PlaybackState::Idle
    }

    /// Get current playback state
    pub fn state(&self) -> PlaybackState {
        self.state
    }

    /// Get a clone of the stop signal (for WhileHolding mode - cleared on button release)
    pub fn stop_signal(&self) -> Arc<AtomicBool> {
        self.stop_signal.clone()
    }
}

impl Default for MacroEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for MacroEngine {
    fn drop(&mut self) {
        self.stop();
    }
}

// ============================================================================
// Playback Thread
// ============================================================================

/// Run macro playback in the dedicated thread
///
/// Dispatches to the correct playback strategy based on repeat mode.
fn run_playback(config: MacroConfig, stop: Arc<AtomicBool>) {
    match &config.repeat_mode {
        RepeatMode::Once => {
            execute_actions_once(&config.actions, &config, &stop);
        }

        RepeatMode::WhileHolding | RepeatMode::Toggle => {
            // Loop until stop signal
            while !stop.load(Ordering::Relaxed) {
                execute_actions_once(&config.actions, &config, &stop);
            }
        }

        RepeatMode::RepeatN => {
            let n = config.repeat_count;
            for i in 0..n {
                if stop.load(Ordering::Relaxed) {
                    tracing::debug!(iteration = i, total = n, "RepeatN stopped early");
                    return;
                }
                execute_actions_once(&config.actions, &config, &stop);
            }
        }

        RepeatMode::Sequence => {
            if let Some(ref seq) = config.sequence_actions {
                // Press phase: execute once
                execute_actions_once(&seq.press, &config, &stop);

                // Hold phase: loop while not stopped
                while !stop.load(Ordering::Relaxed) {
                    if seq.hold.is_empty() {
                        // Nothing to loop, just wait
                        thread::sleep(Duration::from_millis(10));
                    } else {
                        execute_actions_once(&seq.hold, &config, &stop);
                    }
                }

                // Release phase: execute once (even after stop)
                let no_stop = AtomicBool::new(false);
                execute_actions_once(&seq.release, &config, &no_stop);
            } else {
                tracing::warn!("Sequence mode but no sequence_actions defined, falling back to Once");
                execute_actions_once(&config.actions, &config, &stop);
            }
        }
    }

    tracing::info!("Macro playback finished");
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::macros::types::MacroAction;

    fn test_config_once() -> MacroConfig {
        MacroConfig {
            id: "test-1".to_string(),
            name: "Test Once".to_string(),
            description: String::new(),
            repeat_mode: RepeatMode::Once,
            repeat_count: 3,
            actions: vec![
                MacroAction::Delay(10),
                MacroAction::Delay(10),
            ],
            sequence_actions: None,
            standard_delay_ms: 5,
            use_standard_delay: false,
            assigned_trigger: None,
        }
    }

    #[test]
    fn test_engine_creation() {
        let engine = MacroEngine::new();
        assert!(!engine.is_running());
        assert_eq!(engine.state(), PlaybackState::Idle);
    }

    #[test]
    fn test_effective_delay_recorded() {
        let config = test_config_once();
        let action = MacroAction::Delay(100);
        let delay = effective_delay(&action, &config);
        assert_eq!(delay, Duration::from_millis(100));
    }

    #[test]
    fn test_effective_delay_standard_override() {
        let mut config = test_config_once();
        config.use_standard_delay = true;
        config.standard_delay_ms = 25;

        let action = MacroAction::Delay(100);
        let delay = effective_delay(&action, &config);
        assert_eq!(delay, Duration::from_millis(25));
    }

    #[test]
    fn test_effective_delay_zero() {
        let config = test_config_once();
        let action = MacroAction::Delay(0);
        let delay = effective_delay(&action, &config);
        assert_eq!(delay, Duration::ZERO);
    }

    #[test]
    fn test_effective_delay_non_delay_action() {
        let config = test_config_once();
        let action = MacroAction::KeyDown("a".to_string());
        let delay = effective_delay(&action, &config);
        assert_eq!(delay, Duration::ZERO);
    }

    #[test]
    fn test_engine_stop_when_idle() {
        let mut engine = MacroEngine::new();
        // Should not panic
        engine.stop();
        assert_eq!(engine.state(), PlaybackState::Idle);
    }

    #[test]
    fn test_execute_once_with_delays() {
        // Test that execute_actions_once completes with delay-only actions
        let config = test_config_once();
        let stop = AtomicBool::new(false);
        execute_actions_once(&config.actions, &config, &stop);
        // Should complete without error
    }

    #[test]
    fn test_execute_stops_on_signal() {
        let config = MacroConfig {
            id: "test-stop".to_string(),
            name: "Test Stop".to_string(),
            description: String::new(),
            repeat_mode: RepeatMode::Once,
            repeat_count: 1,
            actions: vec![
                MacroAction::Delay(5000), // Long delay
            ],
            sequence_actions: None,
            standard_delay_ms: 10,
            use_standard_delay: false,
            assigned_trigger: None,
        };

        let stop = Arc::new(AtomicBool::new(false));
        let stop_clone = stop.clone();

        // Set stop signal after a short delay
        thread::spawn(move || {
            thread::sleep(Duration::from_millis(20));
            stop_clone.store(true, Ordering::Relaxed);
        });

        let start = std::time::Instant::now();
        execute_actions_once(&config.actions, &config, &stop);
        let elapsed = start.elapsed();

        // Should have been stopped well before the 5000ms delay
        assert!(elapsed.as_millis() < 500);
    }
}
