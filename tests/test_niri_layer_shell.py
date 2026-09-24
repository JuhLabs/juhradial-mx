"""Optional niri backend selection and stationary-pointer placement."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "overlay"))


@pytest.mark.parametrize("env", [
    {}, {"XDG_CURRENT_DESKTOP": "KDE"}, {"XDG_CURRENT_DESKTOP": "GNOME"},
    {"XDG_CURRENT_DESKTOP": "Hyprland"}, {"XDG_CURRENT_DESKTOP": "COSMIC"},
    {"XDG_CURRENT_DESKTOP": "not-niri"},
])
def test_other_desktops_never_load_layer_shell(env):
    from overlay_layer_shell import start_niri_layer_shell

    def unexpected_load():
        pytest.fail("optional library was loaded on another desktop")

    messages = []
    assert start_niri_layer_shell(env, unexpected_load, messages.append) is None
    assert messages == []


@pytest.mark.parametrize("env", [
    {"XDG_CURRENT_DESKTOP": "niri"},
    {"XDG_CURRENT_DESKTOP": "NIRI:wlroots"},
    {"NIRI_SOCKET": "/run/user/1000/niri.sock"},
])
def test_niri_uses_available_backend(env):
    from overlay_layer_shell import start_niri_layer_shell

    backend = object()
    assert start_niri_layer_shell(env, lambda: backend) is backend


@pytest.mark.parametrize("error", [ImportError("missing typelib"), OSError("missing library"),
                                       RuntimeError("unsupported compositor")])
def test_niri_missing_library_falls_back_with_one_log(error):
    from overlay_layer_shell import start_niri_layer_shell

    def unavailable():
        raise error

    messages = []
    assert start_niri_layer_shell({"XDG_CURRENT_DESKTOP": "niri"}, unavailable, messages.append) is None
    assert len(messages) == 1
    assert "fallback" in messages[0].lower()


def test_pointer_enter_anchors_once_and_motion_cannot_fake_stationary_placement():
    from overlay_layer_shell import PointerAnchor

    anchor = PointerAnchor()
    assert anchor.enter(45, 90) == (45, 90)
    anchor.motion()
    assert anchor.enter(90, 180) is None
    moved_first = PointerAnchor()
    moved_first.motion()
    assert moved_first.enter(45, 90) is None


def test_real_host_startup_failure_falls_back(monkeypatch, tmp_path):
    from overlay_layer_shell import start_niri_layer_shell

    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-unavailable")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    messages = []
    assert start_niri_layer_shell({"XDG_CURRENT_DESKTOP": "niri"}, log=messages.append) is None
    assert len(messages) == 1


@pytest.mark.parametrize("case", [
    "stationary_enter_places_and_renders_existing_menu",
    "tap_before_pointer_enter_is_preserved",
    "cancelled_hold_and_stale_enter_cannot_reopen_menu",
    "new_open_can_render_while_old_frame_ack_is_pending",
])
def test_niri_widget_lifecycle_in_own_application(case):
    import os
    import subprocess

    # Existing settings tests own a QGuiApplication, which cannot host QWidget.
    # A separate process exercises real rendering without changing their setup.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         str(Path(__file__).parent / "fixtures" / "niri_widget_checks.py"), "-k", case],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
