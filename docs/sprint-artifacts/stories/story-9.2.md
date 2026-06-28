# Story 9.2: Logi Options+ Style Settings Dashboard

Status: complete

## Story

As a Linux MX Master user,
I want a settings window that looks and feels exactly like Logi Options+ (Windows/macOS),
So that I have a familiar, professional interface for configuring my mouse and radial menu.

## Acceptance Criteria

### AC1: Window Shell & Layout
**Given** I click the JuhRadialMX system tray icon
**When** the settings window opens
**Then** the window title is "Logi Options+"
**And** the window is 1160x740 pixels (fixed or minimum)
**And** the window uses dark theme regardless of system theme
**And** the background is pure black (#000000) or very dark gray (#111111)
**And** the window has 12px corner radius

### AC2: Two-Column Layout
**Given** the settings window is open
**When** I observe the layout
**Then** the left side (40% width) shows the device illustration area
**And** the right side (60% width) shows a scrollable list of setting cards

### AC3: Left Side - Device Illustration
**Given** the left side panel is displayed
**When** I observe the content
**Then** there is a header with device name and battery percentage
**And** a large (~580x580px) MX Master image is centered vertically
**And** the image has transparency and a realistic drop shadow
**And** the mouse PNG is located at `/usr/share/juhradialmx/devices/mx_master_4.png`

### AC4: Right Side - Setting Cards
**Given** the right side panel is displayed
**When** I scroll through the cards
**Then** I see cards in this exact order:
1. Point & Scroll
2. Button assignments (most important)
3. Thumbwheel
4. SmartShift / Ratchet mode
5. Flow (only if multiple devices)
6. App-specific settings
7. Device info & firmware (at bottom)

### AC5: Button Assignments Card
**Given** I view the Button Assignments card
**When** I observe the content
**Then** I see clickable rows for each button
**And** each row shows: button name (left) and current action (right) with arrow
**And** the Thumb/gesture button row shows "Radial Menu" as the action
**And** clicking any row opens an action editor

### AC6: Visual Styling
**Given** any element in the settings window
**When** I inspect the styling
**Then** cards use #111111 background with 10px corner radius
**And** text colors are #FFFFFF (titles) and #AAAAAA (subtext)
**And** accent color for selected items is #00A0E9 (Logitech cyan)
**And** cards have 24px vertical spacing between them

### AC7: Behavior
**Given** the settings window is open
**When** I change any setting
**Then** changes are applied instantly (no "Apply" button)
**And** the window stays on top of other windows until closed

## Tasks / Subtasks

### Task 1: Create GTK4/Adwaita Window Shell (AC: #1)
- [x] 1.1 Create new GTK4 application for settings window
- [x] 1.2 Set window title to "Logi Options+"
- [x] 1.3 Set minimum/fixed size to 1160x740 pixels
- [x] 1.4 Force dark theme using Adw.StyleManager or CSS
- [x] 1.5 Set background color to #000000
- [x] 1.6 Apply 12px corner radius (Adw.Window or custom CSS)

### Task 2: Implement Two-Column Layout (AC: #2)
- [x] 2.1 Create horizontal box/grid layout
- [x] 2.2 Left column: 40% width, centered content
- [x] 2.3 Right column: 60% width, scrollable container
- [x] 2.4 Add Adw.Clamp or similar for responsive sizing

### Task 3: Left Panel - Device Illustration (AC: #3)
- [x] 3.1 Create header bar with device name ("MX Master 4")
- [x] 3.2 Add battery icon + percentage display
- [x] 3.3 Add firmware version in small gray text
- [x] 3.4 Create/source MX Master 4 PNG (580x580, transparent)
- [x] 3.5 Center image vertically with 40px margins
- [x] 3.6 Add drop shadow effect to image
- [x] 3.7 Add grayscale state for disconnected mouse

### Task 4: Right Panel - Settings Cards (AC: #4, #6)
- [x] 4.1 Create scrollable container (Gtk.ScrolledWindow)
- [x] 4.2 Use Adw.PreferencesGroup for each card (no frame)
- [x] 4.3 Apply card styling: #111111 bg, 10px radius, 24px spacing
- [x] 4.4 Implement Card 1: Point & Scroll
  - [x] Pointer speed slider
  - [x] Natural scrolling toggle
  - [x] Smooth scrolling toggle
- [x] 4.5 Implement Card 2: Button Assignments (see Task 5)
- [x] 4.6 Implement Card 3: Thumbwheel
  - [x] Horizontal scroll toggle
  - [x] Zoom toggle for wheel left/right
- [x] 4.7 Implement Card 4: SmartShift
  - [x] Enable SmartShift toggle
  - [x] Sensitivity threshold slider
- [x] 4.8 Implement Card 5: Flow (conditional)
  - [x] Show only if multiple Logitech receivers detected
  - [x] Enable Flow toggle
  - [x] List of computers
- [x] 4.9 Implement Card 6: App-specific settings
  - [x] Enable per-application toggle
  - [x] List with + button for adding apps
- [x] 4.10 Implement Card 7: Device info
  - [x] Serial number display
  - [x] Firmware version
  - [x] "Check for updates" button
  - [x] "Restore defaults" button (red text)

### Task 5: Button Assignments Card (AC: #5)
- [x] 5.1 Create card titled "Button assignments"
- [x] 5.2 Add row: Back button → Back
- [x] 5.3 Add row: Forward button → Forward
- [x] 5.4 Add row: Thumb (gesture) button → Radial Menu (highlighted)
- [x] 5.5 Add row: Top button → Mission Control / Show Desktop
- [x] 5.6 Add row: Horizontal scroll left → Volume Down
- [x] 5.7 Add row: Horizontal scroll right → Volume Up
- [x] 5.8 Each row: button name left, action right, arrow indicator
- [x] 5.9 Clicking row opens action editor modal

### Task 6: Bottom Bar (AC: #7)
- [x] 6.1 Create fixed bottom bar
- [x] 6.2 Left: "Restore Device Defaults" button (red outline)
- [x] 6.3 Right: "Close" button

### Task 7: Instant Apply Behavior (AC: #7)
- [x] 7.1 Connect all controls to D-Bus daemon
- [x] 7.2 Changes save immediately on interaction
- [x] 7.3 No "Apply" or "Save" buttons needed
- [x] 7.4 Set window to stay on top until closed

### Task 8: Add Device Assets
- [x] 8.1 Source or create MX Master 4 PNG (high-res, transparent)
- [x] 8.2 Place at `/usr/share/juhradialmx/devices/mx_master_4.png`
- [x] 8.3 Add Logitech "L" logo SVG (white, 28px)
- [x] 8.4 Add standard icons or use system symbolic icons with cyan tint

## Dev Notes

### Technology Choice: GTK4 + libadwaita

Use GTK4 with libadwaita for the settings window because:
1. Already using GTK4 for the invisible cursor-capture window (Story 9.1)
2. Adwaita provides dark theme support and preference groups
3. Better integration with GNOME/Plasma dark themes
4. Forces dark mode easily with Adw.StyleManager

### Color Palette (Exact Values)

```css
/* Backgrounds */
--bg-window: #000000;
--bg-cards: #111111;

/* Text */
--text-primary: #FFFFFF;
--text-secondary: #AAAAAA;

/* Accent */
--accent-logitech: #00A0E9;  /* Logitech cyan */

/* Borders/Danger */
--danger: #FF4444;
```

### CSS Override for Logi Options+ Look

```css
window {
  background: #000000;
  border-radius: 12px;
}

.settings-card {
  background: #111111;
  border-radius: 10px;
  margin-bottom: 24px;
  padding: 16px;
}

.button-row {
  padding: 12px 16px;
  border-bottom: 1px solid #222222;
}

.button-row:hover {
  background: #1a1a1a;
}

.accent-text {
  color: #00A0E9;
}

.restore-defaults-btn {
  color: #FF4444;
  border: 1px solid #FF4444;
  background: transparent;
}
```

### D-Bus Integration

Connect to existing daemon interface:
- `org.kde.juhradialmx.Daemon`
- Add new methods if needed:
  - `GetSettings() -> (config_json: s)`
  - `SetSetting(key: s, value: v) -> (success: b)`

### References

- [Source: User requirements - Logi Options+ exact layout specification]
- [Source: Logitech Options+ Windows/macOS screenshots - visual reference]
- [Source: docs/architecture.md - D-Bus interface]
- [Source: GTK4 documentation - Adw.PreferencesGroup, Adw.StyleManager]

## Dev Agent Record

### Context Reference
<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used
{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
