#!/usr/bin/env python3
"""Flow tab: the settings app's view of the running Flow server (connected
and waiting computers, approvals written in the format the overlay's bridge
reads), the port and firewall checks, and the overlay applying the Flow
switch live instead of at the next login (P0 #11).

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_flow_backend.py -q
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtDBus")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(REPO_ROOT / "settings-qt"))
sys.path.insert(0, os.fspath(REPO_ROOT / "overlay"))

from PyQt6.QtGui import QGuiApplication  # noqa: E402

_qt_app = QGuiApplication.instance() or QGuiApplication([])
assert _qt_app is not None

import bridge.backend as bk  # noqa: E402
from flow.trust import DENIED, PENDING, TRUSTED, TrustStore  # noqa: E402

flow_pkg = sys.modules["flow"]


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setattr(bk, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bk, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(bk, "PROFILES", tmp_path / "profiles.json")
    monkeypatch.setattr(bk, "AUTOSTART", tmp_path / "autostart" / "juhradial-mx.desktop")
    monkeypatch.setattr(bk.Backend, "_installed_launcher", staticmethod(lambda: None))
    return bk.Backend()


def _status(tmp_path, peers, age=0):
    (tmp_path / "flow_status.json").write_text(
        json.dumps({"peers": peers, "updated_at": time.time() - age}))


MAC = {"id": "a", "hostname": "MacBook-Pro", "platform": "macos", "ip": "192.168.1.44",
       "connected_at": 1, "fingerprint": "9F3A 11C2 7B40 E5D8", "state": "pending"}


def test_status_lists_waiting_and_approved_computers(backend, tmp_path):
    _status(tmp_path, [MAC, {"id": "p", "hostname": "office-mac", "platform": "unknown",
                             "ip": "", "connected_at": 0}])
    st = backend.flowStatus()
    assert [p["state"] for p in st["peers"]] == ["pending", "trusted"], "Options+ peers count as approved"
    backend.approveFlowPeer(MAC["fingerprint"], MAC["hostname"], MAC["platform"])
    st = backend.flowStatus()
    assert st["trusted"] == [{"fingerprint": MAC["fingerprint"], "hostname": "MacBook-Pro",
                              "platform": "macos", "connected": True}]
    _status(tmp_path, [MAC], age=60)
    assert backend.flowStatus()["peers"] == [], "a stale status file means nobody is connected"


def test_approvals_are_what_the_bridge_reads(backend, tmp_path):
    store = TrustStore(tmp_path / "flow_trusted.json")
    fp = MAC["fingerprint"]
    assert store.state(fp) == PENDING
    backend.approveFlowPeer(fp, "MacBook-Pro", "macos")
    assert store.state(fp) == TRUSTED
    backend.denyFlowPeer(fp, "MacBook-Pro", "macos")
    assert store.state(fp) == DENIED
    backend.forgetFlowPeer(fp)
    assert store.state(fp) == PENDING
    assert oct((tmp_path / "flow_trusted.json").stat().st_mode & 0o777) == "0o600"


def test_listening_reads_proc_net(tmp_path):
    header = "  sl  local_address rem_address   st tx_queue rx_queue\n"
    (tmp_path / "tcp").write_text(header + "   0: 00000000:E9E0 00000000:0000 0A 00000000:00000000\n")
    (tmp_path / "tcp6").write_text(header)
    assert bk.Backend._flow_listening(proc=str(tmp_path))
    (tmp_path / "tcp").write_text(header + "   0: 0100007F:E9E0 0100007F:9C40 01 00000000:00000000\n")
    assert not bk.Backend._flow_listening(proc=str(tmp_path)), "a connection, not a listener"


def test_firewall_hint(backend, monkeypatch):
    class R:
        def __init__(self, rc=0, out=""):
            self.returncode, self.stdout = rc, out

    def run(cmd, **kw):
        if cmd[:2] == ["systemctl", "is-active"]:
            return R(0 if cmd[-1] == "firewalld" else 3)
        return R(0, "no")
    monkeypatch.setattr(bk.subprocess, "run", run)
    fw = backend.flowFirewall()
    assert fw["firewall"] == "firewalld" and fw["open"] is False
    assert "59872/tcp" in fw["command"] and "59873/udp" in fw["command"]


def test_overlay_applies_the_flow_switch_live(monkeypatch):
    calls = []
    monkeypatch.setattr(flow_pkg, "start_flow_server", lambda *a, **k: calls.append("start"))
    monkeypatch.setattr(flow_pkg, "stop_flow_server", lambda: calls.append("stop"))
    cfg = {"enabled": True}
    monkeypatch.setattr(flow_pkg, "_read_flow_config", lambda: dict(cfg))
    monkeypatch.setattr(flow_pkg, "_flow_server", None)
    flow_pkg.apply_config()
    assert calls == ["start"]

    class Detector:
        enabled = None

        def set_enabled(self, v):
            Detector.enabled = v
    monkeypatch.setattr(flow_pkg, "_flow_server", object())
    monkeypatch.setattr(flow_pkg, "_edge_detector", Detector())
    monkeypatch.setattr(flow_pkg, "update_indicator_direction", lambda d=None: calls.append(("dir", d)))
    cfg.update(edge_trigger=False, direction="left")
    flow_pkg.apply_config()
    assert Detector.enabled is False and calls[-1] == ("dir", "left")

    def stop():
        calls.append("stop")
        flow_pkg._flow_server = None
    monkeypatch.setattr(flow_pkg, "stop_flow_server", stop)
    cfg["enabled"] = False
    flow_pkg.apply_config()
    assert calls[-1] == "stop"


def test_identify_screens_refuses_without_x11_and_settings_says_why(backend, monkeypatch):
    import overlay_identify
    assert QGuiApplication.platformName() != "xcb"
    assert overlay_identify.identify_screens("", "Flow") is False, "no cards off X11 (niri layer shell)"
    assert overlay_identify._cards == []

    notes = []
    monkeypatch.setattr(backend, "notify", lambda text, kind: notes.append(text))
    for answer in (None, False, True):
        monkeypatch.setattr(backend, "_overlay_call", lambda method, *a, done=None: done(answer))
        backend.identifyScreens("Flow")
    assert len(notes) == 2 and "not running" in notes[0] and "X11" in notes[1]
