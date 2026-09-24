"""Optional GTK4 layer-shell host for niri, isolated from the Qt renderer.

The host owns Wayland surfaces and pointer input. The existing Qt menu sends
PNG frames over a private pipe so its painting and action code stay shared.
"""

import json
import os
import sys


def start_niri_layer_shell(environ=None, factory=None, log=print):
    """Probe only on niri, before selecting Qt's platform plugin."""
    env = os.environ if environ is None else environ
    desktops = env.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    if "niri" not in desktops and not env.get("NIRI_SOCKET"):
        return None
    try:
        return (factory or LayerShellProcess)()
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        log(f"OVERLAY: niri layer-shell unavailable; using existing fallback ({error})")
        return None


class PointerAnchor:
    """Motion before enter cannot establish stationary-cursor placement."""

    def __init__(self):
        self.moved = False
        self.anchored = False

    def enter(self, x, y):
        if self.moved or self.anchored:
            return None
        self.anchored = True
        return x, y

    def motion(self):
        self.moved = True


class LayerShellProcess:
    def __init__(self):
        import select
        import subprocess

        env = dict(os.environ, GDK_BACKEND="wayland")
        self.process = subprocess.Popen(
            [sys.executable, __file__, "--host"], env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, bufsize=0,
        )
        self.buffer = b""
        if not select.select([self.process.stdout], [], [], 3)[0]:
            self.close()
            raise RuntimeError("host startup timed out")
        if self.process.stdout.readline() != b'["ready"]\n':
            self.close()
            raise RuntimeError("GTK4 layer-shell or Wayland display unavailable")

    def attach(self, menu):
        from PyQt6.QtCore import QSocketNotifier

        self.menu = menu
        os.set_blocking(self.process.stdout.fileno(), False)
        self.notifier = QSocketNotifier(
            self.process.stdout.fileno(), QSocketNotifier.Type.Read, menu,
        )
        self.notifier.activated.connect(self.read_events)

    def send(self, *message):
        payload = (json.dumps(message) + "\n").encode()
        # FileIO writes may be partial for large PNG frames.
        while payload:
            written = self.process.stdin.write(payload)
            if not written:
                raise BrokenPipeError("layer-shell host exited")
            payload = payload[written:]

    def read_events(self, *_args):
        try:
            data = os.read(self.process.stdout.fileno(), 65536)
        except BlockingIOError:
            return
        if not data:
            self.notifier.setEnabled(False)
            self.menu.host_closed()
            return
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.menu.layer_event(*json.loads(line))

    def close(self):
        import subprocess

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()


def run_host():
    import base64
    import ctypes
    import ctypes.util
    import io
    import math

    # The library must interpose Wayland symbols before GTK loads them.
    ctypes.CDLL(ctypes.util.find_library("gtk4-layer-shell") or "libgtk4-layer-shell.so.0")
    import cairo
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell as LS

    Gtk.init()
    display = Gdk.Display.get_default()
    if display is None or not LS.is_supported():
        raise RuntimeError("layer shell is not supported")

    def emit(*message):
        print(json.dumps(message), flush=True)

    class Host:
        def __init__(self):
            self.serial = 0
            self.windows = []
            self.selected = None
            self.image = None
            self.origin = (0, 0)
            self.anchor = PointerAnchor()
            self.timeout = None
            self.buffer = b""
            self.loop = GLib.MainLoop()

        def hide(self):
            if self.timeout is not None:
                GLib.source_remove(self.timeout)
                self.timeout = None
            for win in self.windows:
                win.destroy()
            self.windows = []
            self.selected = None
            self.image = None

        def show(self, serial):
            self.hide()
            self.serial = serial
            self.anchor = PointerAnchor()
            monitors = display.get_monitors()
            # No cursor IPC: map one transparent surface on each output. Only
            # the output beneath the stationary pointer receives its enter.
            for index in range(monitors.get_n_items()):
                win = Gtk.Window()
                LS.init_for_window(win)
                LS.set_monitor(win, monitors.get_item(index))
                LS.set_namespace(win, "juhradial-mx")
                LS.set_layer(win, LS.Layer.OVERLAY)
                LS.set_exclusive_zone(win, -1)
                LS.set_keyboard_mode(win, LS.KeyboardMode.NONE)
                for edge in (LS.Edge.LEFT, LS.Edge.RIGHT, LS.Edge.TOP, LS.Edge.BOTTOM):
                    LS.set_anchor(win, edge, True)
                area = Gtk.DrawingArea()
                area.set_draw_func(self.draw)
                win.set_child(area)
                motion = Gtk.EventControllerMotion()
                motion.connect("enter", self.enter, win)
                motion.connect("motion", self.motion, win)
                motion.connect("leave", self.leave, win)
                win.add_controller(motion)
                click = Gtk.GestureClick()
                click.set_button(0)
                click.connect("pressed", self.pressed)
                win.add_controller(click)
                keys = Gtk.EventControllerKey()
                keys.connect("key-pressed", self.key_pressed)
                win.add_controller(keys)
                self.windows.append(win)
                win.present()
            self.timeout = GLib.timeout_add(1200, self.no_pointer)

        def no_pointer(self):
            self.timeout = None
            if self.selected is None:
                self.hide()
                emit("unavailable", self.serial, "no stationary pointer-enter on map")
            return GLib.SOURCE_REMOVE

        def enter(self, _controller, x, y, win):
            if self.anchor.enter(x, y) is None:
                return
            self.selected = win
            for other in self.windows:
                if other is not win:
                    other.set_visible(False)
            LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
            emit("enter", self.serial, x, y, win.get_width(), win.get_height())

        def motion(self, _controller, x, y, win):
            self.anchor.motion()
            if win is self.selected:
                emit("motion", self.serial, x, y)

        def leave(self, _controller, win):
            if win is self.selected:
                emit("leave", self.serial)

        def pressed(self, gesture, _count, x, y):
            emit("motion", self.serial, x, y)
            emit("click", self.serial, gesture.get_current_button())

        def key_pressed(self, _controller, keyval, _keycode, _state):
            if keyval == Gdk.KEY_Escape:
                emit("escape", self.serial)
                return True
            return False

        def draw(self, _area, cr, _width, _height):
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            if self.image is not None:
                cr.set_source_surface(self.image, *self.origin)
                cr.paint()

        def frame(self, serial, x, y, png):
            if serial != self.serial:
                return
            if self.selected is not None:
                self.image = cairo.ImageSurface.create_from_png(io.BytesIO(base64.b64decode(png)))
                self.origin = (x, y)
                # A disc includes the submenu fan; everything outside passes
                # through to the application below, including transparent corners.
                radius = self.image.get_width() // 2
                region = cairo.Region()
                for row in range(-radius, radius):
                    half = int(math.sqrt(max(0, radius * radius - row * row)))
                    if half:
                        region.union(cairo.RectangleInt(x + radius - half, y + radius + row, 2 * half, 1))
                self.selected.get_surface().set_input_region(region)
                self.selected.get_child().queue_draw()
            emit("painted", self.serial)

        def read_commands(self, _fd, _condition):
            data = os.read(sys.stdin.fileno(), 65536)
            if not data:
                self.hide()
                self.loop.quit()
                return GLib.SOURCE_REMOVE
            self.buffer += data
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                command, *args = json.loads(line)
                if command == "show":
                    self.show(*args)
                elif command == "hide":
                    self.hide()
                elif command == "frame":
                    self.frame(*args)
            return GLib.SOURCE_CONTINUE

    css = Gtk.CssProvider()
    css.load_from_data(b"window, drawingarea { background: transparent; }")
    Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    host = Host()
    GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, host.read_commands)
    emit("ready")
    host.loop.run()


if __name__ == "__main__" and sys.argv[1:] == ["--host"]:
    run_host()
