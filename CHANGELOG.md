# Changelog

All notable changes to JuhRadial MX will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Directional gestures no longer move the pointer** - While directional gestures are on, the gesture button is diverted with HID++ raw XY: the mouse reports the drag over HID++ and the cursor stays where it was, so a flick never nudges it off what you were pointing at (the same route Solaar's mouse gestures take). A gesture button without raw XY keeps the previous behaviour, where the drag is read from the mouse's relative motion. Requested by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146).
- **Drag distance is defined at 1000 DPI and scaled to the mouse's DPI** - `threshold_px` was compared with raw sensor counts, so the same setting meant a quarter of the distance at 4000 DPI and four times it at 250. It now means counts at 1000 DPI, and the daemon scales it by the DPI it last set or read on the mouse, so one value is one physical flick at any DPI. Nothing changes at 1000 DPI; at other DPIs set the distance you want the flick to be (the slider now goes down to 1, in steps of 1). Measured and reported by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146).
- **Direction arrows on the gesture pad** - Each direction picker in Settings → Buttons → Directional gestures carries an arrow for its drag, and the four corners are translated.

## [0.4.5-beta.2] - 2026-09-25

### Added

- **Maximize and minimize as button actions** - `maximize_window` and `minimize_window` join the desktop-portable presets: KWin's own shortcuts on KDE Plasma, `hyprctl` on Hyprland (a minimized window is parked on the `special:minimized` workspace), and the Super+Up / Super+H bindings elsewhere. Requested by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146).
- **Diagonal directional gestures** - The four corners of the directional gesture pad (`up_left`, `up_right`, `down_left`, `down_right`) can carry actions too. While all four are empty a drag is classified four ways exactly as before; once one is set the plane splits into eight 45 degree sectors, and a corner left empty hands its drags to the nearest axis. Requested by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146).

### Fixed

- **A directional gesture set to Custom runs** - It logged "Button set to custom but no custom action is saved" because custom actions were looked up by the button that fired, and a drag has none. Each direction now has its own slot (`buttons.custom.gesture_up` and so on, `gesture_click` for the plain press when it has its own action), the Settings picker offers Custom on every direction and corner and opens the same editor as the buttons. Reported by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146).
- **Drag distance for directional gestures** - The default of 40 sensor counts (about 1 mm at 1000 DPI) turned most forward and back drags into plain presses; a thumb-held drag is short, especially on that axis. The default is now 15, the slider starts at 5, and the setting is described as what it is: sensor counts at the mouse's DPI, not pixels. An existing config keeps its value, so lower it in Settings → Buttons → Directional gestures. Reported with measurements by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146).
- **An input hotplug elsewhere no longer drops the mouse grab** - While a macro-bound button kept the mouse grabbed, any device appearing on or leaving `/dev/input` (a keyboard re-binding its USB interfaces, a hub enumerating) made the daemon release the grab, destroy its virtual mouse and take both again. A click inside that gap reached the compositor from the physical node while its release arrived from the new virtual mouse, and libinput then held the button for the whole seat, on every mouse, until the mouse's node went away or the daemon was stopped. On a hotplug notification the daemon now asks the kernel whether it still backs the device it holds and only re-scans when it does not; the keyboard remap grab follows the same rule. Reported, with the diagnosis, by [@iceteaSA](https://github.com/iceteaSA) in [#150](https://github.com/JuhLabs/juhradial-mx/issues/150).
- **Recording a macro captures keys and clicks again** - Every recording came back empty ("Nothing was recorded"): each recording thread created its async event stream before it had a runtime to drive it and died on the spot, silently, before the first event. The GTK settings app never showed it because its dialog captured keys itself; the Qt app records through the daemon. The stream is now created inside the thread's runtime, a recording thread that dies is logged, and a test records from a virtual keyboard. `ListReceivers` (the Receivers card) and `ModifiersHeld` (the shortcut recorder) failed the same way on the D-Bus executor and now run on their own thread.

## [0.4.5-beta.1] - 2026-09-24

### Added

- **New Qt/QML settings app** - Settings is now a PyQt6 + QML application (`settings-qt/`): a rich wallpaper behind dark glass cards, twelve colour themes (Azure default, plus Sky, Indigo, Violet, Emerald, Teal, Cyan, Brass, Amber, Coral, Rose, Magenta) that each pair an accent with a matched wallpaper, real MX Master 4 product photos with clickable button callouts, eight radial wheel skins decoupled from the colour theme, a deeper slice editor (action, label, command, colour, reorder), a macro step editor with trigger binding, per-application hardware profiles, a Devices page with live battery, wheel mode and connection, and full keyboard navigation. The overlay follows the app: the chosen accent (`radial.accent`) recolours the ring and the chosen wheel skin (`radial.wheel`) is drawn live on the next menu open, both without a restart. The GTK4 settings app stays in the tree as the automatic fallback on distros with Qt older than 6.9 (Ubuntu 24.04, Debian 13), selected by `juhradial-settings` and by the overlay's tray entry; `JUHRADIAL_SETTINGS=gtk` forces it. Packaging (installer, PKGBUILD, RPM spec, Nix flake) ships the app and its QML dependencies; the design assets were compressed from 142 MB of PNG masters to 15 MB of runtime images.
- **Master haptic strength** - `haptics.intensity` (0-100, default 70) gates every haptic path, with 0 silencing the actuator entirely; on legacy force-feedback devices it also scales the pulse amplitude. The MX Master 4's fixed firmware waveforms carry no amplitude byte, so there it acts as an on/off gate, which is documented in Settings.
- **Keyboard support (beta, opt-in)** - A new `keyboard` config section, off by default. `keyboard.enabled` plus a `remap` table rewrites evdev key codes on the first physical keyboard through a virtual device (CapsLock to Ctrl and friends); `keyboard.mx_keys.enabled` lets the daemon read an MX Keys S battery over HID++ and set its backlight (the backlight write runs only on an explicit request and is verified on an MX Keys S over Bolt). Presence is answered from the receiver's pairing table, so the Devices page shows the keyboard even while its radio sleeps. New D-Bus methods: `GetKeyboardBattery`, `GetKeyboardPaired`, `SetKeyboardBacklight`, `ListKeyboardKeys`. Nothing in this path touches a mouse-only install.
- **Directional gestures on the gesture button** - Hold the gesture button and drag up, down, left, or right to run four separate actions, with a plain press keeping whatever `buttons.gesture` already does. Off by default; Settings → Buttons → Gesture Button gets an "Enable directional gestures" switch, four direction pickers, and a drag-distance threshold (default 40 px). The daemon measures the drag from the mouse's own relative motion through a tracker shared between the HID++ button handler (which owns the diverted gesture button) and the evdev loop (which sees the motion), and a directional press never opens or closes the radial overlay. Applies to the HID++-diverted gesture button, which is how every MX Master 4 / 3S / 3 install runs; the evdev-only fallback keeps its existing single-button behaviour. Requested by [@iceteaSA](https://github.com/iceteaSA) in [#146](https://github.com/JuhLabs/juhradial-mx/issues/146), whose PR [#148](https://github.com/JuhLabs/juhradial-mx/pull/148) shaped the config layout.
- **Version consistency guard** - `scripts/bump-version.sh` rewrites every file that carries the version (Cargo, PKGBUILD, RPM spec, flake.nix, README badge, SECURITY.md, AppStream metainfo) and `tests/test_version_consistency.py` fails whenever they disagree, ending the 0.4.3/0.4.4/0.4.1 drift between packaging files.
- **Release assets and a download counter** - Tagging `v*` now builds a Linux x86_64 tarball (source snapshot plus a prebuilt daemon) with `SHA256SUMS` and attaches it to a draft GitHub Release with notes taken from this changelog. `install.sh` downloads that tarball first and only falls back to `git clone` when no asset exists (or `JUHRADIAL_FROM_SOURCE=1` is set), reusing the prebuilt daemon when it runs on the host, so most installs skip the Rust build. The README shows the total download count.
- **Pick an installed application for a radial slice** - The slice editor in Settings has a "Pick application" button, on every slice, that lists installed applications the same way your desktop menu would, instead of typing a raw command by hand. Picking one fills the command and imports the app's real icon (cached under `~/.config/juhradial/icons/`), replacing the generic glyph on the wheel. Quick links got the same treatment: each of the four rows can point at an app instead of a URL, via its own "Pick application" button, with a clear button to switch back to a link. A submenu without links starts empty in the editor, which says the wheel shows the AI assistants until you add one ("Edit the AI links" copies them in). Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#117](https://github.com/JuhLabs/juhradial-mx/pull/117) and [#118](https://github.com/JuhLabs/juhradial-mx/pull/118).
- **Haptic feedback on application switch** - The MX Master 4 actuator now pulses whenever the focused application window changes (Alt+Tab, taskbar, clicking a different app), independent of the radial menu. On by default, with its own toggle and pattern in Settings → Haptics → App switch, so it can be turned off separately from the menu's own haptics. Reuses the daemon's existing window tracker (also used for per-application profiles), so it works wherever that already does: KDE, Hyprland, and X11. Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#120](https://github.com/JuhLabs/juhradial-mx/pull/120).
- **Haptic feedback on monitor switch** - Also pulses when the cursor moves to a different physical monitor. On by default, with its own toggle and pattern in Settings → Haptics → Monitor switch. On KDE this is driven by a persistent KWin script reacting to `workspace.cursorPosChanged`, since the overlay's own ambient cursor poll (used for Hyprland/GNOME/X11) reads a stale, frozen position on Wayland whenever no XWayland window is focused - true almost all the time outside of an open radial menu. COSMIC and niri aren't given a native alternative yet, so a crossing there may occasionally be missed or delayed. Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#122](https://github.com/JuhLabs/juhradial-mx/pull/122).
- **Configurable Actions Ring size** - The ring's outer radius and center dead-zone were fixed in source. Settings → Radial menu now has two sliders ("Ring size", "Center zone", with Automatic size off) to resize them; icon placement, submenu spacing, shadow spread, and the overlay window itself all scale proportionally with the ring rather than staying at the default pixel sizes, so a bigger or smaller ring stays visually consistent throughout. Fixes [#134](https://github.com/JuhLabs/juhradial-mx/issues/134). Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#137](https://github.com/JuhLabs/juhradial-mx/pull/137).
- **Real MX Master 3/3S product photo and button layout on the Buttons page** - The mouse diagram and its button callouts were always tuned for the MX Master 4's body, regardless of which mouse was actually detected. MX Master 3/3S (which share one body/button layout) now get their own product photo and matching callout positions. Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#136](https://github.com/JuhLabs/juhradial-mx/pull/136).
- **Every control the mouse reports is assignable** - The daemon enumerates the mouse's HID++ `REPROG_CONTROLS_V4` inventory and publishes it as `ListControls` on D-Bus (id, name, capability bits as JSON). Any divertable control beyond the named slots (the side buttons of an MX Anywhere, the DPI switch of an MX Vertical) can carry an action under `buttons.controls` keyed by its control id, is diverted while assigned and handed back to the mouse on `none`; Settings → Buttons lists them under "Other controls" whenever the connected mouse reports any.
- **Export and import your setup** - Settings → Settings → Backup writes one zip file with `config.json`, `profiles.json` and the files under `macros/`, `icons/` and `themes/` (plus a manifest), and restores such a file on this or another machine; the same two operations run from the command line as `juhradiald --export FILE` and `juhradiald --import FILE`. Import validates the whole archive before touching the disk (JuhRadial manifest, allowed paths only, every JSON entry parsed), keeps the replaced `config.json` and `profiles.json` as `.bak`, writes atomically, reloads a running daemon and rebuilds the open Settings page. Flow pairing keys never leave the machine.
- **Tray tooltip and badge** - The overlay's tray tooltip names the mouse with its battery (and charging), the Easy-Switch host with its name, and the per-app profile being applied; the icon carries the profile's initial while one is active and turns red on low battery. Everything follows the daemon's signals, including the new `ActiveProfileChanged(s app)` the daemon emits when focus enters or leaves a profiled app. The low-battery desktop notification moves into the always-running overlay (one notice at 15 percent, re-armed above 20 percent or while charging), so it no longer needs Settings to be open; Settings keeps its own notice only when no overlay is running.
- **Profile suggestions for new apps** - The first time an application without a profile takes focus, the daemon announces it (`NewAppSeen(s app)`, once per app per run) and Settings offers "Give it its own profile?" with a Create profile action that adds the profile and opens App profiles. The offer appears when the Settings window is in front, each app is asked about once (`app.profile_prompted`), Settings' own window and the desktop shell are never offered, and Settings → App profiles → Suggest profiles for new apps turns it off.
- **Plugins** - A folder in `~/.config/juhradial/plugins/` with a `plugin.json` adds actions that run a command, a D-Bus call or a script shipped in the folder. They appear in the slice action picker under the plugin's name and in Settings → Settings → Plugins (with the reason when a manifest is invalid), both read on open, so no restart is needed. The daemon validates every manifest (known fields only, one way to run per action, scripts confined to their folder, symlinks out refused) and exposes `ListPlugins` and `RunPluginAction` on D-Bus. Two examples ship in `examples/plugins/` (screenshot tools; clipboard to a note with a haptic tap), documented on the new Plugins docs page. Physical buttons keep the fixed action list for now.
- **Settings per mouse** - The daemon reads each mouse's unit id (HID++ device information) and publishes it as `GetUnitId`; Settings → Devices shows it as "Unit 0x…". A `devices` block in `config.json` keyed by that id holds any subset of the file's keys and is deep-merged over the top-level values while that mouse is connected (at startup, on reconnect, and on every reload), so two mice on one machine keep separate button maps and thumb-wheel settings. Configs without a `devices` block behave exactly as before.
- **Custom actions on any button** - A button can run a recorded keyboard shortcut (modifier chips plus a key list that covers F13-F24, Print, Insert and keys the desktop grabs first), open an application, run a command, open a link (http, https or mailto), play a saved macro or run a plugin action. Invalid shortcuts and links are refused before they are saved, and the ring's slice editor uses the same recorder instead of a free text field.
- **Per-app buttons and a "this mouse only" scope** - The Buttons tab edits for all apps, for this mouse only (kept under its unit id) or for one app profile. An app profile's buttons and custom actions take over while that app has focus; only buttons whose effective action changes are diverted or released, and saving an app's pointer settings keeps its buttons.
- **More actions for buttons and gestures** - Left and right click, scroll left and right, DPI cycle, up, down and hold-for-precision, next, previous, close and reopen tab, Page Up, Page Down, Home and End, Easy-Switch to computer 1-3 or to the next one, and gaming mode on and off. A DPI picked with a button survives a wake.
- **Deeper MX Master 4 haptics** - Four strength levels on the actuator (HID++ `0x19B0`), the Sense Panel press force (`0x19C0`, Light to Firm), six new events (a tick when a directional gesture passes its threshold, DPI change, macro start and finish, low battery, arriving back from another computer), a switch per event, mute while gaming or while chosen apps are in front, a pattern picker that previews on hover, and a Test button that says why nothing played. Levels and force are written only when they differ from what the mouse holds.
- **Gaming mode that reaches the daemon** - A `gaming` section the daemon applies at start and on reload: up to five DPI presets with names and colours, the active preset applied at once while gaming mode is on, the radial menu hidden in games when asked, a ring-button job (precision DPI or cycling the presets), the wheel locked to ratchet or free-spin, and an automatic mode that turns on while Feral GameMode runs a game or a listed app is in front (off by default; it only undoes what it switched on itself). The tray menu gets a Gaming mode entry.
- **App profiles that override only what you change, with their own ring** - A new profile starts empty and follows the global settings; each row has an Override switch. A profile can carry its own radial menu slices, which the overlay shows while that app has focus. Copy, remove with Undo, validation of window classes and one-click recent apps.
- **Easy-Switch slots, safer switching and the keyboard along** - The tab lists each of the mouse's computer slots as paired or empty with how it is paired, names this computer, asks before switching away (saying how to come back) and no longer switches on a stray row click. "Move the keyboard too" sends an MX Keys S to the same computer as the mouse, matched by name, and a sleeping keyboard follows when it wakes.
- **Devices tab rebuilt** - Live link state for the mouse (connected, asleep, on another computer) with the last battery reading when it is away, an MX Keys S that shows up before its support is turned on (read passively from the receiver's pairing table), the keyboard backlight read back from the keyboard with Automatic or Manual mode, its level and how long it stays on (on battery and on a cable), battery alerts per device at 10, 15 or 20 %, About this mouse (model, connection, unit id with copy, firmware, the features the mouse reports, and the settings kept only for this mouse with review and reset), Copy diagnostics with the last 50 service log lines, and generic mode moved to Advanced behind a confirmation.
- **Flow you can set up from the app** - The switch starts and stops Flow at once, a Computers list shows who is connected and who is waiting, the other computer is placed by clicking the side of this screen it sits on, the screen with the handoff edge is picked from the real list, the Easy-Switch channels of both computers can be set so the mouse follows the cursor, the edge glow and whole-edge options are back, the push firmness is explained in milliseconds, and a setup guide covers the Mac companion app and the firewall ports.
- **User-mode install for Bazzite, Fedora Atomic and other image-based systems** - `install.sh --user` (automatic when `/run/ostree-booted` exists) installs under `~/.local` with `sudo` only for the udev rules, `uinput` and the `input` group, offers to layer missing runtime packages with `rpm-ostree`, and builds the daemon in a distrobox when the host has no compiler. The launchers, the overlay and Settings find a user-mode install. `--yes` skips the questions. Requested by [@sandking1101](https://github.com/sandking1101) in [#138](https://github.com/JuhLabs/juhradial-mx/issues/138).
- **Settings: icon size, automatic ring size and more** - Icon size (60 to 160 %) on top of the ring size, an Automatic size that fits ring, centre zone and icons to each monitor, Monochrome 2 as the default icon style (a configured style is kept), a daily update check against GitHub's latest release (nothing about the machine is sent), a troubleshooting card (service and overlay status, restart, open log, copy system info, report a bug), Apply desktop defaults that resolves Auto-detect, and keyboard shortcuts (F1 lists them).
- **Dashboard** - The hero says whether the mouse is reachable, a health line names what needs a fix and how, a short Getting started list, an Actions Ring preview that matches the real ring and opens a slice on click, and the active app profile and keyboard battery as badges.
- **Point & Scroll reads the mouse's real DPI range** - The DPI control follows the range and step the mouse reports (200 to 8000 in steps of 50 on the MX Master 4) and snaps to it; the desktop's pointer settings are read back.
- **Native radial menu on niri** - With `gtk4-layer-shell` installed, the menu opens on a Wayland layer-shell surface at the pointer instead of an XWayland popup, so it lands where the cursor is on every output. Without the library the previous path is used, and every other desktop keeps its current path. Requested by [@TomiEckert](https://github.com/TomiEckert) in [#22](https://github.com/JuhLabs/juhradial-mx/issues/22).
- **NixOS module** - `services.juhradial-mx.enable` registers the packaged user service, loads `uinput`, installs the udev rules and grants the `input` group access to `uinput`; `nix flake check` covers the package and the module, and CI builds both. Requested by [@GarrettGR](https://github.com/GarrettGR) in [#9](https://github.com/JuhLabs/juhradial-mx/issues/9).
- **MX Keypad support** - The new Logitech MX Keypad (USB, `046d:c354`) gets its own tab: nine display keys whose plates show each key's icon and label, pages that the two page buttons flip through (from the last page back to the first), four ready templates (Everyday, Media, Developer, Meetings) and keys that run shortcuts, apps, commands or macros. The daemon drives the key displays through the new `mx-keypad` protocol crate (MIT or Apache-2.0), and the udev rules grant access to the device.
- **Classic Light wheel skin** - The white Classic ring from 0.4.4 is back as Classic Light, next to Classic in Themes and Buttons.
- **Monochrome 2 icon style** - A filled single-colour icon set, offered as Mono 2 next to Mono, Line and Classic in Settings and Themes, and the default for configs that never picked a style. The ring and this window both use it; glyphs it does not cover come from the line family.
- **Settings in 18 languages** - The Qt settings app ships complete translations for Arabic, Chinese (Simplified), Dutch, French, German, Hindi, Italian, Japanese, Korean, Norwegian Bokmål, Polish, Portuguese (Brazil), Russian, Spanish, Swedish, Thai, Turkish and Ukrainian. Settings → Language picks one, or the desktop locale by default.
- **MX Keypad app profiles** - Pages can belong to apps and come up by themselves while that app is in front, like Options+ app profiles (the page buttons stay within the app's pages; apps without pages get the general ones). 27 ready profiles with each app's real default shortcuts (web browsers, VS Code, JetBrains IDEs, terminals, media players and Spotify, Zoom, Teams, Google Meet, OBS, GIMP, Krita, Inkscape, Blender, LibreOffice, ONLYOFFICE, Dolphin and GTK file managers, Discord, Slack, Telegram, Element, Kdenlive, Shotcut and a General profile). Settings suggests them for the apps on this computer, the ones you use most first (time in front is counted locally in `app_usage.json` and never leaves the machine).
- **More MX Keypad key options** - A key's image can be a glyph, any installed app's icon or your own picture; keys without an image show their label large. New custom action "Text" pastes a text or prompt through the clipboard (exact characters on every keyboard layout, optional Enter), and "Hold while pressed" keeps a shortcut down for as long as the key or mouse button is held (push to talk). Key brightness, and "Import pack" for keypad packs (portable.json with ready key images): pictures and labels come along, actions where Linux has a sure match.
- **MX Keypad art and AI profiles** - A gallery of key art in two styles (artsy and minimal) that any key can use, with your label kept on the key. New profiles for Claude Code, Codex CLI, the Claude app, the Codex app (the ChatGPT desktop app) and Prompts (18 one-press prompts for AI coding agents), built from each tool's documented commands and shortcuts. Text keys can paste "Automatically": Ctrl+Shift+V in terminals, Ctrl+V elsewhere. The Claude Code and Codex CLI profiles show the tools' own marks.
- **Your own MX Keypad profiles** - "New app profile" starts pages for any app; the Pages list is grouped by the apps that bring them up, with each app's icon, and every group can be saved as a pack that Import pack restores (actions, art, pictures and apps; a shared pack never brings shell commands along, only launches of apps you have, not even on a two-state key's second state, and its text keys come with Press Enter after turned off and without line breaks). App profile rows show the app's icon.
- **Animated MX Keypad keys** - A GIF or animated WebP picture plays on its key.
- **MX Keypad page keys and peek** - A key can go to a page by name, or to the next or previous page. Holding the left page key shows the general pages while an app's own pages are up. Scripts can paint a key live over D-Bus (`SetKeypadKeyImage`).
- **Two-state keys, folders and key colours on the MX Keypad** - A key can have two states (each press runs the state it shows, then the key turns to the other one, like a mute toggle), a page can be a folder that opens from a key (either page button goes back), and each key can have its own colour and hide its label. While the screen is locked the keys go blank and do nothing, so a text key never types into the lock screen (on desktops that report the lock to logind, such as KDE Plasma and GNOME; `keypad.dim_on_lock`).
- **MX Keypad as it looks** - The Key plates card draws the keypad itself, in pale grey or graphite, with each plate in its key window; its two page buttons turn pages there too.
- **Quick switches in the header** - "Simplified" (the wheel without its ring) and "Generic mouse" sit next to the search field on every tab and stay in step with the same switches on the Settings and Devices tabs; turning generic mode on there offers Undo.
- **Mouse follows the keyboard** - With "Mouse and keyboard move together" on, pressing an MX Keys S Easy-Switch key now takes the mouse to the same computer too (matched by computer name), not only the other way round.
- **Scroll force** - How firmly the wheel clicks in ratchet mode (MX Master 4 and other wheels with tunable torque), with a Default button.
- **Try an app profile now** - App profiles have "Try now": for a minute the buttons, ring and pointer settings act as if that app were in front.
- **Receivers** - The Devices tab lists what each Bolt or Unifying receiver has paired, and which one is this mouse or keyboard.
- **Flow extras** - "Hold Ctrl to cross" (the edge leads on only while Ctrl is held), "Send cursor now" and "Identify screens" (a numbered card on every monitor).
- **Keyboard backlight follows the keys** - Changing the MX Keys S backlight with its own keys updates Settings right away.
- **Generic mode button capture** - Press the mouse button you want for the radial menu instead of picking it from a list.
- **Artistic wheel skins** - Azure, Obsidian, Chrome, Glass, Violet, Emerald, Ember, Crimson and Brass get textured materials (frost, rock, brushed metal, plasma, nebula, malachite, lava, ruby silk, engraved brass) on the Classic geometry.
- **Wheel skins with the Classic shape** - Every wheel skin is now drawn with exactly the Classic ring's slices, hover fill, icon discs and centre, in the menu and in every Settings preview. All skins were redrawn as materials without the dark outer ring (new Chrome and Violet), plus three new skins: Brass, Aurora and Carbon.

### Changed

- **Quieter battery polling after startup** - Contributed by [@frizikk](https://github.com/frizikk) in [#90](https://github.com/JuhLabs/juhradial-mx/pull/90): the first successful battery sample ends fast polling immediately. Failed startup queries retry for at most one minute, while radio recovery still restores the mouse's volatile settings.
- **Batched thumb-wheel actions** - Contributed by [@frizikk](https://github.com/frizikk) in [#97](https://github.com/JuhLabs/juhradial-mx/pull/97): one rotation sends its configured repeats through one helper invocation. Horizontal-scroll bursts have no added click delay and the fallback emits real wheel motion.
- **Settings design pass: frosted glass, one icon family, lit states** - Every card in the Qt settings app is now real frosted glass (a blurred sample of the wallpaper under a graphite tint, with a hairline and a lit top edge) instead of a flat translucent rectangle, on a legibility floor checked against the brightest region of all twelve wallpapers; "Reduce transparency" in Settings → Appearance swaps in solid cards. Navigation, action pickers, the radial editor and the on-screen ring share one 24-grid line-icon family rendered from SVG at the exact pixel size, so nothing is blurry or skewed at any scale; the radial "slice buttons" are composed from those glyphs on machined discs with identical geometry; the four isometric spot illustrations were redrawn flat and follow the theme accent. Accent colour and glow now mean state only (active tab, checked switches, the focused control, the hovered ring slice, connected devices), hover never scales anything, and keyboard focus gets one unified accent halo on every control. The Dashboard trades four metric tiles for a single instrument strip of live readouts, the Buttons ring names and lights the slice under the cursor, Themes becomes a gallery with a miniature of the UI in each accent plus the wheel skins, Devices lists every connected device in one roster (the MX Keys S included), empty states explain the next step, Ctrl+K focuses search, Ctrl+1..9 switch tabs, and a small "Support" link sits quietly at the bottom of the sidebar. The startup splash is gone: the window opens straight into the Dashboard. The Qt app also reports the real release version (it said 0.5.0-dev) via `settings-qt/VERSION`, which the bump script and the consistency test now cover.
- **The radial menu follows the Icon style choice** - Settings → Appearance → Icon style (Line / Classic / Mono) used to change only the settings previews; the on-screen ring kept painting its own vector glyphs. The overlay now reads `radial.icon_style` on every open (older configs fall back to `radial.monochrome_icons`) and draws from the same asset sets the settings app previews: Line uses the composed slice buttons and the line glyphs, Classic the 0.4.4 glossy buttons and glyphs, Mono flat single-colour glyphs only. An application icon picked for a slice still wins over the family. Selecting Classic in Settings now also brings back the 0.4.4 icon set in the app itself, not only the wheel buttons.
- **The Qt settings app carries every 0.4.4 control** - A parity pass against the GTK app it replaces as the default UI. Haptics gets the App Switch and Monitor Switch toggles with their own patterns (from [@gcarmin](https://github.com/gcarmin)'s haptics work); Settings → Radial menu gets the Ring size and Center zone sliders (with Automatic size off) and a Default sizes reset (#134); the slice editor and every quick-link row get "Pick application", listing installed applications like the desktop menu and putting the app's real icon on the wheel ([@gcarmin](https://github.com/gcarmin)'s picker); Buttons shows the MX Master 3/3S photo and callouts when the daemon reports one, and adds the Directional gestures card (enable, four direction pickers, drag distance) that so far only the GTK dialog had; Devices names the real link (Bolt, Unifying, USB receiver, Bluetooth, read from sysfs) and follows `DeviceNameRefreshed` once Bolt answers with the model ([@FoxQwartz](https://github.com/FoxQwartz)'s Devices work); Point & Scroll shows the scroll speed as approximate lines per notch instead of a raw position.
- **Quick links edit what the wheel shows** - The Qt app wrote its AI Assistant links to a key the overlay never read (`radial_menu.ai_links`), so edits changed nothing on the wheel. They now live on the submenu slice (`submenu`, up to four entries, links or applications), exactly where the overlay has read them since 0.4.3; an old `ai_links` list is picked up once and moved over on the next save.
- **SmartShift sensitivity matches the hardware in the Qt app** - The Qt backend still carried the pre-#123 inverted mapping (Easy 1% wrote the hardest threshold, Hard 100% the easiest, spread over 1..254). It now uses the same monotonic 1..49 mapping the GTK app got in #123 (hardware-verified), the slider follows a threshold set from elsewhere without nudging, and a test pins the Qt and GTK mappings together for every value. Per-app profiles now read their threshold back with the same mapping they save with (a saved 50% used to reappear as about 90%), and a new profile starts at the global default instead of an out-of-range 128.
- **Start at Login from the Qt app starts the overlay** - The Qt toggle could point the autostart entry at the bare daemon (which the systemd unit already runs), leaving the radial menu unstarted at login; the entry now always targets the `juhradial-mx` launcher, defaults on like the installer, and a stale `Exec` from an older build is repaired on the next Settings start (#32, #129).
- **Opening the Devices page no longer stalls** - The page queried the keyboard over D-Bus synchronously, and on every open the daemon dropped its keyboard connection after a failed battery read and rescanned both receivers (seconds of receiver traffic on the D-Bus executor). The daemon now recognises the receiver's "connection failed" answer as a parked radio, keeps the keyboard connection and reports it asleep for two seconds instead of rescanning, and answers receiver errors on long HID++ requests immediately instead of waiting out a one-second deadline (this also shortens every divert call to a sleeping mouse). Settings fetches the keyboard state asynchronously and shows "Checking" until it lands. A keyboard that reports battery levels instead of a percentage now shows an estimate instead of reading asleep. The keyboard row also follows the keyboard live: an idle MX Keys S parks its radio, and the page used to keep saying "asleep" until it was reopened. The daemon now listens on the keyboard's receiver for the link-up notice a key press produces, reads the battery right then and pushes it (`KeyboardBatteryChanged`), so the row flips to awake with the fresh reading while you type; while the keyboard is parked the row shows the last reading instead of a dash.
- **Themes preview on hover** - Hovering a colour theme or ring skin previews it on the ring with the real palette colours before anything is saved.
- **The Qt settings app needs Qt 6.9** - The launcher and the tray's Settings entry check for Qt 6.9 (RectangularShadow, VectorImage) and for libadwaita 1.4 for the GTK fallback, and explains when neither is present instead of crashing.
- **Every Settings tab is translatable** - All pages go through `qsTr()` and gettext catalogs, with a lint test that keeps them so.

### Fixed

- **Blurred disc beside the ring on scaled displays** - With fractional scaling (Qt at 1.25 under XWayland), the background blur was placed in the wrong pixels and a blurred disc stuck out up-left of the ring.
- **MX Keypad right page button** - Only the left page button was taken over from the device; both are now.
- **Menu background blur edge** - The frosted area behind the ring had a stepped edge (clearly visible through translucent skins at 125 % scaling) and showed as a stray disc around the minimal ring, which draws no disc. The edge is smooth now and the minimal ring is not frosted.
- **App icons without an icon theme** - App icons in pickers and profile rows now also come from the standard hicolor and pixmaps folders when Qt has no icon theme (some GNOME, sway and Flatpak setups).
- **Apps started from a button or keypad key run on their own** - Commands, apps and links started by the background service used to run inside its hardened service: capped at 100 MB and half a CPU core, without `sudo` (no new privileges) and closed whenever the service restarted. They now start as their own user service, like apps from the desktop menu, with a direct start as the fallback where `systemd-run` is missing.
- **Gaming mode on KDE Plasma** - With gaming mode on, the ring button's gaming job (precision DPI, next preset) and the hidden radial menu now also apply on KDE, where the menu opens through KWin.
- **Easy-Switch OS logos on dark rings** - The Apple, iOS and unknown-OS glyphs were drawn black and disappeared on dark rings; they now take the ring's icon colour. The Linux penguin is a new flat Tux face that fills its circle.
- **Per-app profiles, app-switch and monitor-switch haptics after a slow login** - The daemon decided once, at startup, which desktop it runs on. Started by systemd before the desktop had published its environment (common on a slow boot), it settled on "unknown" and ran the whole session without window tracking or the KDE monitor-switch script. It now re-checks every two seconds for up to three minutes and starts both as soon as the desktop is known, so no unit drop-in is needed. Found and diagnosed by [@sandking1101](https://github.com/sandking1101) on Bazzite in [#138](https://github.com/JuhLabs/juhradial-mx/issues/138).
- **The cursor helper extension loads on GNOME 51** - GNOME Shell refuses to load an extension whose `shell-version` list does not name the running release, so on GNOME 51 the helper stayed "out of date" and the menu opened in the top-left corner. The extension now declares 45 to 51; its code (`global.get_pointer()` over a session D-Bus export) is unchanged in GNOME 51, checked against the 51.0 source. Log out and back in once after updating. Reported in [#144](https://github.com/JuhLabs/juhradial-mx/issues/144).
- **DPI, SmartShift, Easy-Switch and the keyboard backlight from the Qt settings app** - PyQt6 sends a plain integer as a 32-bit D-Bus int, and the daemon rejects a call whose argument types differ from the declared ones before it runs, so those four controls (declared as byte or uint16) did nothing. The app now sends the declared types, and a test checks every call site against the daemon's interface. Hints such as "keyboard not reachable" now show as toasts instead of being dropped.
- **Haptics, battery and DPI keep working after the mouse returns from another Easy-Switch host** - A battery poll that merely timed out (the mouse idle, or answering another host) was treated like an unplugged device: the daemon dropped its healthy HID++ handle and spun a multi-second rediscovery that kept failing for minutes, during which haptics, battery and DPI were dead until a restart. Only a real I/O error disconnects now; a timeout keeps the handle. The Easy-Switch `HostChanged` notification also wakes the hidraw loop so the volatile button diverts and thumb-wheel reporting are re-applied the moment the mouse is back, the same path device hotplug uses.
- **Menu-open latency and bus load** - HID++ request loops and the battery reader wait on `poll(2)` for the reply instead of sleeping in fixed 10 ms steps (about 5 ms saved per round trip, and shorter mutex hold windows), `TriggerHaptic` uses `try_lock` so a busy haptic manager can never stall the single D-Bus executor thread that also dispatches `ShowMenuAtCursor` (a late pulse is dropped instead), the haptic emit paths reconnect when the device handle was dropped (previously dead code), and diverted-button handling takes one config lock per event instead of three with per-event logs demoted to debug.
- **The ring highlights the slice under the cursor on scaled displays, and every submenu item is reachable** - Two geometry mismatches between what the overlay drew and what it hit-tested. With a per-monitor ring scale other than 1.0 (4K at 125%, for example) the ring was painted `(ring_scale - 1) * window / 2` px down-right of its hit regions, so hovering an icon highlighted and executed the next slice clockwise; the paint centre now lives in the same coordinate space as the hit-test origin. Submenu items were drawn 18° apart but hit-tested at 15°, which made the outer items of a large fan (Quick Links, AI assistant) respond off-centre or not at all; the spread is now one shared constant and the nearest item wins. Found, measured and fixed by [@iceteaSA](https://github.com/iceteaSA) in [#145](https://github.com/JuhLabs/juhradial-mx/pull/145). Fixes [#147](https://github.com/JuhLabs/juhradial-mx/issues/147). `tests/test_ring_geometry.py` now pins both invariants.
- **Icons, badges, submenu items and the centre label scale with the ring size** - The Ring Size slider (#134) moved icons outward with the ring but left them, the submenu circles and the centre text at their default pixel sizes, as reported by [@LightOSproblems](https://github.com/LightOSproblems) on the follow-up. A single `ui_scale` now follows the configured outer radius and drives icon and badge size (`icon_scale`), the submenu item radius and its matching hover radius, and the centre font sizes, so a bigger or smaller ring keeps its proportions.
- **Haptic feedback works inside submenus** - Hovering between items in an open submenu (Quick Links, AI assistant, the app-picker submenu rows) gave no haptic pulse, only the main Actions Ring did. Submenu hover now triggers the same `slice_change` pulse as the main ring. Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#119](https://github.com/JuhLabs/juhradial-mx/pull/119).
- **The event listener binds to the receiver that actually owns the mouse** - With two Logitech receivers plugged in, both tie in the auto-detect priority ranking, and directory order decided which one the HID++ event listener opened. Landing on the wrong receiver left the daemon deaf: button diverts were acknowledged on the mouse's receiver while the listener sat on the other one, so pressing the haptic button did nothing at all. Previously the hotplug-loop churn accidentally masked this by reconnecting until it happened to land right; with that loop fixed the wrong pick became permanent. The listener now always prefers the ping-verified path the HID++ manager is connected on, and a listener that opened a different node re-binds within seconds of the manager connecting, so multi-receiver setups converge on the right interface instead of depending on enumeration order.
- **Bluetooth mice no longer lag from the daemon's own virtual device** - On every connection the daemon creates a "JuhRadial Virtual Mouse" uinput node for button suppression, and creating or dropping that node fires the same inotify Create/Remove events on `/dev/input` as a real plug or unplug. Since the v0.4.2 reconnect rework cancels a healthy session on any hotplug event, the virtual device's own churn re-triggered the reconnect endlessly: USB/Bolt usually landed inside the 500 ms debounce and self-corrected, but Bluetooth timing kept escaping it, so the cursor hitched and the radial menu, thumb wheel, and haptics never stabilized. The hotplug watcher now identifies the virtual device by reading the new node's name from sysfs when the Create arrives (the daemon cannot pre-register the path, because the kernel publishes the node while it is still being built) and remembers those paths so the matching Remove is ignored too. Every other Create/Remove still counts as real hotplug, so Easy-Switch host changes and receiver reconnects behave exactly as before. Diagnosed by co-maintainer [@gcarmin](https://github.com/gcarmin) in PR [#124](https://github.com/JuhLabs/juhradial-mx/pull/124), with the loop confirmed on hardware by [@sndev28](https://github.com/sndev28) in PR [#126](https://github.com/JuhLabs/juhradial-mx/pull/126). Fixes [#121](https://github.com/JuhLabs/juhradial-mx/issues/121), [#125](https://github.com/JuhLabs/juhradial-mx/issues/125).
- **Invert Direction actually inverts the horizontal thumb wheel** - With the thumb wheel on Horizontal scroll, toggling Invert Direction never changed anything: the switch briefly pushed a diverted and inverted state to the mouse, then the follow-up config reload re-applied reporting with the invert byte hardcoded to 0, restoring normal direction. The ThumbWheel (`0x2150`) invert byte now follows the config on every apply path (connect, reconnect, reload, per-app profiles): Horizontal scroll stays un-diverted and inverts in hardware, while Volume/Zoom stay software-inverted with the hardware byte at 0, so nothing inverts twice. Per-app profiles also stop diverting the wheel for scroll mode, which used to route rotations through the wrong resolver and could kill native scrolling. Reported by [@YacineSahli](https://github.com/YacineSahli). Fixes [#127](https://github.com/JuhLabs/juhradial-mx/issues/127).
- **Settings copes with a missing python3-gi-cairo** - On Debian/Ubuntu setups without `python3-gi-cairo` (part of the installer since 0.4.2, but absent on older installs such as 0.4.1), the sidebar heart animation raised `TypeError: Couldn't find foreign struct converter for 'cairo.Context'` 33 times per second, flooding the journal and leaking file descriptors through the crash handler until Settings died. Settings now detects the missing converter at startup, leaves the Cairo-drawn heart (and its 30 ms timer) off, and shows a single dialog naming the package to install. Installing `python3-gi-cairo` (or re-running `install.sh`) remains the actual fix. Reported by [@Addonis-13](https://github.com/Addonis-13). Fixes [#128](https://github.com/JuhLabs/juhradial-mx/issues/128).
- **The radial menu starts at login** - Nothing ever wrote the XDG autostart entry: the installer only enabled the daemon service, and the Settings "Start at Login" switch defaults to ON without writing the file (only manually toggling it did). `install.sh` now writes `~/.config/autostart/juhradial-mx.desktop` (skipped when Start at Login is off in Settings), and Settings creates the missing file whenever the switch is on. The overlay deliberately stays a launcher-started process rather than a systemd user unit: a second unit is how duplicate overlays ([#60](https://github.com/JuhLabs/juhradial-mx/issues/60)) and the GNOME login loop ([#67](https://github.com/JuhLabs/juhradial-mx/issues/67)) happened. Reported by [@Addonis-13](https://github.com/Addonis-13). Fixes [#129](https://github.com/JuhLabs/juhradial-mx/issues/129).
- **Settings shows your actual mouse model** - The header badge and Devices page always read "MX Master 4", even on other models, because the local detection guessed the model from the USB/Bluetooth product ID, and Logitech reuses the same ID (`0xB034`) across the MX Master 3S and 4 generations - no static table can tell those apart. Both now query the daemon's `GetDeviceName`, which reports the device's own HID++/evdev-provided name string instead of guessing. Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#136](https://github.com/JuhLabs/juhradial-mx/pull/136).
- **Device name no longer gets stuck on a generic receiver name over Bolt** - `GetDeviceName` was computed once, at daemon startup, from a probe that often lost a race against Bolt: the receiver's HID++ interface routinely wasn't ready yet, so the probe fell back to evdev's kernel-reported name, which for a Bolt receiver's paired mouse is generic ("Logitech USB Receiver Mouse") rather than the real model - and once set, it was never recomputed for the rest of the daemon's life, not even after HID++ went on to connect successfully seconds later. The name is now held in a shared cell that the HID++ reconnect loop (already running on every hotplug/host-switch cycle to re-apply button diverts) updates and broadcasts (`DeviceNameRefreshed`) whenever it learns a better name, so Settings shows the real model on next open without a daemon restart. Contributed by co-maintainer [@gcarmin](https://github.com/gcarmin) in [#136](https://github.com/JuhLabs/juhradial-mx/pull/136).
- **Scroll speed on KDE Plasma Wayland** - It never worked: the setting wrote `[Mouse] ScrollFactor`, which KWin ignores on Wayland. Scroll speed, pointer acceleration profile and natural scrolling are now written per device through KWin's `InputDevice` D-Bus interface, apply at once and are read back; GNOME, Hyprland, sway and X11 keep their own paths.
- **Middle, Back and Forward remaps send real mouse buttons** - They sent key chords (`alt+Left`, `alt+Right`) or an invalid xdotool call; they now press BTN_MIDDLE, BTN_SIDE and BTN_EXTRA through uinput on Wayland and xdotool on X11. The SmartShift button action toggles ratchet and free-spin instead of doing nothing.
- **Copy, Paste, Undo and the other shortcut slices on the ring** - They did nothing (the overlay had no branch for them); they now press the chord through the daemon.
- **Record then Save saves a macro in the Qt app** - The saved payload lacked an id, a repeat mode and the recorded timing, so no macro could be created. Recording now reads every keyboard and the mice (clicks included), playback on Wayland goes through uinput, a new binding works without a restart, and a Settings save no longer releases a macro-bound button.
- **Settings stay put after a wake or a trip to another computer** - DPI, SmartShift, hi-res and natural scrolling are replayed after start, reconnect, wake and an Easy-Switch return (only keys you set). Leaving a profiled app restores the global DPI, SmartShift and hi-res instead of keeping the profile's values, and profiles keep your natural-scroll setting instead of forcing it off.
- **Easy-Switch slot names and states** - The HOSTS_INFO (`0x1815`) reply was read at the wrong offsets, so the slot count, pairing state and bus type were misread; a refused switch is now reported instead of shown as done.
- **Battery charging state** - The UNIFIED_BATTERY status was read from the external-power byte, so a device on a cable read as charging even when full or discharging; mouse and keyboard now use the charging-status byte. A keyboard sharing the mouse's receiver can no longer have its reports decoded as the mouse's (a wrong battery or a phantom button press).
- **Point & Scroll follows the hardware in the Qt app** - The wheel mode follows the mouse, the SmartShift slider no longer flips the wheel mode, and the DPI readout keeps re-syncing (the #108 regressions in the new app).
- **Click outside the ring closes it** - Issue #59 was closed but the dismiss scrim never shipped; it now works in toggle mode, never executes a slice and never takes focus. Menu background blur works on KDE Plasma, and Show tray icon is honoured at start and live.
- **Gaming settings reach the daemon** - The daemon had no gaming section, so "Show the radial menu in games", the DPI presets and the active preset did nothing.
- **The Flow switch applies at once** - The overlay read it only at login; it now starts and stops Flow when Settings saves.
- **Config defaults match the runtime** - An unrelated save no longer adds the Easy-Switch slice, flips the Flow edge, pins English or shows the overlay in games; the saved DPI and scroll device keys are no longer merged into every save.

### Security

- **Flow shares nothing with computers you did not approve** - The Flow bridge accepted any computer on the network after an anonymous key exchange, then sent it the clipboard and acted on its cursor messages. A computer is now listed as waiting until you approve it in Settings > Flow (its key fingerprint is pinned); until then it gets only keep-alives, its messages are ignored, and a computer you turn away is disconnected. The GTK settings app can approve too.

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
