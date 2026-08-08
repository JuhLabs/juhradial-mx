"""Behavioral regressions for non-blocking overlay haptic calls."""

import ast
from pathlib import Path


OVERLAY_PATH = Path(__file__).resolve().parents[1] / "overlay" / "juhradial-overlay.py"


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


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self, watcher):
        assert self.callback is not None
        self.callback(watcher)


class _Watcher:
    created = []

    def __init__(self, pending_call, parent):
        self.pending_call = pending_call
        self.parent = parent
        self.finished = _Signal()
        self.error = None
        self.deleted = False
        self.created.append(self)

    def deleteLater(self):
        self.deleted = True


class _PendingReply:
    def __init__(self, watcher):
        self._watcher = watcher

    def isError(self):
        return self._watcher.error is not None

    def error(self):
        return self._watcher.error


class _Error:
    def __init__(self, name="org.example.Error", message="failed"):
        self._name = name
        self._message = message

    def name(self):
        return self._name

    def message(self):
        return self._message


class _SyncReply:
    class MessageType:
        ErrorMessage = object()

    def type(self):
        return object()


class _Interface:
    def __init__(self, valid=True):
        self.valid = valid
        self.async_calls = []
        self.sync_calls = []

    def isValid(self):
        return self.valid

    def asyncCall(self, method, event):
        self.async_calls.append((method, event))
        return (method, event)

    def call(self, method, event):
        self.sync_calls.append((method, event))
        return _SyncReply()


_NAMESPACE = {
    "QDBusPendingCallWatcher": _Watcher,
    "QDBusPendingReply": _PendingReply,
}
_ON_HAPTIC_FINISHED = _radial_menu_method("_on_haptic_finished", _NAMESPACE)
_TRIGGER_HAPTIC = _radial_menu_method("_trigger_haptic", _NAMESPACE)


class _MenuHarness:
    _on_haptic_finished = _ON_HAPTIC_FINISHED
    _trigger_haptic = _TRIGGER_HAPTIC

    def __init__(self, valid=True):
        self.daemon_iface = _Interface(valid=valid)
        self._haptic_watchers = set()
        self._pending_haptic_events = set()


def setup_function():
    _Watcher.created.clear()


def test_haptic_uses_async_dbus_without_a_blocking_call():
    menu = _MenuHarness()

    menu._trigger_haptic("menu_appear")

    assert menu.daemon_iface.async_calls == [("TriggerHaptic", "menu_appear")]
    assert menu.daemon_iface.sync_calls == []
    assert len(menu._haptic_watchers) == 1
    assert menu._pending_haptic_events == {"menu_appear"}


def test_duplicate_pending_event_is_coalesced():
    menu = _MenuHarness()

    menu._trigger_haptic("slice_change")
    menu._trigger_haptic("slice_change")

    assert menu.daemon_iface.async_calls == [("TriggerHaptic", "slice_change")]
    assert len(menu._haptic_watchers) == 1


def test_distinct_events_are_sent_in_order():
    menu = _MenuHarness()

    menu._trigger_haptic("menu_appear")
    menu._trigger_haptic("slice_change")

    assert menu.daemon_iface.async_calls == [
        ("TriggerHaptic", "menu_appear"),
        ("TriggerHaptic", "slice_change"),
    ]
    assert len(menu._haptic_watchers) == 2


def test_successful_reply_releases_pending_state():
    menu = _MenuHarness()
    menu._trigger_haptic("confirm")
    watcher = _Watcher.created[-1]

    watcher.finished.emit(watcher)

    assert menu._haptic_watchers == set()
    assert menu._pending_haptic_events == set()
    assert watcher.deleted


def test_error_reply_releases_pending_state(capsys):
    menu = _MenuHarness()
    menu._trigger_haptic("invalid")
    watcher = _Watcher.created[-1]
    watcher.error = _Error()

    watcher.finished.emit(watcher)

    output = capsys.readouterr().out
    assert "org.example.Error" in output
    assert "failed" in output
    assert menu._haptic_watchers == set()
    assert menu._pending_haptic_events == set()
    assert watcher.deleted


def test_invalid_interface_does_not_create_a_pending_call():
    menu = _MenuHarness(valid=False)

    menu._trigger_haptic("menu_appear")

    assert menu.daemon_iface.async_calls == []
    assert _Watcher.created == []
