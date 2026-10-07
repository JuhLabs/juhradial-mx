"""A page whose QML cannot be loaded says why, instead of an empty pane (#172).

Runs the real window from a copy of the QML tree in which one page imports a
module that does not exist, then goes to that page the way search results do
(Backend.goTo, a Python slot). The panel must show Qt's error and the
package hint, and the app must still be running: a failed import builds its
message through the installed translator on the QML loader thread, which is
exactly where a deadlock would sit.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtQml")

ROOT = Path(__file__).resolve().parents[1]
QT_DIR = ROOT / "settings-qt"
sys.path.insert(0, os.fspath(QT_DIR))

DRIVER = r"""
import json, os, pathlib, sys
tree = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(tree))
import PyQt6.sip as sip
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtQuick import QQuickWindow
from bridge import compat
from bridge.backend import Backend
from bridge.i18n import install_translator
from bridge.theme import Theme

app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
theme, backend = Theme(probe_desktop=False), Backend()
compat.install(engine, theme)
_ = install_translator(app)
ctx = engine.rootContext()
ctx.setContextProperty("Theme", theme)
ctx.setContextProperty("Backend", backend)
ctx.setContextProperty("Slices", backend.slices)
ctx.setContextProperty("assetsDir", (tree / "assets").as_uri())
ctx.setContextProperty("initialPage", 0)
engine.load(str(tree / "qml" / "Main.qml"))
window = sip.cast(engine.rootObjects()[0], QQuickWindow)

def walk(item, out):
    for child in item.childItems():
        if child.objectName() == "pageError" and child.isVisible():
            out.append(child)
        walk(child, out)
    return out

def report():
    panels = walk(window.contentItem(), [])
    print("RESULT " + json.dumps([{"detail": p.property("detail"), "fix": p.property("fix")} for p in panels]))
    app.quit()

QTimer.singleShot(200, lambda: backend.goTo("haptics"))
QTimer.singleShot(900, report)
sys.exit(app.exec())
"""


def test_a_broken_page_explains_itself(tmp_path):
    from bridge import compat

    tree = tmp_path / "settings-qt"
    tree.mkdir()
    for name in ("qml", "bridge"):
        shutil.copytree(QT_DIR / name, tree / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(QT_DIR / "VERSION", tree / "VERSION")
    (tree / "assets").symlink_to(QT_DIR / "assets")
    page = tree / "qml" / "pages" / "HapticsPage.qml"
    page.write_text("import QtQuick.NoSuchModule\n" + page.read_text(encoding="utf-8"), encoding="utf-8")

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=os.fspath(tmp_path / "config"),
               XDG_CACHE_HOME=os.fspath(tmp_path / "cache"))
    try:
        result = subprocess.run([sys.executable, "-c", DRIVER, os.fspath(tree)],
                                capture_output=True, text=True, env=env, timeout=60)
    except subprocess.TimeoutExpired:
        raise AssertionError("the settings app hung on a page that cannot be loaded") from None
    line = next((line for line in result.stdout.splitlines() if line.startswith("RESULT ")), None)
    assert line, result.stdout + result.stderr
    panels = json.loads(line[len("RESULT "):])
    assert len(panels) == 1, panels
    detail = panels[0]["detail"]
    assert 'module "QtQuick.NoSuchModule" is not installed' in detail
    assert "HapticsPage.qml" in detail
    assert panels[0]["fix"] == compat.hint_for_error(detail)
