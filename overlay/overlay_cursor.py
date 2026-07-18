"""
JuhRadial MX - Cursor Position Detection

All cursor position detection functions for different Wayland compositors:
- Hyprland (IPC socket)
- GNOME (D-Bus extension)
- XWayland (libX11 ctypes)
- Qt fallback

SPDX-License-Identifier: GPL-3.0
"""

import os
import subprocess

from overlay_constants import IS_HYPRLAND, IS_GNOME, _HAS_XWAYLAND

# =============================================================================
# HYPRLAND CURSOR DETECTION
# =============================================================================

# Cache for Hyprland socket path
_hyprland_socket = None

# Cache for Hyprland monitor info (refreshed on each menu show)
_monitors_cache = None


def _get_hyprland_socket():
    """Get Hyprland socket path (cached)."""
    global _hyprland_socket
    if _hyprland_socket is None:
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
        _hyprland_socket = f"{xdg_runtime}/hypr/{sig}/.socket.sock"
    return _hyprland_socket


def _hyprland_ipc(command: bytes) -> str:
    """Send a command to Hyprland IPC and return the response string."""
    import socket as _socket

    sock = None
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(0.1)
        sock.connect(_get_hyprland_socket())
        sock.send(command)
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            except _socket.timeout:
                break
        return b"".join(chunks).decode("utf-8").strip()
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass  # Socket cleanup failure is non-fatal


def _refresh_monitors():
    """Refresh cached monitor info from Hyprland."""
    global _monitors_cache
    import json

    try:
        response = _hyprland_ipc(b"j/monitors")
        _monitors_cache = json.loads(response)
    except Exception as e:
        print(f"[HYPRLAND] Failed to refresh monitors: {e}")
        if _monitors_cache is None:
            _monitors_cache = []


def get_monitor_at_cursor(cx, cy):
    """Find which monitor contains the given global cursor coordinates.

    Returns dict with keys: x, y, width, height (logical pixel coords).
    Falls back to the focused monitor, then first monitor.
    """
    global _monitors_cache
    if _monitors_cache is None:
        _refresh_monitors()

    for mon in _monitors_cache or []:
        mx = mon.get("x", 0)
        my = mon.get("y", 0)
        # Use logical (transformed) size -- accounts for scaling and rotation
        mw = mon.get("width", 1920) / mon.get("scale", 1.0)
        mh = mon.get("height", 1080) / mon.get("scale", 1.0)
        if mx <= cx < mx + mw and my <= cy < my + mh:
            return {
                "x": mx,
                "y": my,
                "width": int(mw),
                "height": int(mh),
                "name": mon.get("name", "?"),
            }

    # Fallback: focused monitor
    for mon in _monitors_cache or []:
        if mon.get("focused", False):
            mw = mon.get("width", 1920) / mon.get("scale", 1.0)
            mh = mon.get("height", 1080) / mon.get("scale", 1.0)
            return {
                "x": mon.get("x", 0),
                "y": mon.get("y", 0),
                "width": int(mw),
                "height": int(mh),
                "name": mon.get("name", "?"),
            }

    return {"x": 0, "y": 0, "width": 1920, "height": 1080, "name": "fallback"}


def get_all_monitors_logical():
    """Return all Hyprland monitors as logical-pixel rects.

    Each rect is {x, y, width, height, name}. Width/height are the transformed
    (scaled) logical sizes, matching the compositor-logical cursor coordinate
    space. Used to map the cursor onto Qt screen geometry for menu placement.
    """
    global _monitors_cache
    if _monitors_cache is None:
        _refresh_monitors()

    rects = []
    for mon in _monitors_cache or []:
        scale = mon.get("scale", 1.0) or 1.0
        rects.append({
            "x": mon.get("x", 0),
            "y": mon.get("y", 0),
            "width": int(mon.get("width", 1920) / scale),
            "height": int(mon.get("height", 1080) / scale),
            "name": mon.get("name", "?"),
        })
    return rects


# ---------------------------------------------------------------------------
# KDE Wayland logical monitor layout (issue: second-monitor menu drift).
#
# The daemon's KWin script reports the cursor in KWin-LOGICAL coordinates,
# but QWidget.move() runs in Qt/XWayland space. With mixed per-monitor
# scaling these spaces differ per monitor (same size, shifted origin, or
# scaled - depends on the "legacy applications" XWayland mode), so the
# menu drifts on every monitor whose logical rect != Qt rect. The fix is
# the same fraction-invariant mapping as Hyprland issue #45; KScreen is
# the logical-layout source. At 100% everywhere the rects match and the
# mapping reduces to identity, so single-scale setups are untouched.
# ---------------------------------------------------------------------------

_kde_monitors_cache = None
_kde_monitors_ts = 0.0
_KDE_MONITORS_TTL = 10.0  # layout changes are rare; 27ms spawn once per TTL


def _parse_kscreen_json(text):
    """Parse `kscreen-doctor -o --json` output into logical monitor rects.

    The output is one JSON document possibly followed by trailing non-JSON
    text, so decode only the first document. Logical rect = pos + current
    mode size / scale, with width/height swapped for 90/270 rotation
    (KScreen enum: 1=normal, 2=left/90, 4=inverted/180, 8=right/270), so
    portrait monitors map correctly.
    """
    import json
    doc, _idx = json.JSONDecoder().raw_decode(text)
    rects = []
    for out in doc.get("outputs", []):
        if not out.get("enabled"):
            continue
        pos = out.get("pos") or {}
        scale = float(out.get("scale") or 1.0) or 1.0
        mode = next((m for m in out.get("modes", [])
                     if m.get("id") == out.get("currentModeId")), None)
        size = (mode or {}).get("size") or {}
        w, h = size.get("width"), size.get("height")
        if not w or not h:
            continue
        if out.get("rotation", 1) in (2, 8):
            w, h = h, w
        rects.append({
            "x": pos.get("x", 0),
            "y": pos.get("y", 0),
            "width": int(round(w / scale)),
            "height": int(round(h / scale)),
            "name": out.get("name", "?"),
        })
    return rects


def get_kde_monitors_logical():
    """KDE logical monitor rects via kscreen-doctor, cached with a short TTL.

    Returns [] when kscreen-doctor is unavailable or fails (non-KDE distro,
    old Plasma) - callers then keep the previous identity behaviour.

    The refresh timestamp advances on FAILURE too, so a broken kscreen-doctor
    costs at most one subprocess timeout per TTL, never one per menu open.
    The child must NOT inherit the overlay's QT_QPA_PLATFORM=xcb: kscreen-doctor
    is a Qt Wayland-session tool and hangs for many seconds under the xcb
    platform (verified on Plasma 6), which both stalled the open path and
    left the layout empty.
    """
    global _kde_monitors_cache, _kde_monitors_ts
    import time
    now = time.monotonic()
    if _kde_monitors_ts and now - _kde_monitors_ts < _KDE_MONITORS_TTL:
        return _kde_monitors_cache or []
    _kde_monitors_ts = now
    child_env = dict(os.environ)
    child_env.pop("QT_QPA_PLATFORM", None)
    try:
        result = subprocess.run(
            ["kscreen-doctor", "-o", "--json"],
            capture_output=True, text=True, timeout=0.5, env=child_env,
        )
        rects = _parse_kscreen_json(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        from overlay_constants import _log
        _log(f"[KDE] kscreen-doctor failed: {e}")
        rects = []
    if rects:
        _kde_monitors_cache = rects
    return _kde_monitors_cache or []


def find_monitor_at(x, y, monitors):
    """Return the monitor rect containing (x, y), else None."""
    for mon in monitors or []:
        if (mon["x"] <= x < mon["x"] + mon["width"]
                and mon["y"] <= y < mon["y"] + mon["height"]):
            return mon
    return None


def get_cursor_position_hyprland():
    """Get cursor position using Hyprland IPC socket (faster than subprocess).

    Returns global coordinates directly -- on Hyprland, XWayland windows
    use the same coordinate space as the compositor (no offset subtraction
    needed).
    """
    try:
        response = _hyprland_ipc(b"cursorpos")
        parts = response.split(",")
        if len(parts) >= 2:
            return (int(parts[0].strip()), int(parts[1].strip()))
    except (OSError, ValueError):
        pass  # IPC can fail transiently; subprocess fallback below handles it

    # Fallback to subprocess
    try:
        result = subprocess.run(
            ["hyprctl", "cursorpos"], capture_output=True, text=True, timeout=0.1
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                return (int(parts[0].strip()), int(parts[1].strip()))
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        pass  # hyprctl may be unavailable or return unparsable output

    return None


# =============================================================================
# GNOME CURSOR DETECTION
# =============================================================================

# Cached GLib D-Bus proxy for high-frequency cursor polling
_gnome_cursor_proxy = None
_gnome_cursor_proxy_failed = False


def _get_gnome_cursor_proxy():
    """Get or create a cached Gio.DBusProxy for the cursor helper.

    Using a persistent proxy avoids spawning a gdbus subprocess on every call,
    which is critical for 120Hz edge detection polling.
    """
    global _gnome_cursor_proxy, _gnome_cursor_proxy_failed
    if _gnome_cursor_proxy is not None:
        return _gnome_cursor_proxy
    if _gnome_cursor_proxy_failed:
        return None
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES
            | Gio.DBusProxyFlags.DO_NOT_CONNECT_SIGNALS,
            None,
            "org.juhradial.CursorHelper",
            "/org/juhradial/CursorHelper",
            "org.juhradial.CursorHelper",
            None,
        )
        _gnome_cursor_proxy = proxy
        return proxy
    except Exception:
        _gnome_cursor_proxy_failed = True
        return None


def get_cursor_position_gnome():
    """Get cursor position via JuhRadial GNOME Shell extension D-Bus.

    Uses a cached Gio.DBusProxy for low-latency calls. Falls back to
    gdbus subprocess if GLib bindings are unavailable.
    """
    proxy = _get_gnome_cursor_proxy()
    if proxy is not None:
        try:
            from gi.repository import GLib
            result = proxy.call_sync(
                "GetCursorPosition",
                None,
                0,  # Gio.DBusCallFlags.NONE
                100,  # timeout ms
                None,
            )
            if result:
                # Result is a GVariant tuple: (x, y)
                x = result.get_child_value(0).get_int32()
                y = result.get_child_value(1).get_int32()
                return (x, y)
        except (GLib.Error, TypeError, ValueError, AttributeError):
            pass  # D-Bus call can fail if extension is not installed
        return None

    # Fallback: gdbus subprocess (slow, only used if GLib unavailable)
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.juhradial.CursorHelper",
                "--object-path", "/org/juhradial/CursorHelper",
                "--method", "org.juhradial.CursorHelper.GetCursorPosition",
            ],
            capture_output=True, text=True, timeout=0.2,
        )
        if result.returncode == 0:
            # Output format: "(1234, 567)\n"
            text = result.stdout.strip().strip("()")
            parts = text.split(",")
            if len(parts) >= 2:
                return (int(parts[0].strip()), int(parts[1].strip()))
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return None
    return None


# =============================================================================
# XWAYLAND CURSOR DETECTION
# =============================================================================

_xlib = None
_xdisplay = None
_xroot = None
_sync_window = None
_sync_window_size = None


def _init_xlib():
    """Initialize Xlib bindings (cached)."""
    global _xlib, _xdisplay, _xroot
    if _xlib is not None:
        return True
    try:
        import ctypes
        c_int, c_uint, c_ulong, c_void_p, c_long = ctypes.c_int, ctypes.c_uint, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_long
        POINTER, Structure = ctypes.POINTER, ctypes.Structure

        _xlib = ctypes.cdll.LoadLibrary("libX11.so.6")
        _xlib.XOpenDisplay.argtypes = [c_void_p]
        _xlib.XOpenDisplay.restype = c_void_p
        _xlib.XDefaultRootWindow.argtypes = [c_void_p]
        _xlib.XDefaultRootWindow.restype = c_ulong
        _xlib.XQueryPointer.argtypes = [
            c_void_p, c_ulong,
            POINTER(c_ulong), POINTER(c_ulong),
            POINTER(c_int), POINTER(c_int),
            POINTER(c_int), POINTER(c_int), POINTER(c_uint),
        ]
        _xlib.XQueryPointer.restype = c_int
        _xlib.XDisplayWidth.argtypes = [c_void_p, c_int]
        _xlib.XDisplayWidth.restype = c_int
        _xlib.XDisplayHeight.argtypes = [c_void_p, c_int]
        _xlib.XDisplayHeight.restype = c_int
        _xlib.XCreateSimpleWindow.argtypes = [
            c_void_p, c_ulong,
            c_int, c_int, c_uint, c_uint,
            c_uint, c_ulong, c_ulong,
        ]
        _xlib.XCreateSimpleWindow.restype = c_ulong
        _xlib.XMapWindow.argtypes = [c_void_p, c_ulong]
        _xlib.XUnmapWindow.argtypes = [c_void_p, c_ulong]
        _xlib.XDestroyWindow.argtypes = [c_void_p, c_ulong]
        _xlib.XFlush.argtypes = [c_void_p]
        _xlib.XSync.argtypes = [c_void_p, c_int]
        _xlib.XCloseDisplay.argtypes = [c_void_p]

        # For ARGB transparent sync window
        class _XVisualInfo(Structure):
            _fields_ = [
                ("visual", c_void_p), ("visualid", c_ulong),
                ("screen", c_int), ("depth", c_int), ("class_", c_int),
                ("red_mask", c_ulong), ("green_mask", c_ulong),
                ("blue_mask", c_ulong), ("colormap_size", c_int),
                ("bits_per_rgb", c_int),
            ]

        class _XSetWindowAttributes(Structure):
            _fields_ = [
                ("background_pixmap", c_ulong), ("background_pixel", c_ulong),
                ("border_pixmap", c_ulong), ("border_pixel", c_ulong),
                ("bit_gravity", c_int), ("win_gravity", c_int),
                ("backing_store", c_int), ("backing_planes", c_ulong),
                ("backing_pixel", c_ulong), ("save_under", c_int),
                ("event_mask", c_long), ("do_not_propagate_mask", c_long),
                ("override_redirect", c_int), ("colormap", c_ulong),
                ("cursor", c_ulong),
            ]

        # Store struct types on _xlib for later use
        _xlib._XVisualInfo = _XVisualInfo
        _xlib._XSetWindowAttributes = _XSetWindowAttributes

        _xlib.XMatchVisualInfo.argtypes = [
            c_void_p, c_int, c_int, c_int, POINTER(_XVisualInfo),
        ]
        _xlib.XMatchVisualInfo.restype = c_int
        _xlib.XCreateColormap.argtypes = [c_void_p, c_ulong, c_void_p, c_int]
        _xlib.XCreateColormap.restype = c_ulong
        _xlib.XCreateWindow.argtypes = [
            c_void_p, c_ulong,
            c_int, c_int, c_uint, c_uint, c_uint,
            c_int, c_uint, c_void_p,
            c_ulong, POINTER(_XSetWindowAttributes),
        ]
        _xlib.XCreateWindow.restype = c_ulong

        _xdisplay = _xlib.XOpenDisplay(None)
        if not _xdisplay:
            _xlib = None
            return False
        _xroot = _xlib.XDefaultRootWindow(_xdisplay)
        return True
    except (OSError, AttributeError):
        _xlib = None
        return False


def _xquery_pointer():
    """Raw XQueryPointer call (assumes _init_xlib() was called)."""
    import ctypes
    c_int, c_uint, c_ulong, byref = ctypes.c_int, ctypes.c_uint, ctypes.c_ulong, ctypes.byref

    root_return, child_return = c_ulong(), c_ulong()
    root_x, root_y = c_int(), c_int()
    win_x, win_y = c_int(), c_int()
    mask = c_uint()
    result = _xlib.XQueryPointer(
        _xdisplay, _xroot,
        byref(root_return), byref(child_return),
        byref(root_x), byref(root_y),
        byref(win_x), byref(win_y), byref(mask),
    )
    if result:
        return (root_x.value, root_y.value)
    return None


def _xdisplay_size():
    """Return current X display size for screen 0."""
    return (
        _xlib.XDisplayWidth(_xdisplay, 0),
        _xlib.XDisplayHeight(_xdisplay, 0),
    )


def get_cursor_position_xwayland():
    """Get cursor position via XWayland using Xlib XQueryPointer.

    Works on any Wayland compositor with XWayland (COSMIC, GNOME, Sway, etc.).
    Uses ctypes to call libX11 directly - no external tools needed.
    """
    if not _HAS_XWAYLAND:
        return None
    if not _init_xlib():
        return None
    return _xquery_pointer()


def get_cursor_position_xwayland_synced():
    """Get cursor position with forced XWayland sync (change-detection).

    On COSMIC, XWayland doesn't track the cursor unless it's over an
    XWayland window.  XQueryPointer returns stale cached coords from the
    last time the cursor was over ANY XWayland surface.

    This function:
    1. Records the stale XQueryPointer reading
    2. Maps a fullscreen transparent override-redirect X11 window
    3. Polls until XQueryPointer returns a DIFFERENT position (fresh data)
    4. Falls back after 120ms if no change (cursor was already over XWayland)

    Uses a 32-bit ARGB window (alpha=0 = truly invisible, no flash) with
    override-redirect (bypasses WM, no tiling/grid).  The window is created
    once and reused across calls.
    """
    import ctypes
    import time
    from overlay_constants import _log

    if not _HAS_XWAYLAND:
        return None
    if not _init_xlib():
        return None

    global _sync_window, _sync_window_size
    w, h = _xdisplay_size()
    if _sync_window is not None and _sync_window_size != (w, h):
        _xlib.XDestroyWindow(_xdisplay, _sync_window)
        _sync_window = None

    if _sync_window is None:

        # X11 constants
        TrueColor = 4
        InputOutput = 1
        AllocNone = 0
        CWBackPixel = 2
        CWBorderPixel = 8
        CWOverrideRedirect = 512
        CWColormap = 8192

        XVisualInfo = _xlib._XVisualInfo
        XSetWindowAttributes = _xlib._XSetWindowAttributes

        vinfo = XVisualInfo()
        if _xlib.XMatchVisualInfo(_xdisplay, 0, 32, TrueColor, ctypes.byref(vinfo)):
            # 32-bit ARGB visual found — create truly transparent window
            colormap = _xlib.XCreateColormap(
                _xdisplay, _xroot, vinfo.visual, AllocNone
            )
            attrs = XSetWindowAttributes()
            attrs.background_pixel = 0       # ARGB(0,0,0,0) = fully transparent
            attrs.border_pixel = 0
            attrs.override_redirect = 1      # Bypass WM (no tiling/grid)
            attrs.colormap = colormap
            mask = CWBackPixel | CWBorderPixel | CWOverrideRedirect | CWColormap
            _sync_window = _xlib.XCreateWindow(
                _xdisplay, _xroot, 0, 0, w, h, 0,
                32, InputOutput, vinfo.visual,
                mask, ctypes.byref(attrs),
            )
        else:
            # No 32-bit visual; fall back to simple override-redirect window
            _sync_window = _xlib.XCreateSimpleWindow(
                _xdisplay, _xroot, 0, 0, w, h, 0, 0, 0
            )
        _sync_window_size = (w, h)
        _xlib.XFlush(_xdisplay)

    # Capture stale reading BEFORE mapping the sync window
    stale_pos = _xquery_pointer()
    _log(f"X11 sync: stale = {stale_pos}")

    # Map the fullscreen window to force COSMIC to route pointer events
    _xlib.XMapWindow(_xdisplay, _sync_window)
    _xlib.XSync(_xdisplay, 0)  # Ensure map request reaches X server

    # Poll with change-detection
    deadline = time.time() + 0.35        # 350ms hard timeout
    change_deadline = time.time() + 0.12 # 120ms to detect change
    fresh_pos = stale_pos
    changed = False

    while time.time() < deadline:
        time.sleep(0.004)  # 4ms poll — fast
        pos = _xquery_pointer()
        if pos is None:
            continue
        fresh_pos = pos
        if stale_pos is not None and pos != stale_pos:
            changed = True
            _log(f"X11 sync: fresh {stale_pos} -> {pos}")
            break
        if not changed and time.time() >= change_deadline:
            _log(f"X11 sync: no change, accepting {pos}")
            break

    # Unmap immediately
    _xlib.XUnmapWindow(_xdisplay, _sync_window)
    _xlib.XFlush(_xdisplay)

    _log(f"X11 sync: result = {fresh_pos} (changed={changed})")
    return fresh_pos


# =============================================================================
# DISPATCHER
# =============================================================================


def get_cursor_pos():
    """Get cursor position in Qt coordinate space (matching QWidget.move()).

    Uses QCursor.pos() as the primary source on most compositors because it
    returns coordinates in Qt's own space, correctly handling HiDPI scaling
    and devicePixelRatio. Falls back to compositor-specific methods when
    QCursor returns (0,0) - which happens on Wayland when no XWayland window
    is visible.

    Hyprland is the exception: hyprctl returns logical coords that already
    match Qt's coordinate space.
    """
    if IS_HYPRLAND:
        pos = get_cursor_position_hyprland()
        if pos:
            return pos
    # QCursor.pos() is the most reliable source for Qt coordinate space.
    # On KDE/GNOME Wayland with HiDPI, XWayland raw coords differ from
    # Qt logical coords by the devicePixelRatio. QCursor handles this.
    pos = get_cursor_position_qt()
    if pos:
        return pos
    # QCursor returns (0,0) when no XWayland window is visible.
    # Fall back to compositor-specific methods.
    if IS_GNOME:
        pos = get_cursor_position_gnome()
        if pos:
            return pos
    if _HAS_XWAYLAND:
        pos = get_cursor_position_xwayland()
        if pos:
            return pos
    return (0, 0)


def get_cursor_position_qt():
    """Get cursor position in Qt's current screen coordinate space.

    Returns None if Qt reports the common Wayland no-window fallback (0,0), or
    if the coordinate is outside every known Qt screen.
    """
    try:
        from PyQt6.QtGui import QCursor
        from PyQt6.QtWidgets import QApplication

        qpos = QCursor.pos()
        x, y = qpos.x(), qpos.y()
        if x == 0 and y == 0:
            return None

        app = QApplication.instance()
        if not app:
            return (x, y)

        for screen in app.screens():
            geom = screen.geometry()
            if (geom.x() <= x < geom.x() + geom.width() and
                    geom.y() <= y < geom.y() + geom.height()):
                return (x, y)
    except (ImportError, AttributeError, RuntimeError):
        pass  # Qt cursor position unavailable; fall through to None

    return None


# =============================================================================
# CURSOR WARPING
# =============================================================================


def warp_cursor(x: int, y: int) -> bool:
    """Warp cursor to absolute position (x, y).

    Tries compositor-native methods first, then falls back to generic tools.
    Returns True on success.
    """
    if IS_HYPRLAND:
        try:
            result = subprocess.run(
                ["hyprctl", "dispatch", "movecursor", str(x), str(y)],
                capture_output=True, timeout=0.5,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.SubprocessError):
            pass  # hyprctl not available or failed

    # ydotool works on most Wayland compositors (needs ydotoold running)
    try:
        result = subprocess.run(
            ["ydotool", "mousemove", "--absolute", "-x", str(x), "-y", str(y)],
            capture_output=True, timeout=0.5,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.SubprocessError):
        pass  # ydotool not available or failed

    # XWarpPointer via libX11 (works on X11/XWayland)
    if _HAS_XWAYLAND and _init_xlib():
        try:
            import ctypes
            # XWarpPointer(display, src_window, dst_window, src_x, src_y,
            #              src_width, src_height, dst_x, dst_y)
            if not hasattr(_xlib, '_warp_setup'):
                _xlib.XWarpPointer.argtypes = [
                    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                    ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                    ctypes.c_int, ctypes.c_int,
                ]
                _xlib.XWarpPointer.restype = ctypes.c_int
                _xlib._warp_setup = True

            _xlib.XWarpPointer(_xdisplay, 0, _xroot, 0, 0, 0, 0, x, y)
            _xlib.XFlush(_xdisplay)
            return True
        except Exception:
            pass  # XWarpPointer ctypes call can fail on some setups

    return False


def get_screen_geometry(cursor_pos=None):
    """Get the current screen geometry for cursor position.

    Returns dict with x, y, width, height of the monitor at cursor.
    Pass cursor_pos=(x,y) to avoid a redundant get_cursor_pos() call.
    """
    pos = cursor_pos or get_cursor_pos()
    if not pos:
        return {"x": 0, "y": 0, "width": 1920, "height": 1080}

    cx, cy = pos

    # Hyprland: use monitor detection
    if IS_HYPRLAND:
        return get_monitor_at_cursor(cx, cy)

    # Other compositors: try Qt screen geometry
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            for screen in app.screens():
                geom = screen.geometry()
                if (geom.x() <= cx < geom.x() + geom.width() and
                        geom.y() <= cy < geom.y() + geom.height()):
                    return {
                        "x": geom.x(), "y": geom.y(),
                        "width": geom.width(), "height": geom.height(),
                    }
    except (ImportError, AttributeError, RuntimeError):
        pass  # Qt screen geometry may not be available on all compositors

    return {"x": 0, "y": 0, "width": 1920, "height": 1080}
