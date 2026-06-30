#!/usr/bin/env bash
#
# Distro build/install smoke test for JuhRadial MX.
#
# Spins up a disposable container for the latest image of each supported distro
# family and verifies, against the fixed installer behaviour:
#   - the daemon builds with a bootstrapped rustup toolchain (issue #23: the
#     committed Cargo.lock is lockfile v4 and toml_edit needs rustc >= 1.76,
#     so an old apt/dnf Rust must be replaced by rustup)
#   - on openSUSE Tumbleweed, python3-PyQt6 resolves and PyQt6.QtSvg imports
#     (issue #24: python3-qt6-svg does not exist there)
#
# Usage:   tests/distro_build_test.sh [SOURCE_DIR]
#   SOURCE_DIR defaults to the repo root (must contain daemon/ and install.sh).
#   RUNTIME=docker tests/distro_build_test.sh   # use docker instead of podman
#   DISTROS="ubuntu fedora" tests/distro_build_test.sh   # subset
#
set -uo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNTIME="${RUNTIME:-podman}"
DISTROS="${DISTROS:-ubuntu fedora tumbleweed arch}"

if [ ! -f "$SRC/install.sh" ] || [ ! -d "$SRC/daemon" ]; then
    echo "ERROR: $SRC does not look like the repo (need install.sh and daemon/)" >&2
    exit 2
fi

# Static check: the installer carries the issue #23 / #24 fixes.
echo "=== static install.sh checks ==="
grep -q "ensure_rust_toolchain" "$SRC/install.sh" && echo "  ok: ensure_rust_toolchain present (#23)" || echo "  WARN: ensure_rust_toolchain missing (#23)"
grep -q "python3-PyQt6" "$SRC/install.sh" && echo "  ok: python3-PyQt6 present (#24)" || echo "  WARN: python3-PyQt6 missing (#24)"
grep -q "python3-qt6-svg" "$SRC/install.sh" && echo "  WARN: stale python3-qt6-svg still present (#24)" || echo "  ok: stale python3-qt6-svg gone (#24)"
grep -q 'id -u' "$SRC/install.sh" && grep -q 'id -g' "$SRC/install.sh" && echo "  ok: installer uses numeric uid/gid (#52)" || echo "  WARN: installer not using numeric uid/gid (#52)"
grep -q '\$USER:\$USER' "$SRC/install.sh" && echo "  WARN: installer still assumes username equals group name (#52)" || echo "  ok: no \$USER:\$USER group assumption (#52)"
echo

# Bootstrap a new-enough Rust (mirrors install.sh ensure_rust_toolchain) then
# build the daemon. Source is mounted read-only; the build target goes to a
# writable dir so we never copy the (potentially huge) host target/ tree.
read -r -d '' BUILD_DAEMON <<'EOS'
set -e
export CARGO_TARGET_DIR=/tmp/jr-target
if ! command -v cargo >/dev/null 2>&1 || [ "$(cargo --version | cut -d' ' -f2 | cut -d. -f2)" -lt 78 ]; then
    echo "-- bootstrapping rustup (distro cargo absent or too old)"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable --profile minimal
    . "$HOME/.cargo/env"
fi
cargo --version
cargo build --release --manifest-path /src/daemon/Cargo.toml
test -x "$CARGO_TARGET_DIR/release/juhradiald"
echo "DAEMON_BUILD_OK"
EOS

declare -A RESULTS

run_one() {
    local key="$1" image="$2" prep="$3" extra="${4:-true}"
    echo "============================================================"
    echo "=== [$key] $image"
    echo "============================================================"
    local script="set -e; $prep; $extra; $BUILD_DAEMON"
    # label=disable avoids SELinux denying the container access to the bind
    # mount (Fedora hosts relabel by default and would otherwise EACCES).
    if "$RUNTIME" run --rm --security-opt label=disable -v "$SRC:/src:ro" "$image" bash -lc "$script"; then
        RESULTS[$key]="PASS"
    else
        RESULTS[$key]="FAIL"
    fi
}

for d in $DISTROS; do
    case "$d" in
        ubuntu)
            run_one "ubuntu-24.04" "docker.io/library/ubuntu:24.04" \
              "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq; apt-get install -y -qq curl ca-certificates build-essential pkg-config python3 python3-pyqt6 python3-pyqt6.qtsvg >/dev/null"
            ;;
        fedora)
            run_one "fedora-latest" "registry.fedoraproject.org/fedora:latest" \
              "dnf install -y -q curl gcc gcc-c++ make pkgconf-pkg-config python3 python3-pyqt6 qt6-qtsvg >/dev/null"
            ;;
        tumbleweed)
            run_one "opensuse-tumbleweed" "registry.opensuse.org/opensuse/tumbleweed:latest" \
              "zypper -n --gpg-auto-import-keys refresh >/dev/null; zypper -n install -y curl gcc gcc-c++ make pkg-config python3-PyQt6 >/dev/null" \
              "python3 -c 'from PyQt6.QtSvg import QSvgRenderer; from PyQt6.QtSvgWidgets import QSvgWidget; print(\"QtSvg import OK (#24)\")'"
            ;;
        arch)
            run_one "arch-latest" "docker.io/library/archlinux:latest" \
              "pacman -Syu --noconfirm --quiet curl gcc make pkgconf rust python-pyqt6 qt6-svg >/dev/null"
            ;;
        *) echo "unknown distro: $d" ;;
    esac
    echo
done

echo "============================================================"
echo "=== SUMMARY"
echo "============================================================"
rc=0
for k in "${!RESULTS[@]}"; do
    printf "  %-22s %s\n" "$k" "${RESULTS[$k]}"
    [ "${RESULTS[$k]}" = "PASS" ] || rc=1
done
exit $rc
