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

from overlay_constants import IS_HYPRLAND, IS_GNOME, IS_COSMIC, _HAS_XWAYLAND

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


def get_cursor_position_gnome():
    """Get cursor position via JuhRadial GNOME Shell extension D-Bus.

    Uses the juhradial-cursor@juhlabs.com extension which exposes
    global.get_pointer() over D-Bus.
    """
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
        pass
    return None


# =============================================================================
# XWAYLAND CURSOR DETECTION
# =============================================================================

_xlib = None
_xdisplay = None
_xroot = None
_sync_window = None


def _init_xlib():
    """Initialize Xlib bindings (cached)."""
    global _xlib, _xdisplay, _xroot
    if _xlib is not None:
        return True
    try:
        import ctypes
        from ctypes import c_int, c_uint, c_ulong, c_void_p, c_long, POINTER, Structure

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
    from ctypes import c_int, c_uint, c_ulong, byref

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

    global _sync_window
    if _sync_window is None:
        w = _xlib.XDisplayWidth(_xdisplay, 0)
        h = _xlib.XDisplayHeight(_xdisplay, 0)

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
    """Get cursor position - uses hyprctl on Hyprland, GNOME extension on GNOME, XWayland, or QCursor."""
    if IS_HYPRLAND:
        pos = get_cursor_position_hyprland()
        if pos:
            return pos
    if IS_GNOME:
        pos = get_cursor_position_gnome()
        if pos:
            return pos
    # XWayland fallback (works on COSMIC, Sway, and other Wayland compositors)
    if _HAS_XWAYLAND:
        pos = get_cursor_position_xwayland()
        if pos:
            return pos
    # Fallback to Qt (works on X11/KDE)
    from PyQt6.QtGui import QCursor
    qpos = QCursor.pos()
    return (qpos.x(), qpos.y())
