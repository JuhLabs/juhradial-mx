//! Macro event recorder
//!
//! Captures keyboard events from /dev/input (evdev) during recording.
//! Records timestamps for delay calculation and emits D-Bus signals
//! for live UI updates.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

use super::types::{MacroEvent, RecordedEventType};

// ============================================================================
// Key Code Mapping
// ============================================================================

/// Convert an evdev key code to a human-readable key name
///
/// Uses the common key names that xdotool/ydotool understand.
fn evdev_code_to_key_name(code: u16) -> Option<String> {
    // Common key codes from linux/input-event-codes.h
    let name = match code {
        1 => "Escape",
        2 => "1", 3 => "2", 4 => "3", 5 => "4", 6 => "5",
        7 => "6", 8 => "7", 9 => "8", 10 => "9", 11 => "0",
        12 => "minus", 13 => "equal",
        14 => "BackSpace", 15 => "Tab",
        16 => "q", 17 => "w", 18 => "e", 19 => "r", 20 => "t",
        21 => "y", 22 => "u", 23 => "i", 24 => "o", 25 => "p",
        26 => "bracketleft", 27 => "bracketright",
        28 => "Return",
        29 => "ctrl",
        30 => "a", 31 => "s", 32 => "d", 33 => "f", 34 => "g",
        35 => "h", 36 => "j", 37 => "k", 38 => "l",
        39 => "semicolon", 40 => "apostrophe", 41 => "grave",
        42 => "shift",
        43 => "backslash",
        44 => "z", 45 => "x", 46 => "c", 47 => "v", 48 => "b",
        49 => "n", 50 => "m",
        51 => "comma", 52 => "period", 53 => "slash",
        54 => "shift", // Right shift
        56 => "alt",
        57 => "space",
        58 => "Caps_Lock",
        // F-keys
        59 => "F1", 60 => "F2", 61 => "F3", 62 => "F4",
        63 => "F5", 64 => "F6", 65 => "F7", 66 => "F8",
        67 => "F9", 68 => "F10", 87 => "F11", 88 => "F12",
        // Navigation
        102 => "Home", 103 => "Up", 104 => "Page_Up",
        105 => "Left", 106 => "Right",
        107 => "End", 108 => "Down", 109 => "Page_Down",
        110 => "Insert", 111 => "Delete",
        // Modifiers (right side)
        97 => "ctrl",  // Right ctrl
        100 => "alt",  // Right alt
        125 => "super", // Left super
        126 => "super", // Right super
        _ => return None,
    };
    Some(name.to_string())
}

// ============================================================================
// Macro Recorder
// ============================================================================

/// State shared between the recorder and its evdev thread
struct RecorderState {
    /// Captured events
    events: Vec<MacroEvent>,
    /// Recording start time
    start_time: Instant,
}

/// Macro event recorder
///
/// Captures keyboard input events from /dev/input for macro recording.
/// Records are stored with timestamps relative to recording start.
pub struct MacroRecorder {
    /// Whether recording is active
    recording: Arc<AtomicBool>,

    /// Shared state for captured events
    state: Arc<Mutex<RecorderState>>,

    /// Handle to the recording thread
    thread_handle: Option<std::thread::JoinHandle<()>>,
}

impl MacroRecorder {
    /// Create a new macro recorder
    pub fn new() -> Self {
        Self {
            recording: Arc::new(AtomicBool::new(false)),
            state: Arc::new(Mutex::new(RecorderState {
                events: Vec::new(),
                start_time: Instant::now(),
            })),
            thread_handle: None,
        }
    }

    /// Start recording keyboard events
    ///
    /// Opens the first available keyboard device from /dev/input and
    /// records key press/release events with timestamps.
    pub fn start(&mut self) -> Result<(), RecorderError> {
        if self.recording.load(Ordering::Relaxed) {
            return Err(RecorderError::AlreadyRecording);
        }

        // Reset state
        {
            let mut state = self.state.lock().unwrap();
            state.events.clear();
            state.start_time = Instant::now();
        }

        self.recording.store(true, Ordering::Relaxed);

        let recording = self.recording.clone();
        let state = self.state.clone();

        // Spawn recording thread
        self.thread_handle = Some(std::thread::spawn(move || {
            if let Err(e) = record_events(recording, state) {
                tracing::error!(error = %e, "Recording thread error");
            }
        }));

        tracing::info!("Macro recording started");
        Ok(())
    }

    /// Stop recording and return captured events
    pub fn stop(&mut self) -> Vec<MacroEvent> {
        self.recording.store(false, Ordering::Relaxed);

        // Wait for recording thread to finish
        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }

        let state = self.state.lock().unwrap();
        let events = state.events.clone();

        tracing::info!(event_count = events.len(), "Macro recording stopped");
        events
    }

    /// Check if currently recording
    pub fn is_recording(&self) -> bool {
        self.recording.load(Ordering::Relaxed)
    }

    /// Get a snapshot of events captured so far (for live UI preview)
    pub fn current_events(&self) -> Vec<MacroEvent> {
        self.state.lock().unwrap().events.clone()
    }
}

impl Default for MacroRecorder {
    fn default() -> Self {
        Self::new()
    }
}

// ============================================================================
// Recording Thread
// ============================================================================

/// Record keyboard events from evdev
///
/// Scans /dev/input for keyboard devices and captures key events.
#[cfg(target_os = "linux")]
fn record_events(
    recording: Arc<AtomicBool>,
    state: Arc<Mutex<RecorderState>>,
) -> Result<(), RecorderError> {
    use evdev::{Device, EventType};

    // Find a keyboard device
    let keyboard_path = find_keyboard_device()?;
    tracing::info!(path = %keyboard_path.display(), "Recording from keyboard device");

    let device = Device::open(&keyboard_path)
        .map_err(|e| RecorderError::DeviceError(format!("Failed to open keyboard: {}", e)))?;

    let mut events = device
        .into_event_stream()
        .map_err(|e| RecorderError::DeviceError(format!("Failed to create event stream: {}", e)))?;

    // Use tokio runtime to poll the async event stream from a sync thread
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_io()
        .build()
        .map_err(|e| RecorderError::DeviceError(format!("Failed to create runtime: {}", e)))?;

    rt.block_on(async {
        loop {
            if !recording.load(Ordering::Relaxed) {
                break;
            }

            // Use tokio::select with a timeout to check the recording flag periodically
            let event_result = tokio::time::timeout(
                std::time::Duration::from_millis(100),
                events.next_event(),
            )
            .await;

            match event_result {
                Ok(Ok(event)) => {
                    if event.event_type() != EventType::KEY {
                        continue;
                    }

                    let code = event.code();
                    let value = event.value();

                    // Skip repeat events (value=2)
                    if value == 2 {
                        continue;
                    }

                    let key_name = match evdev_code_to_key_name(code) {
                        Some(name) => name,
                        None => {
                            tracing::debug!(code, "Unknown key code, skipping");
                            continue;
                        }
                    };

                    let event_type = if value == 1 {
                        RecordedEventType::KeyDown
                    } else {
                        RecordedEventType::KeyUp
                    };

                    let mut state = state.lock().unwrap();
                    let timestamp_ms = state.start_time.elapsed().as_millis() as u64;

                    let macro_event = MacroEvent {
                        timestamp_ms,
                        event_type,
                        key: key_name.clone(),
                    };

                    tracing::debug!(
                        key = %key_name,
                        timestamp_ms,
                        "Captured key event"
                    );

                    state.events.push(macro_event);
                }
                Ok(Err(e)) => {
                    tracing::error!(error = %e, "Error reading event");
                    break;
                }
                Err(_) => {
                    // Timeout - check recording flag and continue
                    continue;
                }
            }
        }
    });

    Ok(())
}

/// Find a keyboard device in /dev/input
#[cfg(target_os = "linux")]
fn find_keyboard_device() -> Result<std::path::PathBuf, RecorderError> {
    use evdev::{Device, EventType, KeyCode};
    use std::fs;

    let input_dir = std::path::PathBuf::from("/dev/input");
    let entries = fs::read_dir(&input_dir)
        .map_err(|e| RecorderError::DeviceError(format!("Cannot read /dev/input: {}", e)))?;

    for entry in entries.flatten() {
        let path = entry.path();
        let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("");

        if !filename.starts_with("event") {
            continue;
        }

        let device = match Device::open(&path) {
            Ok(d) => d,
            Err(_) => continue,
        };

        // Check for keyboard capabilities (has EV_KEY with letter keys)
        let has_keys = device.supported_events().contains(EventType::KEY);
        if !has_keys {
            continue;
        }

        // Verify it has actual keyboard keys (not just mouse buttons)
        let has_keyboard_keys = device.supported_keys().map(|keys| {
            keys.contains(KeyCode::KEY_A) && keys.contains(KeyCode::KEY_Z)
        }).unwrap_or(false);

        if has_keyboard_keys {
            return Ok(path);
        }
    }

    Err(RecorderError::NoKeyboard)
}

/// Non-Linux stub
#[cfg(not(target_os = "linux"))]
fn record_events(
    _recording: Arc<AtomicBool>,
    _state: Arc<Mutex<RecorderState>>,
) -> Result<(), RecorderError> {
    tracing::warn!("Macro recording is only supported on Linux");
    Err(RecorderError::DeviceError("Not supported on this platform".to_string()))
}

// ============================================================================
// Error Type
// ============================================================================

/// Recorder error type
#[derive(Debug)]
pub enum RecorderError {
    /// Already recording
    AlreadyRecording,
    /// No keyboard device found
    NoKeyboard,
    /// Device access error
    DeviceError(String),
}

impl std::fmt::Display for RecorderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RecorderError::AlreadyRecording => write!(f, "Already recording"),
            RecorderError::NoKeyboard => write!(f, "No keyboard device found"),
            RecorderError::DeviceError(msg) => write!(f, "Device error: {}", msg),
        }
    }
}

impl std::error::Error for RecorderError {}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_evdev_code_to_key_name() {
        assert_eq!(evdev_code_to_key_name(30), Some("a".to_string()));
        assert_eq!(evdev_code_to_key_name(29), Some("ctrl".to_string()));
        assert_eq!(evdev_code_to_key_name(57), Some("space".to_string()));
        assert_eq!(evdev_code_to_key_name(28), Some("Return".to_string()));
        assert_eq!(evdev_code_to_key_name(59), Some("F1".to_string()));
        assert_eq!(evdev_code_to_key_name(9999), None);
    }

    #[test]
    fn test_recorder_creation() {
        let recorder = MacroRecorder::new();
        assert!(!recorder.is_recording());
        assert!(recorder.current_events().is_empty());
    }

    #[test]
    fn test_recorder_error_display() {
        let err = RecorderError::AlreadyRecording;
        assert!(format!("{}", err).contains("Already recording"));

        let err = RecorderError::NoKeyboard;
        assert!(format!("{}", err).contains("keyboard"));

        let err = RecorderError::DeviceError("test".to_string());
        assert!(format!("{}", err).contains("test"));
    }
}
