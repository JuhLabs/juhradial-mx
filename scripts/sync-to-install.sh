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
