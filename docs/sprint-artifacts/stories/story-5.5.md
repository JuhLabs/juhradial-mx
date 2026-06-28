# Story 5.5: Graceful Fallback & Error Handling

Status: complete

## Story

As a Linux user,
I want JuhRadial MX to work perfectly even if haptic feedback fails,
So that device compatibility issues don't break core functionality.

## Acceptance Criteria

1. **Given** the daemon cannot open the HID device
   **When** initialization fails with permission error
   **Then** all menu functionality continues to work normally without crashes

2. **Given** HID device handle becomes invalid mid-session
   **When** the mouse is disconnected or sleeps
   **Then** the daemon attempts to re-initialize haptic support on next menu appearance

## Tasks / Subtasks

- [x] Task 1: Ensure graceful initialization fallback (AC: #1)
  - [x] 1.1: Verify HapticManager::connect() returns Ok(false) on failure
  - [x] 1.2: Add error logging without panic for permission errors
  - [x] 1.3: Ensure all pulse/emit calls succeed silently when no device

- [x] Task 2: Add device reconnection logic (AC: #2)
  - [x] 2.1: Add `reconnect_if_needed()` method to HapticManager
  - [x] 2.2: Track connection state (NotConnected, Connected, Disconnected, Cooldown)
  - [x] 2.3: Attempt reconnect on next menu appearance after disconnect

- [x] Task 3: Handle mid-session errors gracefully (AC: #2)
  - [x] 3.1: Catch IO errors during pulse and mark device disconnected
  - [x] 3.2: Don't crash or spam logs on repeated failures
  - [x] 3.3: Add 5-second cooldown between reconnection attempts

- [x] Task 4: Add verification tests (AC: #1, #2)
  - [x] 4.1: Test pulse/emit succeed when device is None
  - [x] 4.2: Test state transitions (NotConnected, Connected, Disconnected, Cooldown)
  - [x] 4.3: Test cooldown constant is reasonable (5s)

## Dev Notes

### Design Philosophy

**Haptics are optional. The menu must always work.**

If haptic feedback fails for any reason:
1. Log the issue once (don't spam)
2. Continue menu operation normally
3. Attempt to recover silently in background

### Connection States

```
         ┌─────────────────────────────────────────┐
         │                                         │
         ▼                                         │
    ┌─────────────┐  connect()   ┌───────────┐    │
    │ NotConnected│ ───────────► │ Connected │ ───┘
    └─────────────┘              └───────────┘   IO error
         ▲                            │
         │                            ▼
         │                   ┌──────────────┐
         └───────────────────│ Disconnected │
           cooldown expired  └──────────────┘
                                    │
                                    ▼
                              ┌──────────┐
                              │ Cooldown │
                              └──────────┘
```

### Reconnection Strategy

- On IO error: Mark device disconnected, clear device handle
- On next menu appearance: Call `reconnect_if_needed()`
- Cooldown: 5 seconds between reconnection attempts
- Don't block main thread for reconnection

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Tests require Linux target with Rust toolchain

### Completion Notes List

- Created `ConnectionState` enum (NotConnected, Connected, Disconnected, Cooldown)
- Added connection_state and last_disconnect_ms fields to HapticManager
- Implemented `handle_disconnect()` private method for graceful error handling
- Implemented `reconnect_if_needed()` public method for automatic reconnection
- Added `connection_state()` getter method
- Updated `connect()` to set connection state
- Updated `pulse()` to catch IO errors and call handle_disconnect()
- Added RECONNECT_COOLDOWN_MS constant (5 seconds)
- Cooldown prevents reconnection spam
- 9 new tests for graceful fallback and reconnection logic

### File List

- daemon/src/hidpp.rs (MODIFIED - added ~100 lines for connection state and reconnection)

### Change Log

- 2025-12-12: Story 5.5 created
- 2025-12-12: Story 5.5 implemented - Graceful Fallback & Error Handling complete
