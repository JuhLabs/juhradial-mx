#!/bin/bash
# Sync dev files to install locations and restart
# Run with: sudo bash scripts/sync-to-install.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/juhradial-mx"
SHARE_DIR="/usr/share/juhradial"

echo "=== Stopping running processes ==="
pkill -x juhradiald 2>/dev/null || true
pkill -f '[j]uhradial-overlay' 2>/dev/null || true
pkill -f '[j]uhradial-settings' 2>/dev/null || true
# The Qt settings app runs as "python3 .../settings-qt/main.py", which the
# pattern above never matches; a stale instance would keep serving the old UI.
pkill -f '[s]ettings-qt/main\.py' 2>/dev/null || true
sleep 1

echo "=== Syncing dev -> $INSTALL_DIR ==="

# Overlay Python files
cp "$DEV_DIR"/overlay/*.py "$INSTALL_DIR/overlay/"

# Flow module
mkdir -p "$INSTALL_DIR/overlay/flow"
cp "$DEV_DIR"/overlay/flow/*.py "$INSTALL_DIR/overlay/flow/"

# Locales
mkdir -p "$INSTALL_DIR/overlay/locales"
cp -r "$DEV_DIR"/overlay/locales/* "$INSTALL_DIR/overlay/locales/"

# 3D radial wheel images
mkdir -p "$INSTALL_DIR/assets/radial-wheels"
cp "$DEV_DIR"/assets/radial-wheels/*.png "$INSTALL_DIR/assets/radial-wheels/"

# Device/settings imagery used by the settings dashboard
mkdir -p "$INSTALL_DIR/assets/devices"
cp "$DEV_DIR"/assets/devices/*.png "$DEV_DIR"/assets/devices/*.svg "$INSTALL_DIR/assets/devices/" 2>/dev/null || true
mkdir -p "$INSTALL_DIR/assets/settings-generated"
cp "$DEV_DIR"/assets/settings-generated/control-ring.png "$INSTALL_DIR/assets/settings-generated/" 2>/dev/null || true
cp "$DEV_DIR"/assets/settings-generated/easyswitch.png "$INSTALL_DIR/assets/settings-generated/" 2>/dev/null || true
cp "$DEV_DIR"/assets/settings-generated/haptics.png "$INSTALL_DIR/assets/settings-generated/" 2>/dev/null || true

# Daemon binary
cp "$DEV_DIR/daemon/target/release/juhradiald" "$INSTALL_DIR/daemon/target/release/juhradiald"
install -Dm755 "$DEV_DIR/daemon/target/release/juhradiald" /usr/local/bin/juhradiald

echo "=== Syncing dev -> $SHARE_DIR ==="
mkdir -p "$SHARE_DIR"

# Overlay + flow
cp "$DEV_DIR"/overlay/*.py "$SHARE_DIR/"
mkdir -p "$SHARE_DIR/flow"
cp "$DEV_DIR"/overlay/flow/*.py "$SHARE_DIR/flow/"

# Locales
mkdir -p "$SHARE_DIR/locales"
cp -r "$DEV_DIR"/overlay/locales/* "$SHARE_DIR/locales/"

# Qt/QML settings app (mirrors install.sh: main.py + bridge/ + qml/ + assets/,
# no tools/ or __pycache__) and the wheel skins the overlay resolves
rm -rf "$SHARE_DIR/settings-qt"
mkdir -p "$SHARE_DIR/settings-qt"
cp "$DEV_DIR/settings-qt/main.py" "$DEV_DIR/settings-qt/VERSION" "$SHARE_DIR/settings-qt/"
cp -r "$DEV_DIR"/settings-qt/bridge "$DEV_DIR"/settings-qt/qml "$DEV_DIR"/settings-qt/assets "$SHARE_DIR/settings-qt/"
find "$SHARE_DIR/settings-qt" -type d -name __pycache__ -exec rm -rf {} +
mkdir -p "$SHARE_DIR/assets"
cp -r "$DEV_DIR"/settings-qt/assets/wheels "$SHARE_DIR/assets/"

# Assets
mkdir -p "$SHARE_DIR/assets"
cp "$DEV_DIR"/assets/ai-*.svg "$SHARE_DIR/assets/" 2>/dev/null || true
cp "$DEV_DIR"/assets/os-*.svg "$SHARE_DIR/assets/" 2>/dev/null || true
cp "$DEV_DIR"/assets/flow-indicator.png "$SHARE_DIR/assets/" 2>/dev/null || true
cp "$DEV_DIR"/assets/genericmouse.png "$SHARE_DIR/assets/" 2>/dev/null || true
cp "$DEV_DIR"/assets/nav-*.png "$SHARE_DIR/assets/" 2>/dev/null || true
mkdir -p "$SHARE_DIR/assets/devices"
cp "$DEV_DIR"/assets/devices/*.png "$DEV_DIR"/assets/devices/*.svg "$SHARE_DIR/assets/devices/" 2>/dev/null || true
mkdir -p "$SHARE_DIR/assets/settings-generated"
cp "$DEV_DIR"/assets/settings-generated/control-ring.png "$SHARE_DIR/assets/settings-generated/" 2>/dev/null || true
cp "$DEV_DIR"/assets/settings-generated/easyswitch.png "$SHARE_DIR/assets/settings-generated/" 2>/dev/null || true
cp "$DEV_DIR"/assets/settings-generated/haptics.png "$SHARE_DIR/assets/settings-generated/" 2>/dev/null || true

echo ""
echo "Done! Use your keyboard shortcut to start JuhRadial MX."

# The daemon runs as the invoking user's systemd unit; pkill above stopped it,
# so bring it back under the user manager (not root's) before handing over.
if [ -n "${SUDO_USER:-}" ]; then
    echo "=== Restarting juhradialmx-daemon.service for $SUDO_USER ==="
    sudo -u "$SUDO_USER" XDG_RUNTIME_DIR="/run/user/$(id -u "$SUDO_USER")" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$SUDO_USER")/bus" \
        systemctl --user restart juhradialmx-daemon.service 2>/dev/null || \
        echo "(no user unit; start the daemon with juhradial-mx)"
fi
