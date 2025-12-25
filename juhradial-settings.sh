#!/bin/bash
#
# JuhRadial MX Settings Launcher
# https://github.com/JuhLabs/juhradial-mx
#

# Try installed location first, then fall back to local development
if [ -f /usr/share/juhradial/settings_dashboard.py ]; then
    exec python3 /usr/share/juhradial/settings_dashboard.py "$@"
elif [ -f "$(dirname "$0")/overlay/settings_dashboard.py" ]; then
    exec python3 "$(dirname "$0")/overlay/settings_dashboard.py" "$@"
else
    echo "Error: settings_dashboard.py not found"
    echo "Please run the installer or launch from the project directory"
    exit 1
fi
