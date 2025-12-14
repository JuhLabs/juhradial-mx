<div align="center">
  <img src="assets/juhradial-mx.svg" width="128" alt="JuhRadial MX Logo">
  <h1>JuhRadial MX</h1>
  <p><strong>Beautiful radial menu for Logitech MX Master mice on Linux</strong></p>
  <p>A Logi Options+ inspired experience for KDE Plasma 6</p>

  <p>
    <a href="https://github.com/JuhLabs/juhradial-mx/actions/workflows/ci.yml">
      <img src="https://github.com/JuhLabs/juhradial-mx/actions/workflows/ci.yml/badge.svg?branch=master" alt="Build Status">
    </a>
    <a href="https://github.com/JuhLabs/juhradial-mx/actions/workflows/security.yml">
      <img src="https://github.com/JuhLabs/juhradial-mx/actions/workflows/security.yml/badge.svg?branch=master" alt="Security Scan">
    </a>
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0">
    </a>
  </p>
</div>

---

## Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="assets/screenshots/radial-menu-dark.png" width="300" alt="Radial Menu">
        <br><em>Radial Menu with AI Submenu</em>
      </td>
      <td align="center">
        <img src="assets/screenshots/settings-buttons.png" width="300" alt="Settings">
        <br><em>Settings Dashboard</em>
      </td>
    </tr>
  </table>
</div>

## Features

- **Radial Menu** - Beautiful overlay triggered by gesture button (hold or tap)
- **AI Quick Access** - Submenu with Claude, ChatGPT, Gemini, and Perplexity
- **Multiple Themes** - Catppuccin, Nord, Dracula, and light themes
- **Settings Dashboard** - Modern GTK4/Adwaita settings app
- **Battery Monitoring** - Real-time battery status via HID++ protocol
- **DPI Control** - Visual DPI adjustment (400-8000 DPI)
- **Native Wayland** - Full KDE Plasma 6 Wayland support

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
sudo dnf install rust cargo logiops python3-pyqt6 python3-pyqt6-svg \
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
sudo pacman -S rust python-pyqt6 python-pyqt6-svg python-gobject gtk4 libadwaita
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

- **KDE Plasma 6** on Wayland
- **logiops** (logid) for button mapping
- **Rust** (for building)
- **Python 3** with PyQt6 and GTK4/Adwaita

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
- Catppuccin Mocha (default)
- Catppuccin Latte
- Nord
- Dracula
- Solarized Light
- GitHub Light

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Menu doesn't appear | Check logid: `sudo systemctl status logid` |
| Wrong cursor position | Ensure you're on Wayland, not X11 |
| Mouse not detected | Restart logid: `sudo systemctl restart logid` |
| Build fails | Install dev packages: `hidapi-devel`, `dbus-devel` |

### Debug Mode

```bash
# Run daemon with verbose output
./daemon/target/release/juhradiald --verbose
```

---

## Project Structure

```
juhradial-mx/
├── daemon/              # Rust daemon (F19 listener, D-Bus, HID++)
├── overlay/             # Python UI (PyQt6 radial menu + GTK4 settings)
├── assets/              # Icons and screenshots
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
- [Catppuccin](https://github.com/catppuccin/catppuccin) - Beautiful color scheme

---

<div align="center">

**Made with love by [JuhLabs](https://github.com/JuhLabs)**

[Report Bug](https://github.com/JuhLabs/juhradial-mx/issues) · [Request Feature](https://github.com/JuhLabs/juhradial-mx/issues) · [Discussions](https://github.com/JuhLabs/juhradial-mx/discussions)

</div>
