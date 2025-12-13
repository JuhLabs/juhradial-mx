#!/bin/bash
# JuhRadial MX Launcher
# Starts the daemon and overlay for the radial menu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Kill any existing instances
pkill -f "juhradiald" 2>/dev/null
pkill -f "juhradial-overlay" 2>/dev/null
sleep 0.5

# Start the overlay
cd "$SCRIPT_DIR/overlay"
python3 juhradial-overlay.py > /tmp/overlay.log 2>&1 &
OVERLAY_PID=$!

# Start the daemon
cd "$SCRIPT_DIR/daemon"
./target/release/juhradiald &
DAEMON_PID=$!

echo "JuhRadial MX started"
echo "  Overlay PID: $OVERLAY_PID"
echo "  Daemon PID: $DAEMON_PID"

# Keep running (for desktop launcher)
wait $DAEMON_PID
