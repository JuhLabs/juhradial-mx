# Story 10.1: MX Master 4 Haptic Protocol Implementation

Status: in_progress

## Story

As a MX Master 4 user,
I want the haptic feedback to use the correct HID++ protocol for my device,
So that I feel tactile vibrations during menu interactions.

## Background

The original HID++ haptic implementation (Epic 5) used feature ID 0x8123 (Force Feedback), which is the correct feature for Logitech racing wheels like G920/G923. However, the MX Master 4 uses a different feature ID for its haptic motor.

**IMPORTANT UPDATE**: Initial research pointed to mx4notifications using `0x0B4E`, but this was INCORRECT. The authoritative source is [Solaar](https://github.com/pwr-Solaar/Solaar), which correctly identifies the feature as **`0x19B0`** (HAPTIC).

Reference implementations:
- [Solaar hidpp20_constants.py](https://github.com/pwr-Solaar/Solaar/blob/master/lib/logitech_receiver/hidpp20_constants.py) - **AUTHORITATIVE**
- [lukasfri/mx4notifications](https://github.com/lukasfri/mx4notifications) - Initial reference (used wrong feature ID)

### Key Findings

1. **Correct Feature ID**: MX Master 4 uses `0x19B0` for haptics (from Solaar's `HAPTIC` constant)
2. **Waveform-Based System**: The device supports predefined haptic waveforms (0x00-0x1B)
3. **Simple Command Format**: Just send waveform ID as parameter
4. **Official Waveform Names**: From Solaar's `HapticWaveForms`:
   - SHARP_STATE_CHANGE, DAMP_STATE_CHANGE, SHARP_COLLISION, etc.

## Acceptance Criteria

1. **Given** the daemon connects to an MX Master 4
   **When** it enumerates HID++ features
   **Then** it finds haptic support via feature ID 0x19B0 (not 0x8123)

2. **Given** haptic feedback is enabled
   **When** a UX haptic event is triggered (MenuAppear, SliceChange, etc.)
   **Then** the correct MX4 pattern ID (0-14) is sent to the device
   **And** the user feels a tactile vibration

3. **Given** the existing HapticEvent system
   **When** mapping events to MX4 patterns
   **Then** each event uses an appropriate pattern from the 15 available

## Tasks / Subtasks

- [x] Task 1: Update HID++ feature constants (AC: #1)
  - [x] 1.1: Add MX_MASTER_4_HAPTIC feature constant (0x19B0 - from Solaar)
  - [x] 1.2: Keep FORCE_FEEDBACK for potential future racing wheel support
  - [x] 1.3: Add 0x19B0 to allowed_features safelist

- [x] Task 2: Implement MX4-specific haptic waveforms (AC: #2, #3)
  - [x] 2.1: Create Mx4HapticPattern enum with Solaar waveform IDs (0x00-0x1B)
  - [x] 2.2: Add official waveform names from Solaar's HapticWaveForms
  - [x] 2.3: Implement send_haptic_pattern(pattern: Mx4HapticPattern) function

- [x] Task 3: Update HidppDevice for MX4 haptics (AC: #1, #2)
  - [x] 3.1: Modify enumerate_features to detect 0x19B0
  - [x] 3.2: Store mx4_haptic_feature_index separately from force_feedback
  - [x] 3.3: Add mx4_haptic_supported() method to check device capability

- [x] Task 4: Map HapticEvent to MX4 waveforms (AC: #3)
  - [x] 4.1: Map MenuAppear -> SubtleCollision (subtle pattern)
  - [x] 4.2: Map SliceChange -> SharpStateChange (distinct click)
  - [x] 4.3: Map SelectionConfirm -> Completed (confirmation feel)
  - [x] 4.4: Map InvalidAction -> AngryAlert (error feel)

- [ ] Task 5: Test on real hardware (AC: #2)
  - [ ] 5.1: Verify device detection with feature 0x19B0
  - [ ] 5.2: Test all waveforms to document behavior
  - [ ] 5.3: Validate UX event mappings feel correct

## Dev Notes

### MX Master 4 Haptic Feature

```
Feature ID: 0x19B0 (HAPTIC - from Solaar)
Function: 0x00 (trigger haptic waveform)
Parameter: Waveform ID (0x00-0x1B)
Message Format: HID++ Long (20 bytes)
```

### Reference Implementation (Solaar)

```python
# From Solaar's hidpp20_constants.py
class SupportedFeature(IntEnum):
    HAPTIC = 0x19B0  # <-- Correct for MX Master 4

HapticWaveForms = NamedInts(
    SHARP_STATE_CHANGE=0x00,
    DAMP_STATE_CHANGE=0x01,
    SHARP_COLLISION=0x02,
    DAMP_COLLISION=0x03,
    SUBTLE_COLLISION=0x04,
    HAPPY_ALERT=0x05,
    ANGRY_ALERT=0x06,
    COMPLETED=0x07,
    SQUARE=0x08,
    WAVE=0x09,
    FIREWORK=0x0A,
    MAD=0x0B,
    KNOCK=0x0C,
    JINGLE=0x0D,
    RINGING=0x0E,
    WHISPER_COLLISION=0x1B,
)
```

### Waveform ID Mapping (implemented)

| ID   | Enum Name          | UX Event Mapping    |
|------|-------------------|---------------------|
| 0x00 | SharpStateChange  | SliceChange         |
| 0x04 | SubtleCollision   | MenuAppear          |
| 0x06 | AngryAlert        | InvalidAction       |
| 0x07 | Completed         | SelectionConfirm    |
| 0x01-0x1B | (others)    | (available)         |

### Files Modified

- `daemon/src/hidpp.rs` - Add MX4 haptic feature, patterns, and send function

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Research Log

- Initially discovered mx4notifications project (used wrong feature ID 0x0B4E)
- Found authoritative source: Solaar's hidpp20_constants.py
- **CRITICAL FIX**: Corrected feature ID from 0x0B4E to 0x19B0 (HAPTIC)
- Adopted Solaar's official HapticWaveForms naming convention

### Completion Notes List

- Added `MX_MASTER_4_HAPTIC` constant (0x19B0 - from Solaar) to features module
- Added 0x19B0 to allowed_features SAFELIST
- Created `Mx4HapticPattern` enum with Solaar waveform IDs (0x00-0x1B)
- Added `to_id()`, `from_id()`, `name()` methods to Mx4HapticPattern
- Added `mx4_haptic_supported` and `mx4_haptic_feature_index` fields to HidppDevice
- Modified `enumerate_features()` to detect both 0x8123 and 0x19B0
- Implemented `send_haptic_pattern()` using HID++ long message format
- Added `mx4_haptic_supported()` and `legacy_haptic_supported()` getter methods
- Added `mx4_pattern()` method to HapticEvent for UX-to-hardware mapping
- Updated `HapticManager::emit()` to use MX4 patterns when available, with legacy fallback
- Code compiles successfully with `cargo check`
- All 177 tests passing

### File List

- daemon/src/hidpp.rs (MODIFIED - ~150 lines added for MX4 haptic support)

### Change Log

- 2025-12-14: Story 10.1 created based on haptic protocol research
- 2025-12-14: Tasks 1-4 implemented - MX4 haptic protocol support added
- 2025-12-14: CRITICAL FIX - Changed feature ID from 0x0B4E (mx4notifications) to 0x19B0 (Solaar)
- 2025-12-14: Updated waveform names to match Solaar's HapticWaveForms
- 2025-12-14: Ready for hardware validation (Task 5)
