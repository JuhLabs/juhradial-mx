#!/usr/bin/env python3
"""Settings → Backup runs `juhradiald --export / --import` and reloads itself.

The archive format and its validation live in the daemon (daemon/src/backup.rs,
covered by cargo test). These tests pin the app side: which binary is run with
which arguments, how a url from the QML FileDialog becomes a path, the toast on
success and failure, and that a successful import re-reads config.json and
tells the shell to rebuild the visible page.

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_backup.py -q
"""

import json
import os
import stat
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None

import bridge.backend as bk  # noqa: E402


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    return bk.Backend()


@pytest.fixture
def fake_daemon(tmp_path, monkeypatch):
    """A stand-in juhradiald that records its arguments. `--export` creates
    the target; `--import` rewrites config.json the way a real import would;
    `--import` of a path containing "bad" fails like a rejected archive."""
    script = tmp_path / "juhradiald"
    log = tmp_path / "args.log"
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$1\" \"$2\" > '{log}'\n"
        "case \"$1\" in\n"
        "  --export) : > \"$2\"; echo \"Exported 3 file(s)\";;\n"
        "  --import)\n"
        "    case \"$2\" in *bad*) echo 'Import failed: not a JuhRadial backup: no manifest.json' >&2; exit 1;; esac\n"
        f"    printf '{{\"scroll\": {{\"mode\": \"freespin\"}}}}' > '{tmp_path / 'config.json'}'\n"
        "    echo 'Imported 2 file(s)';;\n"
        "esac\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(bk.Backend, "_daemon_binary", staticmethod(lambda: str(script)))
    return log


def _toasts(backend):
    seen = []
    backend.toastRequested.connect(lambda text, kind: seen.append((text, kind)))
    return seen


def test_daemon_binary_prefers_the_installed_daemon(monkeypatch, tmp_path):
    fake = tmp_path / "juhradiald"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(bk.shutil, "which", lambda name: str(fake))
    assert bk.Backend._daemon_binary() == str(fake)
    monkeypatch.setattr(bk.shutil, "which", lambda name: None)
    monkeypatch.setattr(bk.os.path, "isfile", lambda p: False)
    assert bk.Backend._daemon_binary() is None


def test_file_urls_become_paths():
    assert bk.Backend._local_path("file:///home/me/a b.zip") == "/home/me/a b.zip"
    assert bk.Backend._local_path("/home/me/a.zip") == "/home/me/a.zip"


def test_suggested_export_name_is_a_dated_zip_url(backend):
    url = backend.suggestedBackupUrl()
    assert url.startswith("file://")
    assert url.endswith(".zip")
    assert "/juhradial-backup-" in url


def test_export_runs_the_daemon_and_toasts_the_file_name(backend, fake_daemon, tmp_path):
    seen = _toasts(backend)
    target = tmp_path / "out" / "juhradial-backup.zip"
    target.parent.mkdir()
    assert backend.exportBackup(target.as_uri()) is True
    assert fake_daemon.read_text().split("\n")[:2] == ["--export", str(target)]
    assert target.exists()
    assert seen == [("Backup saved as juhradial-backup.zip", "success")]


def test_import_reloads_config_and_rebuilds_the_page(backend, fake_daemon, tmp_path):
    backend.setLocal("scroll.mode", "ratchet")
    seen = _toasts(backend)
    reloaded = []
    backend.configReloaded.connect(lambda: reloaded.append(True))
    changed = []
    backend.configChanged.connect(lambda: changed.append(True))
    archive = tmp_path / "juhradial-backup.zip"
    archive.write_bytes(b"PK")
    assert backend.importBackup(archive.as_uri()) is True
    assert fake_daemon.read_text().split("\n")[:2] == ["--import", str(archive)]
    assert backend.get("scroll.mode") == "freespin"
    assert json.loads((tmp_path / "config.json").read_text())["scroll"]["mode"] == "freespin"
    assert reloaded == [True] and changed == [True]
    assert seen and seen[-1][1] == "success"


def test_import_failure_shows_the_daemons_reason_and_changes_nothing(backend, fake_daemon, tmp_path):
    backend.setLocal("scroll.mode", "ratchet")
    seen = _toasts(backend)
    reloaded = []
    backend.configReloaded.connect(lambda: reloaded.append(True))
    assert backend.importBackup((tmp_path / "bad.zip").as_uri()) is False
    assert backend.get("scroll.mode") == "ratchet"
    assert reloaded == []
    assert seen == [("Import failed: Import failed: not a JuhRadial backup: no manifest.json", "danger")]


def test_missing_daemon_binary_is_reported(backend, monkeypatch):
    monkeypatch.setattr(bk.Backend, "_daemon_binary", staticmethod(lambda: None))
    seen = _toasts(backend)
    assert backend.exportBackup("/tmp/x.zip") is False
    assert seen == [("Export failed: juhradiald not found", "danger")]


def test_restore_defaults_also_rebuilds_the_page(backend):
    reloaded = []
    backend.configReloaded.connect(lambda: reloaded.append(True))
    backend.restoreDefaults()
    assert reloaded == [True]
