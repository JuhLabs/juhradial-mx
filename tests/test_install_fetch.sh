#!/usr/bin/env bash
# install.sh fetch_release: the release tarball carries a prebuilt daemon, so
# it is unpacked only when it matches the SHA256SUMS of the same release. A
# changed tarball, or a release without the checksum, falls back to building
# from source (fetch_release returns 1) and installs nothing. curl is stubbed
# to serve files from a local "release" directory.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

eval "$(sed -n '/^fetch_release() {$/,/^}$/p' "$repo/install.sh")"
log_info() { :; }
log_dim() { echo "$*"; }
log_success() { echo "$*"; }
log_warning() { echo "WARN $*"; }

version=9.9.9
name="juhradial-mx-$version-linux-x86_64.tar.gz"
mkdir -p "$tmp/src/juhradial-mx-$version/daemon" "$tmp/release" "$tmp/stubs"
echo '[package]' > "$tmp/src/juhradial-mx-$version/daemon/Cargo.toml"
echo "$version" > "$tmp/src/juhradial-mx-$version/VERSION"
tar -C "$tmp/src" -czf "$tmp/release/$name" "juhradial-mx-$version"
(cd "$tmp/release" && sha256sum -- "$name" > SHA256SUMS)

# curl [-fsSL] [-o FILE] URL: the file named by the URL's last part.
cat > "$tmp/stubs/curl" <<EOF
#!/bin/sh
out=""
while [ \$# -gt 1 ]; do
    case "\$1" in -o) out="\$2"; shift 2 ;; -H) shift 2 ;; *) shift ;; esac
done
file="$tmp/release/\$(basename "\$1")"
[ -f "\$file" ] || exit 22
if [ -n "\$out" ]; then cp "\$file" "\$out"; else cat "\$file"; fi
EOF
chmod +x "$tmp/stubs/curl"

fetch() {
    rm -rf "$tmp/install"
    (
        set -e +u +o pipefail
        export PATH="$tmp/stubs:$PATH"
        PRIV="" INSTALL_DIR="$tmp/install" REPO_URL="https://github.com/JuhLabs/juhradial-mx" RELEASE_VERSION="$version"
        fetch_release && echo "status=0" || echo "status=1"
    )
}

out="$(fetch)"
grep -q '^status=0$' <<< "$out" || fail "a matching tarball was refused: $out"
[ "$(cat "$tmp/install/VERSION")" = "$version" ] || fail "the release was not unpacked"

# A valid tarball, but not the one SHA256SUMS lists.
echo "changed" > "$tmp/src/juhradial-mx-$version/VERSION"
tar -C "$tmp/src" -czf "$tmp/release/$name" "juhradial-mx-$version"
out="$(fetch)"
grep -q '^status=1$' <<< "$out" && grep -q '^WARN .*SHA256SUMS' <<< "$out" || fail "a changed tarball was installed: $out"
[ ! -e "$tmp/install" ] || fail "a changed tarball left files behind"

# A release without SHA256SUMS.
(cd "$tmp/release" && sha256sum -- "$name" > SHA256SUMS)
rm "$tmp/release/SHA256SUMS"
out="$(fetch)"
grep -q '^status=1$' <<< "$out" || fail "a tarball without SHA256SUMS was installed: $out"
echo "PASS: install.sh fetch_release checks SHA256SUMS"
