<div align="center">
  <img src="assets/juhradial-mx.svg" width="128" alt="JuhRadial MX Logo">
  <h1>JuhRadial MX</h1>
  <p><strong>Beautiful radial menu for Logitech MX Master mice on Linux</strong></p>
  <p>A Logi Options+ inspired experience — works on GNOME, KDE Plasma, Hyprland, COSMIC & more</p>
  <img src="assets/github/githubheader.png" width="100%" alt="JuhRadial MX Banner">
  <p>
    <a href="https://github.com/JuhLabs/juhradial-mx/releases">
      <img src="https://img.shields.io/badge/version-0.2.9-cyan.svg" alt="Version 0.2.9">
    </a>
    <a href="https://github.com/JuhLabs/juhradial-mx/actions/workflows/ci.yml">
      <img src="https://github.com/JuhLabs/juhradial-mx/actions/workflows/ci.yml/badge.svg?branch=master" alt="Build Status">
    </a>
    <a href="https://github.com/JuhLabs/juhradial-mx/actions/workflows/security.yml">
      <img src="https://github.com/JuhLabs/juhradial-mx/actions/workflows/security.yml/badge.svg?branch=master" alt="Security Scan">
    </a>
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0">
    </a>
    <a href="https://github.com/JuhLabs/juhradial-mx/stargazers">
      <img src="https://img.shields.io/github/stars/JuhLabs/juhradial-mx?style=flat&color=yellow" alt="GitHub Stars">
    </a>
  </p>

  <p>
    <strong>New in <a href="CHANGELOG.md">v0.2.9</a>:</strong> GNOME Wayland & COSMIC support, multi-monitor HiDPI fixes, 7-level cursor fallback chain. <a href="#installation">Update now</a>.
  </p>
</div>

---

## Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="assets/screenshots/RadialWheel.png" width="260" alt="Radial Menu">
        <br><em>Radial Menu</em>
      </td>
      <td align="center">
        <img src="assets/screenshots/RadialScreen1.png" width="260" alt="3D Radial Wheel">
        <br><em>3D Neon</em>
      </td>
      <td align="center">
        <img src="assets/screenshots/RadialScreen2.png" width="260" alt="3D Radial Wheel">
        <br><em>3D Blossom</em>
      </td>
    </tr>
    <tr>
      <td colspan="3" align="center">
        <img src="assets/screenshots/Settings.png" width="500" alt="Settings Dashboard">
        <br><em>Settings Dashboard</em>
      </td>
    </tr>
    <tr>
      <td colspan="3" align="center">
        <img src="assets/screenshots/settingsscroll.png" width="500" alt="Settings - DPI & Scroll">
        <br><em>DPI & Scroll Configuration</em>
      </td>
    </tr>
  </table>
</div>

## Features

- **Radial Menu** - Beautiful overlay triggered by gesture button (hold or tap)
- **AI Quick Access** - Submenu with Claude, ChatGPT, Gemini, and Perplexity
- **Multiple Themes** - JuhRadial MX, Catppuccin, Nord, Dracula, and light themes
- **Settings Dashboard** - Modern GTK4/Adwaita settings app with Actions Ring configuration
- **Easy-Switch** - Quick host switching with real-time paired device names via HID++
- **Flow** - Multi-computer control with clipboard sync (inspired by Logi Options+ Flow)
- **Battery Monitoring** - Real-time battery status with instant charging detection via HID++
- **DPI Control** - Visual DPI adjustment (400-8000 DPI)
- **Native Wayland** - Full support for GNOME, KDE Plasma 6, Hyprland, COSMIC, Sway & more
- **Multi-Monitor** - Correct cursor positioning across 1-4+ monitors with HiDPI scaling

## Supported Platforms

<table>
  <tr>
    <th>Desktop Environment</th>
    <th>Cursor Detection</th>
    <th>Status</th>
  </tr>
  <tr>
    <td><strong>GNOME</strong> (Ubuntu, Fedora, Pop!_OS)</td>
    <td>Shell extension D-Bus</td>
    <td>Fully supported</td>
  </tr>
  <tr>
    <td><strong>KDE Plasma 6</strong></td>
    <td>KWin scripting / D-Bus</td>
    <td>Fully supported</td>
  </tr>
  <tr>
    <td><strong>Hyprland</strong></td>
    <td>IPC socket</td>
    <td>Fully supported</td>
  </tr>
  <tr>
    <td><strong>COSMIC</strong> (Fedora, Pop!_OS)</td>
    <td>XWayland sync</td>
    <td>Fully supported</td>
  </tr>
  <tr>
    <td><strong>Sway / wlroots</strong></td>
    <td>XWayland fallback</td>
    <td>Supported</td>
  </tr>
  <tr>
    <td><strong>X11</strong> (any DE)</td>
    <td>xdotool</td>
    <td>Supported</td>
  </tr>
</table>

**Distros:** Fedora, Ubuntu/Debian, Arch/Manjaro, openSUSE, and derivatives. The installer auto-detects your distro and package manager.

## Supported Devices

| Device | Status |
|--------|--------|
| Logitech MX Master 4 | Fully supported |
| Logitech MX Master 3S | Fully supported |
| Logitech MX Master 3 | Fully supported |

---

## Installation

### One-Line Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/install.sh | bash
```

This script will detect your distro, install dependencies, build from source, and configure everything.

### Manual Install - Fedora

```bash
# 1. Install dependencies
sudo dnf install rust cargo logiops python3-pyqt6 qt6-qtsvg \
    python3-gobject gtk4 libadwaita dbus-devel hidapi-devel

# 2. Clone and build
git clone https://github.com/JuhLabs/juhradial-mx.git
cd juhradial-mx
cd daemon && cargo build --release && cd ..

# 3. Configure logiops (maps haptic button to F19)
sudo cp packaging/logid.cfg /etc/logid.cfg
sudo systemctl enable --now logid

# 4. Run
./juhradial-mx.sh
```

### Manual Install - Arch Linux

```bash
# 1. Install dependencies
sudo pacman -S rust python-pyqt6 qt6-svg python-gobject gtk4 libadwaita
yay -S logiops  # or paru -S logiops

# 2. Clone and build
git clone https://github.com/JuhLabs/juhradial-mx.git
cd juhradial-mx
cd daemon && cargo build --release && cd ..

# 3. Configure logiops
sudo cp packaging/logid.cfg /etc/logid.cfg
sudo systemctl enable --now logid

# 4. Run
./juhradial-mx.sh
```

### Requirements

- **Wayland compositor** (GNOME, KDE Plasma 6, Hyprland, COSMIC, Sway) or **X11**
- **logiops** (logid) for button mapping
- **Rust** (for building the daemon)
- **Python 3** with PyQt6 and GTK4/Adwaita
- **XWayland** (for overlay window positioning on Wayland)

---

## Usage

**Hold mode:** Press and hold gesture button → drag to select → release to execute

**Tap mode:** Quick tap gesture button → menu stays open → click to select

### Default Actions (clockwise from top)

| Position | Action |
|----------|--------|
| Top | Play/Pause |
| Top-Right | New Note |
| Right | Lock Screen |
| Bottom-Right | Settings |
| Bottom | Screenshot |
| Bottom-Left | Emoji Picker |
| Left | Files |
| Top-Left | AI (submenu) |

---

## Autostart

```bash
# Add to KDE autostart
cp juhradial-mx.desktop ~/.config/autostart/
sed -i "s|Exec=.*|Exec=$(pwd)/juhradial-mx.sh|" ~/.config/autostart/juhradial-mx.desktop
```

---

## Configuration

Configuration is stored in `~/.config/juhradial/config.json`.

### Themes

Open Settings and select a theme:
- **JuhRadial MX** (default) - Premium dark theme with vibrant cyan accents
- Catppuccin Mocha - Soothing pastel theme with lavender accents
- Catppuccin Latte - Light pastel theme
- Nord - Arctic, north-bluish palette
- Dracula - Dark theme with vibrant colors
- Solarized Light - Precision colors for machines and people
- GitHub Light - Clean light theme

---

## Hyprland Setup

**Automatic:** The installer detects Hyprland and configures window rules automatically.

**Manual:** If needed, add these rules to your `hyprland.conf` or `custom/rules.conf`:

```conf
# JuhRadial MX overlay window rules
windowrulev2 = float, title:^(JuhRadial MX)$
windowrulev2 = noblur, title:^(JuhRadial MX)$
windowrulev2 = noborder, title:^(JuhRadial MX)$
windowrulev2 = noshadow, title:^(JuhRadial MX)$
windowrulev2 = pin, title:^(JuhRadial MX)$
windowrulev2 = noanim, title:^(JuhRadial MX)$
```

These rules ensure the radial menu overlay appears correctly on all workspaces without animations or decorations.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Menu doesn't appear | Check logid: `sudo systemctl status logid` |
| Menu at top-left corner | Log out/in to load GNOME extension, or run `gnome-extensions enable juhradial-cursor@dev.juhlabs.com` |
| Mouse not detected | Should auto-recover (udev restarts logid). Manual fix: `sudo systemctl restart logid` |
| Build fails | Install dev packages: `hidapi-devel`, `dbus-devel` |
| Hyprland: Menu hidden | Add window rules from Hyprland Setup section above |
| GNOME: Extension not loading | Requires session restart (log out/in) on Wayland |

### Debug Mode

```bash
# Run daemon with verbose output
./daemon/target/release/juhradiald --verbose
```

---

## Project Structure

```
juhradial-mx/
├── daemon/              # Rust daemon (HID++ listener, D-Bus, cursor detection)
│   └── src/cursor.rs    # 7-level cursor fallback chain
├── overlay/             # Python UI
│   ├── juhradial-overlay.py   # Main overlay entry point
│   ├── overlay_cursor.py      # Multi-compositor cursor detection
│   ├── overlay_actions.py     # Radial menu actions & themes
│   ├── overlay_painting.py    # Qt rendering & animations
│   └── settings_*.py          # GTK4/Adwaita settings app
├── gnome-extension/     # GNOME Shell cursor helper extension
├── assets/              # Icons, themes, and screenshots
└── packaging/           # logid.cfg, systemd, udev rules
```

---

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE)

---

## Acknowledgments

- [logiops](https://github.com/PixlOne/logiops) - Logitech device configuration
- [logitech-flow-kvm](https://github.com/coddingtonbear/logitech-flow-kvm) by Adam Coddington - Flow multi-computer control inspiration
- [Catppuccin](https://github.com/catppuccin/catppuccin) - Beautiful color scheme

---

## Disclaimer

This project is **not affiliated with, endorsed by, or associated with Logitech** in any way. "Logitech", "MX Master", "Logi Options+", and related names are trademarks of Logitech International S.A. This is an independent, open-source project created by the community for the community.

---

## Star History

<div align="center">
  <a href="https://star-history.com/#JuhLabs/juhradial-mx&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=JuhLabs/juhradial-mx&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=JuhLabs/juhradial-mx&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=JuhLabs/juhradial-mx&type=Date" width="600" />
    </picture>
  </a>
</div>

> If you find JuhRadial MX useful, consider giving it a star — it helps others discover the project!

---

<div align="center">

**Made with love by [JuhLabs](https://github.com/JuhLabs)**

[Report Bug](https://github.com/JuhLabs/juhradial-mx/issues) · [Request Feature](https://github.com/JuhLabs/juhradial-mx/issues) · [Discussions](https://github.com/JuhLabs/juhradial-mx/discussions)

</div>
