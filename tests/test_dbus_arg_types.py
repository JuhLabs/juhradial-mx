#!/usr/bin/env python3
"""Qt settings calls into the daemon carry the D-Bus types the daemon declares.

PyQt6 marshals a Python int as int32 (`i`). zbus rejects a method call whose
body signature differs from the handler's declared one ("Signature mismatch:
got `i`, expected `y`") before the handler runs, so an untyped int silently
broke DPI, SmartShift, Easy-Switch and the keyboard backlight in the Qt app.
The static test reads every method's parameter types from the daemon's
interface and checks each call site in the Qt bridge; the behavioural test
captures what the slots actually hand to QtDBus.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_dbus_arg_types.py -q
"""

import ast
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
INTERFACE = REPO_ROOT / "daemon" / "src" / "dbus" / "interface.rs"
BRIDGE = REPO_ROOT / "settings-qt" / "bridge" / "backend.py"
sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))

from PyQt6.QtDBus import QDBusArgument  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])

import bridge.backend as bk  # noqa: E402

# Rust parameter type -> the bridge helper that produces that D-Bus type.
WRAPPERS = {"u8": "_u8", "u16": "_u16"}
# Types a plain Python int can never satisfy and that have no helper yet.
UNSUPPORTED = {"u32", "u64", "i16", "i64", "f32", "f64"}


def _pascal(name):
    return "".join(part.title() for part in name.split("_"))


def daemon_methods():
    """{PascalCaseName: [rust types of the D-Bus arguments, in order]}."""
    text = INTERFACE.read_text(encoding="utf-8")
    methods = {}
    for match in re.finditer(r"(?:async )?fn (\w+)\(", text):
        start = i = match.end()
        depth = 1
        while depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        params = re.sub(r"#\[zbus\([^\]]*\)\]\s*\w+:\s*[^,]+,?", "", text[start:i - 1])
        types = []
        for param in params.split(","):
            param = param.strip()
            if not param or param.startswith("&self") or ":" not in param:
                continue
            types.append(param.split(":", 1)[1].strip())
        methods[_pascal(match.group(1))] = types
    return methods


def test_the_interface_parser_sees_the_known_signatures():
    methods = daemon_methods()
    assert methods["SetDpi"] == ["u16"]
    assert methods["SetSmartShift"] == ["bool", "u8"]
    assert methods["SetHost"] == ["u8"]
    assert methods["SetKeyboardBacklight"] == ["u8"]
    assert methods["NotifySliceHover"] == ["u8"]
    assert methods["TriggerHapticPattern"] == ["&str"]
    assert methods["SetKeypadPage"] == ["u8"]


def test_every_bridge_call_types_its_numeric_arguments():
    methods = daemon_methods()
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    problems, checked = [], 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("call", "call_async", "call_then", "call1", "_hw_then",
                                       "_kb_write_then")):
            continue
        # _hw_then(key, method, revert, *args); the others (method, ...)
        at = 1 if node.func.attr == "_hw_then" else 0
        if not (len(node.args) > at and isinstance(node.args[at], ast.Constant)
                and isinstance(node.args[at].value, str)):
            continue
        name = node.args[at].value
        if name not in methods:
            continue
        passed = node.args[at + 1:]
        if node.func.attr in ("call_then", "_hw_then"):
            passed = passed[1:]  # (method, callback | revert, *args)
        for rust_type, arg in zip(methods[name], passed):
            if rust_type in UNSUPPORTED:
                problems.append(f"line {node.lineno}: {name} takes {rust_type}, add a helper")
                continue
            wrapper = WRAPPERS.get(rust_type)
            if wrapper is None:
                continue
            checked += 1
            ok = (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                  and arg.func.id == wrapper)
            if not ok:
                problems.append(f"line {node.lineno}: {name} needs {wrapper}(...) for its {rust_type}")
    assert not problems, "\n".join(problems)
    # SetDpi, SetSmartShift (wheel mode and threshold), SetHost, SetKeyboardBacklight
    assert checked >= 5, "expected the DPI, SmartShift, host and backlight call sites"


class _Capture:
    def __init__(self):
        self.calls = []

    def call(self, method, *args):
        self.calls.append((method, args))
        return [True]

    call_async = call

    def call1(self, method, *args, default=None):
        self.calls.append((method, args))
        return default

    def call_then(self, method, callback, *args):
        self.calls.append((method, args))


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    b.daemon = _Capture()
    return b


def test_slots_hand_typed_arguments_to_qtdbus(backend):
    backend.setDpi(1600)
    backend.setScrollMode("smartshift")
    backend.setScrollMode("ratchet")
    backend.setScrollMode("freespin")
    backend.setSmartShiftThreshold(50)
    backend.setKeyboardBacklight(75)
    backend.switchHost(1)
    seen = {}
    for method, args in backend.daemon.calls:
        seen.setdefault(method, []).append(args)
    assert set(seen) >= {"SetDpi", "SetSmartShift", "SetKeyboardBacklight", "SetHost"}
    assert all(isinstance(a[0], QDBusArgument) for a in seen["SetDpi"])
    assert all(a[0] in (True, False) and isinstance(a[1], QDBusArgument) for a in seen["SetSmartShift"])
    assert isinstance(seen["SetKeyboardBacklight"][0][0], QDBusArgument)
    assert isinstance(seen["SetHost"][0][0], QDBusArgument)
