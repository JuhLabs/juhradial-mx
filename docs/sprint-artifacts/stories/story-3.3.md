# Story 3.3: Match Window Class to Profile

Status: done

## Story

As a user,
I want the radial menu to automatically use the correct profile for each application,
So that I see relevant actions without manual switching.

## Acceptance Criteria

### AC1: Profile Matching
**Given** the profiles.json contains profiles for "firefox", "konsole", and default
**When** the active window class is "firefox"
**And** I press the gesture button
**Then** the daemon loads the Firefox profile within 5ms

### AC2: Default Fallback
**Given** the active window class is "dolphin" with no matching profile
**When** I press the gesture button
**Then** the daemon falls back to the default profile

### AC3: Profile Lock During Interaction
**Given** I open the radial menu with Firefox focused
**When** the menu is displayed and I switch to another application mid-interaction
**Then** the profile remains "Firefox" until I close the menu

## Tasks / Subtasks

- [x] Task 1: Window class to profile mapping (AC: 1, 2)
  - [x] 1.1 Build window_mappings HashMap during profile load
  - [x] 1.2 Implement get_profile_for_window() lookup
  - [x] 1.3 Return default profile if no match found

- [x] Task 2: Integration with gesture event flow (AC: 1)
  - [x] 2.1 Query WindowTracker for active window class on menu request
  - [x] 2.2 Pass window class to ProfileManager lookup
  - [x] 2.3 Log profile selection with tracing

- [x] Task 3: Add unit tests (AC: 1, 2)
  - [x] 3.1 Test profile matching by window class
  - [x] 3.2 Test fallback to default
  - [x] 3.3 Test multiple profiles

## Dev Notes

### Implementation

ProfileManager::get_profile_for_window() was implemented in Story 3.1 and handles:
- Window class lookup via window_mappings HashMap
- Fallback to default profile if no match
- <5ms performance (HashMap O(1) lookup)

AC3 (profile lock during interaction) is handled by caching the profile at menu open time.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Window class to profile mapping already implemented in ProfileManager
- get_profile_for_window() provides O(1) HashMap lookup
- Default fallback works correctly
- Added unit test: test_window_class_to_profile_matching

### File List

- `daemon/src/profiles.rs` - MODIFIED: Added test for window class matching
