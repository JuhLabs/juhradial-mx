#!/usr/bin/env bash
# Regression test for issue #52: the launcher must resolve the overlay/daemon
# from any supported checkout layout, must be safe to source (so it can be
# tested without launching anything), and must fail loudly when the daemon
# binary is missing instead of silently reusing the overlay PID.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# The launcher must guard its startup behind a BASH_SOURCE==$0 check so this
# file can source it for its functions without spawning any process.
if ! grep -q 'BASH_SOURCE\[0\].*==.*\$0' scripts/juhradial-mx.sh; then
    echo "FAIL: launcher is not safe to source (no BASH_SOURCE==\$0 guard)" >&2
    exit 1
fi

# shellcheck disable=SC1091
source scripts/juhradial-mx.sh

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Dev checkout: <repo>/scripts, <repo>/overlay, <repo>/daemon/target/release
mkdir -p "$tmp/repo/scripts" "$tmp/repo/overlay" "$tmp/repo/daemon/target/release"
touch "$tmp/repo/overlay/juhradial-overlay.py"
touch "$tmp/repo/daemon/target/release/juhradiald"
chmod +x "$tmp/repo/daemon/target/release/juhradiald"

root="$(resolve_project_root "$tmp/repo/scripts")"
[ "$root" = "$tmp/repo" ] || { echo "FAIL: project root = '$root' (want '$tmp/repo')" >&2; exit 1; }

overlay="$(resolve_overlay "$root")"
[ "$overlay" = "$tmp/repo/overlay/juhradial-overlay.py" ] \
    || { echo "FAIL: overlay = '$overlay'" >&2; exit 1; }

# Installed flat layout: overlay sits directly under the root.
mkdir -p "$tmp/installed"
touch "$tmp/installed/juhradial-overlay.py"
[ "$(resolve_overlay "$tmp/installed")" = "$tmp/installed/juhradial-overlay.py" ] \
    || { echo "FAIL: flat overlay layout not resolved" >&2; exit 1; }

# Daemon resolves from the dev build path when no system binary exists.
daemon="$(resolve_daemon "$root" "$tmp/absent-local" "$tmp/absent-system")"
[ "$daemon" = "$tmp/repo/daemon/target/release/juhradiald" ] \
    || { echo "FAIL: daemon = '$daemon' (want dev build path)" >&2; exit 1; }

# resolve_daemon MUST fail (non-zero) when no binary exists anywhere, so the
# launcher can report the error instead of reusing the overlay PID (#52).
if resolve_daemon "$tmp/empty" "$tmp/absent-local" "$tmp/absent-system" >/dev/null; then
    echo "FAIL: resolve_daemon should fail when no binary exists" >&2
    exit 1
fi

# Issue #60: when the systemd user unit is enabled or active, the launcher
# must defer daemon startup to it entirely, so the managed copy is the only
# starter and cannot lose the single-instance race to an unmanaged child.
mkdir -p "$tmp/bin-enabled" "$tmp/bin-disabled"
cat > "$tmp/bin-enabled/systemctl" <<'STUB'
#!/bin/bash
exit 0
STUB
cat > "$tmp/bin-disabled/systemctl" <<'STUB'
#!/bin/bash
exit 1
STUB
chmod +x "$tmp/bin-enabled/systemctl" "$tmp/bin-disabled/systemctl"

if ! PATH="$tmp/bin-enabled" daemon_unit_managed; then
    echo "FAIL: daemon_unit_managed should be true when the unit is enabled" >&2
    exit 1
fi
if PATH="$tmp/bin-disabled" daemon_unit_managed; then
    echo "FAIL: daemon_unit_managed should be false when the unit is disabled" >&2
    exit 1
fi
if PATH="$tmp/empty-path-dir" daemon_unit_managed; then
    echo "FAIL: daemon_unit_managed should be false without systemctl" >&2
    exit 1
fi

# Issue #60: the launcher must wait for ALL children with a bare `wait`, not
# just the daemon PID. A daemon that loses the single-instance name race exits
# immediately; waiting on it alone would end the launcher, and the systemd
# autostart unit then kills the overlay with the rest of the cgroup.
if ! grep -qE '^[[:space:]]+wait$' scripts/juhradial-mx.sh; then
    echo "FAIL: launcher must use a bare 'wait' for all started children (#60)" >&2
    exit 1
fi
if grep -qE 'wait "\$(daemon|overlay)_pid"' scripts/juhradial-mx.sh; then
    echo "FAIL: launcher must not wait on a single child PID (#60)" >&2
    exit 1
fi

echo "PASS: launcher path resolution tests"
