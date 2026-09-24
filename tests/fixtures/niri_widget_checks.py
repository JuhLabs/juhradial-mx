"""Real QWidget checks run separately from the suite's QGuiApplication."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "overlay"))


@pytest.fixture(scope="module")
def qt_app():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def menu(monkeypatch, qt_app):
    import importlib.util
    import overlay_layer_shell
    from overlay_niri import create_niri_menu

    app = qt_app
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(overlay_layer_shell, "start_niri_layer_shell", lambda: None)
    path = Path(__file__).resolve().parents[2] / "overlay" / "juhradial-overlay.py"
    spec = importlib.util.spec_from_file_location("niri_test_overlay", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(module, "IS_KDE", False)

    class Host:
        def __init__(self):
            self.messages = []

        def attach(self, menu):
            pass

        def send(self, *message):
            self.messages.append(message)

    host = Host()
    widget = create_niri_menu(module.RadialMenu, host)
    yield widget, host, app
    widget.hide()
    widget.deleteLater()
    app.processEvents()


def test_stationary_enter_places_and_renders_existing_menu(menu):
    import base64
    from PyQt6.QtGui import QImage

    widget, host, app = menu
    widget.on_show(9999, 9999)  # Stale daemon coordinates must be ignored.
    assert not widget.isVisible()
    widget.layer_event("enter", widget._serial, 800, 600, 1920, 1080)
    assert widget.isVisible()
    assert (widget.menu_center_x, widget.menu_center_y) == (800, 600)
    assert widget.highlighted_slice == -1
    app.processEvents()
    frame = next(message for message in host.messages if message[0] == "frame")
    image = QImage.fromData(base64.b64decode(frame[4]), "PNG")
    assert not image.isNull()
    assert (image.width(), image.height()) == (widget.win_px, widget.win_px)
    assert image.pixelColor(0, 0).alpha() == 0
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    assert max(rgba.constBits().asstring(rgba.sizeInBytes())[3::4]) > 0


def test_tap_before_pointer_enter_is_preserved(menu):
    widget, host, _app = menu
    widget.on_show(0, 0)
    widget.on_hide()
    widget.layer_event("enter", widget._serial, 800, 600, 1920, 1080)
    assert widget.isVisible() and widget.toggle_mode
    widget.layer_event("escape", widget._serial)
    assert not widget.isVisible()
    assert host.messages[-1] == ("hide",)


def test_cancelled_hold_and_stale_enter_cannot_reopen_menu(menu):
    widget, _host, _app = menu
    widget.on_show(0, 0)
    old_serial = widget._serial
    widget.show_time -= 1
    widget.on_hide()
    widget.layer_event("enter", old_serial, 800, 600, 1920, 1080)
    assert not widget.isVisible()
    widget.on_show(0, 0)
    widget.layer_event("enter", old_serial, 800, 600, 1920, 1080)
    assert not widget.isVisible()


def test_new_open_can_render_while_old_frame_ack_is_pending(menu):
    widget, host, app = menu
    widget.on_show(0, 0)
    widget.layer_event("enter", widget._serial, 800, 600, 1920, 1080)
    app.processEvents()
    assert widget._frame_pending
    widget.hide()
    widget.on_show(0, 0)
    widget.layer_event("enter", widget._serial, 800, 600, 1920, 1080)
    app.processEvents()
    assert widget._frame_pending
    assert len([message for message in host.messages if message[0] == "frame"]) == 2
