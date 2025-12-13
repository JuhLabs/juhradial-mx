#!/bin/bash
# JuhRadial MX Launcher
# Starts the daemon and overlay for the radial menu

# Find script directory (works for both installed and dev mode)
if [ -d "/opt/juhradial-mx" ]; then
    SCRIPT_DIR="/opt/juhradial-mx"
elif [ -d "/usr/share/juhradial" ]; then
    SCRIPT_DIR="/usr/share/juhradial"
else
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# Kill any existing instances
pkill -f "juhradiald" 2>/dev/null
pkill -f "juhradial-overlay" 2>/dev/null
sleep 0.3

# Start the overlay first (it listens for D-Bus signals)
if [ -f "$SCRIPT_DIR/overlay/juhradial-overlay.py" ]; then
    python3 "$SCRIPT_DIR/overlay/juhradial-overlay.py" &
elif [ -f "$SCRIPT_DIR/juhradial-overlay.py" ]; then
    python3 "$SCRIPT_DIR/juhradial-overlay.py" &
fi
OVERLAY_PID=$!

# Start the daemon
if [ -x "/usr/local/bin/juhradiald" ]; then
    /usr/local/bin/juhradiald &
elif [ -x "/usr/bin/juhradiald" ]; then
    /usr/bin/juhradiald &
elif [ -x "$SCRIPT_DIR/daemon/target/release/juhradiald" ]; then
    "$SCRIPT_DIR/daemon/target/release/juhradiald" &
fi
DAEMON_PID=$!

echo "JuhRadial MX started"
echo "  Overlay PID: $OVERLAY_PID"
echo "  Daemon PID: $DAEMON_PID"

# Keep running
wait $DAEMON_PID
