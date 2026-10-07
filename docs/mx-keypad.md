---
title: "Logitech MX Keypad on Linux"
description: "Set up the Logitech MX Keypad on Linux with JuhRadial MX: pages of display keys, pages per app, folders, key art, text keys and packs, on Wayland and X11."
---

# The Logitech MX Keypad on Linux

The MX Keypad is a USB pad with nine display keys and two page buttons. Out of the box Linux sees it as a device with nothing on its keys. JuhRadial MX drives the displays and runs what the keys do.

## Set it up

1. [Install JuhRadial MX](installation.md) and plug the keypad in. If it is not found right after an upgrade, unplug it and plug it back in once so the device rules apply.
2. Open **Settings**. The **MX Keypad** tab appears while a keypad is connected.
3. Pick a template (Everyday, Media, Developer, Meetings) or add an empty page, then click a key on the picture to give it an action.

A keypad with no pages shows nine black keys. That is a keypad waiting for its first page, not one that was not detected.

From a terminal, without opening Settings:

```bash
juhradial-settings --keypad-template            # lists the ready templates
juhradial-settings --keypad-template everyday   # adds one as a page
```

## What a key can do

| Key | What it does |
|---|---|
| Shortcut, app, command, link | The same actions the radial menu and the mouse buttons have. |
| Macro or plugin action | Anything you recorded or a plugin added. |
| Text | Pastes a text or prompt with the exact characters on every keyboard layout, with Enter if you want. |
| Hold | Keeps a shortcut down for as long as the key is held (push to talk). |
| Page or folder | Jumps to a page by name, or opens a folder of keys. Either page button goes back. |
| Two states | Switches between two states and shows which one is on (a mute key). |

## Workflows

- **A page per app.** Give a page one or more apps and it comes up by itself while that app is in front. Settings suggests ready profiles for the apps you use most: browsers, editors and IDEs, terminals, media players, video calls, creative tools, office suites, chat apps and AI coding tools.
- **Meetings.** A two-state mute key, a camera key and a hold key for push to talk on one page that follows your call app.
- **Prompts and snippets.** Text keys paste what you would otherwise type, the same on every layout.
- **One keypad, several setups.** Save a group of pages as a pack and import it on another computer, pictures and labels included.

## How the keys look

Each key takes a glyph, any installed app's icon, key art from the gallery in two styles, your own picture, or an animated GIF or WebP, with its own colour and an optional label. Brightness is set for the whole pad.

## Good to know

- While the screen is locked the keys go blank and do nothing on desktops that report the lock to logind, such as KDE Plasma and GNOME. Other lock screens (swaylock, hyprlock) leave the keys active for now.
- Pages per app follow the focused window. On GNOME, COSMIC, sway and niri that works for XWayland apps only; see [Compositor & Desktop Support](compositor-support.md).
- Scripts can paint a key live over D-Bus.

More in [Features: MX Keypad](features.md#mx-keypad), and for a keypad that stays dark see [Troubleshooting](troubleshooting.md).
