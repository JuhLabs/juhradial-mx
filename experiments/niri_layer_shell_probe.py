#!/usr/bin/env python3
"""niri layer-shell feasibility probe for issue #22 (NOT shipped code).

Tests the gates the radial menu needs from a wlr-layer-shell overlay on niri,
where the current XWayland override-redirect path cannot position correctly:

  GATE 1  a transparent OVERLAY-layer surface maps fullscreen on the active
          output and we learn its monitor geometry/connector;
  GATE 2  GTK receives the pointer's coordinates shortly after the surface maps
          WITHOUT the user moving the mouse (a HID-triggered menu must center on
          the stationary cursor) -- the make-or-break gate;
  GATE 3  the input region can be restricted so clicks outside a small disc fall
          through to the windows below.

Run inside a niri session:  python3 niri_layer_shell_probe.py
It logs PROBE: lines, draws a ring at the detected pointer, screenshots via grim
(if present) to /tmp/niri_probe.png, then exits non-zero if GATE 2 failed.
"""
import sys
import time

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gtk4LayerShell as LS  # noqa: E402

RING_R = 110
state = {"px": None, "py": None, "t_map": None, "t_pointer": None,
         "mon": None, "ok": False, "moved": False}


def log(msg):
    print(f"PROBE: {msg}", flush=True)


def on_draw(area, cr, w, h, _):
    # Transparent clear, then a ring at the detected pointer (or center).
    cr.set_operator(1)  # CLEAR-ish: paint nothing opaque
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(2)  # OVER
    px = state["px"] if state["px"] is not None else w / 2
    py = state["py"] if state["py"] is not None else h / 2
    cr.set_source_rgba(0.0, 0.0, 0.0, 0.55)
    cr.arc(px, py, RING_R, 0, 6.2832)
    cr.fill()
    cr.set_source_rgba(0.85, 0.7, 0.4, 1.0)  # brass ring
    cr.set_line_width(6)
    cr.arc(px, py, RING_R, 0, 6.2832)
    cr.stroke()


def record_enter(_ctrl, x, y):
    # Only an enter that precedes any motion proves the compositor delivers
    # coords on map; an enter provoked by a mouse nudge proves nothing.
    if state["t_pointer"] is None:
        if state["moved"]:
            log(f"GATE2 tainted: pointer-enter at ({x:.0f},{y:.0f}) arrived "
                f"only after user movement; cannot claim coords-on-map")
        else:
            state["t_pointer"] = time.monotonic()
            dt = state["t_pointer"] - state["t_map"] if state["t_map"] else -1
            log(f"GATE2 pointer coords received WITHOUT movement: ({x:.0f},{y:.0f}) "
                f"{dt*1000:.0f}ms after map")
    state["px"], state["py"] = x, y


def record_motion(_ctrl, x, y):
    if not state["moved"]:
        state["moved"] = True
        if state["t_pointer"] is None:
            log("GATE2 mouse moved before any enter event; a later pass would be tainted")
    state["px"], state["py"] = x, y


def finish(win):
    # GATE 3: restrict input to a small disc around the pointer so clicks
    # elsewhere pass through. Approximated with a rectangular input region.
    try:
        surface = win.get_surface()
        px = int(state["px"] or 0)
        py = int(state["py"] or 0)
        reg = cairo.Region(cairo.RectangleInt(px - RING_R, py - RING_R,
                                              2 * RING_R, 2 * RING_R))
        surface.set_input_region(reg)
        log(f"GATE3 input region restricted to {2*RING_R}px disc at "
            f"({px},{py}); rest of the surface passes input through")
    except Exception as e:  # noqa: BLE001
        log(f"GATE3 input-region restriction FAILED: {e}")

    import subprocess
    try:
        subprocess.run(["grim", "/tmp/niri_probe.png"], timeout=8, check=False)
        log("screenshot written to /tmp/niri_probe.png")
    except FileNotFoundError:
        log("grim not installed; skipped screenshot")

    state["ok"] = state["t_pointer"] is not None
    log(f"RESULT gate1_mapped=True gate2_pointer_on_map={state['ok']} "
        f"monitor={state['mon']}")
    win.get_application().quit()
    return False


def on_app(app):
    win = Gtk.ApplicationWindow(application=app)
    LS.init_for_window(win)
    LS.set_layer(win, LS.Layer.OVERLAY)
    LS.set_namespace(win, "juhradial-probe")
    for edge in (LS.Edge.LEFT, LS.Edge.RIGHT, LS.Edge.TOP, LS.Edge.BOTTOM):
        LS.set_anchor(win, edge, True)
    LS.set_exclusive_zone(win, -1)
    LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)

    area = Gtk.DrawingArea()
    area.set_draw_func(on_draw, None)
    win.set_child(area)

    motion = Gtk.EventControllerMotion()
    motion.connect("enter", record_enter)
    motion.connect("motion", record_motion)
    win.add_controller(motion)

    css = Gtk.CssProvider()
    css.load_from_data(b"window, drawingarea { background: transparent; }")
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_USER
    )

    def after_map():
        state["t_map"] = time.monotonic()
        disp = Gdk.Display.get_default()
        mons = disp.get_monitors()
        if mons.get_n_items():
            m = mons.get_item(0)
            g = m.get_geometry()
            state["mon"] = f"{m.get_connector()} {g.width}x{g.height}+{g.x}+{g.y} scale={m.get_scale_factor()}"
        log(f"GATE1 layer surface mapped; monitor={state['mon']}")
        # Give the compositor a beat to deliver the pointer-enter, then finish.
        GLib.timeout_add(1200, finish, win)
        return False

    win.connect("map", lambda _w: GLib.idle_add(after_map))
    win.present()


def _on_timeout(app):
    log("TIMEOUT: no result in 8s")
    app.quit()
    return False


def main():
    app = Gtk.Application(application_id="com.juhlabs.niriprobe")
    app.connect("activate", on_app)
    # Safety: quit if the session never delivers map/pointer.
    GLib.timeout_add(8000, _on_timeout, app)
    app.run(None)
    sys.exit(0 if state["ok"] else 2)


if __name__ == "__main__":
    main()
