# Compositor & Desktop Support

JuhRadial MX runs natively across the major Linux desktops. Two things have to work for the radial menu to land on your cursor: the daemon has to **find the cursor position** when you press the gesture button, and the overlay window has to **position itself** at that point. Different compositors expose this in different ways, so the daemon picks the most accurate source available for your session.

This page documents how cursor detection works per compositor, what is needed to set each one up, and the known limitations.

See also: [Installation](installation.md), [Configuration](configuration.md), [Troubleshooting](troubleshooting.md), [Architecture](architecture.md), [FAQ](faq.md).

---

## Status at a glance

| Desktop / Compositor | Cursor detection | Overlay positioning | Status |
|:---|:---|:---|:---:|
| **GNOME** (Wayland) | Shell extension over D-Bus (`org.juhradial.CursorHelper`) | XWayland | Fully supported |
| **KDE Plasma 6** (Wayland) | KWin script (`workspace.cursorPos`) | XWayland | Fully supported |
| **Hyprland** | IPC socket (`cursorpos`), `hyprctl` fallback | XWayland | Fully supported |
| **COSMIC** | XWayland `XQueryPointer` | XWayland | Fully supported |
| **Sway / wlroots** | XWayland `XQueryPointer` | XWayland | Supported |
| **niri** | XWayland `XQueryPointer` via `xwayland-satellite` | XWayland (interim) | Supported |
| **X11** (any DE) | `XQueryPointer` / `xdotool` | Native X11 | Supported |

!!! note
    On every Wayland session the overlay relies on **XWayland** for window positioning. Make sure XWayland is installed and running before reporting a positioning bug. The cursor *detection* method varies per compositor, as described below, but the overlay window itself is placed through XWayland on all Wayland desktops.


---

## How cursor detection works

When you trigger the menu, the daemon resolves the cursor position. On KDE this happens directly through a KWin script that calls the daemon back with the position. On every other desktop the daemon walks an ordered fallback chain and uses the first source that answers:

1. **Hyprland IPC** (only if `HYPRLAND_INSTANCE_SIGNATURE` is set)
2. **KWin D-Bus** `cursorPos` property (older Plasma only)
3. **GNOME Shell extension** D-Bus (only if `XDG_CURRENT_DESKTOP` contains `GNOME`)
4. **XWayland** `XQueryPointer` (any compositor with XWayland, i.e. `DISPLAY` is set)
5. **xdotool** (X11)
6. **Screen-center fallback** (so the menu is always visible if nothing else answers)

The sections below explain each desktop in detail.

---

## GNOME (Wayland)

GNOME does not expose the global pointer position to external clients, so JuhRadial MX ships a small **GNOME Shell extension** (`juhradial-cursor@dev.juhlabs.com`) that exposes `global.get_pointer()` over D-Bus. The daemon queries it at:

```
dest:   org.juhradial.CursorHelper
path:   /org/juhradial/CursorHelper
method: org.juhradial.CursorHelper.GetCursorPosition
```

The extension is only consulted when `XDG_CURRENT_DESKTOP` contains `GNOME`.

### Setup

The installer enables the extension for you. If the menu appears in the **top-left corner**, the extension is not loaded yet:

```bash
gnome-extensions enable juhradial-cursor@dev.juhlabs.com
```

!!! tip
    GNOME loads new Shell extensions at session start. If enabling it from the terminal does not take effect immediately, log out and back in.


### Known limitation: per-app profiles on GNOME Wayland

Per-application profiles (auto-switching DPI, buttons, and scroll on focus change) need a source of truth for the **focused window's application class**. The daemon's active-window tracker has a native source only for **KDE** (a persistent KWin script) and **Hyprland** (the event socket). Every other session falls back to polling `xprop _NET_ACTIVE_WINDOW` + `WM_CLASS`, which only reliably reflects native windows under X11.

Under **GNOME Wayland** there is no equivalent native focus signal exposed to external clients, and the `xprop` fallback sees XWayland clients only, not native Wayland toplevels. As a result:

!!! warning
    Per-application profiles do not switch reliably on GNOME Wayland. The radial menu, cursor positioning, and all other features work normally; only the automatic per-app DPI/button/scroll switching is affected. Use a single global profile on GNOME Wayland, or run a KDE Plasma / Hyprland / X11 session if you depend on per-app switching.


---

## KDE Plasma 6 (Wayland)

KDE uses **KWin scripting**, which is both the most accurate path and the only one that natively understands multi-monitor logical geometry on Plasma 6.

### Cursor positioning

When the gesture button is pressed, the daemon loads a one-shot KWin script that reads `workspace.cursorPos` and calls the daemon's `ShowMenuAtCursor` D-Bus method directly. KWin reports `workspace.cursorPos` in **logical pixels**, which is the same device-independent coordinate space the overlay's window placement uses on the XWayland (`xcb`) platform, so the position is passed through unchanged:

```js
var pos = workspace.cursorPos;
callDBus("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
         "org.kde.juhradialmx.Daemon", "ShowMenuAtCursor",
         Math.round(pos.x), Math.round(pos.y));
```

!!! note
    **Fractional scaling:** earlier builds applied a `devicePixelRatio` correction to this position. Because KWin's logical coordinates already match the overlay's point space, multiplying overshot the cursor toward the bottom-right and dividing overshot toward the top-left, with the error growing the further the cursor sat from the top-left of the monitor. The identity pass-through is what lands the menu on the cursor at any scale, including 125 percent, 150 percent, and other fractional factors.


A **D-Bus fallback** (`org.kde.KWin` → `cursorPos`) exists for older Plasma versions; this property is not available on Plasma 6, so Plasma 6 always uses the script path above.

### Per-app profiles

KDE installs a **persistent** KWin script (loaded with `loadScript` + `Script.run`) that connects to the activation signal and calls the daemon's `ReportActiveWindow` method on every focus change. It handles both Plasma 6 (`windowActivated` / `activeWindow`) and Plasma 5 (`clientActivated` / `activeClient`), so per-application profiles work out of the box.

### Setup

No manual setup is required. KWin scripting is driven over the session bus, which the daemon already uses.

---

## Hyprland

Hyprland exposes the cursor position over its **IPC socket**, which is the fastest source and avoids spawning a subprocess on each menu open.

### Cursor positioning

The daemon connects to the per-session Hyprland socket and sends `cursorpos`:

```
$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket.sock
```

If the socket is unavailable it falls back to the `hyprctl cursorpos` subprocess. Screen bounds for edge-clamping are read from `hyprctl monitors -j` (Hyprland reports monitor `x`/`y` in logical coordinates but `width`/`height` in physical pixels, so the daemon divides by each monitor's `scale` to recover logical dimensions).

### Per-app profiles

Hyprland's per-app tracking reads the `.socket2` event stream and parses `activewindow>>CLASS,TITLE` lines, so per-application profiles work natively.

### Setup

The installer detects Hyprland and adds the overlay window rules automatically. To add them manually, put these in `hyprland.conf` (or an included rules file):

```conf
# JuhRadial MX overlay window rules
windowrulev2 = float,    title:^(JuhRadial MX)$
windowrulev2 = noblur,   title:^(JuhRadial MX)$
windowrulev2 = noborder, title:^(JuhRadial MX)$
windowrulev2 = noshadow, title:^(JuhRadial MX)$
windowrulev2 = pin,      title:^(JuhRadial MX)$
windowrulev2 = noanim,   title:^(JuhRadial MX)$
```

!!! tip
    If the menu is drawn but blurred, bordered, or animated into place, the window rules above are missing. The `float` and `pin` rules are what keep the overlay where the daemon positions it.


---

## COSMIC

COSMIC does not expose a dedicated cursor IPC, so the daemon reads the pointer through **XWayland** using `XQueryPointer` on the root window (the daemon loads `libX11.so.6` directly and queries it whenever `DISPLAY` is set). The overlay is placed as a synchronized override-redirect XWayland surface.

### Setup

Ensure XWayland is installed and running (it is enabled by default on COSMIC). No further configuration is required for the radial menu and cursor positioning.

---

## Sway / wlroots

Sway (and other wlroots compositors) use the same **XWayland `XQueryPointer`** path as COSMIC. The session is identified by `SWAYSOCK`; cursor detection itself does not depend on the Sway IPC, it relies on XWayland.

### Setup

Make sure XWayland is enabled in your Sway config (`xwayland enable`, which is the default), and that XWayland is installed. The overlay positions itself through XWayland once `DISPLAY` is set.

!!! note
    As with all non-KDE/non-Hyprland Wayland sessions, per-application profiles rely on the `xprop` fallback and therefore only reflect XWayland clients, not native Wayland toplevels. Use a global profile if per-app switching does not behave as expected.


---

## niri

niri exposes `NIRI_SOCKET` but has **no cursor IPC**, and it tiles XWayland toplevels rather than allowing free override-redirect placement. The current (interim) approach runs **`xwayland-satellite`** to provide an XWayland display, then uses the same raw XWayland `XQueryPointer` + synchronized override-redirect surface path as COSMIC.

### Setup

1. Install and run **`xwayland-satellite`** so that `DISPLAY` is set in your niri session. Without it the daemon has no XWayland to query and falls back to screen-center.
2. Confirm `echo $DISPLAY` prints a value (for example `:0`) inside your niri session before launching JuhRadial MX.

!!! note
    niri support is **interim**. Because niri tiles XWayland surfaces, precise free-floating placement depends on the satellite. A dedicated `wlr-layer-shell` surface (via `gtk4-layer-shell`) is the planned path for fully native niri positioning. Until then, run JuhRadial MX with `xwayland-satellite` active.


---

## X11 (any desktop)

On a native X11 session, cursor detection is the most straightforward: the daemon queries the pointer through `XQueryPointer` (via `libX11`, since `DISPLAY` is always set on X11), with **`xdotool getmouselocation`** as an additional fallback. Screen bounds for edge-clamping come from `xrandr` (multi-monitor aware), falling back to `xdotool getdisplaygeometry`.

The overlay is a normal X11 window placed at the reported coordinates, so positioning is native and does not depend on XWayland translation.

### Per-app profiles

X11 per-app tracking polls `xprop _NET_ACTIVE_WINDOW` and reads `WM_CLASS`, so per-application profiles work natively on X11.

### Setup

Install `xdotool` (used as the cursor and screen-bounds fallback) and `xrandr` for multi-monitor edge-clamping. These are typically already present on an X11 desktop.

---

## How the daemon and overlay detect your session

The daemon and overlay both branch on environment variables rather than guessing. The overlay reads these flags at startup:

| Flag | Set when |
|:---|:---|
| `IS_HYPRLAND` | `HYPRLAND_INSTANCE_SIGNATURE` is present |
| `IS_GNOME` | `XDG_CURRENT_DESKTOP` contains `GNOME` |
| `IS_COSMIC` | `XDG_CURRENT_DESKTOP` contains `COSMIC` |
| `IS_KDE` | `XDG_CURRENT_DESKTOP` contains `KDE` or `PLASMA` |
| `IS_SWAY` | `SWAYSOCK` is present |
| `IS_NIRI` | `NIRI_SOCKET` is present |
| `IS_X11` | `XDG_SESSION_TYPE` equals `x11` |
| `_HAS_XWAYLAND` | `DISPLAY` is present |

If detection looks wrong (for example, the menu opens in the top-left corner or at screen center), the usual cause is a missing or misreported variable in your session. Confirm them:

```bash
echo "$XDG_CURRENT_DESKTOP $XDG_SESSION_TYPE"
echo "DISPLAY=$DISPLAY  HYPRLAND=$HYPRLAND_INSTANCE_SIGNATURE  NIRI=$NIRI_SOCKET"
```

---

## Quick reference: what to check per desktop

| Symptom | Desktop | Fix |
|:---|:---|:---|
| Menu in top-left corner | GNOME | Enable the cursor extension, then log out/in (see GNOME section) |
| Menu blurred / animated / off-position | Hyprland | Add the overlay window rules |
| Menu at screen center | niri | Run `xwayland-satellite` so `DISPLAY` is set |
| Menu off-position at non-100% scale | KDE Plasma 6 | Update to a current build (the identity cursor pass-through fixes fractional scaling) |
| Per-app profiles never switch | GNOME Wayland | Known limitation; use a global profile or a KDE/Hyprland/X11 session |
| Menu does not appear at all | Any | Confirm the daemon is running (`pgrep juhradiald`) and XWayland is available |

For deeper diagnosis see [Troubleshooting](troubleshooting.md). For how the daemon, overlay, and D-Bus service fit together, see [Architecture](architecture.md).
