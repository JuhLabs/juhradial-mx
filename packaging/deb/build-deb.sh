#!/bin/bash
# Build the Debian/Ubuntu package from a release tree (the unpacked release
# tarball, which carries the prebuilt daemon): same layout as the Arch and
# RPM packages, daemon and launchers in /usr/bin.
#
# Usage: packaging/deb/build-deb.sh <tree> <version> <outdir>
set -euo pipefail

tree="$(cd "$1" && pwd)"
version="$2"
out="$(mkdir -p "$3" && cd "$3" && pwd)"
stage="$(mktemp -d)/juhradial-mx_${version}_amd64"
share="$stage/usr/share/juhradial"

cd "$tree"
install -Dm755 daemon/target/release/juhradiald "$stage/usr/bin/juhradiald"
install -Dm755 scripts/juhradial-mx.sh "$stage/usr/bin/juhradial-mx"
install -Dm755 scripts/juhradial-settings.sh "$stage/usr/bin/juhradial-settings"
install -dm755 "$share"
install -m644 overlay/*.py "$share/"
cp -r overlay/flow overlay/locales "$share/"
install -dm755 "$share/assets"
cp -r assets/* "$share/assets/"
install -dm755 "$share/settings-qt"
install -m644 settings-qt/main.py settings-qt/VERSION "$share/settings-qt/"
cp -r settings-qt/bridge settings-qt/qml settings-qt/assets "$share/settings-qt/"
cp -r settings-qt/assets/wheels "$share/assets/"
find "$share" -type d -name __pycache__ -prune -exec rm -rf {} +
install -Dm644 packaging/juhradial-mx.desktop "$stage/usr/share/applications/juhradial-mx.desktop"
install -Dm644 packaging/org.kde.juhradialmx.settings.desktop "$stage/usr/share/applications/org.kde.juhradialmx.settings.desktop"
install -Dm644 assets/juhradial-mx.svg "$stage/usr/share/icons/hicolor/scalable/apps/juhradial-mx.svg"
install -Dm644 packaging/systemd/juhradialmx-daemon.service "$stage/usr/lib/systemd/user/juhradialmx-daemon.service"
sed -i 's|^ExecStart=/usr/local/bin/juhradiald|ExecStart=/usr/bin/juhradiald|' "$stage/usr/lib/systemd/user/juhradialmx-daemon.service"
install -Dm644 packaging/udev/99-juhradialmx.rules "$stage/usr/lib/udev/rules.d/99-juhradialmx.rules"
install -Dm644 packaging/udev/60-ydotool-uinput.rules "$stage/usr/lib/udev/rules.d/60-ydotool-uinput.rules"
install -Dm644 LICENSE "$stage/usr/share/doc/juhradial-mx/copyright"

mkdir -p "$stage/DEBIAN"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: juhradial-mx
Version: ${version}
Architecture: amd64
Maintainer: JuhLabs <dev@juhlabs.com>
Homepage: https://github.com/JuhLabs/juhradial-mx
Section: utils
Priority: optional
Depends: python3, python3-pyqt6, python3-cryptography, python3-gi, python3-gi-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, libc6
Recommends: ydotool, python3-pyqt6.qtsvg, python3-pyqt6.qtqml, python3-pyqt6.qtquick, qml6-module-qtquick-effects, libgtk4-layer-shell0
Description: Radial menu and configuration for Logitech MX Master mice on Linux
 Hold the gesture button to open a radial menu, remap buttons, set DPI,
 SmartShift, haptics, Easy-Switch and per-app profiles. The Qt settings app
 needs Qt 6.9; older releases use the GTK settings app automatically.
CONTROL
cat > "$stage/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --action=add --subsystem-match=hidraw --subsystem-match=input 2>/dev/null || true
echo uinput > /etc/modules-load.d/juhradial-uinput.conf
modprobe uinput 2>/dev/null || true
gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
echo "JuhRadial MX: add yourself to the input group (sudo usermod -aG input \$USER), log out and in, then run juhradial-mx."
POSTINST
chmod 755 "$stage/DEBIAN/postinst"

dpkg-deb --root-owner-group --build "$stage" "$out/juhradial-mx_${version}_amd64.deb"
