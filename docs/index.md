<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/readme-header.png" width="100%" alt="JuhRadial MX">
  <p><strong>The Logitech MX experience on Linux, native on Wayland</strong></p>
  <p>
    <code>Actions Ring</code> &nbsp;&middot;&nbsp; <code>Settings app</code> &nbsp;&middot;&nbsp; <code>Haptics</code> &nbsp;&middot;&nbsp; <code>Per-app profiles</code> &nbsp;&middot;&nbsp; <code>MX Keypad</code> &nbsp;&middot;&nbsp; <code>MX Keys S</code> &nbsp;&middot;&nbsp; <code>Easy-Switch</code> &nbsp;&middot;&nbsp; <code>Flow</code>
  </p>
</div>

JuhRadial MX is a native Linux companion for Logitech MX devices. A small Rust daemon talks HID++ to the hardware, an overlay draws the Actions Ring at your cursor, and a Qt/QML Settings app configures everything: buttons, gestures, haptics, scrolling, per-app profiles, Easy-Switch, the MX Keypad's display keys and the MX Keys S backlight. The MX Master 4 gets the full feature set, including its haptic motor; the MX Master 3S and 3 use every control they expose, and most other mice can use generic mode for extra-button remapping. This site is the complete guide.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

The installer detects your distro, installs the runtime packages, downloads the newest release (with a prebuilt daemon, so most installs skip the Rust build), sets up the udev rules and autostart, and works for updates too. There are also `.deb` and `.rpm` downloads on the [releases page](https://github.com/JuhLabs/juhradial-mx/releases), `install.sh --user` for Bazzite and Fedora Atomic, and a NixOS module. Full steps and per-distro notes: [Installation](installation.md).

## Explore

| Page | What's there |
|------|--------------|
| [Installation](installation.md) | One-line install, packages, user-mode install, NixOS, building from source, updating |
| [Features](features.md) | Actions Ring, the Settings app, remapping and gestures, haptics, MX Keypad, MX Keys S, Easy-Switch, Flow, gaming, macros |
| [Configuration](configuration.md) | `config.json` reference: buttons, gestures, haptics, keypad, profiles, themes |
| [Plugins](plugins.md) | Add your own actions to the ring with a folder and a `plugin.json` |
| [Compositor Support](compositor-support.md) | GNOME, KDE Plasma 6, Hyprland, COSMIC, Sway, niri, X11 |
| [Troubleshooting](troubleshooting.md) | Common problems and how to fix them |
| [Architecture](architecture.md) | How the daemon, overlay and Settings app fit together, for contributors |
| [FAQ](faq.md) | Quick answers to common questions |

## What is new in 0.4.5

0.4.5 is out as a beta (Beta 2 as of 25 September 2026) and is feature complete; it is marked beta because so much is new and we want it tested on more hardware and desktops before the stable release.

- **A new Settings app** built with Qt/QML: frosted glass cards over a wallpaper, twelve colour themes with matched wallpapers, search across every setting, keyboard navigation and 18 languages. The GTK app stays as the fallback on Qt older than 6.9.
- **MX Keypad support**: nine display keys with pages, per-app profiles, key art, folders, two-state keys, text keys and shareable packs.
- **MX Keys S support** (opt-in, beta): battery, backlight, Easy-Switch follow and key remapping.
- **Directional gestures**: hold the gesture button and drag up, down, left or right, or diagonally, for more actions, with Custom on any direction.
- **Deeper MX Master 4 haptics**: four strength levels, the Sense Panel press force and a switch and pattern for each event.
- **Custom actions on any button**, per-app buttons, macros that record and play back on Wayland, gaming mode, plugins, and a one-zip backup of your whole setup.
- **More ways to install**: `.deb` and `.rpm` downloads, a prebuilt daemon in the release tarball, `install.sh --user` for image-based systems, a NixOS module and a native radial menu on niri.

Beta 2 fixes the mouse grab dropping on unrelated input hotplugs (which could leave a button stuck for the whole desktop), macro recording coming back empty, and rounds out the directional gestures. The full list, with credits and issue links, is in the [changelog](https://github.com/JuhLabs/juhradial-mx/blob/master/CHANGELOG.md).

## A look at it

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/shot-buttons.jpg" width="49%" alt="Settings, Buttons page: the MX Master 4 with clickable button callouts and the Actions Ring editor">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/shot-themes.jpg" width="49%" alt="Settings, Themes page: colour themes with matched wallpapers and wheel skins">
  <br>
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/shot-haptics.jpg" width="49%" alt="Settings, Haptics page: strength, Sense Panel force and a pattern per event">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/github/shot-keypad.jpg" width="49%" alt="Settings, MX Keypad page: nine display keys with pages and key art">
  <br><sub>Click a button on the mouse to reassign it, click a slice of the Actions Ring to edit it.</sub>
</div>

---

New here? Start with [Installation](installation.md), then skim [Features](features.md). Stuck? See [Troubleshooting](troubleshooting.md) or open an [issue](https://github.com/JuhLabs/juhradial-mx/issues).
