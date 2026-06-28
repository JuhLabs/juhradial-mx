# Story 5.4: Runtime-Only Commands (No Memory Writes)

Status: complete

## Story

As a cross-platform mouse user,
I want JuhRadial MX to never write to my mouse's onboard memory,
So that my mouse configuration remains compatible with macOS/Windows.

## Acceptance Criteria

1. **Given** the haptic subsystem is initialized
   **When** any haptic command is constructed
   **Then** it uses only volatile/runtime HID++ commands
   **And** no persistent memory write commands are ever used

2. **Given** the mouse is disconnected and reconnected
   **When** the daemon re-initializes haptic support
   **Then** no configuration is persisted on the device
   **And** the mouse behaves identically to before JuhRadial MX was installed

## Tasks / Subtasks

- [x] Task 1: Audit existing code for memory write safety (AC: #1)
  - [x] 1.1: Review all HID++ commands used in hidpp.rs
  - [x] 1.2: Document which commands are volatile vs persistent
  - [x] 1.3: Verify no SET_LONG_REGISTER or profile write commands exist

- [x] Task 2: Add compile-time safety markers (AC: #1)
  - [x] 2.1: Create blocklisted_features module with persistent feature IDs
  - [x] 2.2: Create allowed_features module with safe feature IDs
  - [x] 2.3: Document SAFETY comments on all HID++ send functions

- [x] Task 3: Add runtime assertions (AC: #1, #2)
  - [x] 3.1: Add verify_feature_safety() function
  - [x] 3.2: Block blocklisted features from feature_table during enumeration
  - [x] 3.3: Add SafetyViolation error type with feature_id and reason

- [x] Task 4: Add verification tests (AC: #1, #2)
  - [x] 4.1: Test blocklisted features are detected (7 features)
  - [x] 4.2: Test allowed features pass safety check
  - [x] 4.3: Test verify_feature_safety returns error for blocklisted
  - [x] 4.4: Test FORCE_FEEDBACK (haptic) is explicitly safe

## Dev Notes

### Critical Safety Constraint

**NEVER write to onboard mouse memory.**

The MX Master 4 stores profiles, button mappings, and settings in onboard memory.
JuhRadial MX must ONLY use volatile/runtime HID++ commands that:
- Do not persist after power cycle
- Do not modify onboard profiles
- Do not interfere with Logitech Options+ settings

### HID++ Commands BLOCKLISTED

| Feature ID | Name | Risk |
|------------|------|------|
| 0x1B04 | Special Keys & Mouse Buttons | Persistent remap |
| 0x8060 | Report Rate | May persist |
| 0x8090 | Mode Status | Profile switching |
| 0x8100 | Onboard Profiles | Profile storage |
| 0x8110 | Mouse Button Spy | Profile modification |
| 0x1BC0 | Persistent Remappable Action | Key remapping |
| 0x1815 | Host Info | Pairing persistence |

### HID++ Commands ALLOWED (Safelist)

| Feature ID | Name | Safe |
|------------|------|------|
| 0x0000 | IRoot | Read-only |
| 0x0001 | IFeatureSet | Read-only |
| 0x0005 | Device Name | Read-only |
| 0x1000 | Battery Status | Read-only |
| 0x1300 | LED Control | Runtime-only |
| 0x8123 | Force Feedback | Runtime-only haptic |

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Tests require Linux target with Rust toolchain

### Completion Notes List

- Created `blocklisted_features` module with 7 forbidden feature IDs
- Created `allowed_features` module with 6 explicitly safe features
- Added `is_blocklisted()` and `blocklist_reason()` functions
- Added `is_allowed()` function for safelist checking
- Created `verify_feature_safety()` function for runtime validation
- Added `HapticError::SafetyViolation` variant with feature_id and reason
- Modified `enumerate_features()` to skip blocklisted features entirely
- Added #[macro_export] `assert_safe_feature!` macro for compile-time docs
- Enhanced SAFETY comments throughout HID++ code
- 10 new safety verification tests

### File List

- daemon/src/hidpp.rs (MODIFIED - added ~150 lines for safety verification)

### Change Log

- 2025-12-12: Story 5.4 created
- 2025-12-12: Story 5.4 implemented - Runtime-Only Commands verification complete
