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

echo "PASS: launcher path resolution tests"
