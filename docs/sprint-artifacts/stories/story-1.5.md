# Story 1.5: Create Proof-of-Concept KWin Overlay

## Story Info
- **Epic:** 1 - Foundation & Architecture Spike
- **Story ID:** 1.5
- **Priority:** P0 (Critical)
- **Estimate:** L (Large)
- **Status:** Complete

## Story
As a developer,
I want a minimal KWin script that can display an overlay window,
So that I can validate the overlay rendering approach on Wayland.

## Acceptance Criteria

### AC1: KWin Script Structure
**Given** I have KDE Plasma 6 running on Wayland
**When** I create a KWin script in `kwin-script/contents/code/main.js`
**Then** the script registers a D-Bus listener for `org.kde.juhradialmx.Daemon.MenuRequested`
**And** the metadata.json file contains: `"Api": "KWin/Script"`, `"Type": "Service"`

### AC2: Overlay Window Display
**Given** the KWin script is installed and enabled
**When** the daemon emits a `MenuRequested` signal with coordinates (500, 300)
**Then** a basic QML window appears at screen position (500, 300)
**And** the window is a frameless overlay with no title bar or decorations
**And** the window appears on top of all other windows
**And** the window does not steal keyboard focus

## Dev Notes

### Architecture Reference
From `docs/architecture.md`:
- KWin script uses TypeScript compiled to JavaScript
- Uses @opekope2/kwin-script-types for type definitions
- D-Bus listener for MenuRequested signal
- QML overlay for rendering

### KWin Script Requirements
- metadata.json with proper KWin/Script API declaration
- TypeScript source in src/ compiled to dist/
- D-Bus client to listen for daemon signals
- Basic QML overlay component

## Tasks

- [x] 1. Update KWin script metadata.json
  - [x] 1.1 Add KWin/Script API declaration
  - [x] 1.2 Add KPackageStructure
  - [x] 1.3 Add X-KWin-Requires for dbus

- [x] 2. Implement D-Bus client in TypeScript
  - [x] 2.1 Update dbus-client.ts with proper interface docs
  - [x] 2.2 Add signal handler types
  - [x] 2.3 Add method wrappers for KWin callDBus()

- [x] 3. Create basic QML overlay component
  - [x] 3.1 Create contents/ui/RadialMenu.qml
  - [x] 3.2 Configure as frameless overlay (Qt.FramelessWindowHint)
  - [x] 3.3 Set window flags for always-on-top (Qt.WindowStaysOnTopHint)
  - [x] 3.4 Disable focus stealing (Qt.BypassWindowManagerHint)

- [x] 4. Wire D-Bus signal to overlay display
  - [x] 4.1 Create main.js with D-Bus listener setup
  - [x] 4.2 Position overlay at signal coordinates with edge clamping
  - [x] 4.3 Add keyboard shortcut (Meta+G) for PoC testing

- [x] 5. Add slice calculation logic
  - [x] 5.1 Implement calculateSlice() function
  - [x] 5.2 Add cursor position tracking

## Testing Requirements

- KWin script loads without errors
- D-Bus listener receives MenuRequested signals
- Overlay appears at correct screen coordinates
- Overlay is frameless and stays on top
- Overlay does not steal focus

## Definition of Done
- [x] All tasks completed
- [x] All acceptance criteria verified
- [x] Code compiles without errors
- [x] Code reviewed
- [x] Story marked complete in sprint-status.yaml

---

## Dev Agent Record

### Agent Model Used
Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References
No issues encountered.

### Completion Notes
Story 1.5 completed - KWin Overlay Proof of Concept:

**KWin Script Structure (AC1):**
- Updated `metadata.json` with KPackageStructure and X-KWin-Requires
- Created `contents/code/main.js` with D-Bus listener registration
- Script registers for `org.kde.juhradialmx.Daemon.MenuRequested` signal
- Added Meta+G keyboard shortcut for PoC testing

**Overlay Window (AC2):**
- Created `contents/ui/RadialMenu.qml` with full overlay implementation
- Window flags: `Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.BypassWindowManagerHint | Qt.Tool`
- No focus stealing with `activeFocusOnPress: false`
- 280px diameter menu with 8 slices and center zone
- Catppuccin Mocha theme colors as default
- Glassmorphism effect with blur and transparency
- Appear/dismiss animations (30ms/50ms)

**Additional Features:**
- Edge clamping to keep menu 20px from screen edges
- Slice calculation: N=0, NE=1, E=2, SE=3, S=4, SW=5, W=6, NW=7
- Center zone detection (40px radius)
- Cursor tracking for slice highlighting
- Updated TypeScript dbus-client.ts with proper interface documentation

**Testing:**
- Meta+G shortcut toggles menu at cursor position
- Full visual rendering with 8 labeled slices
- Highlight animation on slice hover

### File List
**Modified:**
- `/kwin-script/metadata.json` - Added KPackageStructure, X-KWin-Requires
- `/kwin-script/package.json` - Added install-script, remove-script targets
- `/kwin-script/src/dbus-client.ts` - Updated with proper D-Bus interface docs

**Created:**
- `/kwin-script/contents/code/main.js` - Main KWin script with D-Bus and overlay logic
- `/kwin-script/contents/ui/RadialMenu.qml` - QML radial menu overlay component

### Change Log
| Date | Change | Author |
|------|--------|--------|
| 2025-12-12 | Story 1.5 completed - KWin overlay PoC | James (Dev Agent) |
