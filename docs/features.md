# Features

JuhRadial MX turns the Logitech MX Master 4 (and the MX Master 3S / 3) into a
fully programmable Linux power tool: a radial gesture menu, button and action
remapping, thumb-wheel actions, SmartShift scroll, actuator haptics,
Easy-Switch host control, per-application profiles, cross-computer JuhFlow, and
a gaming mode with macros.

This page is the feature reference. For installation see [Installation](installation.md), for
the on-disk config schema see [Configuration](configuration.md), for compositor specifics see
[Compositor-Support](compositor-support.md), and for fixes see [Troubleshooting](troubleshooting.md).

!!! note
    Most features depend on HID++ and so require a Logitech MX Master. In
    **generic mouse mode** (any mouse via evdev) the radial menu and button
    remapping still work, but Haptics, Easy-Switch, Flow, SmartShift, and the
    thumb-wheel card are hidden because they need Logitech-specific protocols.


---

## Feature overview

| Feature | What it gives you | Needs HID++ |
|---|---|:---:|
| [Radial Menu](#radial-menu) | 8-slice gesture ring with hold-drag or tap selection | No |
| [Button & Action Remapping](#button-action-remapping) | Reassign back / forward / middle / shift-wheel and the gesture buttons | Partial |
| [Thumb-Wheel](#thumb-wheel) | Bind the side wheel to volume, zoom, or horizontal scroll | Yes |
| [Scroll & SmartShift](#scroll-smartshift) | Pointer speed, wheel mode, SmartShift threshold, HiRes scroll | Yes |
| [Haptic Feedback](#haptic-feedback) | Per-event actuator pulses with presets | Yes |
| [Easy-Switch](#easy-switch) | Switch between paired computers, read paired names | Yes |
| [Per-Application Profiles](#per-application-profiles) | Auto DPI / buttons / scroll on window focus | Yes |
| [JuhFlow](#juhflow) | Encrypted cross-computer cursor and clipboard (Linux and Mac) | No |
| [Gaming Mode + Macros](#gaming-mode-macros) | DPI profiles, overlay suppression, macro engine | Partial |

---

## Radial Menu

<div align="center">
  <img src="https://raw.githubusercontent.com/JuhLabs/juhradial-mx/master/assets/screenshots/RadialWheel.png" width="280" alt="Radial menu">
</div>

A circular overlay of eight action slices that appears at the cursor. It is
drawn by the PyQt6 overlay process and positioned over the pointer wherever you
are working.

### Triggering it

The ring opens on whichever mouse button is bound to the **Radial Menu**
action. By default that is the dedicated Actions Ring button on the MX Master 4
(the lower thumb control, shown in Settings as **Show Actions Ring**). The
larger gesture button defaults to **Virtual Desktops**, and the two can be
swapped or reassigned on the Buttons page.

### Hold-drag vs tap

There are two interaction styles, and both work from the same press:

- **Hold mode:** press and hold the button, drag toward a slice, then release
  to execute that slice.
- **Tap mode:** give the button a quick tap. The menu stays open so you can
  move the pointer and click a slice to execute it.

### The 8 slices

Slices are laid out clockwise from the top. The factory defaults are:

| Position | Default action |
|---|---|
| Top | Play / Pause |
| Top-Right | New Note |
| Right | Lock Screen |
| Bottom-Right | Settings |
| Bottom | Screenshot |
| Bottom-Left | Emoji Picker |
| Left | Files |
| Top-Left | AI (submenu) |

Open **Settings → Buttons → Actions Ring** and click any slice to customize it.
Each slice can run one of several action kinds:

- **Launch command** (for example `flameshot gui`, `dolphin`)
- **Keyboard shortcut** (for example Copy `ctrl+c`, Paste `ctrl+v`)
- **Open Settings**
- **Submenu** (the AI submenu opens Claude, ChatGPT, Gemini, and Perplexity)
- **Emoji picker**
- **Do nothing**

Launch commands adapt to your desktop: Screenshot, Files, Note editor, Emoji,
and Lock resolve to the right tool for KDE, GNOME, COSMIC, or a generic
fallback, so the same slice does the sensible thing on each environment.

!!! tip
    Turn on **Easy-Switch Shortcuts** on the Buttons page to replace the Emoji
    slice with an Easy-Switch 1 / 2 / 3 submenu, so you can change host straight
    from the ring.


### Minimal mode

The **Minimal Radial HUD** toggle (in the settings header) renders the ring as
floating icons only, with no pizza-slice wedges or text labels. It is a
quieter, lower-footprint HUD for users who already know the layout. Backed by
the `radial.minimal_mode` config key.

### Themes

Themes recolor the entire wheel. Vector themes are drawn live in their own
palette; the 3D themes ship bespoke pre-rendered wheel art. The theme preview
in Settings shows the actual ring each theme produces before you apply it.

| Theme | Style |
|---|---|
| PHOSPHOR | Signature dark, phosphor accent |
| JuhRadial MX | Premium dark with cyan accents |
| Catppuccin Mocha | Soothing dark pastel |
| Catppuccin Latte | Light pastel |
| Nord | Arctic north-bluish |
| Dracula | Dark, vibrant |
| GitHub Light | Clean light |
| Solarized Light | Precision light palette |
| Pearl Blossom / Neon Sci-Fi / Dark Ember / Golden Classic | 3D rendered wheels |

The menu also animates: a bloom on open, smooth slice-hover crossfades, a
droplet pop-out for submenu items, and a selection flash on the picked slice.

---

## Button & Action Remapping

Reassign the mouse's physical buttons to system actions, media keys, clipboard
shortcuts, or the radial menu. Configured in **Settings → Buttons → Button
Assignments**.

### Remappable buttons and defaults

| Button | Default action |
|---|---|
| Gesture | Virtual Desktops |
| Show Actions Ring (thumb) | Radial Menu |
| Middle | Middle Click |
| Shift-Wheel | SmartShift |
| Forward | Forward |
| Back | Back |
| Horizontal Scroll (thumb wheel) | Scroll Left/Right |

### Available actions

Pick from a full catalog: Middle Click, Back, Forward, Copy, Paste, Undo, Redo,
Screenshot, SmartShift, Scroll Left/Right, Volume Up / Down, Play/Pause, Mute,
Radial Menu, Virtual Desktops, Zoom In / Out, **Custom Action**, **Do Nothing**,
plus the portable system actions:

| System action | What it does |
|---|---|
| Show Desktop | Minimize everything to reveal the desktop |
| Switch Desktop Left / Right | Move to the adjacent virtual desktop |
| Task Switcher | Open the window switcher / overview |
| Close Window | Close the active window |
| Lock Screen | Lock the session |
| Calculator | Launch the calculator |

Each system action uses the native mechanism for your desktop (GNOME, KDE,
Hyprland, Sway, COSMIC), so it behaves correctly across environments.

!!! note
    Reassigned actions are injected through the kernel **uinput** device, so they
    fire on Wayland as well as X11.


### How diverting works (and why it is safe)

The gesture and Actions Ring buttons are always handled by the daemon. The
back, forward, middle, and shift-wheel buttons are only intercepted (HID++
diverted) **when you reassign them away from their native default**. Return any
of them to its default and the daemon clears the divert, so the hardware
behavior comes back immediately, no reconnect required. See [Architecture](architecture.md)
for the divert model in detail.

---

## Thumb-Wheel

The small side thumb-wheel on the MX Master can drive a system action instead
of its default behavior. Configured in **Settings → Point & Scroll → Thumb
Wheel** (Logitech only).

| Control | Options |
|---|---|
| **Action** | Off · Volume · Horizontal scroll · Zoom |
| **Invert Direction** | Reverse which way rotation maps |
| **Speed** | 1 to 8 (repeats applied per rotation notch) |

- **Volume** and **Zoom** divert the wheel to HID++ notifications and re-inject
  the action. Zoom uses layout-independent keys, so it works on non-US
  keyboards.
- **Horizontal scroll** keeps the wheel's native hardware scrolling, which is
  reliable on every compositor.
- **Off** leaves the wheel at its native behavior.

Invert is applied in software, and Speed reaches the daemon through the config
reload, so neither needs a special hardware command.

---

## Scroll & SmartShift

Pointer and scroll tuning lives on the **Point & Scroll** page.

### Pointer speed (DPI)

- DPI slider from **400 to 8000**, with quick presets 800 / 1600 / 3200 / 4000.
- Click the DPI readout to type an exact value.
- **Acceleration Profile:** Adaptive (recommended), Flat (linear), or System
  Default.

### Scroll wheel mode

A three-way selector matching the hardware modes:

| Mode | Behavior |
|---|---|
| **Ratchet** | Click-to-click detents |
| **SmartShift** | Auto-switch to free-spin when you flick the wheel |
| **Free-spin** | Always frictionless |

In SmartShift mode a **Sensitivity** slider (1 to 100%, Easy to Hard) sets how
hard you must flick before the wheel releases into free-spin. Click the
percentage to type an exact value.

### Other scroll controls

- **Speed:** lines scrolled per wheel notch (1 to 10), applied per compositor
  (GNOME, KDE, Hyprland, Sway, X11).
- **Natural Scrolling:** content follows finger direction.
- **Smooth Scrolling:** high-resolution (HiRes) scroll for smoother movement.

---

## Haptic Feedback

The MX Master 4's actuator can fire a tuned pulse on radial-menu events.
Configured in **Settings → Haptic Feedback**, which shows a live animated
actuator trace of the selected waveform.

### Per-event patterns

Assign a waveform to each interaction independently, or use **Apply to All** to
set them in one move:

| Event | Default pattern |
|---|---|
| Menu Appear | Soft Click (`damp_state_change`) |
| Slice Hover | Subtle (`subtle_collision`) |
| Selection | Sharp Click (`sharp_state_change`) |
| Invalid Action | Alert (`angry_alert`) |

### Waveform library and presets

Sixteen HID++ predefined waveforms are available, including Sharp Click, Soft
Click, Sharp Bump, Soft Bump, Subtle, Whisper, Happy, Alert, Complete, Square
Wave, Wave, Firework, Knock, Jingle, and Ringing.

Above the per-event list, quick **presets** (Tick, Bump, Pulse, Ramp, Double,
Off) apply a feel to every event at once and show its intensity, duration, and
sharpness on the trace. The **Test pulse** button plays the selected preset on
the device so you can feel it before committing.

A master switch turns haptics off entirely; when off, the trace idles and Test
does nothing, matching the daemon. Debounce timings (to avoid rapid-fire pulses
during fast cursor movement) are tunable in the config file; see
[Configuration](configuration.md).

---

## Easy-Switch

Switch the mouse between the computers it is paired to, and see their real
names. Configured in **Settings → Easy-Switch**.

- **Paired computers:** up to three host slots, auto-detected from the mouse's
  pairing state. Names are read from the device over HID++ and reflect the
  computer names set during pairing.
- **Switch hosts:** click a slot to move the mouse to that computer. The active
  slot is marked, and switching is instant.
- **OS per slot:** tag each host as Linux, Windows, macOS, iOS, Android,
  ChromeOS, or Unknown. The chosen OS drives the icon shown in the radial
  Easy-Switch submenu.
- **Refresh:** re-detect slots after you add or remove pairings on the
  mouse/receiver side.

---

## Per-Application Profiles

DPI, button assignments, and scroll settings can switch **automatically as you
change the focused window**. Active-window tracking is supported on KDE,
Hyprland, and X11.

- Add a profile with the **+** (Add Application) control in the settings header,
  matched to a window class.
- Each profile carries its own hardware state (DPI, SmartShift, HiRes scroll
  mode, and per-button actions), applied by the daemon on every focus change.
- A grid view lets you review, edit, and remove application profiles.

The default profile applies whenever the focused window has no specific match,
so unconfigured apps keep your global settings.

---

## JuhFlow

<div align="center">
  <a href="https://github.com/JuhLabs/juhradial-mx/raw/master/juhflow/JuhFlow.dmg">
    <img src="https://img.shields.io/badge/Download_JuhFlow-macOS_(.dmg)-000000?style=for-the-badge&logo=apple&logoColor=white" alt="Download JuhFlow for macOS">
  </a>
</div>

Move one cursor across multiple machines and share the clipboard between them,
peer-to-peer with no cloud. Configured in **Settings → Flow**.

- **Cross-computer control:** glide the pointer to a screen edge and it crosses
  over to the linked computer. Works between Linux and Mac.
- **Encrypted end to end:** X25519 key exchange plus AES-256-GCM. All traffic
  is encrypted; the Link Status card surfaces connection state, latency,
  throughput, and how long the peers have been paired.
- **Zero config discovery:** peers auto-discover each other on the local
  network (mDNS / Zeroconf). Use **Scan Network** to refresh.
- **Clipboard sharing:** copy on one machine, paste on the other.

### Setup

| Side | Steps |
|---|---|
| **Linux** | Built in. Enable **Cross-screen cursor** in Settings → Flow. |
| **Mac** | Download [JuhFlow.dmg](https://github.com/JuhLabs/juhradial-mx/raw/master/juhflow/JuhFlow.dmg) (signed and notarized), install, and pair. |

### Edge and indicator controls

- **Edge to cross:** Left, Right, or Top (Bottom is also selectable).
- **Edge sensitivity:** how eagerly the edge triggers a crossing.
- **Monitor:** which screen detects edges and shows the indicator.
- **Hide indicator** and **Extend edge trigger area** for fine-tuning the feel.

!!! warning
    If you quit JuhRadial MX while JuhFlow is connected, restart JuhFlow on the
    Mac side and reconnect. Windows support is planned.


---

## Gaming Mode + Macros

### Gaming Mode

A profile aimed at games, configured in **Settings → Gaming**.

- **Enable Gaming Mode:** master toggle for gaming-optimized settings.
- **Show Radial Menu:** allow or suppress the ring while gaming, to prevent
  accidental activation mid-game.
- **DPI Profiles:** three editable presets (Precision 400, Normal 1000, Fast
  3200 by default), each with a name, color, and DPI value, plus an Active
  Profile selector to switch quickly.

### Macros

A full macro engine, edited in the timeline macro studio at **Settings →
Macros**.

- **Steps:** key sequences, delays, text typing, and mouse actions, arranged on
  a millisecond timeline.
- **Repeat modes:** Once, While Holding, Toggle On/Off, Repeat N Times, and
  Sequence.
- **Record:** capture a sequence directly, then refine the steps.
- **Binding:** assign a macro to a key or a mouse button.

Macros pair with gaming mode through evdev capture: bind **any** mouse button
(side buttons, extra buttons) on essentially any mouse with extra buttons to a
macro, with a capture dialog that detects exactly the button you press.

---

## See also

- [Configuration](configuration.md): the `~/.config/juhradial/config.json` schema for every
  setting above
- [Compositor-Support](compositor-support.md): per-compositor cursor and positioning behavior
- [Architecture](architecture.md): daemon, overlay, D-Bus, and the HID++ divert model
- [Troubleshooting](troubleshooting.md): fixes for menu position, detection, and permissions
- [FAQ](faq.md): common questions
- [Home](index.md): project overview and quick links
