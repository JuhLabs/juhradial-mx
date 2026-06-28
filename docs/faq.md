# Frequently Asked Questions

Quick answers to the questions people ask most about JuhRadial MX, the native Linux power-tool for the Logitech MX Master 4 (and friends). If you do not find your answer here, check [Troubleshooting](troubleshooting.md) or open a thread in [Discussions](https://github.com/JuhLabs/juhradial-mx/discussions).

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## Devices and compatibility

### Which mice are supported?

| Device | Support level |
|--------|---------------|
| Logitech MX Master 4 | Full HID++ (radial menu, haptics, DPI, scroll, easy-switch, battery) |
| Logitech MX Master 3S | Full HID++ |
| Logitech MX Master 3 | Full HID++ |
| Any other mouse | Generic mode via evdev (radial menu + button remapping) |

!!! note
    Hardware-specific features (haptic feedback, DPI control, easy-switch host names, live battery) need a real HID++ device. On a generic mouse you still get the radial menu and button remapping. See [Features](features.md) for the full breakdown.


### Do I need Logitech's own software installed?

No. JuhRadial MX is a fully independent, open-source project. It speaks HID++ to the mouse directly over `hidraw`, so there is no vendor daemon, account, or proprietary client involved. Nothing else needs to be installed alongside it, and it is not affiliated with or endorsed by Logitech.

### Does it work over Bluetooth as well as the USB receiver?

Yes, both the Logi Bolt / Unifying USB receiver and direct Bluetooth pairing work. Bluetooth mice show up as virtual `uhid` kernel devices, which JuhRadial MX matches and talks to over HID++ the same way it does a wired/receiver connection.

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## Display server and desktop

### Does it work on Wayland or only X11?

Both. JuhRadial MX is built Wayland-first and also runs on X11. The daemon detects the cursor position through the best available path for your session and positions the radial menu there.

### Which desktops and compositors are supported?

| Desktop / compositor | Cursor detection | Status |
|----------------------|------------------|--------|
| GNOME (Ubuntu, Fedora, Pop!_OS) | Shell extension over D-Bus | Fully supported |
| KDE Plasma 6 | KWin scripting / D-Bus | Fully supported |
| Hyprland | IPC socket | Fully supported |
| COSMIC | XWayland sync | Fully supported |
| Sway / wlroots | XWayland fallback | Supported |
| niri | XWayland (xwayland-satellite) | Supported |
| X11 (any DE) | xdotool | Supported |

GNOME and niri have specific setup notes (a Shell extension for GNOME, an XWayland satellite for niri). See [Compositor-Support](compositor-support.md) for the details.

!!! tip
    On Wayland the overlay relies on XWayland for window positioning. If the menu appears in the top-left corner instead of at your cursor, that is almost always a compositor cursor-detection issue covered in [Troubleshooting](troubleshooting.md).


<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## Safety and permissions

### Is it safe for my mouse? Does it write firmware?

Yes, it is safe. JuhRadial MX never writes or flashes firmware. It only sends standard HID++ feature commands that the mouse already exposes (DPI, scroll, haptics, easy-switch, battery queries) and reads input events.

Button "diverts" (which let the daemon intercept the gesture and haptic buttons) are applied with the HID++ **volatile** flag. Volatile diverts are not persisted to the device and are cleared automatically on unplug, reboot, or hotplug. The daemon simply re-applies them when the device reconnects. Nothing about your mouse's saved state is permanently changed.

### Does it need root?

No, the daemon runs as your normal user. It needs access to the mouse's `hidraw` node and to `uinput` (for injecting remapped actions), and that access is granted by your user being in the `input` group, set up by the installer's udev rule. The one-line installer uses `sudo` to copy files into system locations during installation, but the running daemon itself does not run as root.

### Is my data private?

Yes. Your configuration lives entirely on your machine in `~/.config/juhradial/config.json`. There is no telemetry, no account, and no cloud service. JuhFlow traffic (see below) is end-to-end encrypted and stays on your local network.

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## JuhFlow

### What is JuhFlow?

JuhFlow is the cross-computer control feature. It lets you move your cursor seamlessly between your Linux machine and a Mac, sharing input and clipboard, similar to a software KVM. The Linux side is built into JuhRadial MX (just enable Flow in Settings); the Mac side is a small companion app you download and pair.

- **Peer-to-peer:** machines auto-discover each other on your local network, no cloud or relay server.
- **Encrypted:** X25519 key exchange plus AES-256-GCM, so all traffic is end-to-end encrypted.
- **Zero config:** no manual IP entry needed.

!!! note
    If you quit JuhRadial MX while JuhFlow is connected, restart the companion app on the Mac side and reconnect. Windows support is planned.


<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## Configuration and usage

### How do I change or remap the gesture button?

The thumb gesture button opens the radial menu by default. Open the Settings app and go to the **Buttons** page to remap buttons and to configure what each radial slice does.

By default, the daemon diverts only the gesture button and the haptic button. Other buttons (back, forward, middle, thumb-wheel click) are not diverted out of the box, so they keep their normal behavior until you assign an action to them in Settings. After saving, the daemon reloads its configuration automatically. See [Configuration](configuration.md) for the full schema and per-slice options.

### How do I trigger the menu?

- **Hold mode:** press and hold the gesture button, drag to a slice, release to execute.
- **Tap mode:** quickly tap the gesture button; the menu stays open and you click to select.

### Where is my configuration stored?

In `~/.config/juhradial/config.json`. Editing in the Settings app is the recommended path, since it validates input and tells the daemon to reload.

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## Maintenance

### How do I uninstall it?

There is no destructive system change to undo, but if you want to remove everything, stop the daemon and delete the installed files:

```bash
# Stop and disable the per-user service
systemctl --user disable --now juhradialmx-daemon.service 2>/dev/null || pkill -f juhradiald

# Remove installed binaries and launchers
sudo rm -f /usr/local/bin/juhradiald /usr/local/bin/juhradial-mx /usr/local/bin/juhradial-settings

# Remove the app, shared data, and desktop entries
sudo rm -rf /opt/juhradial-mx /usr/share/juhradial
sudo rm -f /usr/share/applications/juhradial-mx.desktop
sudo rm -f /usr/share/applications/org.kde.juhradialmx.settings.desktop

# Remove the udev rule and reload
sudo rm -f /etc/udev/rules.d/99-juhradialmx.rules
sudo udevadm control --reload-rules

# Remove the per-user service unit and your config (optional)
rm -f ~/.config/systemd/user/juhradialmx-daemon.service
rm -rf ~/.config/juhradial
```

!!! warning
    The last line deletes your saved configuration (themes, button maps, profiles, Flow pairing). Skip it if you plan to reinstall later.


### How do I update?

Re-run the one-line installer; it rebuilds from the latest source. See [Installation](installation.md) for details.

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/separator.png" width="80%" alt="">
</div>

## Still stuck?

- [Troubleshooting](troubleshooting.md) for the common "menu in the wrong corner" and "mouse not detected" fixes
- [Architecture](architecture.md) if you want to understand how the daemon, overlay, and Settings app fit together
- [Home](index.md) for the full table of contents

<div align="center">
  <strong>Made with care by <a href="https://github.com/JuhLabs">JuhLabs</a></strong>
</div>
