#!/bin/bash
# Sync dev files to both install locations
# Run with: sudo bash scripts/sync-to-install.sh

set -e
DEV_DIR="/home/nordlys/Downloads/Prosjekter/JuhRadialMX"
INSTALL_DIR="/opt/juhradial-mx"
SHARE_DIR="/usr/share/juhradial"

echo "Syncing dev → $INSTALL_DIR ..."

# Overlay Python files (all .py files)
cp "$DEV_DIR"/overlay/*.py "$INSTALL_DIR/overlay/"

# Locales (translations)
mkdir -p "$INSTALL_DIR/overlay/locales"
cp -r "$DEV_DIR"/overlay/locales/* "$INSTALL_DIR/overlay/locales/"

# 3D radial wheel images
mkdir -p "$INSTALL_DIR/assets/radial-wheels"
cp "$DEV_DIR"/assets/radial-wheels/*.png "$INSTALL_DIR/assets/radial-wheels/"

# Also sync to /usr/share/juhradial (used by settings launcher)
if [ -d "$SHARE_DIR" ]; then
    echo "Syncing dev → $SHARE_DIR ..."
    cp "$DEV_DIR"/overlay/*.py "$SHARE_DIR/"
    mkdir -p "$SHARE_DIR/locales"
    cp -r "$DEV_DIR"/overlay/locales/* "$SHARE_DIR/locales/"
fi

echo "Done! Restart JuhRadial MX to use the new build."
