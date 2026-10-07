"""Ready MX Keypad pages from a terminal.

The Settings app needs Qt 6.4 and its QML modules. The keypad templates and
the key images need QtGui and QtSvg only, so where the GTK Settings fallback
opens instead (Ubuntu 22.04, or no QML packages) a keypad still gets pages:

    juhradial-settings --keypad-template            list the templates
    juhradial-settings --keypad-template everyday   add that page
"""
import os
import pathlib
import sys

# No window is shown, so this also runs on a console and over SSH.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtDBus import QDBusConnection  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402

# Owned by the Settings window, Qt or GTK, while it is open.
SETTINGS_SERVICE = "org.kde.juhradialmx.settings"


def main(argv):
    _ = QGuiApplication(argv[:1])  # fonts and images need one; _ keeps it alive for the whole run
    from bridge.backend import Backend

    backend = Backend()
    templates = backend.keypadTemplates()
    listing = "\n".join(f"  {t['id']:<10} {t['name']}: {t['description']}" for t in templates)
    if len(argv) < 2:
        print(f"MX Keypad templates:\n{listing}\nAdd one with: juhradial-settings --keypad-template <name>")
        return 0
    template = next((t for t in templates if t["id"] == argv[1].lower()), None)
    if template is None:
        print(f"No template is called {argv[1]!r}. The templates are:\n{listing}", file=sys.stderr)
        return 2
    bus = QDBusConnection.sessionBus()
    if bus.isConnected() and bus.interface().isServiceRegistered(SETTINGS_SERVICE).value():
        # Its copy of the configuration predates the page and would be saved over it.
        print("Close the JuhRadial MX Settings window first, then run this again.", file=sys.stderr)
        return 1
    if any(page.get("name") == template["name"] for page in backend.keypadPages):
        print(f"The keypad already has a page called {template['name']!r}.")
        return 0

    backend.toastRequested.connect(
        lambda text, kind: print(text, file=sys.stderr if kind == "danger" else sys.stdout))
    if not backend.applyKeypadTemplate(template["id"]):
        return 1
    # The backend tells the daemon through the event loop, which never runs
    # here. A reload re-applies the mouse's diverts, which is slow while it sleeps.
    backend.daemon.TIMEOUT_MS = 10000
    if not backend.daemon.available:
        print("JuhRadial MX is not running. The keypad shows the page once it is started.")
    elif backend.daemon.call("ReloadConfig") is None:
        print("The page is saved, but the service could not reload it. Restart it with: "
              "systemctl --user restart juhradialmx-daemon", file=sys.stderr)
    else:
        backend.daemon.call("RefreshKeypadPlates")
        status = backend.daemon.call("GetKeypadStatus")
        if status and status[0]:
            print("The keypad shows it now.")
        else:
            print("No MX Keypad is connected right now. It shows the page once one is.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
