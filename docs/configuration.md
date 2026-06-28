# Configuration

JuhRadial MX is configured through plain JSON files under your XDG config directory. The Settings app (GTK4) writes these files for you, but every value is human readable and safe to edit by hand. This page is the full reference: where the files live, every top-level section and its key fields, the theme list, the per-application profile format, and autostart.

See also: [Features](features.md) for what each setting does in practice, [Installation](installation.md) for first run, and [Troubleshooting](troubleshooting.md) if a change does not take effect.

## File locations

All configuration lives in `~/.config/juhradial/` (or `$XDG_CONFIG_HOME/juhradial/` when that variable is set).

| File / directory | Written by | Purpose |
| --- | --- | --- |
| `config.json` | Settings app, daemon | Main configuration: haptics, buttons, thumb-wheel, theme, scroll, flow, gaming, app and device settings |
| `profiles.json` | Settings app, daemon | Per-application radial layouts and per-app hardware overrides |
| `macros/<uuid>.json` | Settings app | One file per saved macro |
| `~/.config/autostart/juhradial-mx.desktop` | Settings app | Login autostart entry (created/removed by the Start at Login toggle) |

!!! note
    The daemon reads `haptics`, `theme`, `blur_enabled`, `buttons`, and `thumbwheel` from `config.json`. The remaining sections (`scroll`, `pointer`, `flow`, `gaming`, `app`, `device_mode`, `desktop_environment`, `language`, `radial`, `radial_menu`) are consumed by the Settings app and overlay and applied through helper scripts or D-Bus. Unknown keys are ignored, so the two consumers coexist in one file.


## How configuration is applied

- The Settings app writes `config.json` **atomically** (temp file plus rename) and then calls the daemon's `ReloadConfig` method over D-Bus (`org.kde.juhradialmx` on path `/org/kde/juhradialmx/Daemon`). Changes apply live, no restart required.
- If you edit `config.json` by hand, trigger a reload so the daemon picks it up. Either open and save once in the Settings app, or restart the daemon:

```bash
systemctl --user restart juhradialmx-daemon.service
```

- Missing fields fall back to defaults, so a minimal `{}` file is valid. On first run the Settings app auto-detects your desktop environment and fills in environment-appropriate commands for the radial slices (controlled by the internal `de_defaults_applied` flag).

!!! warning
    The daemon writes only VOLATILE HID++ state to the device (no onboard-memory writes). Diverts and hardware overrides are re-applied on reconnect and on `ReloadConfig`, so a hotplugged mouse comes back to your configured state automatically.


## Top-level structure of config.json

```json
{
  "haptics": { ... },
  "theme": "catppuccin-mocha",
  "blur_enabled": true,
  "buttons": { ... },
  "thumbwheel": { ... },
  "radial": { "minimal_mode": false },
  "radial_menu": { ... },
  "scroll": { ... },
  "pointer": { ... },
  "flow": { ... },
  "gaming": { ... },
  "app": { ... },
  "device_mode": "auto",
  "desktop_environment": "auto",
  "language": "system"
}
```

| Section | Type | What it controls |
| --- | --- | --- |
| `haptics` | object | Haptic feedback patterns and debounce timing |
| `theme` | string | Active UI / overlay theme (see [Themes](#themes)) |
| `blur_enabled` | bool | Overlay blur effect (auto-disabled on slow GPUs) |
| `buttons` | object | Physical button action assignments |
| `thumbwheel` | object | Thumb-wheel behaviour (volume / scroll / zoom / off) |
| `radial` | object | Radial menu display options (`minimal_mode`) |
| `radial_menu` | object | The 8 radial slices, easy-switch options |
| `scroll` | object | Scroll direction, smoothness, SmartShift |
| `pointer` | object | Pointer speed, DPI, acceleration |
| `flow` | object | Multi-machine edge flow (created once configured) |
| `gaming` | object | Gaming mode and DPI profiles (created once configured) |
| `app` | object | Tray icon and autostart toggles |
| `device_mode` | string | UI layout: `auto`, `logitech`, or `generic` |
| `desktop_environment` | string | DE for default commands: `auto`, `kde`, `gnome`, `cosmic`, `generic` |
| `language` | string | UI language (`system` or a locale code) |

## Haptics

```json
"haptics": {
  "enabled": true,
  "default_pattern": "subtle_collision",
  "per_event": {
    "menu_appear": "damp_state_change",
    "slice_change": "subtle_collision",
    "confirm": "sharp_state_change",
    "invalid": "angry_alert"
  },
  "debounce_ms": 20,
  "slice_debounce_ms": 20,
  "reentry_debounce_ms": 50
}
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | Master toggle for haptic feedback |
| `default_pattern` | string | `subtle_collision` | Fallback waveform when no per-event pattern is set |
| `per_event.menu_appear` | string | `damp_state_change` | Pulse when the radial menu opens |
| `per_event.slice_change` | string | `subtle_collision` | Pulse when hovering a different slice |
| `per_event.confirm` | string | `sharp_state_change` | Pulse when selecting an action |
| `per_event.invalid` | string | `angry_alert` | Pulse for a blocked or invalid action |
| `debounce_ms` | int | `20` | Minimum milliseconds between any two pulses |
| `slice_debounce_ms` | int | `20` | Minimum milliseconds between slice-change pulses |
| `reentry_debounce_ms` | int | `50` | Window that suppresses a duplicate pulse when the cursor re-enters the same slice |

Pattern names are MX Master 4 HID++ waveform IDs (for example `subtle_collision`, `damp_state_change`, `sharp_state_change`, `angry_alert`). Pick from the patterns offered in the HAPTIC FEEDBACK page of the Settings app.

## Buttons

Each physical control maps to one action. Defaults preserve the mouse's native behaviour.

```json
"buttons": {
  "gesture": "virtual_desktops",
  "thumb": "radial_menu",
  "middle": "middle_click",
  "shift_wheel": "smartshift",
  "forward": "forward",
  "back": "back",
  "horizontal_scroll": "scroll_left_right"
}
```

| Field | Physical control | Default action |
| --- | --- | --- |
| `gesture` | Gesture button (thumb pad) | `virtual_desktops` |
| `thumb` | Actions-ring / haptic button | `radial_menu` |
| `middle` | Scroll-wheel click | `middle_click` |
| `shift_wheel` | Mode-shift button below the wheel | `smartshift` |
| `forward` | Upper thumb button | `forward` |
| `back` | Lower thumb button | `back` |
| `horizontal_scroll` | Thumb wheel | `scroll_left_right` |

### Available action values

Any button field accepts one of these snake_case values:

```
radial_menu        virtual_desktops    middle_click       back
forward            copy                paste              undo
redo               screenshot          smartshift         scroll_left_right
volume_up          volume_down         play_pause         mute
zoom_in            zoom_out            show_desktop       switch_desktop_left
switch_desktop_right  task_switcher    close_window       lock_screen
calculator         none                custom
```

`none` disables the button. `custom` reserves the slot for a user-defined action configured in the UI.

!!! warning
    The gesture and actions-ring (thumb) buttons are always diverted to the daemon. The back, forward, middle, and shift-wheel buttons are only HID++-diverted when you reassign them away from their native default. Leaving one at its default keeps the firmware behaviour intact (and reassigning back to the default releases the divert without a reconnect). Reassigning `horizontal_scroll` is recorded in the schema but the thumb wheel's native scroll is handled by the `thumbwheel` section below.


## Thumb-wheel

```json
"thumbwheel": {
  "mode": "off",
  "invert": false,
  "speed": 1
}
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `mode` | string | `off` | `off`, `volume`, `scroll`, or `zoom` |
| `invert` | bool | `false` | Reverse rotation direction (applied in software) |
| `speed` | int | `1` | Action repeats per rotation tick, clamped to `1` to `8` |

How modes behave:

- `off` and `scroll` use the wheel's native hardware behaviour and are **not** diverted, so horizontal scroll works reliably on every compositor.
- `volume` and `zoom` are diverted: each rotation tick is re-injected as Volume Up/Down or Ctrl +/- the number of times set by `speed`.

## Radial menu

### Display options

```json
"radial": {
  "minimal_mode": false
}
```

`minimal_mode` shows icons only (no slice labels) when `true`.

### Slices

The 8-way ring is defined under `radial_menu.slices`. Each slice is an object:

```json
{
  "label": "Play/Pause",
  "action_id": "play_pause",
  "type": "exec",
  "command": "playerctl play-pause",
  "color": "green",
  "icon": "media-playback-start-symbolic"
}
```

| Slice field | Meaning |
| --- | --- |
| `label` | Text shown on the slice |
| `action_id` | Stable identifier used for default-command mapping |
| `type` | How the slice acts: `exec`, `shortcut`, `emoji`, `settings`, `submenu`, or `none` |
| `command` | For `exec`: a shell command. For `shortcut`: a key combo such as `ctrl+c`. Empty for other types |
| `color` | A theme color name (`green`, `yellow`, `red`, `blue`, `mauve`, `pink`, `sapphire`, `teal`, and so on) |
| `icon` | A freedesktop symbolic icon name, an emoji, or a path to `.png` / `.svg` / `.ico` |

Slice `type` values:

| Type | Behaviour |
| --- | --- |
| `exec` | Run `command` as a shell command |
| `shortcut` | Inject the key combination in `command` |
| `emoji` | Open the system emoji picker |
| `settings` | Open the JuhRadial MX Settings app |
| `submenu` | Open a nested ring |
| `none` | Do nothing |

!!! tip
    On first run the slice commands are auto-filled for your desktop environment. For example, the Screenshot slice becomes `spectacle` on KDE, `gnome-screenshot --interactive` on GNOME, `cosmic-screenshot` on COSMIC, and `flameshot gui` on generic desktops. Set `desktop_environment` to pin a specific mapping.


### Easy-switch

```json
"radial_menu": {
  "easy_switch_shortcuts": false,
  "easy_switch_host_os": ["linux", "unknown", "unknown"]
}
```

| Field | Meaning |
| --- | --- |
| `easy_switch_shortcuts` | Enable easy-switch slot shortcuts in the ring |
| `easy_switch_host_os` | Host OS label per channel (1, 2, 3): `linux`, `windows`, `mac`, or `unknown` |

## Scroll and pointer

```json
"scroll": {
  "natural": false,
  "smooth": true,
  "smartshift": true,
  "smartshift_threshold": 50,
  "mode": "smartshift"
},
"pointer": {
  "speed": 10,
  "acceleration": true
}
```

| `scroll` field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `natural` | bool | `false` | Invert scroll direction |
| `smooth` | bool | `true` | Hi-res (free-spin) scrolling versus ratchet clicks |
| `smartshift` | bool | `true` | Auto-disengage the ratchet on fast flicks |
| `smartshift_threshold` | int | `50` | Flick force (0 to 100) that triggers free-spin |
| `mode` | string | `smartshift` | Scroll mode selector |
| `speed` | int | (UI) | Scroll speed, written by the Point & Scroll page |

| `pointer` field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `speed` | int | `10` | Pointer speed |
| `acceleration` | bool | `true` | Enable pointer acceleration |
| `dpi` | int | (UI) | Explicit DPI, written when set in the Point & Scroll page |
| `accel_profile` | string | `adaptive` | Acceleration profile when written by the UI |

## Flow

The `flow` section appears once you configure multi-machine edge flow on the FLOW page. Keys are written on demand:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Master flow toggle |
| `direction` | string | `right` | Edge that crosses to the other machine (`left` / `right`) |
| `share_clipboard` | bool | `true` | Sync clipboard across machines |
| `edge_trigger` | bool | `true` | Cross when the pointer hits the screen edge |
| `edge_sensitivity` | int | `50` | Edge trigger sensitivity |
| `monitor` | string | `""` | Monitor whose edge triggers flow (empty = any) |
| `hide_indicator` | bool | `false` | Hide the on-screen flow indicator |
| `extend_edge_zone` | bool | `false` | Enlarge the edge activation zone |

## Gaming

The `gaming` section appears once you open the GAMING page. DPI profiles let you switch precision quickly.

```json
"gaming": {
  "enabled": false,
  "suppress_overlay": true,
  "active_dpi_profile": 1,
  "dpi_profiles": [
    { "name": "Precision", "dpi": 400,  "color": "blue" },
    { "name": "Normal",    "dpi": 1000, "color": "green" },
    { "name": "Fast",      "dpi": 3200, "color": "red" }
  ]
}
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | bool | `false` | Gaming mode master toggle |
| `suppress_overlay` | bool | `true` | Hide the radial overlay while gaming |
| `active_dpi_profile` | int | `1` | Index into `dpi_profiles` |
| `dpi_profiles` | array | (3 built-ins) | Each entry has `name`, `dpi`, and `color` |

## Device mode and desktop environment

| Field | Values | Meaning |
| --- | --- | --- |
| `device_mode` | `auto`, `logitech`, `generic` | UI layout only. The daemon always runs both the MX and generic input loops, so both mice work regardless. `generic` hides the Logitech-only tabs (HAPTIC FEEDBACK, EASY-SWITCH, FLOW) |
| `desktop_environment` | `auto`, `kde`, `gnome`, `cosmic`, `generic` | Chooses default commands for radial slices |
| `language` | `system` or a locale code | UI language |

## App settings and autostart

```json
"app": {
  "start_at_login": true,
  "show_tray_icon": true
}
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `start_at_login` | bool | `true` | Launch the overlay/settings helper at login |
| `show_tray_icon` | bool | `true` | Show the system tray icon |

Toggling **Start at Login** in the SETTINGS page creates or removes `~/.config/autostart/juhradial-mx.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=JuhRadial MX
Comment=Radial menu for Logitech MX Master
Exec=/usr/local/bin/juhradial-mx
Icon=juhradial-mx
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
```

The background daemon runs separately as a systemd user service installed at setup time:

```bash
systemctl --user enable --now juhradialmx-daemon.service
systemctl --user status juhradialmx-daemon.service
```

## Themes

Set the active theme with the `theme` field, or pick it from the SETTINGS page (changes apply to both the overlay and the Settings UI). Use the key from the left column as the `theme` value.

| Theme key | Display name | Style |
| --- | --- | --- |
| `phosphor` | PHOSPHOR | Dark, obsidian with a single mint accent |
| `juhradial-mx` | JuhRadial MX | Dark, vibrant cyan accents |
| `catppuccin-mocha` | Catppuccin Mocha | Dark, pastel lavender accents |
| `nord` | Nord | Dark, arctic blue palette |
| `dracula` | Dracula | Dark, purple accents |
| `catppuccin-latte` | Catppuccin Latte | Light, pastel |
| `github-light` | GitHub Light | Light, clean |
| `solarized-light` | Solarized Light | Light, precision palette |
| `3d-blossom` | Pearl Blossom (3D) | Dark, pre-rendered rose-gold wheel |
| `3d-neon` | Neon Sci-Fi (3D) | Dark, cyberpunk neon wheel |
| `3d-pastel` | Dark Ember (3D) | Dark, golden ember wheel |
| `3d-crystal` | Golden Classic (3D) | Dark, ornamental golden wheel |

The `3d-*` themes render the ring from a pre-baked image; the others are drawn as vectors. To switch by hand:

```json
"theme": "phosphor"
```

!!! note
    If `theme` is missing, set to `system`, or names an unknown theme, the overlay falls back to `phosphor`. The default `config.json` written on install uses `catppuccin-mocha`. The companion `blur_enabled` flag controls the overlay's background blur and may be auto-disabled on slow GPUs.


## Per-application profiles (profiles.json)

`profiles.json` holds per-app radial layouts and per-app hardware overrides, matched against the focused window's resource class (case-insensitive). The Settings app writes a **flat** shape: top-level keys are application names, plus one `hardware` map.

```json
{
  "default": {
    "name": "default",
    "app_class": "default",
    "slices": []
  },
  "Firefox": {
    "name": "Firefox",
    "app_class": "Firefox",
    "slices": [ { "label": "Copy", "action_id": "copy", "type": "shortcut", "command": "ctrl+c" } ]
  },
  "hardware": {
    "Firefox": {
      "dpi": 1200,
      "smartshift": { "enabled": true, "threshold": 40 },
      "hires": true,
      "thumbwheel": "scroll"
    }
  }
}
```

### Per-app radial entry

| Field | Meaning |
| --- | --- |
| `name` | Display name of the profile |
| `app_class` | Window resource class to match |
| `slices` | Up to 8 slice objects (same shape as `radial_menu.slices`); padded to 8 |

### Per-app hardware override

Each key under `hardware` is an application name mapping to a hardware profile. Every field is optional: only the fields present are applied while that app is focused, and each maps to a volatile HID++ setter. A missing field means "leave unchanged".

| Field | Type | Maps to |
| --- | --- | --- |
| `dpi` | int | Pointer DPI (ADJUSTABLE_DPI) |
| `smartshift` | object | `{ "enabled": bool, "threshold": int }` (HiResScroll SmartShift) |
| `hires` | bool | Hi-res (free-spin) vs ratchet scroll |
| `thumbwheel` | string | `off`, `volume`, `scroll`, or `zoom` (divert derived: any non-`off` mode diverts) |
| `buttons` | object | Per-button action overrides keyed by `gesture` / `thumb` / `middle` / `back` / `forward` / `shift_wheel` (recorded in the schema; applied via config, not as device state) |

!!! note
    The daemon also accepts a structured form with a top-level `version`, a `profiles` array, and a `hardware` map (schema v2). Older v1 files (no `hardware` map) load unchanged and are migrated automatically. The flat UI shape and the structured shape are both read; the built-in `default` profile is always present even if the file omits it.


## Macros

Saved macros live one-per-file under `~/.config/juhradial/macros/<uuid>.json`, each holding the macro's `id`, `name`, and recorded steps. Manage them from the MACROS page rather than editing the directory by hand.

## Minimal example

A complete, valid `config.json` only needs the fields you want to change; everything else falls back to defaults.

```json
{
  "theme": "phosphor",
  "blur_enabled": true,
  "buttons": {
    "gesture": "radial_menu",
    "thumb": "virtual_desktops"
  },
  "thumbwheel": { "mode": "volume", "invert": false, "speed": 2 },
  "haptics": { "enabled": true, "default_pattern": "subtle_collision" }
}
```

After editing by hand, reload with the Settings app or `systemctl --user restart juhradialmx-daemon.service`. If a value still does not take effect, check [Troubleshooting](troubleshooting.md) and [Compositor-Support](compositor-support.md).
