#!/bin/bash
# JuhRadial MX Launcher
# Starts the daemon and overlay for the radial menu.
#
# Structured so the resolution helpers can be sourced and unit-tested without
# launching anything (see tests/test_launcher.sh). All startup happens in
# main(), guarded by the BASH_SOURCE==$0 check at the bottom.

# Locate the project tree (the one holding the overlay) from the launcher dir.
# Works for a dev checkout (<repo>/scripts/..), an installed flat layout, and
# the system install locations.
resolve_project_root() {
    local script_dir="$1" candidate
    for candidate in \
        "$script_dir/.." \
        "$script_dir" \
        /usr/share/juhradial \
        /opt/juhradial-mx; do
        candidate="$(cd "$candidate" 2>/dev/null && pwd || true)"
        if [ -n "$candidate" ] && {
            [ -f "$candidate/overlay/juhradial-overlay.py" ] ||
            [ -f "$candidate/juhradial-overlay.py" ]
        }; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

resolve_overlay() {
    local root="$1" candidate
    for candidate in "$root/overlay/juhradial-overlay.py" "$root/juhradial-overlay.py"; do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Resolve the daemon binary. Defaults to the install locations; the dev build
# path is derived from the project root (one level up from scripts/, which the
# old SCRIPT_DIR-relative check got wrong). Returns non-zero when nothing is
# found, so the caller can report it instead of pretending the daemon started.
resolve_daemon() {
    local root="$1"
    local local_bin="${2:-/usr/local/bin/juhradiald}"
    local system_bin="${3:-/usr/bin/juhradiald}"
    local candidate
    for candidate in "$local_bin" "$system_bin" "$root/daemon/target/release/juhradiald"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# True when the systemd user unit is responsible for the daemon. When the
# unit is enabled (it will start at login) or active (it is running now), the
# launcher must not start its own copy at all: at login the two would race,
# and if the launcher's unmanaged child won the daemon's single-instance name
# claim, the surviving daemon would run without the unit's resource limits and
# crash supervision, with the unit stuck inactive (issue #60). Skipping here
# keeps the managed copy the only starter on systemd setups; systems without
# the unit fall through to the D-Bus ownership check below.
daemon_unit_managed() {
    local unit="${1:-juhradialmx-daemon.service}"
    command -v systemctl >/dev/null 2>&1 || return 1
    systemctl --user is-enabled --quiet "$unit" 2>/dev/null ||
        systemctl --user is-active --quiet "$unit" 2>/dev/null
}

# True when something (e.g. a systemd user service) already owns the daemon's
# D-Bus name, so we should not start a second, unmanaged copy.
daemon_name_owned() {
    command -v gdbus >/dev/null 2>&1 || return 1
    gdbus call --session \
        --dest org.freedesktop.DBus \
        --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner \
        org.kde.juhradialmx 2>/dev/null | grep -q true
}

main() {
    local script_dir root overlay daemon overlay_pid="" daemon_pid=""

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    root="$(resolve_project_root "$script_dir")" || {
        echo "JuhRadial MX: overlay files not found (looked from $script_dir)" >&2
        return 1
    }
    overlay="$(resolve_overlay "$root")" || {
        echo "JuhRadial MX: overlay entry point not found under $root" >&2
        return 1
    }

    # Start the overlay (it listens for D-Bus signals) unless one is already up.
    if ! pgrep -f '[j]uhradial-overlay.py' >/dev/null 2>&1; then
        python3 "$overlay" &
        overlay_pid=$!
    fi

    # Start the daemon only when systemd is not responsible for it AND nothing
    # already owns the D-Bus name. The daemon's own single-instance claim is
    # the final authority; these checks just avoid spawning doomed copies.
    if daemon_unit_managed; then
        : # the systemd user unit owns the daemon lifecycle
    elif ! daemon_name_owned; then
        if ! daemon="$(resolve_daemon "$root")"; then
            [ -z "$overlay_pid" ] || kill "$overlay_pid" 2>/dev/null || true
            echo "JuhRadial MX: daemon binary (juhradiald) not found." >&2
            echo "  Build it:   (cd \"$root/daemon\" && cargo build --release)" >&2
            echo "  or install: re-run install.sh so juhradiald lands in /usr/local/bin" >&2
            return 1
        fi
        "$daemon" &
        daemon_pid=$!
    fi

    echo "JuhRadial MX started"
    [ -z "$overlay_pid" ] || echo "  Overlay PID: $overlay_pid"
    [ -z "$daemon_pid" ] || echo "  Daemon PID:  $daemon_pid"

    # Keep the launcher alive until EVERYTHING it started has exited, not just
    # the daemon. The daemon's single-instance guard makes a copy that lost the
    # name race exit immediately (issue #60); if the launcher followed it down,
    # the systemd-generated autostart unit would tear down its whole cgroup and
    # kill the overlay that was just started. A bare `wait` covers every child.
    wait
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
