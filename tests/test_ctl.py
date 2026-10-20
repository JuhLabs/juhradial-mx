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
                           which=True, nodes=[("/dev/hidraw3", "Logitech MX Master 4")], blocked=set(),
                           rules={ctl.RULES, ctl.UACCESS_RULES}, overlay=True, gnome="active",
                           hypr=("lua", ["/home/tester/.config/hypr/hyprland.lua"], False), hypr_version=(0, 56), version=ctl.app_version(), qt=["Qt 6.11.2", "ok  effects: QtQuick.Effects"])
        self.values.update(over)

    def env(self, name): return self.values["env"].get(name, "")
    def groups(self): return self.values["groups"]
    def which(self, program): return "/usr/bin/" + program if self.values["which"] else None
    def can_open(self, path): return path not in self.values["blocked"]
    def hidraw_nodes(self): return self.values["nodes"]
    def rules_installed(self, name=ctl.RULES): return name in self.values["rules"]
    def overlay_running(self): return self.values["overlay"]
    def gnome_helper_state(self): return self.values["gnome"]
    def hyprland_rules(self): return self.values["hypr"]
    def hyprland_version(self): return self.values["hypr_version"]
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
                      gnome="not loaded", which=False, rules=set())
    status, text = run(["doctor"], probe=probe)
    assert status == 1
    assert "GNOME Shell has not loaded it" in text and "log out and back in once" in text
    assert "WARN  ydotool is not installed" in text
    assert "WARN  99-juhradialmx.rules is not installed" in text
    assert "WARN  70-juhradialmx-uaccess.rules is not installed" in text


def test_doctor_accepts_uaccess_access_before_the_next_login():
    # 70-juhradialmx-uaccess.rules: the devices open although the session
    # predates the input group; only macro recording and generic mice wait.
    status, text = run(["doctor"], probe=FakeProbe(groups=[1000]))
    assert status == 0, text
    assert "WARN  The MX devices work through this login's device access" in text
    assert "log out and back in" in text


@pytest.mark.parametrize("info, on_disk, state", [
    ("  Description: JuhRadial MX: cursor position\n  Enabled: Yes\n  State: ACTIVE\n", True, "active"),
    ("  State: ENABLED\n", True, "active"),
    ("  Enabled: Yes\n  State: INITIALIZED\n", True, "not loaded"),
    ("  Enabled: No\n  State: INACTIVE\n", True, "off"),
    ("  Enabled: Yes\n  State: OUT OF DATE\n", True, "out of date"),
    ("  Enabled: Yes\n  State: ERROR\n", True, "error"),
    ("", True, "not loaded"),
    ("", False, "missing"),
])
def test_gnome_helper_state_reads_gnome_extensions_info(info, on_disk, state):
    assert ctl.gnome_helper_state(info, on_disk) == state


@pytest.mark.parametrize("state, fix", [
    ("missing", "run the installer again"),
    ("off", "gnome-extensions enable juhradial-cursor@dev.juhlabs.com"),
    ("out of date", "update JuhRadial MX"),
    ("error", "journalctl --user -b -g juhradial-cursor@dev.juhlabs.com"),
])
def test_doctor_names_the_fix_for_each_gnome_helper_state(state, fix):
    probe = FakeProbe(env={"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"}, gnome=state)
    status, text = run(["doctor"], probe=probe)
    assert status == 1 and fix in text


def test_hyprland_rules_follow_the_config_hyprland_loads(tmp_path):
    hypr = tmp_path / "hypr"
    (hypr / "modules").mkdir(parents=True)
    (hypr / "hyprland.lua").write_text('require("modules.rules")\n')
    (hypr / "juhradial-rules.conf").write_text("windowrulev2 = float, title:^(JuhRadial MX)$\n")
    # A stale .conf does not count for a Lua config (issue #179).
    assert ctl.hyprland_rules(hypr) == ("lua", [], True)
    (hypr / "modules" / "rules.lua").write_text('hl.window_rule({ match = { class = "^(JuhRadial MX)$" } })\n')
    (hypr / "modules" / "loop").symlink_to(hypr)
    assert ctl.hyprland_rules(hypr) == ("lua", [str(hypr / "modules" / "rules.lua")], True)
    (hypr / "hyprland.lua").unlink()
    (hypr / "hyprland.conf").write_text("source = juhradial-rules.conf\n")
    assert ctl.hyprland_rules(hypr) == ("conf", [str(hypr / "juhradial-rules.conf")], True)
    assert ctl.hyprland_rules(tmp_path / "none") == (None, [], False)


def test_hyprland_version_reads_the_tag():
    assert ctl.hyprland_version('{\n    "version": "0.56.2",\n    "tag": "v0.56.2",\n}') == (0, 56)
    assert ctl.hyprland_version("") is None


def test_doctor_checks_the_hyprland_window_rules():
    env = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "Hyprland", "HYPRLAND_INSTANCE_SIGNATURE": "x"}
    status, text = run(["doctor"], probe=FakeProbe(env=env))
    assert status == 0 and "ok    Hyprland window rules for the menu are in" in text
    status, text = run(["doctor"], probe=FakeProbe(env=env, hypr=("lua", [], False)))
    assert status == 1 and "No window rules for the menu in hyprland.lua" in text
    status, text = run(["doctor"], probe=FakeProbe(env=env, hypr=("conf", ["/h/hyprland.conf"], True)))
    assert status == 1 and "Hyprland 0.56 rejects the old windowrulev2 rules" in text
    # Before 0.53 windowrulev2 is the right syntax.
    status, text = run(["doctor"], probe=FakeProbe(env=env, hypr=("conf", ["/h/hyprland.conf"], True), hypr_version=(0, 52)))
    assert status == 0, text


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
