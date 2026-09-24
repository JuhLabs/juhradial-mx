#!/usr/bin/env python3
"""JuhRadial MX settings (Qt6/QML redesign, v0.5).

Run:  python3 main.py      (system python3 - has PyQt6; .venv is fal-only)
Unified Qt with the PyQt6 overlay; QML front-end, Python bridges for theme/data.
"""
import os
import sys
import pathlib

from PyQt6.QtGui import QGuiApplication, QIcon, QPixmap, QPainter, QColor, QImage
from PyQt6.QtCore import QSize, Qt, QObject, QRectF, pyqtSlot
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickImageProvider

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bridge.theme import Theme          # noqa: E402
from bridge.backend import Backend      # noqa: E402
from bridge.i18n import install_translator  # noqa: E402

MONO_DIR = HERE / "assets" / "icons" / "mono"
MONO2_DIR = HERE / "assets" / "icons" / "mono2"
NAV_DIR = HERE / "assets" / "icons" / "nav"
ICON_DIRS = (MONO_DIR, NAV_DIR)
CLASSIC_DIRS = (HERE / "assets" / "icons" / "classic" / "mono",
                HERE / "assets" / "icons" / "classic" / "nav")
ICON_STYLES = ("line", "classic", "mono", "mono2")
DBUS_SERVICE = "org.kde.juhradialmx.settings"


class SingleInstance(QObject):
    """D-Bus surface for single-instance activation (issue #65).

    Owning DBUS_SERVICE marks this process as THE settings instance; a
    second launch finds the name taken, calls Activate here, and exits.
    This also closes the two-instances-race on config.json.
    """

    def __init__(self, engine):
        super().__init__()
        self._engine = engine

    @pyqtSlot()
    def Activate(self):
        for win in self._engine.rootObjects():
            win.show()
            win.raise_()
            win.requestActivate()

    @pyqtSlot()
    def Quit(self):
        # Lets a successor instance take over on desktops where a
        # cross-process raise is refused (GNOME/COSMIC focus stealing
        # prevention): quit-and-relaunch is the only path to a visible,
        # focused window there. All settings writes flush on change, so
        # quitting loses nothing.
        QGuiApplication.quit()


class IconProvider(QQuickImageProvider):
    """Resolve icon names for QML, tinted to a requested colour.

    QML usage: image://icon/<hex>/<style>/<icon-name>  (hex and style optional;
    white and "line" by default). "classic" resolves the pre-0.4.5 sets under
    assets/icons/classic first, "mono2" the Monochrome 2 PNGs in
    assets/icons/mono2 (the line family fills any gap). One line-icon family
    (24-grid SVG masters in assets/icons/mono and assets/icons/nav) is
    rendered by QSvgRenderer at the exact requested pixel size, so glyphs stay
    crisp at every scale factor, then tinted by alpha.
    Legacy PNG masters and the freedesktop theme remain as fallbacks so every
    icon name a user config references keeps resolving.
    """

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    @staticmethod
    def _render_svg(path, w, h):
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QPixmap()
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ds = renderer.defaultSize()
        if ds.width() > 0 and ds.height() > 0:
            s = min(w / ds.width(), h / ds.height())
            rw, rh = ds.width() * s, ds.height() * s
            renderer.render(p, QRectF((w - rw) / 2, (h - rh) / 2, rw, rh))
        else:
            renderer.render(p, QRectF(0, 0, w, h))
        p.end()
        return QPixmap.fromImage(img)

    def _base(self, name, w, h, style="line"):
        # Directory order is the style's precedence: "classic" must find its
        # PNG masters before the SVG family of the same name.
        if style == "classic":
            dirs = CLASSIC_DIRS + ICON_DIRS
        elif style == "mono2":
            dirs = (MONO2_DIR,) + ICON_DIRS
        else:
            dirs = ICON_DIRS
        for d in dirs:
            svg = d / (name + ".svg")
            if svg.exists():
                pm = self._render_svg(svg, w, h)
                if not pm.isNull():
                    return pm
            png = d / (name + ".png")
            if png.exists():
                return QPixmap(str(png)).scaled(
                    w, h, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
        icon = QIcon.fromTheme(name)
        return icon.pixmap(QSize(w, h)) if not icon.isNull() else QPixmap()

    def requestPixmap(self, sid, requested):
        w = requested.width() if requested.width() > 0 else 64
        h = requested.height() if requested.height() > 0 else 64
        tint = "#FFFFFF"
        style = "line"
        name = sid
        parts = sid.split("/", 1)
        if len(parts) == 2 and parts[0] == "raw":
            # image://icon/raw/<name>: an application's own themed icon, untinted.
            tint, name = None, parts[1]
        elif len(parts) == 2 and len(parts[0]) in (6, 8) and all(
                c in "0123456789abcdefABCDEF" for c in parts[0]):
            tint, name = "#" + parts[0], parts[1]
        parts = name.split("/", 1)
        if len(parts) == 2 and parts[0] in ICON_STYLES:
            style, name = parts[0], parts[1]
        base = self._base(name, w, h, style)
        if base.isNull() and tint is None:
            # An app icon outside the Qt theme (no platform theme, Flatpak
            # exports): the XDG hicolor/pixmaps file, as cacheAppIcon finds it.
            from bridge.backend import _xdg_icon_file
            found = _xdg_icon_file(name)
            if found.endswith(".svg"):
                base = self._render_svg(found, w, h)
            elif found:
                base = QPixmap(found).scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation)
        if base.isNull():
            base = QPixmap(w, h)
            base.fill(Qt.GlobalColor.transparent)
        if tint is None:
            return base, base.size()
        tinted = QPixmap(base.size())
        tinted.fill(Qt.GlobalColor.transparent)
        p = QPainter(tinted)
        p.drawPixmap(0, 0, base)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(tinted.rect(), QColor(tint))
        p.end()
        return tinted, tinted.size()


def main():
    import time
    t_start = time.perf_counter()
    app = QGuiApplication(sys.argv)
    app.setApplicationName("JuhRadial MX")
    app.setOrganizationName("JuhLabs")
    app.setDesktopFileName("org.kde.juhradialmx.settings")
    icon = HERE / "assets" / "logo" / "icons" / "juhradial-mx-256.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    # Single-instance gate (#65). Skipped for JUH_SHOT screenshot runs: a
    # capture must neither defer to a running instance nor claim the name
    # (it quits after ~1.6s and would leave a tray Activate with no window).
    bus = QDBusConnection.sessionBus()
    if bus.isConnected() and not os.environ.get("JUH_SHOT") \
            and not bus.registerService(DBUS_SERVICE):
        # Another instance owns the name. QDBusMessage.createMethodCall +
        # bounded call, NOT QDBusInterface: its constructor introspects the
        # owner with a 25s default timeout, which stalls if the owner is
        # still loading QML.
        def _call(method):
            msg = QDBusMessage.createMethodCall(
                DBUS_SERVICE, "/", DBUS_SERVICE, method)
            return bus.call(msg, QDBus.CallMode.Block, 2000)

        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        if "KDE" in desktop:
            # KDE honors the cross-process raise: hand off and exit.
            reply = _call("Activate")
            if reply.type() == QDBusMessage.MessageType.ReplyMessage:
                sys.exit(0)
            # Activate failed: owner is mid-exit; fall through to claim.
        else:
            # GNOME/COSMIC refuse tokenless raises, so Activate-and-exit
            # would leave the window buried. Ask the owner to quit and
            # take over: same one-window guarantee, relaunch UX preserved.
            _call("Quit")
        import time
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if bus.registerService(DBUS_SERVICE):
                break
            time.sleep(0.1)
        # If the name never freed (e.g. pre-update owner without a Quit
        # slot), continue anyway: a visible window beats a silent exit.

    translator = install_translator(app)  # qsTr() -> gettext catalogs; keep the reference for the app's lifetime
    engine = QQmlApplicationEngine()
    engine.addImageProvider("icon", IconProvider())

    theme = Theme()
    backend = Backend()

    # B1: the radial overlay colours itself from config.json `radial.accent`,
    # but the settings theme index lives in ui_state.json - so picking a theme
    # never recoloured the overlay. Mirror the chosen accent into config (Backend
    # is the sole config.json writer) on every theme change. At startup only
    # re-mirror for users whose config already has radial.accent: writing
    # unconditionally would seed merged defaults into an untouched config and
    # regress the overlay theme for users who never picked one.
    def _sync_overlay_accent():
        if backend.get("radial.accent") != theme.accent:
            backend.set("radial.accent", theme.accent)
    if backend.get("radial.accent") is not None:
        _sync_overlay_accent()
    theme.changed.connect(_sync_overlay_accent)

    ctx = engine.rootContext()
    ctx.setContextProperty("Theme", theme)
    ctx.setContextProperty("Backend", backend)
    ctx.setContextProperty("Slices", backend.slices)
    ctx.setContextProperty("assetsDir", (HERE / "assets").as_uri())
    ctx.setContextProperty("initialPage", int(os.environ.get("JUH_PAGE", "0")))

    engine.load(str(HERE / "qml" / "Main.qml"))
    if not engine.rootObjects():
        sys.exit("failed to load QML")

    single = SingleInstance(engine)
    bus.registerObject("/", DBUS_SERVICE, single,
                       QDBusConnection.RegisterOption.ExportAllSlots)

    # JUH_PERF=1 (or a file path): measure cold start and every tab switch,
    # print a table, exit. Used by tools/perf_tabs.py and the docs budget
    # (< 80 ms median switch, < 150 ms p95, < 900 ms cold start).
    perf = os.environ.get("JUH_PERF")
    if perf:
        _run_perf_pass(app, engine, t_start, None if perf == "1" else perf)

    shot = os.environ.get("JUH_SHOT")
    if shot:
        import subprocess
        from PyQt6.QtCore import QTimer
        import PyQt6.sip as sip
        from PyQt6.QtQuick import QQuickWindow

        window = sip.cast(engine.rootObjects()[0], QQuickWindow)
        size = os.environ.get("JUH_SHOT_SIZE", "")
        if "x" in size:
            w, h = (int(v) for v in size.lower().split("x", 1))
            window.setWidth(w)
            window.setHeight(h)

        def _grab():
            # Under xcb (tools/shot.py) grabWindow() renders the real scene
            # graph and needs no focus; offscreen renders the software scene
            # graph (no glass effects, exact layout, any window height). On
            # Wayland it comes back empty, so use the native active-window
            # screenshot there (which needs focus).
            if app.platformName() in ("xcb", "offscreen"):
                ok = window.grabWindow().save(shot)
                print(("shot saved: " if ok else "shot FAILED: ") + shot)
            else:
                subprocess.run(["spectacle", "-b", "-n", "-a", "-o", shot],
                               check=False)
                print("shot saved:", shot)
            app.quit()
        QTimer.singleShot(int(os.environ.get("JUH_SHOT_DELAY", "1600")), _grab)

    sys.exit(app.exec())


def _run_perf_pass(app, engine, t_start, out_path):
    """Switch through every tab twice (cold, then warm) and report timings.

    A switch is measured from setting nav.current until the Loader has
    instantiated the page (synchronous, "load") and until the window has
    swapped the first frame showing it ("frame"). Rows come out as Markdown.
    """
    import time
    from PyQt6.QtCore import QTimer

    import PyQt6.sip as sip
    from PyQt6.QtQuick import QQuickWindow

    root = engine.rootObjects()[0]
    window = sip.cast(root, QQuickWindow)
    nav = root.findChild(QObject, "nav")
    if nav is None:
        sys.exit("perf: nav objectName missing in Main.qml")
    # The page Loaders are Repeater delegates under the StackLayout, so they
    # are looked up lazily on the first step rather than at startup.
    loaders = []

    def page_name(loader):
        src = loader.property("source")
        name = src.toString() if hasattr(src, "toString") else str(src)
        return name.rsplit("/", 1)[-1].replace("Page.qml", "")

    passes = [("cold", []), ("warm", [])]
    rows = []
    state = {"pass": 0, "i": 0, "t0": 0.0, "t_load": 0.0, "first_frame": None, "waiting": False}

    def on_frame():
        if state["first_frame"] is None:
            state["first_frame"] = time.perf_counter() - t_start
        if not state["waiting"]:
            return
        state["waiting"] = False
        t_frame = time.perf_counter()
        label, seq = passes[state["pass"]]
        idx = seq[state["i"]]
        rows.append((label, page_name(loaders[idx]),
                     (state["t_load"] - state["t0"]) * 1000.0,
                     (t_frame - state["t0"]) * 1000.0))
        state["i"] += 1
        QTimer.singleShot(60, step)  # let the fade/rise animation settle

    def find_items(item, name, out):
        for child in item.childItems():
            if child.objectName() == name:
                out.append(child)
            find_items(child, name, out)
        return out

    def step():
        if not loaders:
            find_items(window.contentItem(), "pageLoader", loaders)
            if not loaders:
                sys.exit("perf: pageLoader objectNames missing in Main.qml")
            for k in range(len(passes)):
                passes[k] = (passes[k][0], list(range(len(loaders))))
        if state["i"] >= len(passes[state["pass"]][1]):
            state["pass"] += 1
            state["i"] = 0
            if state["pass"] >= len(passes):
                return finish()
        label, seq = passes[state["pass"]]
        idx = seq[state["i"]]
        state["t0"] = time.perf_counter()
        nav.setProperty("current", idx)
        state["t_load"] = time.perf_counter()
        state["waiting"] = True
        root.update()

    def finish():
        lines = ["| pass | page | load ms | first frame ms |", "|---|---|---:|---:|"]
        for label, name, load_ms, frame_ms in rows:
            lines.append(f"| {label} | {name} | {load_ms:.1f} | {frame_ms:.1f} |")
        warm = sorted(r[3] for r in rows if r[0] == "warm")
        if warm:
            median = warm[len(warm) // 2]
            p95 = warm[min(len(warm) - 1, int(round(0.95 * (len(warm) - 1))))]
            lines.append("")
            lines.append(f"warm switch: median {median:.1f} ms, p95 {p95:.1f} ms, max {warm[-1]:.1f} ms")
        if state["first_frame"] is not None:
            lines.append(f"cold start to first frame: {state['first_frame'] * 1000.0:.0f} ms")
        text = "\n".join(lines)
        print(text)
        if out_path:
            pathlib.Path(out_path).write_text(text + "\n", encoding="utf-8")
        app.quit()

    window.frameSwapped.connect(on_frame)
    QTimer.singleShot(int(os.environ.get("JUH_PERF_DELAY", "1200")), step)


if __name__ == "__main__":
    main()
