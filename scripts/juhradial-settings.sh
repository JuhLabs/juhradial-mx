#!/bin/bash
#
# JuhRadial MX Settings Launcher
# https://github.com/JuhLabs/juhradial-mx
#
# Prefers the Qt/QML settings app when it is installed and this Qt can run it
# (6.4 or newer with the QML modules its window is built from: settings-qt's
# bridge/compat.py answers that); otherwise starts the GTK settings app, which
# needs libadwaita 1.4. Both read and write the same config.json. Set
# JUHRADIAL_SETTINGS=gtk to force GTK.

here="$(cd "$(dirname "$0")" && pwd)"
# install.sh --user puts the app under the user's data dir (#138).
user_share="${XDG_DATA_HOME:-$HOME/.local/share}/juhradial"

adw_ok() {
    python3 - <<'PY' 2>/dev/null
import sys
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw
sys.exit(0 if (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 4) else 1)
PY
}

# --keypad-template [name]: ready MX Keypad pages without a Settings window.
# The templates and key images need PyQt6's QtGui and QtSvg only, so this runs
# ahead of the Qt version check and works where the GTK app is the fallback.
if [ "${1:-}" = "--keypad-template" ]; then
    shift
    for keypad_cli in /usr/share/juhradial/settings-qt/bridge/keypad_cli.py "$user_share/settings-qt/bridge/keypad_cli.py" "$here/settings-qt/bridge/keypad_cli.py" "$here/../settings-qt/bridge/keypad_cli.py"; do
        if [ -f "$keypad_cli" ]; then
            exec python3 "$keypad_cli" "$@"
        fi
    done
    echo "Error: the keypad template tool was not found (settings-qt/bridge/keypad_cli.py)"
    echo "Please run the installer or launch from the project directory"
    exit 1
fi

if [ "${JUHRADIAL_SETTINGS:-}" != "gtk" ]; then
    for qt_dir in /usr/share/juhradial/settings-qt "$user_share/settings-qt" "$here/settings-qt" "$here/../settings-qt"; do
        [ -f "$qt_dir/main.py" ] || continue
        # Exit 0: this Qt runs the app. A part that is merely missing gets a
        # stand-in; the report names the package, so say it once on the way in.
        if qt_report="$(python3 "$qt_dir/bridge/compat.py" 2>/dev/null)"; then
            case "$qt_report" in *missing*) printf '%s\n' "$qt_report" >&2 ;; esac
            exec python3 "$qt_dir/main.py" "$@"
        fi
        if [ -n "$qt_report" ]; then
            printf 'The Qt settings app cannot start, opening the GTK one:\n%s\n' "$qt_report" >&2
        fi
        break
    done
fi

# GTK settings app: installed location first, then the local development tree
if ! adw_ok; then
    echo "Error: JuhRadial MX Settings needs either Qt 6.4 or newer (PyQt6 with QtQml and QtQuick)"
    echo "or GTK 4 with libadwaita 1.4 or newer. This system has neither."
    echo "The radial menu and the daemon keep working; edit ~/.config/juhradial/config.json by hand"
    echo "or install PyQt6 with its QML modules from your distribution."
    exit 1
fi
if [ -f /usr/share/juhradial/settings_dashboard.py ]; then
    exec python3 /usr/share/juhradial/settings_dashboard.py "$@"
elif [ -f "$user_share/settings_dashboard.py" ]; then
    exec python3 "$user_share/settings_dashboard.py" "$@"
elif [ -f "$here/overlay/settings_dashboard.py" ]; then
    exec python3 "$here/overlay/settings_dashboard.py" "$@"
elif [ -f "$here/../overlay/settings_dashboard.py" ]; then
    exec python3 "$here/../overlay/settings_dashboard.py" "$@"
else
    echo "Error: no settings app found (settings-qt/main.py or settings_dashboard.py)"
    echo "Please run the installer or launch from the project directory"
    exit 1
fi
