# Story 5.3: UX Haptic Profile Implementation

Status: complete

## Story

As a Linux user,
I want distinct haptic patterns for different menu interactions,
So that I can feel the difference between hovering, selecting, and errors.

## Acceptance Criteria

1. **Given** the radial menu appears
   **When** the menu render completes
   **Then** a haptic pulse at 20% intensity is sent (10ms duration, single pulse)

2. **Given** the cursor highlights a new slice
   **When** the cursor moves from slice N to slice N+1
   **Then** a haptic pulse at 40% intensity is sent (15ms duration, single pulse)

3. **Given** a slice is selected (gesture button released)
   **When** the selection is confirmed
   **Then** a haptic pulse at 80% intensity is sent (25ms duration, double pulse)

4. **Given** an empty slice is selected
   **When** the selection would trigger no action
   **Then** a haptic pulse at 30% intensity is sent (50ms duration, triple short pattern)

## Tasks / Subtasks

- [x] Task 1: Define HapticEvent enum (AC: #1-4)
  - [x] 1.1: Create HapticEvent enum with MenuAppear, SliceChange, SelectionConfirm, InvalidAction
  - [x] 1.2: Add HapticPattern enum (Single, Double, Triple)
  - [x] 1.3: Map each event to UX spec intensity/duration/pattern

- [x] Task 2: Implement pulse pattern support (AC: #3, #4)
  - [x] 2.1: Implement single pulse (duration once)
  - [x] 2.2: Implement double pulse (30ms gap between pulses)
  - [x] 2.3: Implement triple short pulse (20ms gaps)

- [x] Task 3: Create public haptic event API (AC: #1-4)
  - [x] 3.1: Add `HapticManager::emit(event: HapticEvent)` method
  - [x] 3.2: Apply global intensity scaling from config
  - [x] 3.3: Apply per-event intensity overrides from config
  - [x] 3.4: Respect debounce_ms between pulses (reset for pattern continuation)

- [x] Task 4: Add unit tests (AC: #1-4)
  - [x] 4.1: Test each event maps to correct profile values
  - [x] 4.2: Test intensity scaling (global * per-event)
  - [x] 4.3: Test pattern pulse counts and gaps
  - [x] 4.4: Test emit with disabled/zero-intensity/no-device

## Dev Notes

### Architecture

**Files to modify:**
- `daemon/src/hidpp.rs` - Add HapticEvent, HapticPattern, emit() method

### UX Spec Haptic Profiles (Section 2.3)

| Event | Intensity | Duration | Pattern |
|-------|-----------|----------|---------|
| Menu appear | 20/100 | 10ms | Single pulse |
| Slice change | 40/100 | 15ms | Single pulse |
| Selection confirm | 80/100 | 25ms | Double pulse |
| Invalid action | 30/100 | 50ms | Triple short |

### Intensity Calculation

Final intensity = (global_intensity / 100) * (per_event_intensity / 100) * 100

Example: global=50, menu_appear=20 → final=10

### Pulse Pattern Timing

```
Single:  [pulse]
Double:  [pulse]-30ms-[pulse]
Triple:  [pulse]-20ms-[pulse]-20ms-[pulse]
```

### Integration Points

- D-Bus MenuRequested → emit(MenuAppear)
- QML SliceChanged → emit(SliceChange)
- D-Bus ActionExecuted → emit(SelectionConfirm)
- D-Bus InvalidAction → emit(InvalidAction)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Tests require Linux target with Rust toolchain

### Completion Notes List

- Created `HapticEvent` enum with 4 event types matching UX spec
- Created `HapticPattern` enum (Single, Double, Triple) with pulse_count() and gap_ms() methods
- Each event maps to base profile via `base_profile()` and pattern via `pattern()`
- Added `PerEventIntensity` struct for per-event intensity overrides
- Updated `HapticManager` to store per_event intensities
- Updated `from_config()` and `update_from_config()` to load per-event values
- Implemented `emit(event: HapticEvent)` method:
  - Calculates scaled intensity: (global * per_event) / 100
  - Executes appropriate pulse pattern
  - Resets debounce between pattern pulses
- Added `emit_async()` for non-blocking multi-pulse patterns
- 16 new unit tests for haptic events and patterns

### File List

- daemon/src/hidpp.rs (MODIFIED - added ~170 lines for HapticEvent, HapticPattern, emit(), 16 tests)

### Change Log

- 2025-12-12: Story 5.3 created
- 2025-12-12: Story 5.3 implemented - UX Haptic Profile Implementation complete
