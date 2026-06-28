# Story 9.1: Critical Wayland Fixes - Haptic Button, Cursor Position & Visual Polish

Status: complete

## Story

As a Linux user on Fedora KDE Plasma 6 Wayland with an MX Master 4,
I want the radial menu to appear at my cursor when I press the haptic thumb button (not middle mouse),
So that I can use JuhRadialMX as intended with proper Wayland support.

## Problem Statement

**Current Broken Behavior:**
1. Radial wheel shows when pressing **middle mouse button** instead of the **haptic thumb button**
2. Radial wheel appears at **screen center** instead of at **cursor position**
3. Hover highlighting has unwanted color effects

**Root Cause (confirmed December 2025):**
- The haptic thumb button (CID 0xd4 / 212 decimal) is **completely hidden from evdev on Wayland** unless logid diverts it
- Wayland **forbids apps from reading global cursor position** - there is NO working API for this in 2025
- The only working solution is the ydotool + gtk4-layer-shell method

## Acceptance Criteria

### AC1: Haptic Thumb Button Detection
**Given** the MX Master 4 is connected and logid is configured
**When** I press the haptic thumb button (the one that vibrates)
**Then** the daemon receives an F19 keypress from "LogiOps Virtual Input"
**And** the radial menu appears

**Given** I press the middle mouse button
**When** the daemon processes input
**Then** no radial menu appears (middle-click behaves normally)

### AC2: Cursor Position on Wayland (No Screen Blocking)
**Given** the radial menu is triggered by F19
**When** the daemon processes the F19 press
**Then** it immediately injects a fake middle-click via ydotool
**And** the gtk4-layer-shell overlay (on BOTTOM layer, input-passthrough) catches the click
**And** the overlay extracts the real x,y coordinates
**And** the MenuRequested D-Bus signal contains the correct cursor position
**And** the radial menu appears centered at the cursor
**And** the overlay window NEVER blocks normal mouse input

### AC3: Remove Hover Color Highlighting
**Given** the radial menu is displayed
**When** I hover over different slices
**Then** the slice selection is indicated WITHOUT color tinting/highlighting
**And** only structural visual feedback (border, scale, glow) is used

### AC4: Haptic Vibration Working
**Given** the haptic thumb button is pressed
**When** the radial menu appears
**Then** the MX Master 4 vibrates with the configured haptic feedback pattern

## Tasks / Subtasks

### Task 1: Install and Configure logid for Haptic Button Divert (AC: #1)

**Background:** The MX Master 4 haptic thumb button uses CID 0xd4 (212). This button is invisible to evdev on Wayland unless logid diverts it.

- [x] 1.1 Install logiops: `sudo dnf install logiops`
- [x] 1.2 Create config at `/etc/logid.cfg`:

```cfg
devices: ({
    name: "MX Master 4";

    buttons: ({
        cid: 0xd4;
        action = {
            type: "Keypress";
            keys: ["KEY_F19"];
        };
    });
});
```

- [x] 1.3 Enable and start logid service:
```bash
sudo systemctl enable --now logid
```

- [x] 1.4 Verify button works:
```bash
# Run in terminal, press haptic button - should see F19 events
sudo logid -v
```

- [x] 1.5 Document logid installation in user setup guide

**Reference:** [logiops wiki - Configuration](https://github.com/PixlOne/logiops/wiki/Configuration)

### Task 2: Update Daemon to Listen for F19 Key (AC: #1)

- [x] 2.1 Identify "LogiOps Virtual Input" device in `/dev/input/`
- [x] 2.2 Add evdev listener for KEY_F19 (keycode 189)
- [x] 2.3 Remove/disable BTN_SIDE, BTN_EXTRA, BTN_FORWARD listeners (old approach)
- [x] 2.4 On F19 press → trigger cursor capture flow
- [x] 2.5 On F19 release → dismiss menu and execute action

**Code location:** `daemon/src/input/`

**Key codes reference:**
```
KEY_F19 = 189  (from linux/input-event-codes.h)
```

### Task 3: Implement gtk4-layer-shell Cursor Capture (AC: #2) - CRITICAL: NO BLOCKING

**CRITICAL:** The overlay window must NEVER block normal mouse input. Use gtk4-layer-shell with proper configuration.

- [x] 3.1 Add dependencies:
```bash
sudo dnf install gtk4-layer-shell-devel ydotool
```

- [x] 3.2 Enable ydotool service (runs as user):
```bash
# Create udev rule for uinput access
sudo tee /etc/udev/rules.d/60-ydotool-uinput.rules << 'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF

# Enable user service
sudo cp /usr/lib/systemd/system/ydotool.service /usr/lib/systemd/user/
systemctl --user enable --now ydotool.service
```

- [x] 3.3 Create gtk4-layer-shell overlay window (Rust or Python):

**CRITICAL CONFIGURATION - This is what prevents blocking:**
```rust
// Rust with gtk4-rs and gtk4-layer-shell
use gtk4_layer_shell::{Edge, Layer, LayerShell};

fn create_cursor_capture_window(app: &Application) -> Window {
    let window = Window::new(app);

    // Initialize layer shell
    window.init_layer_shell();

    // CRITICAL: Use BOTTOM layer - below all other windows
    window.set_layer(Layer::Bottom);

    // CRITICAL: Set EMPTY input region - clicks pass through
    // We will temporarily expand it only when capturing
    window.set_keyboard_mode(gtk4_layer_shell::KeyboardMode::None);

    // Fullscreen anchoring
    window.set_anchor(Edge::Top, true);
    window.set_anchor(Edge::Bottom, true);
    window.set_anchor(Edge::Left, true);
    window.set_anchor(Edge::Right, true);

    // Fully transparent
    window.set_opacity(0.0);

    // Set empty input region (click-through by default)
    let surface = window.surface().unwrap();
    let empty_region = cairo::Region::create();
    surface.set_input_region(&empty_region);

    window
}
```

- [x] 3.4 Implement click capture flow:

```rust
// When F19 is pressed:
fn on_f19_press(overlay: &Window) {
    // 1. Temporarily enable input capture
    let surface = overlay.surface().unwrap();
    let full_region = cairo::Region::create_rectangle(&cairo::RectangleInt {
        x: 0, y: 0,
        width: i32::MAX, height: i32::MAX,
    });
    surface.set_input_region(&full_region);

    // 2. Inject fake middle-click via ydotool
    // 0xC2 = middle button click (down + up)
    std::process::Command::new("ydotool")
        .args(["click", "0xC2"])
        .spawn()
        .expect("Failed to run ydotool");
}

// In the overlay window's click handler:
fn on_click(gesture: &GestureClick, _n: i32, x: f64, y: f64) {
    // 3. Got real coordinates!
    let screen_x = x as i32;
    let screen_y = y as i32;

    // 4. Immediately disable input capture again
    let surface = gesture.widget().surface().unwrap();
    let empty_region = cairo::Region::create();
    surface.set_input_region(&empty_region);

    // 5. Emit D-Bus signal with coordinates
    emit_menu_requested(screen_x, screen_y);
}
```

- [x] 3.5 Integrate with existing D-Bus interface:
  - Emit `MenuRequested(x, y)` signal after capturing coordinates
  - Existing radial menu overlay receives signal and positions itself

- [x] 3.6 Test that normal clicks work (overlay doesn't block anything)

**Alternative Python implementation:**
```python
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gtk4LayerShell', '1.0')
from gi.repository import Gtk, Gtk4LayerShell, Gdk
import subprocess

class CursorCaptureWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(application=app)

        # Initialize layer shell
        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.BOTTOM)
        Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.NONE)

        # Anchor to all edges (fullscreen)
        for edge in [Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM,
                     Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT]:
            Gtk4LayerShell.set_anchor(self, edge, True)

        # Transparent
        self.set_opacity(0.0)

        # Click handler
        click = Gtk.GestureClick.new()
        click.connect('pressed', self.on_click)
        self.add_controller(click)

        # Start with empty input region (click-through)
        self.set_input_passthrough(True)

    def set_input_passthrough(self, passthrough: bool):
        surface = self.get_surface()
        if surface:
            if passthrough:
                # Empty region = all clicks pass through
                region = cairo.Region()
            else:
                # Full region = capture all clicks
                region = cairo.Region(cairo.RectangleInt(0, 0, 10000, 10000))
            surface.set_input_region(region)

    def trigger_capture(self):
        # Enable capture, then inject click
        self.set_input_passthrough(False)
        subprocess.run(['ydotool', 'click', '0xC2'])

    def on_click(self, gesture, n_press, x, y):
        # Immediately disable capture
        self.set_input_passthrough(True)

        # Emit coordinates via D-Bus
        emit_menu_requested(int(x), int(y))
```

### Task 4: Remove Hover Color Highlighting (AC: #3)

- [x] 4.1 Locate slice hover styling in KWin script / QML
- [x] 4.2 Find and remove color tint/overlay on hover state
- [x] 4.3 Keep only structural feedback:
  - Border highlight (opacity change)
  - Subtle scale (1.0 → 1.03)
  - Glow effect (if any)
- [x] 4.4 Test that slice selection is still clearly visible

**Likely file:** `kwin-script/contents/ui/RadialMenu.qml`

### Task 5: Verify Haptic Feedback Still Works (AC: #4)

- [x] 5.1 Confirm HID++ haptic commands work with new F19 trigger flow
- [x] 5.2 Test haptic on menu appear (20% intensity, 30ms)
- [x] 5.3 Test haptic on slice change (40% intensity, 40ms)
- [x] 5.4 Test haptic on selection confirm (80% intensity, 60ms)
- [x] 5.5 Test haptic on empty slice (30% intensity, double-tap pattern)

## Dev Notes

### Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPLETE WORKING FLOW                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. User presses MX Master 4 haptic thumb button                │
│          │                                                      │
│          ▼                                                      │
│  2. logid intercepts CID 0xd4, emits KEY_F19                   │
│          │                                                      │
│          ▼                                                      │
│  3. juhradialmx-daemon receives F19 from LogiOps Virtual Input │
│          │                                                      │
│          ▼                                                      │
│  4. Daemon enables input capture on gtk4-layer-shell overlay   │
│          │                                                      │
│          ▼                                                      │
│  5. Daemon runs: ydotool click 0xC2 (middle-click)             │
│          │                                                      │
│          ▼                                                      │
│  6. gtk4-layer-shell overlay catches click, gets (x, y)        │
│          │                                                      │
│          ▼                                                      │
│  7. Overlay immediately re-enables passthrough (no blocking!)  │
│          │                                                      │
│          ▼                                                      │
│  8. Overlay emits D-Bus: MenuRequested(x, y)                   │
│          │                                                      │
│          ▼                                                      │
│  9. KWin radial menu receives signal, positions at (x, y)      │
│          │                                                      │
│          ▼                                                      │
│  10. User sees radial menu at cursor position!                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Why gtk4-layer-shell is Required

On Wayland, normal GTK4 windows cannot:
- Position themselves at specific coordinates
- Be made click-through
- Sit below other windows

**gtk4-layer-shell** provides:
- `Layer::Bottom` - window sits below everything, never blocks
- `set_input_region()` - precise control over which areas receive input
- Works on KDE Plasma 6 Wayland (and all wlroots-based compositors)

### Dependencies to Install

```bash
# 1. logid for button divert (run as root)
sudo dnf install logiops
sudo systemctl enable --now logid

# 2. ydotool for click injection (run as user)
sudo dnf install ydotool

# Create udev rule for non-root access
sudo tee /etc/udev/rules.d/60-ydotool-uinput.rules << 'EOF'
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
EOF

# Reload udev and reboot (or re-login)
sudo udevadm control --reload-rules
sudo udevadm trigger

# Enable user service
sudo cp /usr/lib/systemd/system/ydotool.service /usr/lib/systemd/user/
systemctl --user enable --now ydotool.service

# 3. GTK4 layer shell for overlay
sudo dnf install gtk4-layer-shell gtk4-layer-shell-devel

# 4. For Rust development
# Add to Cargo.toml:
# gtk4 = "0.9"
# gtk4-layer-shell = "0.4"
```

### ydotool Click Codes Reference

```
Button codes for ydotool click:
0x00 = LEFT (just select, no action)
0x01 = RIGHT
0x02 = MIDDLE
0x40 = Mouse down only
0x80 = Mouse up only
0xC0 = LEFT click (down + up)
0xC1 = RIGHT click (down + up)
0xC2 = MIDDLE click (down + up)  ← WE USE THIS
```

### logiops CID Reference for MX Master Series

```
Common CIDs:
0x50 = Left click
0x51 = Right click
0x52 = Middle click
0x53 = Back button
0x56 = Forward button
0xc3 = Gesture button (thumb, MX Master 3)
0xc4 = Top button (mode shift)
0xd4 = Haptic thumb button (MX Master 4)  ← THIS IS THE ONE
```

### File Structure

```
daemon/
├── src/
│   ├── input/
│   │   ├── mod.rs
│   │   ├── evdev.rs           # Existing evdev handling
│   │   └── f19_listener.rs    # NEW: F19 key listener
│   ├── cursor/
│   │   ├── mod.rs
│   │   └── gtk4_capture.rs    # NEW: gtk4-layer-shell capture
│   └── main.rs
├── Cargo.toml                  # Add: gtk4, gtk4-layer-shell

kwin-script/
└── contents/
    └── ui/
        └── RadialMenu.qml      # MODIFY: Remove color hover effect

packaging/
├── logid.cfg                   # NEW: Default logid config
└── ydotool-uinput.rules        # NEW: udev rule for ydotool
```

### Testing Checklist

- [ ] logid is running and detects MX Master 4
- [ ] Pressing haptic button emits F19 (check with `evtest`)
- [ ] ydotool service is running (`systemctl --user status ydotool`)
- [ ] `ydotool click 0xC2` works (test in terminal)
- [ ] gtk4-layer-shell overlay starts and is invisible
- [ ] Normal clicks work everywhere (overlay doesn't block!)
- [ ] Radial menu appears at cursor when haptic button pressed
- [ ] Hover highlighting has no color tint
- [ ] Haptic vibration works

### References

- [logiops Wiki - Configuration](https://github.com/PixlOne/logiops/wiki/Configuration)
- [logiops Wiki - CIDs](https://github.com/PixlOne/logiops/wiki/CIDs)
- [ydotool GitHub](https://github.com/ReimuNotMoe/ydotool)
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell)
- [Wayland input regions](https://wayland-book.com/surfaces-in-depth/surface-regions.html)
- [Linux input-event-codes.h](https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h)

## Dev Agent Record

### Context Reference
<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used
{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
