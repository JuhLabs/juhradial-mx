"""Behavioral regressions for conditional, asynchronous media-state queries."""

import ast
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication, QProcess


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "overlay"))

from overlay_media import MediaStateQuery, actions_use_media_state


OVERLAY_PATH = REPO_ROOT / "overlay" / "juhradial-overlay.py"


def _radial_menu_method(name: str, namespace: dict):
    module = ast.parse(OVERLAY_PATH.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == "RadialMenu":
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef) and statement.name == name:
                    exec(
                        compile(
                            ast.Module(body=[statement], type_ignores=[]),
                            f"<RadialMenu.{name}>",
                            "exec",
                        ),
                        namespace,
                    )
                    return namespace[name]
    raise AssertionError(f"RadialMenu.{name} not found")


@pytest.fixture(scope="module")
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


def _program(tmp_path: Path, body: str) -> str:
    path = tmp_path / "playerctl-probe"
    path.write_text("#!/usr/bin/python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return os.fspath(path)


def _wait_until(qt_app, predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for Qt process result")


def test_media_icon_detection_covers_main_actions_and_submenus():
    ordinary = [("Files", "exec", "dolphin", "blue", "folder", None)]
    direct = [("Play", "exec", "playerctl play-pause", "green", "play_pause", None)]
    nested = [
        (
            "Media",
            "submenu",
            "",
            "green",
            "folder",
            [("Play", "exec", "playerctl play-pause", "green", "play_pause")],
        )
    ]

    assert not actions_use_media_state(ordinary)
    assert actions_use_media_state(direct)
    assert actions_use_media_state(nested)


def test_process_query_returns_immediately_and_emits_playing(qt_app, tmp_path):
    program = _program(
        tmp_path,
        'import time\ntime.sleep(0.1)\nprint("Playing", end="")\n',
    )
    query = MediaStateQuery(program=program, timeout_ms=500)
    results = []
    query.state_changed.connect(results.append)

    query.start()

    assert results == []
    _wait_until(qt_app, lambda: bool(results))
    assert results == [True]


def test_paused_status_emits_false(qt_app, tmp_path):
    program = _program(tmp_path, 'print("Paused", end="")\n')
    query = MediaStateQuery(program=program, timeout_ms=500)
    results = []
    query.state_changed.connect(results.append)

    query.start()

    _wait_until(qt_app, lambda: bool(results))
    assert results == [False]


def test_repeated_start_coalesces_a_healthy_running_process(qt_app, tmp_path):
    program = _program(
        tmp_path,
        'import time\ntime.sleep(0.1)\nprint("Playing", end="")\n',
    )
    query = MediaStateQuery(program=program, timeout_ms=500)
    results = []
    query.state_changed.connect(results.append)

    query.start()
    _wait_until(
        qt_app,
        lambda: query._process.state() == QProcess.ProcessState.Running,
    )
    process = query._process
    query.start()

    assert query._process is process
    _wait_until(qt_app, lambda: query._process is None)
    assert results == [True]


def test_timeout_is_non_blocking_and_emits_false(qt_app, tmp_path):
    program = _program(
        tmp_path,
        'import time\ntime.sleep(1)\nprint("Playing", end="")\n',
    )
    query = MediaStateQuery(program=program, timeout_ms=20)
    results = []
    query.state_changed.connect(results.append)

    query.start()

    assert results == []
    _wait_until(qt_app, lambda: bool(results))
    assert results == [False]


def test_two_immediate_missing_playerctl_starts_leave_no_process_retained(
    qt_app, tmp_path
):
    query = MediaStateQuery(
        program=os.fspath(tmp_path / "does-not-exist"),
        timeout_ms=500,
    )
    results = []
    query.state_changed.connect(results.append)

    query.start()
    query.start()

    _wait_until(qt_app, lambda: bool(results))
    assert results == [False]
    _wait_until(qt_app, lambda: query._process is None)
    assert not getattr(query, "_retired_processes", ())


def test_restart_waits_for_the_previous_qprocess_terminal_state(qt_app, tmp_path):
    slow = _program(
        tmp_path,
        'import time\ntime.sleep(0.2)\nprint("Playing", end="")\n',
    )
    query = MediaStateQuery(program=slow, timeout_ms=1000)
    results = []
    query.state_changed.connect(results.append)

    query.start()
    _wait_until(
        qt_app,
        lambda: query._process.state() == QProcess.ProcessState.Running,
    )
    first = query._process

    # Force the timeout path while the real child is running, then request a
    # fresh query before Qt has delivered the killed child's finished signal.
    query._on_timeout(first)
    query.start()

    assert query._process is first

    _wait_until(qt_app, lambda: query._process is not first)
    replacement = query._process
    assert replacement is not None
    assert first.state() == QProcess.ProcessState.NotRunning

    _wait_until(qt_app, lambda: query._process is None)
    assert results == [False, True]


def test_crashed_process_reaches_finished_before_deferred_restart(qt_app, tmp_path):
    crashing = _program(
        tmp_path,
        "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n",
    )
    query = MediaStateQuery(program=crashing, timeout_ms=500)
    results = []
    query.state_changed.connect(results.append)

    query.start()
    crashed = query._process
    restart_requested = []

    retained_during_crash = []

    def request_during_crash(error):
        if error == QProcess.ProcessError.Crashed and not restart_requested:
            restart_requested.append(True)
            query.start()
            # Crashed is terminal at the OS level, but Qt still owes finished().
            retained_during_crash.append(query._process is crashed)

    crashed.errorOccurred.connect(request_during_crash)

    _wait_until(qt_app, lambda: len(results) == 2)
    _wait_until(qt_app, lambda: query._process is None)
    assert restart_requested == [True]
    assert retained_during_crash == [True]
    assert results == [False, False]


def _menu_methods():
    overlay_actions = SimpleNamespace(ACTIONS=[], MEDIA_PLAYING=False)
    namespace = {
        "overlay_actions": overlay_actions,
        "actions_use_media_state": actions_use_media_state,
    }
    refresh = _radial_menu_method("_refresh_media_glyph", namespace)
    changed = _radial_menu_method("_on_media_state_changed", namespace)
    return refresh, changed, overlay_actions


class _Query:
    def __init__(self):
        self.start_calls = 0

    def start(self):
        self.start_calls += 1


class _Menu:
    def __init__(self, visible=True):
        self._visible = visible
        self._media_state_query = _Query()
        self.update_calls = 0

    def isVisible(self):
        return self._visible

    def update(self):
        self.update_calls += 1


def test_menu_skips_playerctl_without_a_media_icon():
    refresh, _changed, overlay_actions = _menu_methods()
    overlay_actions.ACTIONS = [
        ("Files", "exec", "dolphin", "blue", "folder", None)
    ]
    menu = _Menu()

    refresh(menu)

    assert menu._media_state_query.start_calls == 0


def test_menu_starts_query_when_a_media_icon_is_visible():
    refresh, _changed, overlay_actions = _menu_methods()
    overlay_actions.ACTIONS = [
        ("Play", "exec", "playerctl play-pause", "green", "play_pause", None)
    ]
    menu = _Menu()

    refresh(menu)

    assert menu._media_state_query.start_calls == 1


def test_media_result_updates_state_and_only_repaints_a_visible_menu():
    _refresh, changed, overlay_actions = _menu_methods()
    visible = _Menu(visible=True)
    hidden = _Menu(visible=False)

    changed(visible, True)
    assert overlay_actions.MEDIA_PLAYING is True
    assert visible.update_calls == 1

    changed(hidden, False)
    assert overlay_actions.MEDIA_PLAYING is False
    assert hidden.update_calls == 0
