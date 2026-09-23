"""Frosted background behind the ring on KDE Plasma (Settings > blur_enabled).

The overlay is an X11 (XWayland) window. KWin's blur effect blurs whatever
lies behind the region an X11 window lists in _KDE_NET_WM_BLUR_BEHIND_REGION
(CARDINAL x, y, width, height rectangles in window coordinates; an absent
property means no blur). The ring is round, so the region is the disc as a
stack of horizontal strips: a single rectangle would frost a square.
Other compositors ignore the property, so the setting is KDE-only.
"""
import ctypes
import ctypes.util
import math

_ATOM_NAME = b"_KDE_NET_WM_BLUR_BEHIND_REGION"
_XA_CARDINAL = 6
_PROP_MODE_REPLACE = 0


def circle_strips(cx, cy, radius, strips=48):
    """Rectangles (x, y, w, h) covering the disc centred on (cx, cy)."""
    radius = max(0, int(radius))
    if radius == 0:
        return []
    rects = []
    step = max(1, (2 * radius) // strips)
    y = -radius
    while y < radius:
        h = min(step, radius - y)
        mid = y + h / 2
        half = int(math.sqrt(max(0.0, radius * radius - mid * mid)))
        if half > 0:
            rects.append((int(cx - half), int(cy + y), 2 * half, int(h)))
        y += h
    return rects


class _X11:
    """One lazily opened Xlib connection (None when X11 is unavailable)."""

    def __init__(self):
        self.lib = None
        self.dpy = None
        self.atom = None
        path = ctypes.util.find_library("X11")
        if not path:
            return
        try:
            lib = ctypes.CDLL(path)
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XInternAtom.restype = ctypes.c_ulong
            lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            lib.XChangeProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
            lib.XDeleteProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
            lib.XFlush.argtypes = [ctypes.c_void_p]
            dpy = lib.XOpenDisplay(None)
            if not dpy:
                return
            self.lib, self.dpy = lib, dpy
            self.atom = lib.XInternAtom(dpy, _ATOM_NAME, 0)
        except (OSError, AttributeError):
            self.lib = None


_x11 = None


def set_blur_behind(win_id, rects):
    """Ask KWin to blur behind `rects` of window `win_id`; [] or None removes
    the request. Returns False when X11 is not reachable."""
    global _x11
    if _x11 is None:
        _x11 = _X11()
    if _x11.lib is None:
        return False
    lib, dpy = _x11.lib, _x11.dpy
    if rects:
        flat = [v for r in rects for v in r]
        # Xlib passes format-32 property data as C longs.
        data = (ctypes.c_long * len(flat))(*flat)
        lib.XChangeProperty(dpy, int(win_id), _x11.atom, _XA_CARDINAL, 32,
                            _PROP_MODE_REPLACE, ctypes.cast(data, ctypes.c_void_p), len(flat))
    else:
        lib.XDeleteProperty(dpy, int(win_id), _x11.atom)
    lib.XFlush(dpy)
    return True
