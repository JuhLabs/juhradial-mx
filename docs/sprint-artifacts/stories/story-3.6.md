# Story 3.6: Validate Profile Configuration on Load

Status: done

## Story

As a user,
I want the daemon to validate my profile configuration,
So that I'm alerted to errors before they cause runtime failures.

## Acceptance Criteria

### AC1: Configuration Validation
**Given** the daemon loads profiles.json
**When** it parses the configuration
**Then** it validates: default profile exists, each profile has 8 slices, each action has valid type

### AC2: Auto-Fix Slice Count
**Given** a profile has 7 slices (missing one)
**When** the daemon validates the configuration
**Then** it pads the missing slice with a "none" action and continues loading

## Tasks / Subtasks

- [x] Task 1: Validate default profile exists (AC: 1)
  - [x] 1.1 Check for default profile after loading
  - [x] 1.2 Add hardcoded default if missing
  - [x] 1.3 Log warning when default was added

- [x] Task 2: Validate and fix slice count (AC: 2)
  - [x] 2.1 Check each profile has 8 slices
  - [x] 2.2 Pad missing slices with None instead of erroring
  - [x] 2.3 Truncate extra slices to 8
  - [x] 2.4 Log warning when slices were adjusted

- [x] Task 3: Validate action types (AC: 1)
  - [x] 3.1 Validate icon references during load
  - [x] 3.2 Warn on invalid but don't fail
  - [x] 3.3 Action type validation via serde deserialization

- [x] Task 4: Add unit tests
  - [x] 4.1 Test slice count padding
  - [x] 4.2 Test default profile addition
  - [x] 4.3 Test graceful handling of validation warnings

## Dev Notes

### Implementation

Changed from error-on-invalid to warn-and-fix approach:
- Slice count: Pad/truncate to 8 instead of returning error
- Default profile: Add hardcoded if missing
- Icon format: Warn if suspicious but don't fail
- Action type: Validated by serde during JSON deserialization

### Validation Sequence

```
1. Parse JSON via serde (validates structure)
2. Check schema version (warn if mismatch)
3. For each profile:
   a. Fix slice count if != 8
   b. Validate icon references (warn only)
   c. Add to window_mappings if has window_class
4. Ensure default profile exists
5. Log profile count
```

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Changed from error to auto-fix behavior for slice count
- Default profile always ensured after load
- Icon validation warns but doesn't fail
- Schema version check logs warning if mismatch
- Updated test to verify padding behavior

### File List

- `daemon/src/profiles.rs` - MODIFIED: Changed slice validation from error to auto-fix, added tests
