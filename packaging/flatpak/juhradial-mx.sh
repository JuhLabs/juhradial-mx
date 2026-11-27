#!/bin/bash
# JuhRadial MX launcher inside the Flatpak sandbox.
#
#   juhradial-mx                open the Settings window; start the services first
#   juhradial-mx --background   start the services only (no window)
#   juhradial-mx status|doctor|dpi|host|keypad-page|reload|help
#                               ask the running service (settings-qt/bridge/ctl.py)
#
# The services are ydotoold (kernel uinput injection for shortcut actions), the
# daemon (juhradiald: HID++ over hidraw, gesture button, D-Bus) and the Qt
# overlay (the radial menu). Each one is started under flock, so a second
# `flatpak run` never starts a second copy.
#
# Packaging notes: packaging/FLATPAK.md

share=/app/share/juhradial
state="${XDG_RUNTIME_DIR:-/tmp}/app/${FLATPAK_ID:-org.juhlabs.JuhRadialMX}"
mkdir -p "$state"

# The daemon hands KWin a script file to load. KWin runs on the host and cannot
# read the sandbox's private /tmp, so keep temp files under the runtime dir,
# which the manifest shares with the host at the same path.
export TMPDIR="${XDG_RUNTIME_DIR:-/tmp}/juhradial-tmp"
mkdir -p "$TMPDIR"

# One socket for ydotoold and for the daemon's ydotool calls.
export YDOTOOL_SOCKET="$state/ydotool.sock"

case "${1:-}" in
    status|doctor|dpi|host|keypad-page|reload|help|--help|-h)
        exec python3 "$share/settings-qt/bridge/ctl.py" "$@" ;;
esac

# Run a service in the background unless another sandbox already holds its lock.
start() {
    local name="$1"
    shift
    flock -n "$state/$name.lock" "$@" &
}

if [ -c /dev/uinput ]; then
    start ydotoold ydotoold --socket-path="$YDOTOOL_SOCKET" --socket-perm=0600
else
    echo "JuhRadial MX: /dev/uinput is not available; shortcut actions will not work." >&2
    echo "  Host setup is needed once, see packaging/FLATPAK.md (juhradial-host-setup)." >&2
fi
start daemon juhradiald
start overlay python3 "$share/juhradial-overlay.py"

if [ "${1:-}" = "--background" ]; then
    wait
    exit $?
fi

python3 "$share/settings-qt/main.py" "$@"
status=$?
# Keep the radial menu alive after the Settings window closes, like the
# regular launcher does. Closing the last process ends the sandbox.
wait
exit $status
