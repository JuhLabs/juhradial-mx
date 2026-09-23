#!/usr/bin/env python3
"""Macros tab (audit P0 #1 and 4.8): Record then Save actually saves, the
editor's rows round-trip the daemon's flat action list, one button runs one
macro, delete can be undone, and ring slices can run a macro.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_macros_backend.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])

import bridge.backend as bk  # noqa: E402

RECORDED = [{"type": "key_down", "key": "ctrl"}, {"type": "delay", "ms": 120},
            {"type": "key_down", "key": "c"}, {"type": "delay", "ms": 80},
            {"type": "key_up", "key": "c"}, {"type": "delay", "ms": 40},
            {"type": "key_up", "key": "ctrl"}, {"type": "delay", "ms": 300},
            {"type": "key_down", "key": "Return"}, {"type": "key_up", "key": "Return"}]


class FakeDaemon:
    """The daemon's macro methods over an in-memory store."""

    def __init__(self):
        self.macros, self.calls, self.available, self.fail_save = {}, [], True, False

    def call(self, method, *args):
        self.calls.append((method,) + args)
        if method == "SaveMacro":
            m = json.loads(args[0])
            if self.fail_save or "id" not in m or "name" not in m:
                return None  # zbus rejects a MacroConfig without id/name
            self.macros[m["id"]] = m
            return []
        if method == "DeleteMacro":
            self.macros.pop(args[0], None)
            return []
        if method == "StopMacroRecording":
            return [json.dumps({"events": [], "actions": RECORDED})]
        return []

    def call1(self, method, *args, default=None):
        if method == "ListMacros":
            return json.dumps(list(self.macros.values()))
        return default

    def call_async(self, *a, **k):
        pass

    def call_then(self, method, cb, *args):
        cb(None)


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    fake = FakeDaemon()
    for name in ("call", "call1", "call_async", "call_then"):
        monkeypatch.setattr(b.daemon, name, getattr(fake, name))
    monkeypatch.setattr(type(b.daemon), "available", property(lambda self: True))
    b.fake = fake
    return b


def test_record_then_save_saves(backend):
    assert backend.startMacroRecording()
    draft = backend.stopMacroRecording()
    assert draft["steps"] == 3 and draft["ms"] == 540
    assert backend.saveDraft("Copy then enter")
    saved = backend.fake.macros["copy_then_enter"]
    assert saved["use_standard_delay"] is False and saved["repeat_mode"] == "once"
    assert saved["actions"] == RECORDED
    assert ("ReloadMacroTriggers",) in backend.fake.calls
    # the payload is the one the daemon test parses (tests/fixtures)
    fixture = json.loads((REPO / "tests" / "fixtures" / "qt_new_macro.json").read_text())
    assert set(fixture) == set(saved)


def test_a_failed_save_is_reported(backend):
    notes = []
    backend.toastRequested.connect(lambda text, kind: notes.append(kind))
    backend.startMacroRecording()
    backend.stopMacroRecording()
    backend.fake.fail_save = True
    assert backend.saveDraft("x") is False
    assert "danger" in notes


def test_discard_and_nothing_recorded(backend):
    backend.startMacroRecording()
    backend.stopMacroRecording()
    backend.discardDraft()
    assert backend.saveDraft("x") is False
    backend.daemon.call = lambda m, *a: [json.dumps({"actions": []})] if m == "StopMacroRecording" else []
    assert backend.stopMacroRecording() == {}


def test_rows_collapse_key_presses_and_round_trip():
    rows = bk.macro_rows(RECORDED)
    assert rows == [{"kind": "keys", "chord": "ctrl+c", "hold": 240},
                    {"kind": "delay", "ms": 300},
                    {"kind": "keys", "chord": "Return", "hold": 0}]
    again = bk.macro_actions(rows)
    assert again[:5] == [{"type": "key_down", "key": "ctrl"}, {"type": "key_down", "key": "c"},
                         {"type": "delay", "ms": 240}, {"type": "key_up", "key": "c"},
                         {"type": "key_up", "key": "ctrl"}]
    assert bk.macro_rows(again) == rows


def test_rows_keep_what_they_cannot_pair():
    odd = [{"type": "key_down", "key": "shift"}, {"type": "text", "text": "hi"},
           {"type": "key_up", "key": "shift"}, {"type": "mouse_down", "button": "left"},
           {"type": "scroll", "direction": "up", "amount": 2}, {"type": "mouse_click", "button": "back"}]
    rows = bk.macro_rows(odd)
    assert [r["kind"] for r in rows] == ["raw", "text", "raw", "raw", "scroll", "click"]
    assert bk.macro_actions(rows) == odd


def test_recorded_clicks_become_click_steps():
    acts = [{"type": "mouse_down", "button": "back"}, {"type": "delay", "ms": 90},
            {"type": "mouse_up", "button": "back"}, {"type": "mouse_down", "button": "left"},
            {"type": "mouse_up", "button": "right"}]
    rows = bk.macro_rows(acts)
    assert rows[0] == {"kind": "click", "button": "back"}
    assert [r["kind"] for r in rows[1:]] == ["raw", "raw"]


def test_ids_are_file_safe_and_unique():
    assert bk.macro_id_for("Copy & paste!", set()) == "copy_paste"
    assert bk.macro_id_for("Copy & paste!", {"copy_paste"}) == "copy_paste_2"
    assert bk.macro_id_for("  ", set()) == "macro"


def test_one_button_runs_one_macro(backend):
    for mid in ("a", "b"):
        backend.fake.macros[mid] = bk.new_macro(mid, mid.upper(), RECORDED)
    backend.setMacroTrigger("a", "mouse:8")
    backend.setMacroTrigger("b", "mouse:8")
    assert backend.fake.macros["b"]["assigned_trigger"] == "mouse:8"
    assert backend.fake.macros["a"]["assigned_trigger"] is None
    assert backend.triggerForSlot("forward") == "mouse:9"


def test_delete_can_be_undone(backend):
    backend.fake.macros["a"] = bk.new_macro("a", "A", RECORDED)
    snap = backend.deleteMacro("a")
    assert "a" not in backend.fake.macros
    assert backend.restoreMacro(snap) and backend.fake.macros["a"]["name"] == "A"


def test_summary_follows_the_timing_mode(backend):
    m = bk.new_macro("a", "A", RECORDED)
    assert backend.macroSummary(m) == {"steps": 3, "ms": 540}
    m["use_standard_delay"], m["standard_delay_ms"] = True, 10
    assert backend.macroSummary(m)["ms"] == 40   # four pauses of 10 ms


def test_editor_rows_save_and_duplicate(backend):
    backend.fake.macros["a"] = bk.new_macro("a", "A", RECORDED)
    rows = backend.macroEditorRows("a")
    rows.append({"kind": "click", "button": "right"})
    assert backend.saveMacroRows("a", rows)
    assert backend.fake.macros["a"]["actions"][-1] == {"type": "mouse_click", "button": "right"}
    backend.setMacroTrigger("a", "mouse:9")
    copy = backend.duplicateMacro("a")
    assert copy and backend.fake.macros[copy]["assigned_trigger"] is None
    assert backend.setMacroTiming("a", True, 25)
    assert backend.fake.macros["a"]["use_standard_delay"] is True


def test_import_and_export(backend, tmp_path):
    backend.fake.macros["a"] = bk.new_macro("a", "A", RECORDED)
    backend.fake.macros["a"]["assigned_trigger"] = "mouse:8"
    out = tmp_path / "a.json"
    assert backend.exportMacro("a", out.as_uri())
    exported = json.loads(out.read_text())
    assert exported["assigned_trigger"] is None and exported["actions"] == RECORDED
    assert backend.importMacro(out.as_uri())
    assert backend.fake.macros["a_2"]["name"] == "A", "an import never overwrites a macro"
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert backend.importMacro(bad.as_uri()) is False


def test_templates_create_editable_macros(backend):
    ids = [t["id"] for t in backend.macroTemplates()]
    assert "duplicate_line" in ids
    mid = backend.createMacroFromTemplate("duplicate_line")
    assert mid and backend.macroEditorRows(mid)[2] == {"kind": "keys", "chord": "ctrl+c", "hold": 0}


def test_ring_slices_can_run_a_macro(backend):
    backend.fake.macros["a"] = bk.new_macro("a", "Build", RECORDED)
    entries = [a for a in backend.sliceActions() if a["id"].startswith(bk.MACRO_PREFIX)]
    assert entries and entries[0]["type"] == "macro" and entries[0]["command"] == "a"
    backend.slices.setAction(0, bk.MACRO_PREFIX + "a")
    s = backend.slices.slices()[0]
    assert (s["type"], s["command"], s["label"]) == ("macro", "a", "Build")
    src = (REPO / "overlay" / "juhradial-overlay.py").read_text(encoding="utf-8")
    assert 'elif cmd_type == "macro":' in src and 'asyncCall("ExecuteMacro", cmd)' in src
