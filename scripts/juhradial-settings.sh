#!/bin/bash
#
# JuhRadial MX Settings Launcher
# https://github.com/JuhLabs/juhradial-mx
#
# Prefers the Qt/QML settings app when it is installed and the runtime Qt is
# new enough for it (6.9: RectangularShadow, VectorImage); otherwise starts the
# GTK settings app, which needs libadwaita 1.4. Both read and write the same
# config.json. Set JUHRADIAL_SETTINGS=gtk to force GTK.

here="$(cd "$(dirname "$0")" && pwd)"

qt_ok() {
    python3 - <<'PY' 2>/dev/null
import sys
import PyQt6.QtQml  # noqa: F401
from PyQt6.QtCore import qVersion
major, minor = (int(x) for x in qVersion().split(".")[:2])
sys.exit(0 if (major, minor) >= (6, 9) else 1)
PY
}

adw_ok() {
    python3 - <<'PY' 2>/dev/null
import sys
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw
sys.exit(0 if (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 4) else 1)
PY
}

if [ "${JUHRADIAL_SETTINGS:-}" != "gtk" ] && qt_ok; then
    for qt_main in /usr/share/juhradial/settings-qt/main.py "$here/settings-qt/main.py" "$here/../settings-qt/main.py"; do
        if [ -f "$qt_main" ]; then
            exec python3 "$qt_main" "$@"
        fi
    done
fi

# GTK settings app: installed location first, then the local development tree
if ! adw_ok; then
    echo "Error: JuhRadial MX Settings needs either Qt 6.9 or newer (PyQt6 with QtQml)"
    echo "or GTK 4 with libadwaita 1.4 or newer. This system has neither."
    echo "The radial menu and the daemon keep working; edit ~/.config/juhradial/config.json by hand"
    echo "or install PyQt6 6.9 or newer from your distribution."
    exit 1
fi
if [ -f /usr/share/juhradial/settings_dashboard.py ]; then
    exec python3 /usr/share/juhradial/settings_dashboard.py "$@"
elif [ -f "$here/overlay/settings_dashboard.py" ]; then
    exec python3 "$here/overlay/settings_dashboard.py" "$@"
elif [ -f "$here/../overlay/settings_dashboard.py" ]; then
    exec python3 "$here/../overlay/settings_dashboard.py" "$@"
else
    echo "Error: no settings app found (settings-qt/main.py or settings_dashboard.py)"
    echo "Please run the installer or launch from the project directory"
    exit 1
fi
