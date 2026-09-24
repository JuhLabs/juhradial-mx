#!/usr/bin/env bash
# install.sh --user (#138, Bazzite / Fedora Atomic): everything lands under
# $HOME, sudo is used only for udev, uinput, the input group and packages, the
# desktop entries and the systemd unit point at ~/.local/bin, and the login
# autostart entry runs the user-mode launcher. Runs the real installer against
# a scratch HOME with stubbed sudo, systemctl, udevadm and modprobe.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# A copy of the tree with a stand-in prebuilt daemon (no Rust build here).
mkdir -p "$tmp/tree"
tar -C "$repo" --exclude=./.git --exclude=./daemon/target --exclude=__pycache__ \
    --exclude=./settings-qt/.venv -cf - . | tar -C "$tmp/tree" -xf -
mkdir -p "$tmp/tree/daemon/target/release"
printf '#!/bin/sh\necho "juhradiald 0.0.0-test"\n' > "$tmp/tree/daemon/target/release/juhradiald"
chmod +x "$tmp/tree/daemon/target/release/juhradiald"

mkdir -p "$tmp/stubs" "$tmp/home"
for tool in sudo systemctl udevadm modprobe; do
    printf '#!/bin/sh\necho "%s $*" >> "%s/calls.log"\nexit 0\n' "$tool" "$tmp" > "$tmp/stubs/$tool"
    chmod +x "$tmp/stubs/$tool"
done

HOME="$tmp/home" XDG_DATA_HOME="" XDG_CONFIG_HOME="" XDG_CURRENT_DESKTOP=KDE \
    PATH="$tmp/stubs:$PATH" JUHRADIAL_LOCAL_TREE="$tmp/tree" \
    bash "$repo/install.sh" --user --yes > "$tmp/out.log" 2>&1 \
    || { cat "$tmp/out.log" >&2; echo "FAIL: installer exited non-zero" >&2; exit 1; }

share="$tmp/home/.local/share/juhradial"
bin="$tmp/home/.local/bin"
fail() { echo "FAIL: $*" >&2; exit 1; }
[ -f "$share/juhradial-overlay.py" ] || fail "overlay not in $share"
[ -f "$share/settings-qt/main.py" ] || fail "Qt settings app not in $share"
[ -x "$bin/juhradiald" ] && [ -x "$bin/juhradial-mx" ] && [ -x "$bin/juhradial-settings" ] || fail "binaries not in $bin"
grep -q "^Exec=$bin/juhradial-mx" "$tmp/home/.local/share/applications/juhradial-mx.desktop" || fail "desktop Exec not absolute"
grep -q "^Exec=$bin/juhradial-settings" "$tmp/home/.local/share/applications/org.kde.juhradialmx.settings.desktop" || fail "settings Exec not absolute"
[ -f "$tmp/home/.local/share/icons/hicolor/scalable/apps/juhradial-mx.svg" ] || fail "icon missing"
grep -q '^ExecStart=%h/.local/bin/juhradiald$' "$tmp/home/.config/systemd/user/juhradialmx-daemon.service" || fail "unit ExecStart"
grep -q "^Exec=$bin/juhradial-mx$" "$tmp/home/.config/autostart/juhradial-mx.desktop" || fail "autostart Exec"
# sudo only for what needs root: never for the app files.
if grep '^sudo' "$tmp/calls.log" | grep -vE 'udev|modules-load|modprobe|groupadd|usermod|/etc/group|dnf|pacman|apt-get|zypper|rpm-ostree' | grep -q .; then
    grep '^sudo' "$tmp/calls.log" >&2
    fail "sudo used for app files"
fi
# The launcher from ~/.local/bin finds the user-mode tree.
root="$(HOME="$tmp/home" XDG_DATA_HOME="" bash -c "source '$bin/juhradial-mx'; resolve_project_root '$bin'")"
[ "$root" = "$share" ] || fail "launcher resolves '$root'"
echo "PASS: install.sh --user"
