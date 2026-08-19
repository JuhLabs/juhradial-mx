# Changelog

All notable changes to JuhRadial MX will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Pick an installed application for a radial slice** - The slice dialog in Settings has a "Pick Application…" button (for `exec` slices) that lists installed applications the same way your desktop menu would, instead of typing a raw command by hand. Picking one fills the command and imports the app's real icon (cached under `~/.config/juhradial/icons/`), replacing the generic glyph on the wheel. Submenu rows (Quick Links) got the same treatment: each of the four rows can now point at an app instead of a URL, via a per-row "App…" picker with a "Clear" button to switch back to a link.
- **Haptic feedback on application switch** - The MX Master 4 actuator now pulses whenever the focused application window changes (Alt+Tab, taskbar, clicking a different app), independent of the radial menu. On by default, with its own toggle and pattern in Settings → Haptics → App Switch, so it can be turned off separately from the menu's own haptics. Reuses the daemon's existing window tracker (also used for per-application profiles), so it works wherever that already does: KDE, Hyprland, and X11.
- **Haptic feedback on monitor switch** - Also pulses when the cursor moves to a different physical monitor, via a lightweight ambient poll in the overlay process. On by default, with its own toggle and pattern in Settings → Haptics → Monitor Switch. Known limitation: on COSMIC and niri the underlying cursor query can occasionally miss or delay a crossing; KDE, Hyprland, GNOME, and X11 are unaffected.

### Fixed

- **Haptic feedback works inside submenus** - Hovering between items in an open submenu (Quick Links, AI assistant, the app-picker submenu rows) gave no haptic pulse, only the main Actions Ring did. Submenu hover now triggers the same `slice_change` pulse as the main ring.

## [0.4.4] - 2026-08-18

### Fixed

- **SmartShift settings actually reach the mouse now** - On the MX Master 3/3S/4 the daemon was calling SmartShift with the legacy `0x2110` function IDs, but these mice expose SmartShift Enhanced (`0x2111`), whose functions are shifted by one. Reads therefore parsed a capabilities reply as ratchet state (reporting a constant threshold no matter the real setting) and writes landed on a getter, so changing the wheel mode or threshold silently did nothing. The daemon now records which SmartShift variant the device exposes and uses the matching function IDs, keeping the third parameter (torque on `0x2111`, default threshold on `0x2110`) per-variant so a threshold write can no longer reprogram torque. Fixing the writes also exposed an inverted mode mapping in the D-Bus layer (enabling SmartShift would have forced permanent free-spin) and two contradictory threshold encodings between the settings path and per-app profiles; both are now a single mapping. Reported with hardware traces by [@FoxQwartz](https://github.com/FoxQwartz). Fixes [#107](https://github.com/JuhLabs/juhradial-mx/issues/107).
- **Hi-res scroll get/set target the right feature** - `GetHiresscrollMode`/`SetHiresscrollMode` were addressed to the SmartShift feature index instead of HiRes Wheel (`0x2121`), so the reported hi-res state was a misread of SmartShift's wheel mode, and toggling smooth or natural scrolling silently rewrote the SmartShift ratchet mode. Both now resolve `0x2121`, whose function IDs and mode bits the code already used correctly. Also reported by [@FoxQwartz](https://github.com/FoxQwartz). Fixes [#106](https://github.com/JuhLabs/juhradial-mx/issues/106).
- **Settings live state is populated and stays current** - The Devices page WHEEL readout is primed from the daemon on open (previously blank until the wheel-mode button was pressed) and now distinguishes SmartShift from a permanent ratchet; the Connected Device battery row follows charge signals instead of freezing at its load-time value; and the Point-and-scroll mode selector re-reads device state when the hardware wheel-mode button fires. Reported by [@FoxQwartz](https://github.com/FoxQwartz). Fixes [#108](https://github.com/JuhLabs/juhradial-mx/issues/108).
- **Connection row shows the real link** - The Devices page guessed "USB Receiver / Bluetooth"; it now reads the HID bus from sysfs and reports Bolt, Unifying, plain USB receiver, or Bluetooth, with icon names that exist on Breeze (the old hardcoded names rendered as a broken-image glyph on KDE).

### Changed

- **Scroll speed slider shows its effect** - The Point-and-scroll speed slider now displays the approximate lines-per-notch it produces instead of an unlabeled position, and the header info hints render as theme-independent glyphs (the themed info icon is full-color blue on Breeze and clashed with the dark header).

## [0.4.3] - 2026-08-15

### Added

- **Custom quick links in the radial submenu** - The submenu slice (previously fixed to Claude, ChatGPT, Gemini, and Perplexity) is now editable: the slice dialog in Settings offers up to four label + URL rows, so the wheel can open any web page. Known AI domains keep their brand icons, other links get a browser glyph, and leaving the rows empty keeps the familiar AI defaults. The preset is now called "Quick Links".

### Changed

- **Faster, smoother radial menu** - A performance wave contributed by [@frizikk](https://github.com/frizikk): cursor movement is coalesced to one update per physical input frame ([#91](https://github.com/JuhLabs/juhradial-mx/pull/91)), submenu frames that did not change are no longer repainted ([#95](https://github.com/JuhLabs/juhradial-mx/pull/95)), haptic pulses are dispatched asynchronously so a busy daemon cannot stall the menu open ([#93](https://github.com/JuhLabs/juhradial-mx/pull/93)), the play/pause glyph queries the media player without blocking and only when a media slice is configured ([#94](https://github.com/JuhLabs/juhradial-mx/pull/94)), and on KDE the menu-open path talks to KWin over native D-Bus calls instead of spawning two helper processes each time, also cleaning up one-shot cursor scripts KWin used to accumulate ([#98](https://github.com/JuhLabs/juhradial-mx/pull/98)).
- **Lower idle footprint** - Also from [@frizikk](https://github.com/frizikk): Flow stops rewriting its status file every 5 seconds while no other machine is connected ([#92](https://github.com/JuhLabs/juhradial-mx/pull/92)), Flow edge polling relaxes to 32 ms while the cursor is away from the handoff edge ([#96](https://github.com/JuhLabs/juhradial-mx/pull/96)), and X11 active-window tracking watches for focus changes with a persistent `xprop -spy` instead of polling every 750 ms ([#99](https://github.com/JuhLabs/juhradial-mx/pull/99)).

## [0.4.2] - 2026-08-14

### Fixed

- **Gesture button survives the power switch and radio sleep** - The mouse clears its volatile HID++ button divert when switched off or sleeping, but the Bolt receiver keeps its device nodes, so the daemon never saw a reconnect and the gesture and haptic buttons stayed dead until a restart. The daemon now re-applies all volatile state (gesture/haptic divert, reassigned buttons, thumb-wheel reporting) when the mouse announces it is back online, when a failing battery poll recovers, and on `ReloadConfig`, which now also re-diverts the gesture and haptic buttons. Fixes [#102](https://github.com/JuhLabs/juhradial-mx/issues/102).
- **Settings UI and overlay render on Debian/Ubuntu** - The PyGObject cairo bindings (`python3-gi-cairo`) were missing from the Debian/Ubuntu install path. On those distros `python3-gi` does not pull in cairo, so GTK4/libadwaita widgets failed to render. The installer, the installation guide, and the contributor setup now install `python3-gi-cairo`. The Fedora and Arch packaging already list cairo explicitly; those paths and openSUSE are unchanged.
- **Arch PKGBUILD and Fedora RPM spec build again** - Both still installed the removed `packaging/udev/99-logitech-hidpp.rules`, so `makepkg` and `rpmbuild` failed in the packaging step. They now install the current `99-juhradialmx.rules` (and `60-ydotool-uinput.rules` for uinput access, matching `install.sh`). Fixes [#89](https://github.com/JuhLabs/juhradial-mx/issues/89).

## [0.4.1] - 2026-07-21

### Added

- **GNOME Shell 50 support** - The bundled GNOME cursor helper extension now declares compatibility with GNOME Shell 50.

### Fixed

- **Radial menu opens at the cursor on GNOME Wayland** - XWayland only refreshes its pointer while the cursor sits over an X11 window, so on an all-Wayland GNOME desktop the overlay positioned itself from a stale reading. It now forces a refresh and reads the result in Qt's coordinate space, so the menu stays on the cursor on scaled displays too.
- **A second tap closes the menu again** - The daemon emits its open signal twice for a single press, and the duplicate reopened the menu that had just closed.
- **Only one overlay runs at a time** - On KDE, session restore and the launcher could each start an overlay, and the two fought over the menu, leaving the gesture button unresponsive. Fixes [#60](https://github.com/JuhLabs/juhradial-mx/issues/60).
- **Thumb-wheel assignments take effect** - The Buttons tab wrote the setting to a key the daemon does not read, so the wheel kept its previous mode, for example staying on zoom after being set to horizontal scroll.
- **Screenshot action picks a tool that works** - It defaulted to spectacle, which cannot capture outside KDE; GNOME and other portal desktops now use the freedesktop screenshot portal.

## [0.4.0] - 2026-06-28

### Added

- **Thumb-wheel actions** - Bind the side thumb-wheel to system volume, zoom, or horizontal scroll, with direction-invert and speed controls, on the Point & Scroll page.
- **Per-application profiles** - DPI, button, and scroll settings switch automatically as you move between applications. Active-window tracking on KDE, Hyprland, and X11.
- **Portable system actions** - Assign Show Desktop, Switch Desktop (left/right), Task Switcher, Close Window, Lock Screen, or Calculator to any button; each uses the native mechanism for your desktop (GNOME, KDE, Hyprland, Sway, COSMIC).
- **Live device state** - Battery level, DPI, scroll ratchet, and the active Easy-Switch host now update in real time on the Devices page.
- **Settings search** - A search box in the header finds any setting and jumps straight to its page.
- **Low-battery notification** - A desktop notification when the mouse battery runs low.
- **niri compositor support** - The radial menu now appears on niri.

### Fixed

- **Thumb-wheel actions now fire** - Corrected the HID++ thumb-wheel reporting call so wheel rotations are actually delivered and acted on.
- **Button reassignments work on Wayland** - Volume, zoom, copy/paste, and the back/forward/middle reassignments are injected through the kernel uinput device, so they work on Wayland as well as X11. Fixes [#26](https://github.com/JuhLabs/juhradial-mx/issues/26).
- **Correct menu position under fractional scaling** - The radial menu lands on the cursor on KDE Wayland at 125%, 150%, and other scales. Fixes [#25](https://github.com/JuhLabs/juhradial-mx/issues/25).
- **No more menu jitter or wrong monitor after boot** - Fixes [#32](https://github.com/JuhLabs/juhradial-mx/issues/32).
- **Button action icons no longer blank** - Changing an action keeps a proper icon. Fixes [#34](https://github.com/JuhLabs/juhradial-mx/issues/34).
- **Builds on Ubuntu 24.04 and other current distros** - The installer bootstraps an up-to-date Rust toolchain instead of relying on an older system one. Fixes [#23](https://github.com/JuhLabs/juhradial-mx/issues/23).
- **openSUSE Tumbleweed install** - Uses the correct PyQt6 package. Fixes [#24](https://github.com/JuhLabs/juhradial-mx/issues/24).
- **Battery level shows reliably** - Live battery updates appear immediately instead of reading "unavailable", and charging-status labels are correct.

### Changed

- **Themes recolor the whole interface** - Every theme drives the full palette, and the theme preview shows the actual radial wheel each theme uses.
- **More robust zoom and horizontal scroll** - Zoom uses layout-independent keys (works on non-US keyboards); horizontal scroll uses the thumb-wheel's native hardware scrolling, so it works on every compositor.
- **Rebuilt Haptics, Flow, and Macros pages** - Animated actuator waveform with preset-to-event syncing, a clearer Flow topology view, and a timeline macro studio.
- **Application profile picker** - Shows real application icons and adds a search box.
- **Smoother Wayland input** - The installer sets up ydotool autostart and uinput access so injected actions work out of the box.

### Security

- **Resolved code-scanning alerts** - Addressed the open CodeQL findings.

## [0.3.2-beta] - 2026-03-24

### Fixed

- **Daemon now respects button config** - Gesture and thumb buttons dispatch their configured action instead of always opening the radial menu. Fixes [#14](https://github.com/JuhLabs/juhradial-mx/issues/14).
- **Button config dialog redesigned** - Actions grouped into categories (Common, Navigation, Clipboard, Media, System, Mouse) with GNOME HIG checkmark selection pattern.

### Added

- **Config-driven button actions** - 20 assignable actions including Virtual Desktops overview (GNOME, KDE, Hyprland, Sway), keyboard shortcuts (Copy, Paste, Undo, etc.), media controls, and more.
- **Desktop-specific overview toggle** - Virtual Desktops action uses native APIs per desktop: GNOME OverviewActive, KDE kglobalaccel, Hyprland dispatch, Sway fallback.
- **D-Bus and KWin action executors** - Previously stubbed execute_dbus() and execute_kwin() now fully functional.

### Changed

- **Default button assignments** - Fresh installs default to gesture=Virtual Desktops, thumb=Radial Menu (matching Settings UI defaults).
- **Splash screen redesign** - Chrome metallic wheel, warm amber text glow, subtle wheel rotation, slower arc spin for premium feel.

## [0.3.1-beta] - 2026-03-13

### Added

- **Macro system** - Full macro engine with key sequences, delays, text typing, and WhileHolding repeat loops. Configurable per-button via Settings > Macros page with a visual timeline editor.
- **Gaming mode** - Bind any mouse button (side buttons, extra buttons) to macros via evdev. Works with SteelSeries, Razer, Corsair, and any mouse with extra buttons. Capture dialog detects the exact button you press.
- **Splash screen** - Animated startup screen with radial wheel image and 3-layer pulsing text glow effect.
- **Custom sidebar navigation icons** - 9 hand-designed PNG icons for settings navigation (Buttons, Point & Scroll, Haptic Feedback, Devices, Easy-Switch, Flow, Macros, Gaming, Settings).
- **53 new translation strings** across all 19 supported languages - navigation sidebar, macro UI, gaming mode, import tooltips, confirmation dialogs, and more.

### Fixed

- **Removed logid/LogiOps dependency** - Daemon handles HID++ communication directly. No more external logid process, no more logid.cfg. One less thing to install and configure. Fixes device detection issues on many distros.
- **Device name shows actual mouse name** - HID++ device name query returns "MX Master 4" instead of "Logitech USB Receiver Mouse". Fixes [#13](https://github.com/JuhLabs/juhradial-mx/issues/13).
- **DPI controls work reliably** - Proper device matching by HID++ feature detection instead of string name matching. Fixes [#13](https://github.com/JuhLabs/juhradial-mx/issues/13).
- **Settings window fits on screen** - Window sizing respects display bounds. Fixes [#13](https://github.com/JuhLabs/juhradial-mx/issues/13).
- **Gesture button no longer leaks to OS** - BTN_BACK (MX gesture button) is suppressed from reaching applications even with no macro bound.
- **Radial wheel stays open on GNOME** - Uses Tool window type instead of Popup to prevent Mutter from auto-dismissing on focus change.
- **Flow indicator crash on GNOME** - Fixed undefined `_()` call in indicator.py that prevented the Flow edge indicator from ever showing.
- **Navigation sidebar now translates** - Language change signal properly refreshes sidebar labels (root cause: settings_constants using no-op lambda instead of real `_()`).
- **Multi-distro compatibility** - Fixed IS_SWAY detection, ydotool dependency, input group check, log path, and uinput permission hint across Fedora/Ubuntu/Arch/openSUSE.
- **Event batching and timer cleanup** - evdev uinput batches events until SYN_REPORT, all GLib timers properly cancelled on shutdown.
- **Thread safety** - Fixed QApplication.instance() access from non-main threads on KDE Wayland.
- **CodeQL empty-except warnings** - Added specific exception types to all bare except blocks across the codebase.

### Changed

- **Flow edge detection tuned** - Dwell time 100ms to 350ms, velocity threshold 3000 to 8000 px/s, cooldown 1000 to 1500ms, indicator zone 500 to 350px. Prevents accidental triggers and clipboard overwrites.
- **Process names** - Overlay shows as `juhradial-overlay` and settings as `juhradial-settings` in system monitors (via prctl).
- **Host switch cooldown removed** - Easy-Switch host switching is now instant (0ms cooldown).
- **CodeQL upgraded to v4** - CI workflow uses latest CodeQL action.

### Security

- **Resolved all CodeQL code scanning alerts** - Fixed 30 bare `except:` blocks with proper exception types across overlay, flow, and settings code.

## [0.3.0-beta] - 2026-03-07

### Added

- **JuhFlow cross-computer control** - Move your cursor seamlessly between Linux and Mac. Encrypted peer-to-peer (X25519 + AES-256-GCM), auto-discovery on local network, no cloud required. Signed & notarized macOS companion app included.
- **Generic mouse support** - JuhRadial now works with any mouse, not just Logitech MX Master. Bind any mouse button via a "press your button" capture dialog in Settings. SteelSeries, Razer, Corsair, and any other mouse with extra buttons are supported via evdev.
- **Clickable DPI value** - Click the DPI number on Point & Scroll to type an exact value (400-8000) instead of dragging the slider.
- **Clickable sensitivity %** - Click the SmartShift sensitivity percentage to type an exact value (1-100%).
- **Interactive generic mouse visualization** - Labeled button positions with hover highlights and click-to-configure on the generic mouse image.

### Fixed

- **GTK4 child iteration** - Replaced broken Python iteration with get_first_child()/get_next_sibling() throughout settings.
- **Button config persistence** - Dialog now calls config.save() so button remaps survive restart.
- **Battery timer leak** - Timer stops when daemon is unavailable instead of running forever.
- **Atomic profile writes** - Profile JSON uses write-to-tmp + os.replace to prevent corruption on crash.
- **UPower D-Bus cleanup** - Signal subscriptions and system bus properly stored and cleaned up.
- **Capture/connect timer cleanup** - All GLib timers stored and cancelled on window close.
- **RadialMenuConfigDialog** - Uses ConfigManager instead of raw json.load/dump for state consistency.
- **SmartShift parameters** - Uses actual device params instead of hardcoded defaults.
- **Flow server double-start** - Prevented via programmatic toggle flag.
- **Donate card CSS** - Replaced invalid alpha() with pre-computed rgba() values.
- **Connection dot CSS** - Added .connected/.disconnected classes for Flow and EasySwitch pages.

### Changed

- **All print() migrated to logging** - Every settings_*.py file now uses proper logging module.
- **Dead CSS removed** - Removed @keyframes (not supported in GTK4), ~15% unused CSS rules, stale IS_DARK_THEME global.
- **Haptics D-Bus proxy cached** - Single proxy instance instead of creating one per call.
- **GenericMouseVisualization throttled** - Motion events throttled to 33ms to reduce CPU.
- **Root directory cleaned up** - Moved 11 files into packaging/, scripts/, tests/ for a tidier GitHub page.
- **Project structure updated** - New tests/, scripts/ directories; juhflow/ contains Mac companion app + signed .dmg.

## [0.2.12] - 2026-02-27

### Added

- **Smooth hover transitions** - Slice highlights now fade in (~112ms) and fade out (~80ms) with interpolated colors instead of instant hard cuts. Applies to both vector and 3D themes. All visual properties animate smoothly: fill, border, icon background, icon color, and glow ring.
- **Submenu droplet pop-out animation** - AI and Easy-Switch submenu items now animate outward from the wheel edge with OutBack easing (slight overshoot then settle), staggered cascade timing per item, and scale-up from 50% to full size. Creates a fluid "droplet" effect instead of instant appearance.
- **Dynamic play/pause icon** - The Play/Pause slice now shows a pause icon (two bars) when media is actively playing and a play triangle when stopped or paused. State is queried via `playerctl status` each time the radial menu opens. Gracefully falls back to play icon if playerctl is not installed.
- **Selection flash feedback** - Brief white flash on the selected slice before the menu closes, giving clear visual confirmation of which action was picked.
- **Menu open bloom effect** - Radial wheel scales from 0.92x to 1.0x with OutCubic easing during the fade-in, creating a subtle "breathing" bloom on open.
- **Center zone pulse** - The center circle does a brief elastic scale pulse when the menu appears, drawing the eye to the center label.
- **Easy-Switch OS icons** - The Easy-Switch submenu now shows real OS logos (Linux Tux, Windows, macOS Apple, iOS, Android robot, ChromeOS Chrome) instead of generic numbered circles. Users can assign an OS type per host slot in Settings > Easy-Switch. Host 1 defaults to Linux, others to Unknown. Icons are official SVGs from Wikimedia Commons rendered via QSvgRenderer.

### Changed

- **Shared animation timer architecture** - All animations are driven by a single 16ms QTimer that auto-starts on interaction and auto-stops when all animations settle. No CPU usage when the menu is hidden or idle. Zero new dependencies - built entirely on existing PyQt6 primitives.

### Notes

- **Generic mouse support** is now available in v0.3.0-beta. Any mouse with extra buttons works via evdev.
- **First-launch setup wizard** is planned for a future release.
- Looking ahead: exploring Logitech MX Keys S keyboard support (brightness control, hotkey layout customization) via the existing HID++ 2.0 protocol layer.

## [0.2.11] - 2026-02-19

### Fixed

- **MX Master 4 for Business not triggering radial menu** — logid matches devices by exact name; the consumer model is `"MX Master 4"` while the B2B variant reports itself as `"MX Master 4 for Business"`. The logid.cfg only had the consumer name, so the CID `0x1a0` button was never diverted to `KEY_F19` on the Business variant. Added `"MX Master 4 for Business"` as a separate device entry with the identical CID mapping. Fixes [#7](https://github.com/JuhLabs/juhradial-mx/issues/7).

## [0.2.10] - 2026-02-19

### Fixed

- **Multi-monitor menu positioning on KDE Plasma Wayland** — Menu now appears at the correct cursor position on secondary monitors. KWin's `workspace.cursorPos` returns logical coordinates (accounting for per-monitor DPI scaling) while `QWidget.move()` uses XWayland physical pixel coordinates; these diverge on setups with different per-monitor scale factors. On non-Hyprland/GNOME/COSMIC Wayland compositors with XWayland, the overlay now re-queries cursor position via `XQueryPointer` (which is always in XWayland's coordinate space) immediately before positioning the window. Fixes [#8](https://github.com/JuhLabs/juhradial-mx/issues/8).
- **Daemon killed after ~10 seconds on Fedora 43 / KDE** — Two root causes: (1) Fedora's systemd drop-in `10-timeout-abort.conf` activates a watchdog that kills daemons not implementing `sd_notify` heartbeats — fixed by adding `WatchdogSec=0` to explicitly disable watchdog for this service. (2) `PrivateTmp=yes` was set, placing the daemon's `/tmp` in a private namespace invisible to KWin — the daemon creates temporary `.js` script files and passes their paths to KWin via D-Bus, so KWin could not find those files, causing the cursor-position query to silently fail and the menu to never appear; fixed by removing `PrivateTmp`. Fixes [#7](https://github.com/JuhLabs/juhradial-mx/issues/7).

### Changed

- **Daemon service file hardened for reliability** — Added `StartLimitIntervalSec=60` / `StartLimitBurst=5` to prevent infinite restart loops; added `WatchdogSec=0` to silence watchdog; improved `[Unit]` comments explaining why `PrivateTmp` is intentionally absent.
- **Diagnostic logging for unexpected logid key codes** — When the `LogiOps Virtual Input` device emits a key other than `KEY_F19`, the daemon logs a debug message with the received and expected key codes. This helps diagnose misconfigured `logid.cfg` CID mappings without needing to rebuild.

## [0.2.9] - 2026-02-18

### Added

- **GNOME Wayland support** — Bundled GNOME Shell extension (`juhradial-cursor@dev.juhlabs.com`) exposes cursor position via D-Bus using `global.get_pointer()`. The radial menu now works natively on GNOME Wayland (Ubuntu, Fedora GNOME, Pop!_OS, etc.). Fixes [#6](https://github.com/JuhLabs/juhradial-mx/issues/6).
- **COSMIC desktop support** — XWayland cursor sync with change-detection polling for accurate cursor tracking on COSMIC compositor.
- **XWayland cursor fallback** — Dynamic `libX11.so.6` loading via `dlopen`/`XQueryPointer` works on any Wayland compositor with XWayland (Sway, River, etc.).
- **COSMIC desktop commands** in Settings — Screenshot, Files, Note Editor mapped to `cosmic-screenshot`, `cosmic-files`, `cosmic-edit`.

### Fixed

- **Radial menu appearing at top-left corner on GNOME Wayland** — Cursor detection now has a 7-level fallback chain: Hyprland IPC → KWin script → KWin D-Bus → GNOME extension → XWayland → xdotool → screen center. The menu is always visible. Fixes [#6](https://github.com/JuhLabs/juhradial-mx/issues/6).
- **Hyprland multi-monitor screen bounds with HiDPI scaling** — Screen bounds calculation now divides physical pixel dimensions by the monitor's scale factor to match the logical cursor coordinate space. Previously, a 4K monitor at 2x scale would report bounds of 3840px instead of the correct 1920px logical width.
- **Hyprland screen bounds failing on unusual monitor configs** — One monitor with missing JSON fields no longer aborts the entire bounds query; that monitor is skipped and the rest are still used.
- **XWayland `dlsym` safety** — Added null pointer checks before `transmute` on all dynamically resolved X11 symbols to prevent undefined behavior.
- **CodeQL unused variable warnings** ([#90](https://github.com/JuhLabs/juhradial-mx/security/code-scanning), [#91](https://github.com/JuhLabs/juhradial-mx/security/code-scanning), [#92](https://github.com/JuhLabs/juhradial-mx/security/code-scanning)) — Removed dead assignments in exception handlers across overlay cursor detection code.

### Changed

- **Overlay refactored into modules** — Split `juhradial-overlay.py` into `overlay_cursor.py`, `overlay_actions.py`, `overlay_painting.py`, and `overlay_constants.py` for better maintainability.
- **Installer auto-installs GNOME extension** on GNOME desktops and enables it via `gnome-extensions enable`.
- **Screen center fallback** replaces the broken `(0, 0)` default — if all cursor detection methods fail, the menu appears at screen center instead of the top-left corner.

## [0.2.8] - 2026-02-14

### Fixed

- **Mouse not detected after Easy-Switch** — logid only scans devices at startup, so switching the mouse to another computer and back left it undetected. Added a udev rule + systemd oneshot service that automatically restarts logid when a Logitech HID device reconnects.

### Changed

- Installer now deploys `juhradialmx-logid-restart.service` to `/etc/systemd/system/` for automatic logid restarts on device hotplug.

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
- **CodeQL regressions fixed** for uninitialized local translation symbol and empty `except` handlers in overlay cursor fallback logic.

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

[0.4.3]: https://github.com/JuhLabs/juhradial-mx/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/JuhLabs/juhradial-mx/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/JuhLabs/juhradial-mx/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/JuhLabs/juhradial-mx/compare/v0.3.2-beta...v0.4.0
[0.3.2-beta]: https://github.com/JuhLabs/juhradial-mx/compare/v0.3.1-beta...v0.3.2-beta
[0.3.1-beta]: https://github.com/JuhLabs/juhradial-mx/compare/v0.3.0-beta...v0.3.1-beta
[0.3.0-beta]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.9...v0.3.0-beta
[0.2.6]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.5...v0.2.6
[0.2.7]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.6...v0.2.7
[0.2.9]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.8...v0.2.9
[0.2.8]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.7...v0.2.8
[0.2.5]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/JuhLabs/juhradial-mx/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/JuhLabs/juhradial-mx/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/JuhLabs/juhradial-mx/releases/tag/v0.1.0
