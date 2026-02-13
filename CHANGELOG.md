# Changelog

All notable changes to JuhRadial MX will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.7] - 2026-02-13

### Added

- **Application profile grid view** in Settings with refresh, remove, and per-app "Edit Slices" configuration.
- **Easy-Switch refresh controls** in Settings with detected-slot status and clearer pairing guidance.

### Fixed

- **Radial menu labels now follow selected language** when changing language in Settings (not only center text).
- **Settings theme consistency in new dialogs** by applying JuhRadial themed button/card classes.
- **Tray/menu icon loading reliability** with theme lookup + direct icon path fallbacks.
- **Launcher path preference** now prioritizes `/usr/share/juhradial` over legacy `/opt/juhradial-mx` to avoid stale code.
- **Installed asset paths** for mouse/device visuals and AI icons in installer + settings image loader.
- **Hyprland menu positioning/runtime behavior** refreshes monitor and cursor data on show for stable popup at cursor.

## [0.2.6] - 2026-02-13

### Fixed

- **Fixed settings window crash on startup** — missing `GLib` import in Easy-Switch page caused a `NameError` on launch. Fixes [#5](https://github.com/JuhLabs/juhradial-mx/issues/5). Thanks to [@senkiv-n](https://github.com/senkiv-n) for the report.
- **Resolved remaining CodeQL warnings** — unused imports and mixed import styles cleaned up across overlay files.

## [0.2.5] - 2026-02-11

### Added

- **New 3D radial wheel art** with per-theme etching, glow, and consistent slice geometry for easier icon placement.
- **Expanded translations** for settings navigation and radial menu actions, with stable `action_id` mapping.

### Changed

- **Performance improvements** from sharded/optimized settings + overlay code paths to reduce UI lag and CPU usage.
- **Center label auto-fit** now scales and wraps long translations to avoid clipping.
- **Installer improvements** for broader distro detection, optional logiops/systemd handling, and bundled locales + 3D wheels.

### Fixed

- **Radial menu translations update on first open** after language change (no more double-open).
- **Center text truncation** in the radial wheel for longer translations.
- **Removed broken Chrome Steel (3D) theme** from the selector.

## [0.2.4] - 2026-02-08

### Fixed

- **Fixed high CPU usage when settings window is open**. Zeroconf (mDNS) instance was never closed after network discovery, leaving background threads running indefinitely. Fixes [#3](https://github.com/JuhLabs/juhradial-mx/issues/3).
- **Fixed settings process not exiting after window close**. Added proper cleanup handlers (`close-request`, `do_shutdown`) to stop battery polling timer, clean up Zeroconf resources, and ensure the process terminates cleanly.
- **FlowPage now lazy-loaded**. Network discovery only starts when the user navigates to the Flow tab, not on every settings window open.

### Added

- **Input Leap detection in Flow**. FlowPage now discovers [Input Leap](https://github.com/input-leap/input-leap) instances (open-source KVM software) on the network via `_inputLeapServerZeroconf._tcp` and `_inputLeapClientZeroconf._tcp` service types.

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

[0.2.6]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.5...v0.2.6
[0.2.7]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.6...v0.2.7
[0.2.5]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/JuhLabs/juhradial-mx/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/JuhLabs/juhradial-mx/releases/tag/v0.1.0
