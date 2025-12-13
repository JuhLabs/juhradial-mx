<div align="center">
  <img src="assets/juhradial-mx.svg" width="128" alt="JuhRadial MX Logo">
  <h1>JuhRadial MX</h1>
  <p><strong>Beautiful radial menu for Logitech MX Master mice on Linux</strong></p>
  <p>A Logi Options+ inspired experience for KDE Plasma 6</p>

  <p>
    <a href="LICENSE">
      <img src="https://img.shields.io/badge/license-GPL--3.0-blue.svg" alt="License: GPL-3.0">
    </a>
  </p>
</div>

---

## Screenshots

<div align="center">
  <img src="assets/screenshots/radial-menu-dark.png" width="400" alt="Radial Menu">
  <p><em>Radial Menu with AI Submenu</em></p>
</div>

## Features

- **Radial Menu** - Beautiful overlay triggered by gesture button (hold or tap)
- **AI Quick Access** - Submenu with Claude, ChatGPT, Gemini, and Perplexity
- **Multiple Themes** - Catppuccin, Nord, Dracula, and light themes
- **Settings Dashboard** - GTK4/Adwaita settings app
- **Native Wayland** - Full KDE Plasma 6 Wayland support

## Supported Devices

- Logitech MX Master 4
- Logitech MX Master 3S
- Logitech MX Master 3

## Requirements

- **KDE Plasma 6** on Wayland
- **logiops** (logid) for button mapping
- **Rust** for building the daemon
- **Python 3** with PyQt6

---

## Quick Install (Fedora)

```bash
# 1. Install dependencies
sudo dnf install rust cargo logiops python3-pyqt6 python3-pyqt6-svg

# 2. Clone the repo
git clone https://github.com/JuhLabs/juhradial-mx.git
cd juhradial-mx

# 3. Build the daemon
cd daemon && cargo build --release && cd ..

# 4. Configure logiops (maps gesture button to F19)
sudo cp packaging/logid.cfg /etc/logid.cfg
sudo systemctl enable --now logid

# 5. Run JuhRadial MX
./juhradial-mx.sh
```

## Quick Install (Arch Linux)

```bash
# 1. Install dependencies
sudo pacman -S rust logiops python-pyqt6

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
| Top-Left | AI (submenu with Claude, ChatGPT, Gemini, Perplexity) |

---

## Autostart

To start JuhRadial MX automatically on login:

```bash
# Copy desktop file to autostart
cp juhradial-mx.desktop ~/.config/autostart/

# Edit to use full path
sed -i "s|Exec=.*|Exec=$(pwd)/juhradial-mx.sh|" ~/.config/autostart/juhradial-mx.desktop
```

---

## Configuration

Configuration is stored in `~/.config/juhradial/config.json`.

### Changing Theme

Open Settings (from radial menu or tray icon) and select a theme:
- Catppuccin Mocha (default dark)
- Catppuccin Latte
- Nord
- Dracula
- Light
- Solarized Light
- GitHub Light

---

## Troubleshooting

### Menu doesn't appear

1. Check if logid is running: `sudo systemctl status logid`
2. Verify button mapping: `sudo logid -v` (press gesture button, should see F19)
3. Check daemon output: `./daemon/target/release/juhradiald`

### Wrong cursor position

Make sure you're running on Wayland (not X11). The daemon uses KWin scripting to get accurate cursor position.

### logiops not detecting mouse

Try reconnecting your mouse or restarting logid: `sudo systemctl restart logid`

---

## Project Structure

```
juhradial-mx/
├── daemon/              # Rust daemon (listens for F19, sends D-Bus signals)
├── overlay/             # Python overlay (PyQt6 radial menu + GTK4 settings)
├── assets/              # Icons and screenshots
└── packaging/           # logid.cfg, systemd service, udev rules
```

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

</div>
