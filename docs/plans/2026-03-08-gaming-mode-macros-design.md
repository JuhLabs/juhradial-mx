# Gaming Mode & Macro System Design

**Date:** 2026-03-08
**Version target:** v0.3.5+

## Decisions

| Decision | Choice |
|---|---|
| Gaming Mode | Full third mode with dedicated settings page |
| Macro Editor | Record + Edit (Logitech G Hub / SteelSeries style) |
| Repeat Modes | 5: once, hold-repeat, toggle, N-times, sequence (press/hold/release) |
| Macro Triggers | Mouse buttons + radial wheel slices |
| Gaming Features | Macros + DPI profiles + overlay disable |
| Startup Behavior | Remember last mode, first launch = Logitech, smart fallback |
| Macro Storage | Separate JSON files in ~/.config/juhradial/macros/ |
| Architecture | Split - Rust daemon (playback engine) + Python GTK4 (editor UI) |

## File Structure

### Daemon (Rust) - daemon/src/macros/

- `mod.rs` - Module exports
- `types.rs` - MacroAction, MacroConfig, RepeatMode enums/structs
- `engine.rs` - Playback engine (timing loop, repeat modes, 0ms no-delay mode)
- `recorder.rs` - Key/mouse event capture during recording
- `storage.rs` - Load/save macro JSON files
- `dpi.rs` - DPI profile switching via HID++

### Daemon - daemon/src/gaming.rs

- Gaming mode state (overlay suppress, active profile)

### Settings UI (Python/GTK4) - overlay/

- `settings_page_gaming.py` - Gaming Mode page (sidebar entry)
- `settings_page_macros.py` - Macro list/management (subpage)
- `settings_dialog_macro.py` - Macro editor dialog (timeline + record)
- `settings_macro_timeline.py` - Visual timeline widget (drag-drop action list)
- `settings_macro_recorder.py` - Recording dialog (start/stop, event display)
- `settings_macro_actions.py` - Action palette (keystroke, delay, click, text)
- `settings_macro_storage.py` - Python-side macro file I/O

## Macro JSON Format

Location: ~/.config/juhradial/macros/<id>.json

```json
{
  "id": "rapid-fire",
  "name": "Rapid Fire",
  "description": "Fast left-click spam",
  "repeat_mode": "toggle",
  "repeat_count": null,
  "use_standard_delay": false,
  "standard_delay_ms": 50,
  "actions": [
    {"type": "key_down", "key": "mouse_left", "delay_ms": 0},
    {"type": "key_up", "key": "mouse_left", "delay_ms": 30},
    {"type": "delay", "delay_ms": 20}
  ],
  "created": "2026-03-08T12:00:00Z",
  "modified": "2026-03-08T12:00:00Z"
}
```

### Action Types

- `key_down` / `key_up` - Individual key press/release
- `mouse_down` / `mouse_up` - Mouse button press/release
- `delay` - Timed pause (ms precision)
- `text` - Type a text string
- `scroll` - Mouse scroll event

### Repeat Modes

- `once` - Play macro exactly once
- `while_holding` - Loop while trigger button held
- `toggle` - First press starts loop, second press stops
- `repeat_n` - Loop N times then stop
- `sequence` - Different action sets for press/hold/release phases

## Config Additions

```json
{
  "device_mode": "logitech",
  "last_device_mode": "gaming",
  "gaming": {
    "suppress_overlay": true,
    "dpi_profiles": [
      {"name": "Precision", "dpi": 400},
      {"name": "Normal", "dpi": 1000},
      {"name": "Fast", "dpi": 2500}
    ],
    "active_dpi_profile": 1
  }
}
```

## D-Bus Additions

### Methods

- `StartMacroRecording()` - Begin capturing key/mouse events
- `StopMacroRecording() -> String` - Stop, return JSON of captured events
- `ExecuteMacro(id: String)` - Trigger macro playback by ID
- `StopMacro()` - Stop any running macro
- `SetGamingMode(enabled: bool)` - Toggle gaming mode
- `SetDPI(dpi: u16)` - Change mouse DPI

### Signals

- `MacroEventCaptured(event_json: String)` - Live event during recording
- `MacroPlaybackStarted(id: String)` - Macro began executing
- `MacroPlaybackStopped(id: String)` - Macro finished/stopped
- `GamingModeChanged(enabled: bool)` - Gaming mode toggled

## State Persistence

- `last_device_mode` saved to config.json on mode change
- On startup: read `last_device_mode`, validate (fallback to "logitech" if mode invalid or device missing)
- First-ever launch: no `last_device_mode` key exists, default to "logitech"
