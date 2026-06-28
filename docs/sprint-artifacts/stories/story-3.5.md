# Story 3.5: Support Custom Icons for Actions

Status: done

## Story

As a user,
I want to assign custom icons to each slice action,
So that I can visually identify actions at a glance.

## Acceptance Criteria

### AC1: Icon Format Support
**Given** an action object in the profile configuration
**When** I add an "icon" field
**Then** the field accepts: PNG file path, SVG file path, Unicode emoji, or system icon name

### AC2: Emoji Rendering
**Given** I configure a slice with icon: "📋"
**When** the radial menu displays
**Then** the emoji renders at 32px in the slice icon zone (100px from center)

### AC3: Missing Icon Fallback
**Given** the icon file path does not exist
**When** the daemon attempts to load the icon
**Then** it falls back to a default icon and logs a warning

## Tasks / Subtasks

- [x] Task 1: Define icon field in Action struct (AC: 1)
  - [x] 1.1 Action already has icon: Option<String> field
  - [x] 1.2 Support emoji, file paths, and system icon names
  - [x] 1.3 Add validation for icon reference format

- [x] Task 2: Implement icon validation (AC: 1, 3)
  - [x] 2.1 Create validate_icon_reference() function
  - [x] 2.2 Accept emoji (high unicode), file paths (.png/.svg/.ico), system names
  - [x] 2.3 Warn on invalid format but don't fail load

- [x] Task 3: Add unit tests
  - [x] 3.1 Test emoji validation
  - [x] 3.2 Test file path validation
  - [x] 3.3 Test system icon name validation
  - [x] 3.4 Test invalid format detection

## Dev Notes

### Implementation

Icon support implemented with:
1. Action struct already has `icon: Option<String>` field
2. validate_icon_reference() validates format during profile load
3. Warnings logged for potentially invalid icons (don't fail)
4. Actual icon file existence checked at render time (KWin overlay)

### Supported Icon Formats

| Format | Example | Validation |
|--------|---------|------------|
| Emoji | 📋 | Unicode > 0x1F300 |
| PNG | /path/icon.png | .png extension |
| SVG | icons/edit.svg | .svg extension |
| ICO | icon.ico | .ico extension |
| System | edit-copy | alphanumeric + hyphen |

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Action.icon field already existed from earlier stories
- Created validate_icon_reference() for format validation
- Validation warns but doesn't fail load (graceful degradation)
- Added comprehensive unit test: test_validate_icon_reference

### File List

- `daemon/src/profiles.rs` - MODIFIED: Added validate_icon_reference() and tests
