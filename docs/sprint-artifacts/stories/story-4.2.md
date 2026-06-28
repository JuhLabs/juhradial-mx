# Story 4.2: Bundled Theme Implementation

Status: complete

## Story

As a JuhRadial MX user,
I want a selection of pre-configured themes,
So that I can quickly personalize the radial menu appearance without creating themes from scratch.

## Acceptance Criteria

1. **Given** JuhRadial MX is installed
   **When** the daemon starts
   **Then** three bundled themes are available: Catppuccin Mocha, Vaporwave, Matrix Rain

2. **Given** no theme is explicitly configured
   **When** the radial menu is displayed
   **Then** the Catppuccin Mocha theme is used as default

3. **Given** the user selects a bundled theme
   **When** the radial menu is displayed
   **Then** all colors, glassmorphism settings, and glow effects match the theme specification

4. **Given** any bundled theme is selected
   **When** the theme is loaded
   **Then** it passes all validation (colors in hex format, values in valid ranges)

## Tasks / Subtasks

- [x] Task 1: Create theme JSON files
  - [x] 1.1: Create catppuccin-mocha.json with full color palette
  - [x] 1.2: Create vaporwave.json with magenta/cyan neon colors
  - [x] 1.3: Create matrix-rain.json with green-on-black scheme

- [x] Task 2: Create bundled themes module
  - [x] 2.1: Create `bundled_themes.rs` module in daemon/src/
  - [x] 2.2: Embed theme JSON as const strings (include_str! macro)
  - [x] 2.3: Add `get_bundled_theme(name: &str)` function
  - [x] 2.4: Add `list_bundled_themes()` function

- [x] Task 3: Integrate with ThemeManager
  - [x] 3.1: Modify ThemeManager to check bundled themes
  - [x] 3.2: Bundled themes available even without filesystem
  - [x] 3.3: User themes can override bundled by name

- [x] Task 4: Add unit tests
  - [x] 4.1: Test all three bundled themes parse correctly
  - [x] 4.2: Test bundled theme values match UX spec
  - [x] 4.3: Test default theme selection

## Dev Notes

### Architecture Compliance

**Files:**
- `daemon/src/bundled_themes.rs` (NEW)
- `daemon/src/themes/catppuccin-mocha.json` (NEW)
- `daemon/src/themes/vaporwave.json` (NEW)
- `daemon/src/themes/matrix-rain.json` (NEW)
- `daemon/src/theme.rs` (MODIFY - integrate bundled themes, add from_json)
- `daemon/src/lib.rs` (MODIFY - export bundled_themes module)

### UX Spec Reference (Section 4.3)

#### Theme 1: Catppuccin Mocha (Default)
- Warm pastel dark theme
- Lavender accent (#b4befe)
- 24px blur, 75% opacity
- Glow intensity: 1.0

#### Theme 2: Vaporwave
- 80s neon aesthetic
- Accent: #ff6b9d (Magenta)
- Secondary: #00f5d4 (Cyan)
- 20px blur, 70% opacity
- Glow intensity: 1.5

#### Theme 3: Matrix Rain
- Monochrome green hacker theme
- All accent colors: #00ff00 (Matrix green)
- 16px blur, 85% opacity
- Glow intensity: 2.0
- Idle effect: matrix-rain

[Source: docs/ux-design-specification.md#4.3]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Tests to be validated on Linux target (no Rust on macOS dev machine)

### Completion Notes List

- Created 3 theme JSON files in daemon/src/themes/
- Created bundled_themes.rs with include_str! embedding
- Added get_bundled_theme(), get_default_theme(), list_bundled_themes()
- Case-insensitive lookup with dash/space/underscore normalization
- Added BundledThemeInfo struct with display_name and description
- Added from_json() method to Theme for string parsing
- Modified ThemeManager.new() to load all bundled themes
- Modified ThemeManager.load_all() with 3-tier loading: bundled → system → user
- 10 unit tests in bundled_themes.rs
- Updated theme.rs tests for bundled theme integration

### File List

- daemon/src/bundled_themes.rs (NEW - ~260 lines)
- daemon/src/themes/catppuccin-mocha.json (NEW)
- daemon/src/themes/vaporwave.json (NEW)
- daemon/src/themes/matrix-rain.json (NEW)
- daemon/src/theme.rs (MODIFIED - added from_json, updated ThemeManager)
- daemon/src/lib.rs (MODIFIED - added bundled_themes exports)

### Change Log

- 2025-12-12: Story 4.2 implemented - Bundled Theme Implementation complete
