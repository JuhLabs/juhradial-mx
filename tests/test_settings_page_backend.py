#!/usr/bin/env python3
"""Settings tab (0.4.5 pass): language list, ring size / Automatic / icon size,
restore defaults with Undo, import preview with Undo, desktop defaults that
resolve Auto-detect, autostart health and the update version compare.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_settings_page_backend.py -q
"""
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO / "settings-qt"))
sys.path.insert(0, os.fspath(REPO / "overlay"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])

import bridge.backend as bk  # noqa: E402


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk, "UPDATE_CACHE", tmp_path / "update.json")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    b = bk.Backend()
    b.daemon.call_async = lambda *a, **k: None
    return b


def test_every_shipped_locale_is_offered_with_system_default_first(backend):
    shipped = {p.name for p in (REPO / "overlay" / "locales").iterdir() if p.is_dir()}
    langs = backend.languages()
    assert langs[0]["id"] == "system"
    assert {x["id"] for x in langs[1:]} == shipped
    assert dict((x["id"], x["name"]) for x in langs)["de"] == "Deutsch"


def test_ring_rules_match_the_overlay():
    import overlay_actions
    import overlay_constants as oc
    for radial in ({}, {"outer_radius": 180}, {"icon_scale": 1.2}, {"auto_fit": True, "outer_radius": 1},
                   {"auto_fit": False}):
        assert bk.resolve_auto_fit(radial) == overlay_actions.resolve_auto_fit(radial)
    assert (bk.RING_SCALE_REFERENCE_HEIGHT, bk.RING_SCALE_MIN, bk.RING_SCALE_MAX) == \
        (oc.RING_SCALE_REFERENCE_HEIGHT, oc.RING_SCALE_MIN, oc.RING_SCALE_MAX)
    assert (bk.ICON_SCALE_MIN, bk.ICON_SCALE_MAX) == (overlay_actions.ICON_SCALE_MIN, overlay_actions.ICON_SCALE_MAX)


def test_icon_size_and_automatic(backend):
    g = backend.ringGeometry()
    assert g["auto"] is True and g["icon"] == 1.0 and not g["custom"]
    backend.setIconScale(9)
    g = backend.ringGeometry()
    assert g["icon"] == bk.ICON_SCALE_MAX and g["auto"] is False and g["custom"]
    backend.setAutoFit(True)
    assert backend.ringGeometry()["auto"] is True
    assert backend.get("radial.icon_scale") == bk.ICON_SCALE_MAX   # kept for later
    backend.resetRingGeometry()
    assert backend.get("radial.icon_scale") is None
    assert backend.screenRingScale(1080) == pytest.approx(0.8)
    assert backend.screenRingScale(2160) == pytest.approx(1.5)


def test_restore_defaults_keeps_a_copy_and_undo_brings_it_back(backend):
    backend.setLocal("radial.minimal_mode", True)
    assert backend.restoreDefaults() is True
    assert backend.get("radial.minimal_mode") is False
    assert backend.undoRestoreDefaults() is True
    assert backend.get("radial.minimal_mode") is True


def test_import_preview_reads_the_zip_without_changing_anything(backend, tmp_path):
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("manifest.json", json.dumps({"created": "2026-09-23"}))
        f.writestr("config.json", "{}")
        f.writestr("macros/a.json", "{}")
        f.writestr("macros/b.json", "{}")
    info = backend.inspectBackup(str(z))
    assert info["ok"] and info["config"] and info["macros"] == 2 and info["created"] == "2026-09-23"
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as f:
        f.writestr("hello.txt", "x")
    assert backend.inspectBackup(str(junk))["ok"] is False
    assert backend.inspectBackup(str(tmp_path / "missing.zip"))["error"]


def test_undo_import_restores_the_bak_files(backend):
    bk.CONFIG.write_text(json.dumps({"radial": {"minimal_mode": True}}))
    bk.CONFIG.with_name("config.json.bak").write_text(json.dumps({"radial": {"minimal_mode": False}}))
    backend._load()
    assert backend.undoImport() is True
    assert backend.get("radial.minimal_mode") is False


def test_desktop_defaults_resolve_auto_detect(backend, monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    prev = backend.deDefaultsPreview("auto")
    assert prev["desktop"] == "GNOME"
    assert any(c["to"] == "nautilus" for c in prev["changes"])
    backend.applyDeDefaults("auto")
    assert backend.deDefaultsPreview("auto")["changes"] == []   # already matches
    assert bk.detect_desktop_key({"XDG_CURRENT_DESKTOP": "KDE"}) == "kde"
    assert bk.detect_desktop_key({"XDG_CURRENT_DESKTOP": "sway"}) == "generic"


def test_autostart_health_and_repair(backend, tmp_path, monkeypatch):
    backend.setLocal("app.start_at_login", True)
    assert backend.autostartStatus()["ok"] is False          # missing entry
    launcher = tmp_path / "juhradial-mx"
    launcher.write_text("#!/bin/sh\n")
    monkeypatch.setattr(bk.Backend, "_find_launcher", classmethod(lambda cls: str(launcher)))
    backend.repairAutostart()
    assert backend.autostartStatus()["ok"] is True
    launcher.unlink()
    assert backend.autostartStatus()["ok"] is False          # points at a gone program


def test_update_version_compare(backend):
    assert bk.version_tuple("v0.4.6") > bk.version_tuple("0.4.5")
    assert bk.version_tuple("0.4.5-rc1") == (0, 4, 5)
    assert bk.version_tuple("junk") == ()
    backend._update = {"latest": "v99.0.0", "checked": 1}
    assert backend.updateAvailable and backend.latestVersion == "99.0.0"
    backend._update = {"latest": "v0.0.1", "checked": 1}
    assert not backend.updateAvailable


def test_update_check_respects_the_setting(backend):
    backend.setLocal("app.check_updates", False)
    backend.checkForUpdates(False)
    assert backend._net is None                               # no request made


def test_links_point_at_the_project(backend):
    links = backend.links
    assert links["repo"] == "https://github.com/JuhLabs/juhradial-mx"
    assert links["docs"].startswith("https://juhlabs.github.io/juhradial-mx/")
