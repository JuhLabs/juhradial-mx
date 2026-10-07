"""juhradial-mx from a terminal or a script.

    juhradial-mx status [--json]     the mouse, its battery, DPI and computer slot
    juhradial-mx doctor              what is wrong with this install, and the fix
    juhradial-mx dpi [VALUE]         read or set the pointer speed
    juhradial-mx host NUMBER         send the mouse to another Easy-Switch computer
    juhradial-mx keypad-page NUMBER  show an MX Keypad page
    juhradial-mx reload              have the service read config.json again

It talks to the running service over the D-Bus interface Settings uses, opens
no window and needs no display, so it works over SSH and in scripts.
"""
import grp
import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

SERVICE = "juhradialmx-daemon"
RULES = "99-juhradialmx.rules"
RULES_DIRS = ("/etc/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d")
LOGITECH = "046D"
COMMANDS = ("status", "doctor", "dpi", "host", "keypad-page", "reload")


def app_version():
    try:
        return (HERE.parent / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---- status ----------------------------------------------------------------

def as_int(value):
    """A D-Bus number as an int: QtDBus hands a byte (`y`) over as bytes."""
    if isinstance(value, (bytes, bytearray)):
        return value[0] if value else None
    return None if value is None else int(value)


def read_status(daemon):
    """What the service reports, as plain values; None where it has no answer."""
    def one(method, index=0):
        reply = daemon.call(method)
        return reply[index] if reply and len(reply) > index else None

    battery = daemon.call("GetBatteryStatus") or [None, None]
    link = daemon.call("GetDeviceConnection") or [None, None]
    hosts = [as_int(v) for v in daemon.call("GetEasySwitchInfo") or [None, None]]
    keypad = daemon.call("GetKeypadStatus") or [False, "", 0, 0]
    connected = link[0] == "connected"
    return {
        "device": one("GetDeviceName"),
        "mode": one("GetDeviceMode"),
        "link": link[0],
        "transport": link[1],
        # A mouse that is asleep or away answers nothing: the service's last
        # values would read as "0 %" and "DPI 0".
        "battery": as_int(battery[0]) if connected else None,
        "charging": bool(battery[1]) if connected else None,
        "dpi": (as_int(one("GetDpi")) or None) if connected else None,
        # Slots are numbered from 1, as on the mouse and in Settings.
        "host": hosts[1] + 1 if connected and hosts[1] is not None and hosts[0] else None,
        "hosts": hosts[0] or None,
        "gaming": bool(one("GetGamingMode")),
        "keypad": {"name": keypad[1], "page": as_int(keypad[2]) + 1} if keypad[0] else None,
    }


def format_status(status):
    def shown(value, suffix=""):
        return "unknown" if value is None else f"{value}{suffix}"

    lines = [f"Device      {shown(status['device'])} ({shown(status['mode'])} mode)",
             f"Link        {shown(status['link'])}" + (f" via {status['transport']}" if status["transport"] else "")]
    if status["battery"] is not None:
        lines.append(f"Battery     {status['battery']}%" + (", charging" if status["charging"] else ""))
    if status["dpi"]:
        lines.append(f"DPI         {status['dpi']}")
    if status["host"] is not None:
        lines.append(f"Computer    {status['host']} of {shown(status['hosts'])}")
    if status["gaming"]:
        lines.append("Gaming mode on")
    keypad = status["keypad"]
    lines.append(f"MX Keypad   {keypad['name']}, page {keypad['page']}" if keypad else "MX Keypad   not connected")
    return "\n".join(lines)


# ---- doctor ----------------------------------------------------------------

def logitech_hidraw_nodes(sysfs="/sys/class/hidraw", dev="/dev"):
    """[(node path, device name)] of the hidraw nodes of Logitech devices."""
    nodes = []
    try:
        entries = sorted(os.listdir(sysfs))
    except OSError:
        return nodes
    for entry in entries:
        try:
            uevent = pathlib.Path(sysfs, entry, "device", "uevent").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        parts = fields.get("HID_ID", "").split(":")
        if len(parts) == 3 and parts[1].upper().endswith(LOGITECH):
            nodes.append((os.path.join(dev, entry), fields.get("HID_NAME", "Logitech device")))
    return nodes


def in_group(name, user_groups):
    """(member in the group database, active in this login session)."""
    try:
        group = grp.getgrnam(name)
    except KeyError:
        return False, False
    listed = os.environ.get("USER", "") in group.gr_mem
    return listed, group.gr_gid in user_groups


def doctor(daemon, probe=None):
    """[(level, text, fix)] with level "ok", "warn" or "fail"."""
    probe = probe or Probe()
    out = []

    def add(level, text, fix=""):
        out.append((level, text, fix))

    # The service and what it is talking to.
    if daemon.available:
        version = probe.daemon_version()
        if version and app_version() and version != app_version():
            add("fail", f"The service is {version} and the app files are {app_version()}",
                "run the installer again so they match, then: systemctl --user restart " + SERVICE)
        else:
            add("ok", f"The service is running ({version or 'version unknown'})")
        status = read_status(daemon)
        if status["link"] == "connected":
            add("ok", f"{status['device']} is connected via {status['transport'] or 'unknown'}")
        elif status["mode"] == "generic":
            add("ok", "Generic mouse mode")
        else:
            add("warn", f"No mouse answers right now (link: {status['link'] or 'unknown'})",
                "move or switch on the mouse; if it stays like this, check the lines about hidraw below")
        if status["keypad"]:
            add("ok", f"{status['keypad']['name']} is connected")
    else:
        add("fail", "The background service is not running",
            f"systemctl --user enable --now {SERVICE}   (its log: journalctl --user -u {SERVICE} -n 50)")
    if not probe.overlay_running():
        add("fail", "The radial menu (overlay) is not running", "start it with: juhradial-mx")

    # Permissions: the device nodes belong to the input group.
    listed, active = in_group("input", probe.groups())
    if active:
        add("ok", "This session is in the input group")
    elif listed:
        add("fail", "You are in the input group, but this login session predates that", "log out and back in")
    else:
        add("fail", "Your user is not in the input group", "sudo usermod -aG input $USER, then log out and back in")
    nodes = probe.hidraw_nodes()
    blocked = [(node, name) for node, name in nodes if not probe.can_open(node)]
    if not nodes:
        add("warn", "No Logitech device is plugged in or paired right now")
    for node, name in blocked:
        add("fail", f"{node} ({name}) cannot be opened",
            "check the input group above" if not active else f"its udev rule is missing or old: install {RULES}, then replug the device")
    if nodes and not blocked:
        add("ok", f"{len(nodes)} Logitech device node(s) can be opened")
    if not probe.rules_installed():
        add("warn", f"{RULES} is not installed", "run the installer again, or copy packaging/udev/" + RULES + " to /etc/udev/rules.d")
    if not probe.can_open("/dev/uinput"):
        add("warn", "/dev/uinput cannot be opened: remapped buttons and typed shortcuts will not work",
            "sudo modprobe uinput, and check the input group above")

    # The desktop session.
    session = probe.env("XDG_SESSION_TYPE") or "unknown"
    desktop = probe.env("XDG_CURRENT_DESKTOP") or "unknown"
    add("ok", f"Session: {desktop} on {session}")
    if session == "wayland" and not probe.which("ydotool"):
        add("warn", "ydotool is not installed: shortcuts cannot be typed into native Wayland windows",
            "install the ydotool package")
    if "GNOME" in desktop.upper() and session == "wayland" and not probe.gnome_helper_enabled():
        add("fail", "The GNOME cursor helper extension is not enabled: the menu opens in a corner",
            "gnome-extensions enable juhradial-cursor@dev.juhlabs.com, then log out and back in")

    # The Settings app: compat.py's report, one line here.
    report = probe.qt_report()
    if report:
        missing = [line.split()[1].rstrip(":") for line in report if line.startswith("missing")]
        fix = next((line[4:].strip() for line in report if line.startswith("fix:")), "")
        if "needs Qt" in report[0]:
            add("warn", report[0] + " (the GTK Settings window opens instead)")
        elif missing:
            add("warn", f"Settings on {report[0]} draws stand-ins for: {', '.join(missing)}", fix)
        else:
            add("ok", f"Settings runs on {report[0]}")
    return out


def format_doctor(checks):
    label = {"ok": "ok   ", "warn": "WARN ", "fail": "FAIL "}
    lines = []
    for level, text, fix in checks:
        lines.append(f"{label[level]} {text}")
        if fix:
            lines.append(f"      fix: {fix}")
    failed = sum(1 for level, _text, _fix in checks if level == "fail")
    warned = sum(1 for level, _text, _fix in checks if level == "warn")
    lines.append("")
    lines.append("Everything needed is in place." if not failed and not warned
                 else f"{failed} problem(s), {warned} warning(s).")
    return "\n".join(lines)


class Probe:
    """The machine as doctor() sees it; tests hand in their own."""

    def __init__(self, bus=None):
        self._bus = bus

    def env(self, name):
        return os.environ.get(name, "")

    def groups(self):
        return os.getgroups()

    def which(self, program):
        return shutil.which(program)

    def can_open(self, path):
        return os.access(path, os.R_OK | os.W_OK)

    def hidraw_nodes(self):
        return logitech_hidraw_nodes()

    def rules_installed(self):
        return any(os.path.isfile(os.path.join(d, RULES)) for d in RULES_DIRS)

    def overlay_running(self):
        try:
            return subprocess.run(["pgrep", "-f", "[j]uhradial-overlay.py"], capture_output=True, timeout=3).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return True  # cannot tell: say nothing

    def gnome_helper_enabled(self):
        try:
            result = subprocess.run(["gnome-extensions", "info", "juhradial-cursor@dev.juhlabs.com"],
                                    capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return True  # cannot tell: say nothing
        return any(state in result.stdout for state in ("ENABLED", "ACTIVE"))

    def daemon_version(self):
        from PyQt6.QtDBus import QDBus, QDBusMessage
        if self._bus is None:
            return ""
        message = QDBusMessage.createMethodCall("org.kde.juhradialmx", "/org/kde/juhradialmx/Daemon",
                                                "org.freedesktop.DBus.Properties", "Get")
        message.setArguments(["org.kde.juhradialmx.Daemon", "DaemonVersion"])
        reply = self._bus.call(message, QDBus.CallMode.Block, 2000)
        args = reply.arguments()
        return str(args[0]) if reply.type() == QDBusMessage.MessageType.ReplyMessage and args else ""

    def qt_report(self):
        """compat.py's lines for this Qt, in its own process: it needs no
        display, and a QML engine has no place in this one."""
        try:
            result = subprocess.run([sys.executable, str(HERE / "compat.py")], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# ---- commands --------------------------------------------------------------

def number(text, what, low, high):
    try:
        value = int(text)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        raise SystemExit(f"{what} must be a number from {low} to {high}, not {text!r}")
    return value


def run(argv, daemon, probe=None, out=print):
    """Run one command; returns the exit status."""
    from bridge.backend import _u8, _u16

    command, args = argv[0], argv[1:]
    if command == "doctor":
        checks = doctor(daemon, probe)
        out(format_doctor(checks))
        return 1 if any(level == "fail" for level, _text, _fix in checks) else 0
    if not daemon.available:
        out(f"JuhRadial MX is not running. Start it with: systemctl --user start {SERVICE}")
        return 1

    if command == "status":
        status = read_status(daemon)
        out(json.dumps(status, indent=2) if "--json" in args else format_status(status))
    elif command == "dpi":
        if not args:
            dpi = as_int((daemon.call("GetDpi") or [0])[0])
            out(str(dpi) if dpi else "The mouse did not answer (asleep, or on another computer).")
            return 0 if dpi else 1
        low, high, step, _default = (as_int(v) for v in daemon.call("GetDpiRange") or (0, 0, 0, 0))
        if high <= low:  # the mouse has not reported its range yet
            low, high, step = 200, 8000, 50
        dpi = number(args[0], "DPI", low, high)
        dpi = low + round((dpi - low) / step) * step if step else dpi
        if daemon.call("SetDpi", _u16(dpi)) is None:
            out("The mouse did not take the new DPI.")
            return 1
        out(f"DPI {dpi}")
    elif command == "host":
        hosts = as_int((daemon.call("GetEasySwitchInfo") or [3])[0]) or 3
        slot = number(args[0] if args else "", "The computer", 1, hosts)
        reply = daemon.call("SetHost", _u8(slot - 1))
        if not reply or not reply[0]:
            out("The mouse did not switch.")
            return 1
        out(f"The mouse is moving to computer {slot}. Its Easy-Switch button brings it back.")
    elif command == "keypad-page":
        page = number(args[0] if args else "", "The page", 1, 255)
        if daemon.call("SetKeypadPage", _u8(page - 1)) is None:
            out("The keypad has no such page, or is not connected.")
            return 1
        out(f"MX Keypad page {page}")
    elif command == "reload":
        daemon.TIMEOUT_MS = 10000  # re-applying the diverts waits for a sleeping mouse
        if daemon.call("ReloadConfig") is None:
            out("The service did not reload. Its log: journalctl --user -u " + SERVICE + " -n 30")
            return 1
        out("Configuration reloaded")
    return 0


def main(argv):
    if not argv or argv[0] in ("help", "--help", "-h") or argv[0] not in COMMANDS:
        print(__doc__.strip())
        return 0 if argv and argv[0] in ("help", "--help", "-h") else 2
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtDBus import QDBusConnection

    _ = QCoreApplication(sys.argv[:1])  # _ keeps it alive for the bus connection
    from bridge.backend import Daemon

    return run(argv, Daemon(), Probe(QDBusConnection.sessionBus()))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
