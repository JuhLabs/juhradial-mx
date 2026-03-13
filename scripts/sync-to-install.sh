#!/bin/bash
# Sync dev files to install locations and restart
# Run with: sudo bash scripts/sync-to-install.sh

set -e
DEV_DIR="/run/media/juhlabs/483b2e92-c28a-4728-aefd-b04560105994/@home/nordlys/Downloads/Prosjekter/JuhRadialMX"
INSTALL_DIR="/opt/juhradial-mx"
SHARE_DIR="/usr/share/juhradial"

echo "=== Stopping running processes ==="
pkill -f juhradiald 2>/dev/null || true
pkill -f juhradial-overlay 2>/dev/null || true
pkill -f juhradial-settings 2>/dev/null || true
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

echo ""
echo "Done! Use your keyboard shortcut to start JuhRadial MX."
