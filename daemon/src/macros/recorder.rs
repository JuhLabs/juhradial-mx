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

/// Mouse button name for an evdev BTN_* code (what MacroAction::MouseDown
/// and mouse_button_to_number take).
fn evdev_code_to_button_name(code: u16) -> Option<&'static str> {
    match code {
        0x110 => Some("left"),
        0x111 => Some("right"),
        0x112 => Some("middle"),
        0x113 => Some("back"),
        0x114 => Some("forward"),
        _ => None,
    }
}

/// Drop the clicks that start and stop a recording from the Settings window:
/// the release of the Record click at the start, the Stop click at the end.
fn trim_ui_clicks(events: &mut Vec<MacroEvent>) {
    while events.first().is_some_and(|e| e.event_type == RecordedEventType::MouseUp) {
        events.remove(0);
    }
    let n = events.len();
    if n >= 2
        && events[n - 1].event_type == RecordedEventType::MouseUp
        && events[n - 2].event_type == RecordedEventType::MouseDown
        && events[n - 1].key == events[n - 2].key
    {
        events.truncate(n - 2);
    } else if events.last().is_some_and(|e| e.event_type == RecordedEventType::MouseDown) {
        events.pop();
    }
}

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
        183 => "F13", 184 => "F14", 185 => "F15", 186 => "F16", 187 => "F17", 188 => "F18",
        189 => "F19", 190 => "F20", 191 => "F21", 192 => "F22", 193 => "F23", 194 => "F24",
        99 => "Print", 119 => "Pause", 127 => "Menu",
        113 => "XF86AudioMute", 114 => "XF86AudioLowerVolume", 115 => "XF86AudioRaiseVolume",
        163 => "XF86AudioNext", 164 => "XF86AudioPlay", 165 => "XF86AudioPrev",
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

    /// One recording thread per keyboard
    threads: Vec<std::thread::JoinHandle<()>>,

    /// Names of the keyboards being recorded (for the Settings live view)
    devices: Vec<String>,
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
            threads: Vec::new(),
            devices: Vec::new(),
        }
    }

    /// Start recording keyboard events
    ///
    /// Records key press/release events with timestamps from every keyboard
    /// in /dev/input (a laptop keyboard and an MX Keys alike). Fails at once
    /// when there is none, instead of "recording" nothing.
    pub fn start(&mut self) -> Result<(), RecorderError> {
        if self.recording.load(Ordering::Relaxed) {
            return Err(RecorderError::AlreadyRecording);
        }
        let keyboards = find_keyboard_devices();
        if keyboards.is_empty() {
            return Err(RecorderError::NoKeyboard);
        }
        // Mice too, for clicks (P1 #13 "mouse capture").
        let keyboards: Vec<_> = keyboards.into_iter().chain(find_mouse_devices()).collect();

        // Reset state
        {
            let mut state = self.state.lock().unwrap();
            state.events.clear();
            state.start_time = Instant::now();
        }

        self.recording.store(true, Ordering::Relaxed);

        self.devices = keyboards.iter().map(|(_, name)| name.clone()).collect();
        for (path, name) in keyboards {
            let recording = self.recording.clone();
            let state = self.state.clone();
            self.threads.push(std::thread::spawn(move || {
                if let Err(e) = record_events(recording, state, &path) {
                    tracing::error!(error = %e, device = %name, "Recording thread error");
                }
            }));
        }

        tracing::info!(devices = ?self.devices, "Macro recording started");
        Ok(())
    }

    /// Stop recording and return captured events
    pub fn stop(&mut self) -> Vec<MacroEvent> {
        self.recording.store(false, Ordering::Relaxed);

        // Wait for the recording threads to finish. A panicked thread has
        // recorded nothing from its device; say so instead of hiding it.
        for handle in self.threads.drain(..) {
            if handle.join().is_err() {
                tracing::error!("Recording thread panicked; its device recorded nothing");
            }
        }

        let state = self.state.lock().unwrap();
        let mut events = state.events.clone();
        trim_ui_clicks(&mut events);

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

    /// The keyboards the last start() records from.
    pub fn devices(&self) -> &[String] {
        &self.devices
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

/// Record key events from one keyboard device.
#[cfg(target_os = "linux")]
fn record_events(
    recording: Arc<AtomicBool>,
    state: Arc<Mutex<RecorderState>>,
    keyboard_path: &std::path::Path,
) -> Result<(), RecorderError> {
    use evdev::{Device, EventType};

    tracing::info!(path = %keyboard_path.display(), "Recording from keyboard device");

    let device = Device::open(keyboard_path)
        .map_err(|e| RecorderError::DeviceError(format!("Failed to open keyboard: {}", e)))?;

    // This thread has no tokio context of its own, so it builds a runtime and
    // creates the async event stream inside it: registering the fd, like the
    // read timeouts below, needs a running runtime. Created outside, the
    // stream panicked the thread before the first event and every recording
    // came back empty.
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| RecorderError::DeviceError(format!("Failed to create runtime: {}", e)))?;

    rt.block_on(async {
        let mut events = device
            .into_event_stream()
            .map_err(|e| RecorderError::DeviceError(format!("Failed to create event stream: {}", e)))?;

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

                    let (key_name, event_type) = if let Some(button) = evdev_code_to_button_name(code) {
                        let t = if value == 1 { RecordedEventType::MouseDown } else { RecordedEventType::MouseUp };
                        (button.to_string(), t)
                    } else {
                        match evdev_code_to_key_name(code) {
                            Some(name) => {
                                let t = if value == 1 { RecordedEventType::KeyDown } else { RecordedEventType::KeyUp };
                                (name, t)
                            }
                            None => {
                                tracing::debug!(code, "Unknown key code, skipping");
                                continue;
                            }
                        }
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
        Ok(())
    })
}

/// Every real keyboard in /dev/input: (path, name). Synthetic keyboards
/// (ydotool's uinput device, our own virtual mouse) are skipped, or playback
/// and injected shortcuts would be recorded too.
#[cfg(target_os = "linux")]
fn find_keyboard_devices() -> Vec<(std::path::PathBuf, String)> {
    use evdev::{Device, EventType, KeyCode};

    let Ok(entries) = std::fs::read_dir("/dev/input") else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.file_name().and_then(|n| n.to_str()).is_some_and(|n| n.starts_with("event")) {
            continue;
        }
        let Ok(device) = Device::open(&path) else { continue };
        let name = device.name().unwrap_or("").to_string();
        if !is_real_keyboard_name(&name) || !device.supported_events().contains(EventType::KEY) {
            continue;
        }
        let letters = device
            .supported_keys()
            .is_some_and(|keys| keys.contains(KeyCode::KEY_A) && keys.contains(KeyCode::KEY_Z));
        if letters {
            out.push((path, name));
        }
    }
    out.sort();
    out
}

#[cfg(not(target_os = "linux"))]
fn find_keyboard_devices() -> Vec<(std::path::PathBuf, String)> {
    Vec::new()
}

/// Every mouse in /dev/input (left button + relative motion), for clicks.
/// While the daemon grabs the MX mouse its events arrive through our
/// virtual mouse, so that one counts; ydotool's device never does.
#[cfg(target_os = "linux")]
fn find_mouse_devices() -> Vec<(std::path::PathBuf, String)> {
    use evdev::{Device, KeyCode, RelativeAxisCode};

    let Ok(entries) = std::fs::read_dir("/dev/input") else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.file_name().and_then(|n| n.to_str()).is_some_and(|n| n.starts_with("event")) {
            continue;
        }
        let Ok(device) = Device::open(&path) else { continue };
        let name = device.name().unwrap_or("").to_string();
        if name.to_ascii_lowercase().contains("ydotool") {
            continue;
        }
        let buttons = device.supported_keys().is_some_and(|k| k.contains(KeyCode::BTN_LEFT));
        let motion = device
            .supported_relative_axes()
            .is_some_and(|r| r.contains(RelativeAxisCode::REL_X));
        if buttons && motion {
            out.push((path, name));
        }
    }
    out.sort();
    out
}

#[cfg(not(target_os = "linux"))]
fn find_mouse_devices() -> Vec<(std::path::PathBuf, String)> {
    Vec::new()
}

fn is_real_keyboard_name(name: &str) -> bool {
    let low = name.to_ascii_lowercase();
    !(low.contains("ydotool") || name == crate::evdev::VIRTUAL_DEVICE_NAME)
}

/// Non-Linux stub
#[cfg(not(target_os = "linux"))]
fn record_events(
    _recording: Arc<AtomicBool>,
    _state: Arc<Mutex<RecorderState>>,
    _keyboard_path: &std::path::Path,
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
        assert_eq!(evdev_code_to_key_name(183), Some("F13".to_string()));
        assert_eq!(evdev_code_to_key_name(104), Some("Page_Up".to_string()));
    }

    fn ev(t: RecordedEventType, key: &str) -> MacroEvent {
        MacroEvent { timestamp_ms: 0, event_type: t, key: key.into() }
    }

    #[test]
    fn record_and_stop_clicks_are_trimmed() {
        use RecordedEventType::*;
        let mut events = vec![ev(MouseUp, "left"), ev(KeyDown, "a"), ev(KeyUp, "a"),
                              ev(MouseDown, "right"), ev(MouseUp, "right"),
                              ev(MouseDown, "left"), ev(MouseUp, "left")];
        trim_ui_clicks(&mut events);
        let kinds: Vec<_> = events.iter().map(|e| (e.event_type.clone(), e.key.as_str())).collect();
        assert_eq!(kinds, vec![(KeyDown, "a"), (KeyUp, "a"), (MouseDown, "right"), (MouseUp, "right")]);
        let mut pressed_only = vec![ev(KeyDown, "a"), ev(MouseDown, "left")];
        trim_ui_clicks(&mut pressed_only);
        assert_eq!(pressed_only.len(), 1);
        assert_eq!(evdev_code_to_button_name(0x113), Some("back"));
    }

    #[test]
    fn synthetic_keyboards_are_not_recorded() {
        assert!(!is_real_keyboard_name("ydotoold virtual device"));
        assert!(!is_real_keyboard_name(crate::evdev::VIRTUAL_DEVICE_NAME));
        assert!(is_real_keyboard_name("Logitech MX Keys S"));
    }

    #[test]
    fn recorded_key_names_can_be_played_back() {
        // every name the recorder writes has a uinput code for Wayland playback
        for code in 1u16..=200 {
            if let Some(name) = evdev_code_to_key_name(code) {
                assert!(crate::actions::key_code(&name).is_some() || name == "Caps_Lock", "{name}");
            }
        }
    }

    /// The recording thread end to end on a uinput keyboard. The thread used
    /// to create its event stream outside its own runtime and panic before
    /// the first event, so every recording came back empty.
    #[cfg(target_os = "linux")]
    #[test]
    #[ignore] // Needs /dev/uinput; run with `cargo test -- --ignored` on a desktop.
    fn recording_thread_captures_keys_from_a_uinput_keyboard() {
        use evdev::{uinput::VirtualDevice, AttributeSet, Device, EventType, InputEvent, KeyCode};
        use std::time::Duration;

        let mut keys = AttributeSet::<KeyCode>::new();
        keys.insert(KeyCode::KEY_A);
        keys.insert(KeyCode::KEY_Z);
        let mut keyboard = VirtualDevice::builder()
            .expect("uinput available")
            .name("JuhRadial recorder test keyboard")
            .with_keys(&keys)
            .expect("key set")
            .build()
            .expect("virtual keyboard");
        let node = keyboard
            .enumerate_dev_nodes_blocking()
            .expect("dev nodes")
            .find_map(Result::ok)
            .expect("event node");
        // udev may still be settling the new node's permissions.
        let mut openable = false;
        for _ in 0..50 {
            if Device::open(&node).is_ok() {
                openable = true;
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(openable, "open the new node");

        let recording = Arc::new(AtomicBool::new(true));
        let state = Arc::new(Mutex::new(RecorderState { events: Vec::new(), start_time: Instant::now() }));
        let thread = {
            let (recording, state) = (recording.clone(), state.clone());
            std::thread::spawn(move || record_events(recording, state, &node))
        };
        std::thread::sleep(Duration::from_millis(300));
        keyboard
            .emit(&[InputEvent::new(EventType::KEY.0, KeyCode::KEY_A.0, 1)])
            .expect("press");
        keyboard
            .emit(&[InputEvent::new(EventType::KEY.0, KeyCode::KEY_A.0, 0)])
            .expect("release");
        std::thread::sleep(Duration::from_millis(300));
        recording.store(false, Ordering::Relaxed);

        let result = thread.join().expect("recording thread must not panic");
        assert!(result.is_ok(), "{result:?}");
        let captured: Vec<(RecordedEventType, String)> = state
            .lock()
            .unwrap()
            .events
            .iter()
            .map(|e| (e.event_type.clone(), e.key.clone()))
            .collect();
        assert_eq!(
            captured,
            vec![
                (RecordedEventType::KeyDown, "a".to_string()),
                (RecordedEventType::KeyUp, "a".to_string()),
            ]
        );
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
