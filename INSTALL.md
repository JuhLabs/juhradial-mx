# JuhRadial MX Installation Guide

This guide covers the complete setup for JuhRadial MX on Fedora KDE Plasma 6 with Wayland.

## Prerequisites

JuhRadial MX requires several system components for Wayland support:

| Component | Purpose |
|-----------|---------|
| logid (logiops) | Diverts MX Master 4 haptic button to F19 keypress |
| ydotool | Injects fake mouse clicks for cursor position capture |
| gtk4-layer-shell | Wayland layer-shell protocol for overlay positioning |

## Quick Install (Fedora)

```bash
# Install all dependencies
sudo dnf install logiops ydotool gtk4-layer-shell gtk4-layer-shell-devel

# Install JuhRadial MX (when available)
sudo dnf copr enable juhhally/juhradial-mx
sudo dnf install juhradial-mx
```

## Detailed Setup

### Step 1: Install and Configure logid

The MX Master 4's haptic thumb button (CID 0xd4) is completely hidden from evdev on Wayland unless logid diverts it.

```bash
# Install logiops
sudo dnf install logiops

# Copy the configuration file
sudo cp packaging/logid.cfg /etc/logid.cfg

# Enable and start the service
sudo systemctl enable --now logid

# Verify it's working (press haptic button - should see F19 events)
sudo logid -v
```

**Configuration Details:**

The `/etc/logid.cfg` file maps the haptic thumb button to KEY_F19:

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

**CID Reference for MX Master Series:**
| CID | Button |
|-----|--------|
| 0xd4 (212) | Haptic thumb button (MX Master 4) |
| 0xc3 (195) | Gesture button (MX Master 3) |
| 0x52 (82) | Middle click |
| 0x53 (83) | Back button |
| 0x56 (86) | Forward button |

### Step 2: Install and Configure ydotool

ydotool is used to inject a fake middle-click to capture cursor coordinates on Wayland.

```bash
# Install ydotool
sudo dnf install ydotool

# Copy udev rule for non-root uinput access
sudo cp packaging/udev/60-ydotool-uinput.rules /etc/udev/rules.d/

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# Copy the user service file
sudo cp /usr/lib/systemd/system/ydotool.service /usr/lib/systemd/user/

# Enable ydotool as a user service
systemctl --user enable --now ydotool.service

# Verify ydotool is working
ydotool click 0xC2  # Should inject a middle-click
```

**Important:** You may need to log out and back in (or reboot) for the udev rules and user service to take effect.

**ydotool Click Codes:**
| Code | Action |
|------|--------|
| 0xC0 | Left click (down + up) |
| 0xC1 | Right click (down + up) |
| 0xC2 | Middle click (down + up) |
| 0x40 | Button down only |
| 0x80 | Button up only |

### Step 3: Install GTK4 Layer Shell

gtk4-layer-shell provides the wlr-layer-shell protocol for Wayland, allowing our overlay to:
- Sit below all windows (BOTTOM layer)
- Control input regions (click-through support)
- Capture real screen coordinates

```bash
# Install gtk4-layer-shell
sudo dnf install gtk4-layer-shell gtk4-layer-shell-devel

# For Python development
pip install pycairo PyGObject
```

### Step 4: Install JuhRadial MX

**From COPR (recommended):**
```bash
sudo dnf copr enable juhhally/juhradial-mx
sudo dnf install juhradial-mx
```

**From source:**
```bash
git clone https://github.com/juhhally/juhradial-mx.git
cd juhradial-mx
make build
sudo make install
```

### Step 5: Enable the Daemon

```bash
# Enable daemon to start at login
systemctl --user enable --now juhradialmx-daemon.service

# Check status
systemctl --user status juhradialmx-daemon.service

# View logs
journalctl --user -u juhradialmx-daemon.service -f
```

## Verification

After installation, verify each component:

### 1. logid is Running
```bash
systemctl status logid
# Should show "active (running)"

# Test: Press haptic button, check for F19
sudo evtest /dev/input/eventX  # Find LogiOps Virtual Input
```

### 2. ydotool is Working
```bash
systemctl --user status ydotool
# Should show "active (running)"

# Test: Inject a click
ydotool click 0xC2
```

### 3. Daemon is Running
```bash
systemctl --user status juhradialmx-daemon.service
# Should show "active (running)"

# Check D-Bus interface
qdbus6 org.kde.juhradialmx /org/kde/juhradialmx/Daemon
```

### 4. Test the Radial Menu
1. Press the haptic thumb button on your MX Master 4
2. The radial menu should appear at your cursor position
3. Move cursor to select a slice
4. Release to execute the action

## Troubleshooting

### "MX Master 4 not found"
- Ensure the mouse is connected via USB receiver or Bluetooth
- Check if logid detects it: `sudo logid -v`
- Verify evdev can see it: `sudo evtest`

### "Permission denied" errors
- Add yourself to the input group: `sudo usermod -aG input $USER`
- Log out and back in
- Verify udev rules are installed: `ls /etc/udev/rules.d/*juhradial*`

### Menu appears at wrong position
- Ensure ydotool service is running
- Check gtk4-layer-shell is installed: `pkg-config --modversion gtk4-layer-shell`

### Haptic feedback not working
- Verify the daemon has hidraw access
- Check udev rules for hidraw devices
- Run daemon with verbose logging: `juhradiald --verbose`

## Architecture Overview

```
Button Press Flow:
1. User presses haptic thumb button on MX Master 4
2. logid intercepts CID 0xd4, emits KEY_F19
3. juhradiald receives F19 from "LogiOps Virtual Input"
4. Daemon enables input capture on gtk4-layer-shell overlay
5. Daemon injects fake middle-click via ydotool
6. gtk4-layer-shell overlay catches click with real (x, y) coordinates
7. Overlay immediately re-enables click-through (BOTTOM layer)
8. Daemon emits D-Bus: MenuRequested(x, y)
9. Radial menu appears at cursor position
```

## References

- [logiops Wiki - Configuration](https://github.com/PixlOne/logiops/wiki/Configuration)
- [logiops Wiki - CIDs](https://github.com/PixlOne/logiops/wiki/CIDs)
- [ydotool GitHub](https://github.com/ReimuNotMoe/ydotool)
- [gtk4-layer-shell](https://github.com/wmww/gtk4-layer-shell)
- [Wayland layer-shell protocol](https://wayland.app/protocols/wlr-layer-shell-unstable-v1)
