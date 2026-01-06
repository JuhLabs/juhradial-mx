# Changelog

All notable changes to JuhRadial MX will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] - 2026-01-06

### Fixed

- **Critical: Fixed gesture button not working**. Corrected logid button CID from `0xd4` to `0x1a0` for MX Master 4, and added required `divert: true` flag for all MX Master mice. This fix is essential for the radial menu to appear when pressing the gesture button.
- **Fixed systemd service path mismatch**. Service now correctly points to `/usr/local/bin/juhradiald` matching the install location.

## [0.2.2] - 2026-01-06

### Fixed

- **Fixed install script for Fedora 43 and Arch Linux**. Corrected PyQt6 SVG package names: `python3-pyqt6-svg` → `qt6-qtsvg` (Fedora), `python-pyqt6-svg` → `qt6-svg` (Arch). Fixes [#1](https://github.com/JuhLabs/juhradial-mx/issues/1).

## [0.2.1] - 2026-01-03

### Security

- **Fixed command injection vulnerability** in radial menu action execution. Shell commands now use `shlex.split()` instead of `shell=True` to prevent arbitrary command execution via malicious config entries.
- **Fixed insecure pairing code generation** in Flow. Replaced `random.choice()` with `secrets.choice()` for cryptographically secure pairing codes.
- **Fixed overly permissive udev rules**. Changed device permissions from `MODE="0666"` to `MODE="0660"` with `GROUP="input"` and `TAG+="uaccess"`. Only users in the `input` group or the currently logged-in user can access devices.
- **Added Content-Length validation** in Flow HTTP server to prevent denial-of-service attacks via large request bodies (max 1MB).
- **Added host slot validation** for Easy-Switch. Host index is now bounds-checked (0-2) to prevent invalid D-Bus calls.
- **Fixed socket resource leak** in Hyprland cursor position detection. Sockets are now properly closed in finally blocks.

### Fixed

- **Easy-Switch now works in radial menu**. Fixed D-Bus type signature mismatch by switching from PyQt6 QDBusMessage to gdbus CLI for reliable byte parameter handling.
- **Install script now updates udev rules** for existing installations, removing old insecure rules.

### Changed

- Settings dashboard now uses `shlex.quote()` for script path sanitization.
- LogiOps documentation link in Devices tab is now clickable.
- Haptic feedback is triggered on Easy-Switch errors.

## [0.2.0] - 2025-12-27

### Added

- **Flow** - Multi-computer control with clipboard sync (inspired by Logi Options+ Flow)
- **Easy-Switch** - Quick host switching with real-time paired device names via HID++
- **HiResScroll support** - High-resolution scroll wheel detection
- **Battery monitoring** - Real-time battery status with instant charging detection via HID++

### Changed

- Improved cursor detection for radial menu positioning
- Optimized HID++ communication for faster device responses

### Fixed

- Fixed delayed radial menu positioning on Hyprland
- Fixed device detection for MX Master 4

## [0.1.0] - 2025-12-20

### Added

- Initial release
- **Radial Menu** - Beautiful overlay triggered by gesture button (hold or tap)
- **AI Quick Access** - Submenu with Claude, ChatGPT, Gemini, and Perplexity
- **Multiple Themes** - JuhRadial MX, Catppuccin, Nord, Dracula, and light themes
- **Settings Dashboard** - Modern GTK4/Adwaita settings app with Actions Ring configuration
- **DPI Control** - Visual DPI adjustment (400-8000 DPI)
- **Native Wayland** - Full support for KDE Plasma 6 and Hyprland
- Support for MX Master 4, MX Master 3S, and MX Master 3

[0.2.1]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/JuhLabs/juhradial-mx/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/JuhLabs/juhradial-mx/releases/tag/v0.1.0
