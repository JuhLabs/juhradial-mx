#!/bin/bash
# JuhRadial MX: one-time host setup for the Flatpak.
#
# A Flatpak cannot install udev rules, load kernel modules or change group
# membership, and the daemon needs all three: read/write access to the mouse's
# /dev/hidraw* node and to /dev/uinput. Run this once on the host, not inside
# the sandbox. It is the same set of steps install.sh does for the native
# install, without the files, services and desktop entries.
#
#   sh "$(flatpak info --show-location org.juhlabs.JuhRadialMX)/files/share/juhradial/host-setup.sh"
#   sh packaging/flatpak/host-setup.sh --dry-run     (from a source checkout)
#
# Options:
#   --dry-run     print what would be done, change nothing
#   --rules DIR   take the udev rules from DIR instead of auto-detecting them

set -eu

dry=0
rules_dir=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) dry=1 ;;
        --rules) rules_dir="${2:?--rules needs a directory}"; shift ;;
        -h|--help) sed -n '2,/^set -eu/p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

if [ -n "${FLATPAK_ID:-}" ]; then
    echo "This runs on the host, not inside the Flatpak sandbox." >&2
    exit 1
fi

here="$(cd "$(dirname "$0")" && pwd)"
if [ -z "$rules_dir" ]; then
    for candidate in "$here/udev" "$here/../udev"; do
        if [ -f "$candidate/99-juhradialmx.rules" ]; then
            rules_dir="$candidate"
            break
        fi
    done
fi
if [ -z "$rules_dir" ] || [ ! -f "$rules_dir/99-juhradialmx.rules" ]; then
    echo "Could not find the udev rules. Pass --rules DIR (packaging/udev in the source tree)." >&2
    exit 1
fi

run() {
    if [ "$dry" = 1 ]; then
        echo "+ $*"
    else
        "$@"
    fi
}
priv=""
[ "$(id -u)" = 0 ] || priv="sudo"

user="${SUDO_USER:-${USER:-$(id -un)}}"

for rule in 60-ydotool-uinput.rules 70-juhradialmx-uaccess.rules 99-juhradialmx.rules; do
    run $priv install -Dm644 "$rules_dir/$rule" "/etc/udev/rules.d/$rule"
done

# /dev/uinput must exist at boot and now.
if [ "$dry" = 1 ]; then
    echo "+ echo uinput | $priv tee /etc/modules-load.d/juhradial-uinput.conf"
else
    echo uinput | $priv tee /etc/modules-load.d/juhradial-uinput.conf >/dev/null
fi
run $priv modprobe uinput

run $priv udevadm control --reload-rules
run $priv udevadm trigger --action=add --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc

# 99-juhradialmx.rules grants hidraw to group "input". The 70-... uaccess rule
# already covers Logitech devices for the logged-in user; the group is for
# devices of other makers (macro recording) and for sessions without logind.
if ! getent group input >/dev/null 2>&1; then
    run $priv groupadd input
fi
if ! id -nG "$user" | grep -qw input; then
    run $priv usermod -aG input "$user"
    echo "Added $user to the input group: log out and back in for it to apply."
fi

echo "Done. Reconnect the mouse (or log out and in), then start JuhRadial MX."
