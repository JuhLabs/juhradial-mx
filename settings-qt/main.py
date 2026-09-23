#!/usr/bin/env python3
"""JuhRadial MX settings (Qt6/QML redesign, v0.5).

Run:  python3 main.py      (system python3 - has PyQt6; .venv is fal-only)
Unified Qt with the PyQt6 overlay; QML front-end, Python bridges for theme/data.
"""
import os
import sys
import pathlib

from PyQt6.QtGui import QGuiApplication, QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import QSize, Qt, QObject, pyqtSlot
from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickImageProvider

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bridge.theme import Theme          # noqa: E402
from bridge.backend import Backend      # noqa: E402

MONO_DIR = HERE / "assets" / "icons" / "mono"
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

    QML usage: image://icon/<hex>/<icon-name>  (hex optional, defaults white).
    Icons are monochrome and would vanish on the dark UI, so we composite them
    with the requested colour. The bespoke Phosphor mono set
    (assets/icons/mono/<name>.png) is preferred over the freedesktop theme for a
    cohesive line style, then re-tinted by alpha; unknown names fall back to the
    system icon theme.
    """

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Pixmap)

    def requestPixmap(self, sid, requested):
        w = requested.width() if requested.width() > 0 else 64
        h = requested.height() if requested.height() > 0 else 64
        tint = "#FFFFFF"
        name = sid
        parts = sid.split("/", 1)
        if len(parts) == 2 and len(parts[0]) in (6, 8) and all(
                c in "0123456789abcdefABCDEF" for c in parts[0]):
            tint, name = "#" + parts[0], parts[1]
        mono = MONO_DIR / (name + ".png")
        if mono.exists():
            base = QPixmap(str(mono)).scaled(
                w, h, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        else:
            icon = QIcon.fromTheme(name)
            base = icon.pixmap(QSize(w, h)) if not icon.isNull() else QPixmap()
        if base.isNull():
            base = QPixmap(w, h)
            base.fill(Qt.GlobalColor.transparent)
        tinted = QPixmap(base.size())
        tinted.fill(Qt.GlobalColor.transparent)
        p = QPainter(tinted)
        p.drawPixmap(0, 0, base)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(tinted.rect(), QColor(tint))
        p.end()
        return tinted, tinted.size()


def main():
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

    shot = os.environ.get("JUH_SHOT")
    if shot:
        import subprocess
        from PyQt6.QtCore import QTimer

        def _grab():
            # grabWindow() does not expose on this Wayland/KWin setup; use the
            # native screenshot of the active window instead.
            subprocess.run(["spectacle", "-b", "-n", "-a", "-o", shot],
                           check=False)
            print("shot saved:", shot)
            app.quit()
        QTimer.singleShot(int(os.environ.get("JUH_SHOT_DELAY", "1600")), _grab)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
