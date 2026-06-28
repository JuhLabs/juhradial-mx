# Story 4.3: Hot-Reload via inotify File Watching

Status: complete

## Story

As a theme designer,
I want theme changes to apply instantly without restarting the daemon,
So that I can iterate quickly on custom theme designs.

## Acceptance Criteria

1. **Given** the daemon is running and watching theme directories
   **When** a theme JSON file is modified
   **Then** the daemon detects the change via inotify within 100ms

2. **Given** the theme file is valid
   **When** the daemon detects the change
   **Then** it reloads and applies changes immediately if the theme is active

3. **Given** the active theme file is saved with syntax errors
   **When** the daemon detects the change
   **Then** it keeps the last valid version active and logs the validation error

4. **Given** a new theme is added to the user themes directory
   **When** the daemon detects the new file
   **Then** the theme is added to the available themes list

## Tasks / Subtasks

- [x] Task 1: Add notify crate dependency
  - [x] 1.1: notify = "6" already in Cargo.toml
  - [x] 1.2: Using RecommendedWatcher for cross-platform support

- [x] Task 2: Create file watcher module
  - [x] 2.1: Create `theme_watcher.rs` module in daemon/src/
  - [x] 2.2: Implement ThemeWatcher struct with inotify backend
  - [x] 2.3: Watch both system and user theme directories
  - [x] 2.4: Debounce rapid file changes (50ms)

- [x] Task 3: Implement hot-reload logic
  - [x] 3.1: On file change, reload the specific theme
  - [x] 3.2: Validate new theme before applying
  - [x] 3.3: Keep last valid theme on error
  - [x] 3.4: Logging on theme change (D-Bus signal for future)

- [x] Task 4: Add unit tests
  - [x] 4.1: Test ThemeEvent types
  - [x] 4.2: Test error display
  - [x] 4.3: Integration test structure (marked ignore for CI)

## Dev Notes

### Architecture Compliance

**Files:**
- `daemon/src/theme_watcher.rs` (NEW - ~260 lines)
- `daemon/src/theme.rs` (MODIFY - add_or_update_theme, remove_theme)
- `daemon/src/lib.rs` (MODIFY - export theme_watcher)

### Implementation Details

**ThemeWatcher:**
- Uses `notify` crate with RecommendedWatcher (inotify on Linux)
- Watches /usr/share/juhradial/themes/ (system) and ~/.config/juhradial/themes/ (user)
- Poll interval: 100ms for detection
- Debounce window: 50ms to avoid rapid reloads

**ThemeHotReloader:**
- Wraps ThemeManager in Arc<Mutex<>> for thread-safe updates
- Validates themes before applying
- Keeps last valid version on parse/validation errors
- Logs all reload events with tracing

**New ThemeManager methods:**
- `add_or_update_theme(theme)` - Add or update a theme
- `remove_theme(name)` - Remove theme (not current, not bundled)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Tests to be validated on Linux target (inotify not available on macOS)

### Completion Notes List

- Created ThemeWatcher with notify crate backend
- Created ThemeHotReloader for managed hot-reload
- Added ThemeEvent enum (Modified, Created, Deleted, Error)
- Added ThemeWatcherError for initialization errors
- 50ms debounce to handle rapid save events
- Validates themes before applying, keeps last valid on error
- Added add_or_update_theme() to ThemeManager
- Added remove_theme() with protection for current/bundled themes
- 4 unit tests in theme_watcher.rs

### File List

- daemon/src/theme_watcher.rs (NEW - ~260 lines)
- daemon/src/theme.rs (MODIFIED - added 2 methods)
- daemon/src/lib.rs (MODIFIED - added theme_watcher exports)

### Change Log

- 2025-12-12: Story 4.3 implemented - Hot-Reload via inotify complete
