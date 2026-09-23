#!/bin/bash
#
# JuhRadial MX Settings Launcher
# https://github.com/JuhLabs/juhradial-mx
#
# Prefers the Qt/QML settings app when it is installed and PyQt6's QML module
# is importable (Qt >= 6.5); otherwise starts the GTK settings app. Both read
# and write the same config.json. Set JUHRADIAL_SETTINGS=gtk to force GTK.

here="$(cd "$(dirname "$0")" && pwd)"

if [ "${JUHRADIAL_SETTINGS:-}" != "gtk" ] && python3 -c 'import PyQt6.QtQml' 2>/dev/null; then
    for qt_main in /usr/share/juhradial/settings-qt/main.py "$here/settings-qt/main.py" "$here/../settings-qt/main.py"; do
        if [ -f "$qt_main" ]; then
            exec python3 "$qt_main" "$@"
        fi
    done
fi

# GTK settings app: installed location first, then the local development tree
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
