# Story 5.2: Configurable Haptic Intensity

Status: complete

## Story

As a Linux user,
I want to adjust the overall haptic intensity to my preference,
So that the feedback is comfortable and not jarring.

## Acceptance Criteria

1. **Given** the configuration file at `~/.config/juhradial/config.json`
   **When** the daemon reads the haptic section
   **Then** it loads the `haptic_intensity` value (0-100, default 50)

2. **Given** haptic intensity is set to 0
   **When** any haptic event should trigger
   **Then** no HID++ haptic command is sent

## Tasks / Subtasks

- [x] Task 1: Implement config file loading (AC: #1)
  - [x] 1.1: Implement `Config::load()` to read JSON from file path
  - [x] 1.2: Create default config if file doesn't exist
  - [x] 1.3: Validate haptic_intensity is clamped to 0-100

- [x] Task 2: Add HapticConfig subsection (AC: #1)
  - [x] 2.1: Create `HapticConfig` struct with intensity and enabled fields
  - [x] 2.2: Add per-event intensity overrides (menu_appear, slice_change, confirm, invalid)
  - [x] 2.3: Validate all intensity values on load

- [x] Task 3: Integrate Config with HapticManager (AC: #1, #2)
  - [x] 3.1: Add `HapticManager::from_config()` constructor
  - [x] 3.2: Add `HapticManager::update_from_config()` for hot-reload
  - [x] 3.3: Support config hot-reload for haptic settings

- [x] Task 4: Add unit tests (AC: #1, #2)
  - [x] 4.1: Test config file parsing (9 tests in config.rs)
  - [x] 4.2: Test default values when file missing
  - [x] 4.3: Test zero intensity disables haptics
  - [x] 4.4: Test intensity clamping

## Dev Notes

### Architecture

**Files to modify:**
- `daemon/src/config.rs` - Implement JSON loading/saving
- `daemon/src/hidpp.rs` - Add `from_config()` constructor

### Config File Location

```
~/.config/juhradial/config.json
```

### Config Schema

```json
{
  "haptics": {
    "enabled": true,
    "intensity": 50,
    "per_event": {
      "menu_appear": 20,
      "slice_change": 40,
      "confirm": 80,
      "invalid": 30
    }
  },
  "theme": "catppuccin-mocha",
  "blur_enabled": true
}
```

### UX Spec Reference

From Section 2.3 - Global intensity applies as multiplier to per-event values.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Tests require Linux target with Rust toolchain

### Completion Notes List

- Implemented complete config.rs with JSON loading/saving
- Created HapticConfig struct with enabled, intensity, per_event, debounce_ms fields
- Created HapticEventConfig for per-event intensity overrides
- Validation clamps all intensity values to 0-100
- `Config::load()` returns defaults if file doesn't exist
- `Config::save()` creates directory and writes pretty JSON
- `HapticManager::from_config()` constructor from HapticConfig
- `HapticManager::update_from_config()` for hot-reload support
- Added `dirs` crate for platform-specific config directory
- 9 unit tests in config.rs, 3 new tests in hidpp.rs

### File List

- daemon/src/config.rs (MODIFIED - complete rewrite, 422 lines)
- daemon/src/hidpp.rs (MODIFIED - added from_config, update_from_config, 3 tests)
- daemon/Cargo.toml (MODIFIED - added dirs = "5")

### Change Log

- 2025-12-12: Story 5.2 implemented - Configurable Haptic Intensity complete
