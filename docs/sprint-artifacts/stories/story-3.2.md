# Story 3.2: Detect Focused Window via KWin/Plasma APIs

Status: done

## Story

As a user,
I want the system to automatically detect which application I'm using,
So that the correct profile loads when I open the radial menu.

## Acceptance Criteria

### AC1: KWin D-Bus Connection
**Given** the daemon is running on KDE Plasma
**When** it initializes
**Then** it establishes a D-Bus connection to `org.kde.KWin`
**And** it subscribes to window focus change signals

### AC2: Window Focus Detection
**Given** I switch focus to Firefox
**When** Firefox becomes the active window
**Then** the daemon receives a focus change event
**And** it extracts the window class as a string (e.g., "firefox")
**And** this happens within 5ms of the focus change (NFR-004)

## Tasks / Subtasks

- [x] Task 1: Create window_tracker module (AC: 1)
  - [x] 1.1 Create daemon/src/window_tracker.rs module
  - [x] 1.2 Add module to lib.rs/main.rs
  - [x] 1.3 Define WindowTracker struct with D-Bus connection

- [x] Task 2: Implement KWin D-Bus client (AC: 1)
  - [x] 2.1 Connect to org.kde.KWin service
  - [x] 2.2 Subscribe to activeWindow property changes via org.freedesktop.DBus.Properties
  - [x] 2.3 Handle connection failure gracefully (not running on KDE)

- [x] Task 3: Extract window class on focus change (AC: 2)
  - [x] 3.1 Query org.kde.KWin.activeClient for window resource class
  - [x] 3.2 Parse response to extract window class string
  - [x] 3.3 Cache last known window class to avoid redundant queries

- [x] Task 4: Integrate with main daemon (AC: 1, 2)
  - [x] 4.1 Spawn WindowTracker task on daemon startup
  - [x] 4.2 Expose get_active_window_class() method
  - [x] 4.3 Log focus changes with tracing

- [x] Task 5: Add unit tests
  - [x] 5.1 Test WindowTracker creation
  - [x] 5.2 Test window class parsing
  - [x] 5.3 Test cache behavior

## Dev Notes

### Implementation Approach

KDE Plasma 6 exposes window information via KWin's D-Bus interface. The daemon needs to:
1. Monitor `org.kde.KWin` for active window changes
2. Query `org.kde.KWin.activeClient` or use Scripting interface
3. Extract the `resourceClass` property (lowercase window class)

### KWin D-Bus Interface

**Service:** `org.kde.KWin`
**Path:** `/org/kde/KWin`

**Scripting Interface (preferred):**
- Call `org.kde.KWin.Scripting.activeWindow` to get active window info
- Returns window object with `resourceClass` property

**Alternative - KWin::Window interface:**
- Listen for `activeWindow` property changes via Properties interface
- Query window details via `/org/kde/KWin/windows/{id}`

### NFR-004 Performance

Active window detection must complete within 5ms. Strategy:
- Use async D-Bus calls (non-blocking)
- Cache window class to avoid repeated queries
- Only query on actual focus change events

### Architecture Notes

From docs/architecture.md:
- D-Bus is the IPC mechanism for all components
- Daemon handles profile management (this is where window tracking integrates)
- ProfileManager will use WindowTracker to auto-switch profiles

### References

- [Source: docs/epics.md#Story-3.2] - Acceptance criteria
- [Source: docs/architecture.md#ADR-003] - D-Bus interface design
- [KWin D-Bus API](https://invent.kde.org/plasma/kwin/-/blob/master/src/plugins/screencast/screencastmanager.cpp)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

### Completion Notes List

- Created WindowTracker struct with async D-Bus connection to KWin
- Implemented KWinProxy and KWinScriptingProxy using zbus #[proxy] macro
- Added graceful fallback when KWin is not available (non-KDE systems)
- Implemented window class caching via Arc<RwLock<WindowInfo>>
- Added NFR-004 latency monitoring (warns if >5ms detection time)
- Created fallback parser for extracting app name from client ID
- Added 6 unit tests covering creation, parsing, and cache behavior
- Integrated WindowTracker initialization in main.rs daemon startup

### File List

- `daemon/src/window_tracker.rs` - NEW: WindowTracker module with KWin D-Bus integration
- `daemon/src/main.rs` - MODIFIED: Added window_tracker module and WindowTracker initialization

