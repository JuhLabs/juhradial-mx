"""juhradial-mx status | doctor | dpi | host | keypad-page | reload.

settings-qt/bridge/ctl.py against a stand-in for the service and for the
machine: what each command asks the service, what it prints, and what doctor
concludes from groups, device nodes and the session.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtDBus")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT / "settings-qt"))

from bridge import ctl  # noqa: E402

# Replies as QtDBus delivers them: a byte (`y`) arrives as bytes.
AWAKE = {
    "GetDeviceName": ["MX Master 4"], "GetDeviceMode": ["logitech"],
    "GetDeviceConnection": ["connected", "bolt"], "GetBatteryStatus": [b"\x50", False],
    "GetDpi": [1600], "GetDpiRange": [200, 8000, 50, 1000], "GetEasySwitchInfo": [b"\x03", b"\x00"],
    "GetGamingMode": [False], "GetKeypadStatus": [True, "Logitech MX Keypad", b"\x01", b"\x03"],
    "SetDpi": [], "SetHost": [True], "SetKeypadPage": [], "ReloadConfig": [],
}


class FakeDaemon:
    TIMEOUT_MS = 2000

    def __init__(self, replies=None, available=True):
        self.replies = dict(AWAKE if replies is None else replies)
        self.available = available
        self.calls = []

    def call(self, method, *args):
        self.calls.append((method, args))
        return self.replies.get(method)


class FakeProbe:
    def __init__(self, **over):
        self.values = dict(env={"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}, groups=[1000, 104],
                           which=True, nodes=[("/dev/hidraw3", "Logitech MX Master 4")], blocked=set(), rules=True,
                           overlay=True, gnome=True, version=ctl.app_version(), qt=["Qt 6.11.2", "ok  effects: QtQuick.Effects"])
        self.values.update(over)

    def env(self, name): return self.values["env"].get(name, "")
    def groups(self): return self.values["groups"]
    def which(self, program): return "/usr/bin/" + program if self.values["which"] else None
    def can_open(self, path): return path not in self.values["blocked"]
    def hidraw_nodes(self): return self.values["nodes"]
    def rules_installed(self): return self.values["rules"]
    def overlay_running(self): return self.values["overlay"]
    def gnome_helper_enabled(self): return self.values["gnome"]
    def daemon_version(self): return self.values["version"]
    def qt_report(self): return self.values["qt"]


@pytest.fixture(autouse=True)
def _input_group(monkeypatch):
    class Group:
        gr_gid = 104
        gr_mem = ["tester"]
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setattr(ctl.grp, "getgrnam", lambda name: Group)


def run(argv, daemon=None, probe=None):
    lines = []
    status = ctl.run(argv, daemon or FakeDaemon(), probe or FakeProbe(), out=lines.append)
    return status, "\n".join(lines)


def test_status_reads_bytes_and_counts_slots_from_one():
    status, text = run(["status"])
    assert status == 0
    assert "MX Master 4 (logitech mode)" in text
    assert "connected via bolt" in text
    assert "Battery     80%" in text
    assert "DPI         1600" in text
    assert "Computer    1 of 3" in text
    assert "MX Keypad   Logitech MX Keypad, page 2" in text
    status, text = run(["status", "--json"])
    assert json.loads(text)["host"] == 1 and json.loads(text)["battery"] == 80


def test_a_mouse_that_is_away_shows_no_stale_numbers():
    replies = dict(AWAKE, GetDeviceConnection=["away", "bolt"], GetBatteryStatus=[b"\x00", False], GetDpi=[0],
                   GetEasySwitchInfo=[b"\x00", b"\x00"], GetKeypadStatus=[False, "", b"\x00", b"\x00"])
    status, text = run(["status"], FakeDaemon(replies))
    assert status == 0
    assert "Battery" not in text and "DPI" not in text and "Computer" not in text
    assert "MX Keypad   not connected" in text
    assert run(["dpi"], FakeDaemon(replies))[0] == 1


def test_dpi_snaps_to_the_mouse_step_and_is_sent_as_uint16():
    daemon = FakeDaemon()
    status, text = run(["dpi", "1234"], daemon)
    assert (status, text) == (0, "DPI 1250")
    method, args = daemon.calls[-1]
    assert method == "SetDpi" and len(args) == 1 and type(args[0]).__name__ == "QDBusArgument"
    with pytest.raises(SystemExit, match="from 200 to 8000"):
        run(["dpi", "90000"])
    with pytest.raises(SystemExit):
        run(["dpi", "fast"])


def test_host_counts_from_one_and_stays_inside_the_slots():
    daemon = FakeDaemon()
    status, text = run(["host", "2"], daemon)
    assert status == 0 and "computer 2" in text
    assert daemon.calls[-1][0] == "SetHost"
    with pytest.raises(SystemExit, match="from 1 to 3"):
        run(["host", "4"])
    with pytest.raises(SystemExit):
        run(["host"])


def test_commands_need_the_service_except_doctor():
    down = FakeDaemon(available=False)
    status, text = run(["status"], down)
    assert status == 1 and "not running" in text
    status, text = run(["doctor"], down)
    assert status == 1
    assert "FAIL  The background service is not running" in text
    assert "systemctl --user enable --now juhradialmx-daemon" in text


def test_doctor_is_quiet_about_a_healthy_install():
    status, text = run(["doctor"])
    assert status == 0, text
    assert "FAIL" not in text and "WARN" not in text
    assert "Everything needed is in place." in text


def test_doctor_names_each_problem_with_its_fix():
    # The session predates the group membership (issue #52's "log out and in").
    status, text = run(["doctor"], probe=FakeProbe(groups=[1000], blocked={"/dev/hidraw3"}))
    assert status == 1
    assert "this login session predates that" in text and "log out and back in" in text
    assert "/dev/hidraw3 (Logitech MX Master 4) cannot be opened" in text
    # A stale service after an upgrade.
    status, text = run(["doctor"], probe=FakeProbe(version="0.0.1"))
    assert status == 1 and "The service is 0.0.1" in text
    # GNOME without its cursor helper, Wayland without ydotool, missing rules.
    probe = FakeProbe(env={"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"},
                      gnome=False, which=False, rules=False)
    status, text = run(["doctor"], probe=probe)
    assert status == 1
    assert "GNOME cursor helper extension is not enabled" in text
    assert "WARN  ydotool is not installed" in text
    assert "WARN  99-juhradialmx.rules is not installed" in text


def test_doctor_passes_on_the_qt_fix_of_issue_172():
    qt = ["Qt 6.10.2", "ok       effects: QtQuick.Effects", "missing  vector: QtQuick.VectorImage",
          "missing  dialogs: QtQuick.Dialogs", "fix: sudo apt install qml6-module-qtquick-dialogs qml6-module-qtquick-vectorimage"]
    status, text = run(["doctor"], probe=FakeProbe(qt=qt))
    assert status == 0  # stand-ins are drawn: a warning, not a failure
    assert "WARN  Settings on Qt 6.10.2 draws stand-ins for: vector, dialogs" in text
    assert "fix: sudo apt install qml6-module-qtquick-dialogs qml6-module-qtquick-vectorimage" in text


def test_hidraw_nodes_are_found_by_vendor(tmp_path):
    for node, hid_id, name in (("hidraw0", "0003:0000046D:0000C548", "Logitech USB Receiver"),
                               ("hidraw1", "0003:00000C45:00006366", "Webcam"),
                               ("hidraw2", "0005:0000046D:0000B034", "MX Master 4")):
        device = tmp_path / node / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid_id}\nHID_NAME={name}\n")
    assert ctl.logitech_hidraw_nodes(os.fspath(tmp_path), "/dev") == [
        ("/dev/hidraw0", "Logitech USB Receiver"), ("/dev/hidraw2", "MX Master 4")]


def test_the_launcher_hands_the_commands_to_ctl():
    launcher = (ROOT / "scripts" / "juhradial-mx.sh").read_text(encoding="utf-8")
    for command in ctl.COMMANDS:
        assert command in launcher.split("settings-qt/bridge/ctl.py")[0].rsplit("case", 1)[1], command
    result = subprocess.run([sys.executable, os.fspath(ROOT / "settings-qt" / "bridge" / "ctl.py"), "help"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and "juhradial-mx doctor" in result.stdout
