---
title: "Logi Options+ alternative for Linux"
description: "Logitech does not ship Logi Options+ for Linux. JuhRadial MX is the open-source alternative for MX Master mice, the MX Keypad and the MX Keys S, on Wayland and X11."
---

# A Logi Options+ alternative for Linux

Logitech ships Logi Options+ for Windows and macOS only. On Linux an MX Master works as a plain mouse: no Actions Ring, no button customisation, no haptics, no app-specific settings.

JuhRadial MX is an open-source program that brings those features to Linux. It talks to the hardware directly (HID++ over `hidraw`), so nothing from Logitech needs to be installed, and it is not affiliated with or endorsed by Logitech.

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

The [installation guide](installation.md) has the packages, the image-based systems (Bazzite, Fedora Atomic) and NixOS.

## What you get, compared with Logi Options+

| In Logi Options+ | In JuhRadial MX on Linux |
|---|---|
| Actions Ring | The same eight-slice ring under your cursor: hold or tap a button, pick a slice. Slices run shortcuts, apps, commands, links, macros and plugin actions. See [Radial Menu](features.md#radial-menu). |
| Button customisation | Every button and every other control the mouse reports can be reassigned, for all apps, for one mouse or for one app. See [Button & Action Remapping](features.md#button-action-remapping). |
| Gesture button | Hold and drag up, down, left or right for four more actions. See [Directional gestures](features.md#directional-gestures). |
| App-specific settings | Per-app profiles that override only what you change, with their own buttons and their own ring. See [Per-Application Profiles](features.md#per-application-profiles). |
| Pointer speed and SmartShift | DPI over the range the mouse reports, SmartShift, ratchet or free-spin, scroll force, hi-res and natural scrolling, thumb wheel modes. See [Scroll & SmartShift](features.md#scroll-smartshift). |
| Haptic feedback (MX Master 4) | Four strength levels, the Sense Panel press force and a pattern per event. See [Haptic Feedback](features.md#haptic-feedback). |
| Easy-Switch | Every computer slot, switching from the ring or a button, and the MX Keys S following the mouse. See [Easy-Switch](features.md#easy-switch). |
| Flow | Cursor and clipboard between Linux and macOS on your network, with approved computers only. See [JuhFlow](features.md#juhflow). |
| Smart Actions | Macros you record and edit, bound to a button, a slice or a keypad key. See [Macros](features.md#macros). |
| MX Keypad display keys | Pages, per-app pages, folders, two-state keys, key art and shareable packs. See [MX Keypad on Linux](mx-keypad.md). |
| Keyboard backlight (MX Keys S) | Battery, backlight level and mode, key remapping (opt-in, beta). See [MX Keys S](features.md#mx-keys-s-beta). |
| Backup to your account | A zip on your own disk that restores the whole setup on this or another computer. See [Backup](features.md#backup). |

## What it does not do

- **Firmware updates.** JuhRadial MX does not flash devices.
- **Pairing a device with a receiver.** Devices that are already paired are found; pairing itself is not part of JuhRadial MX yet.
- **An account or a cloud.** There is none. Your configuration is a file in `~/.config/juhradial/`, and nothing is sent anywhere: no telemetry, no sign-in.
- **Every Logitech device.** The MX Master 4, 3S and 3 have the full feature set; other HID++ mice get the controls they report. See [which devices are supported](faq.md#which-mice-are-supported).

## Where it runs

Wayland and X11. The menu opens at the pointer on KDE Plasma 6, GNOME 45 to 51, Hyprland, COSMIC, sway, niri and any X11 desktop; what each one needs is in [Compositor & Desktop Support](compositor-support.md).

The one-line installer covers Fedora, Ubuntu, Debian, Linux Mint, Pop!_OS, Arch, Manjaro, EndeavourOS, CachyOS, openSUSE, Bazzite and Fedora Atomic; there are `.deb` and `.rpm` packages and a NixOS module as well.

## Already using something else?

[Coming from logiops or Solaar](migrating.md) lists where each of their settings lives in JuhRadial MX.
