#!/bin/bash
# Launcher for cursor_grabber.py with proper gtk4-layer-shell linking
#
# The gtk4-layer-shell library MUST be loaded before libwayland-client
# This is achieved via LD_PRELOAD

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find gtk4-layer-shell library (check versioned paths too)
LAYER_SHELL_LIB=""
for path in /usr/lib64/libgtk4-layer-shell.so.1.0.3 /usr/lib64/libgtk4-layer-shell.so.0 /usr/lib64/libgtk4-layer-shell.so /usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so /usr/lib/libgtk4-layer-shell.so; do
    if [[ -f "$path" ]]; then
        LAYER_SHELL_LIB="$path"
        break
    fi
done

if [[ -z "$LAYER_SHELL_LIB" ]]; then
    echo "ERROR: Could not find libgtk4-layer-shell.so"
    echo "Install with: sudo dnf install gtk4-layer-shell"
    exit 1
fi

# Force Wayland backend
export GDK_BACKEND=wayland

# Preload gtk4-layer-shell before libwayland-client
export LD_PRELOAD="$LAYER_SHELL_LIB"

echo "Starting cursor_grabber with LD_PRELOAD=$LAYER_SHELL_LIB"
exec python3 "$SCRIPT_DIR/cursor_grabber.py" "$@"
