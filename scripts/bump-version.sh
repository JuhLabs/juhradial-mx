#!/usr/bin/env bash
# Bump the JuhRadial MX version in every file that carries it.
#
# Usage: scripts/bump-version.sh 0.4.5
#
# Sites (kept in sync with tests/test_version_consistency.py):
#   daemon/Cargo.toml                          version = "..."
#   packaging/arch/PKGBUILD                    pkgver=...
#   packaging/rpm/juhradial-mx.spec            Version: ... (+ a %changelog stub)
#   packaging/org.juhlabs.JuhRadialMX.metainfo.xml   <release version="..." date="..."> stub
#   flake.nix                                  version = "..." (both packages)
#   README.md                                  version badge
#   .github/SECURITY.md                        "Current release" row
#
# CHANGELOG.md is deliberately not touched: renaming [Unreleased] to the
# version heading is a release-time editorial step.
set -euo pipefail

if [ $# -ne 1 ] || ! [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "usage: $0 X.Y.Z" >&2
    exit 2
fi

NEW="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OLD="$(sed -n 's/^version = "\([0-9.]*\)"/\1/p' daemon/Cargo.toml | head -1)"
if [ -z "$OLD" ]; then
    echo "could not read the current version from daemon/Cargo.toml" >&2
    exit 1
fi

TODAY_ISO="$(date -u +%Y-%m-%d)"
TODAY_RPM="$(LC_ALL=C date -u '+%a %b %d %Y')"

sed -i "0,/^version = \"$OLD\"/s//version = \"$NEW\"/" daemon/Cargo.toml
sed -i "s/^pkgver=.*/pkgver=$NEW/" packaging/arch/PKGBUILD
sed -i "s/^Version:\([[:space:]]*\).*/Version:\1$NEW/" packaging/rpm/juhradial-mx.spec
sed -i "s/version = \"[0-9.]*\";/version = \"$NEW\";/g" flake.nix
sed -i "s#img.shields.io/badge/version-[0-9.]*-cyan.svg\" alt=\"Version [0-9.]*\"#img.shields.io/badge/version-$NEW-cyan.svg\" alt=\"Version $NEW\"#" README.md

# SECURITY.md: the previous "Current release" row loses the label, the new
# version is inserted as the current one right under the table header.
if ! grep -q "^| $NEW " .github/SECURITY.md; then
    sed -i 's/^\(| [0-9.]* *| :white_check_mark:\) Current release |/\1 |/' .github/SECURITY.md
    sed -i "/^| ------- | ------------------ |\$/a | $NEW   | :white_check_mark: Current release |" .github/SECURITY.md
fi

# RPM %changelog stub (only when this version has no entry yet).
if ! grep -q " - $NEW-1\$" packaging/rpm/juhradial-mx.spec; then
    sed -i "/^%changelog\$/a * $TODAY_RPM Julian Hermstad <dev@juhlabs.com> - $NEW-1\n- Release $NEW (see CHANGELOG.md)\n" packaging/rpm/juhradial-mx.spec
fi

# AppStream release stub (only when this version has no entry yet).
if ! grep -q "<release version=\"$NEW\"" packaging/org.juhlabs.JuhRadialMX.metainfo.xml; then
    sed -i "0,/^  <releases>\$/s//  <releases>\n    <release version=\"$NEW\" date=\"$TODAY_ISO\">\n      <description>\n        <p>Release $NEW. See CHANGELOG.md for details.<\/p>\n      <\/description>\n    <\/release>/" packaging/org.juhlabs.JuhRadialMX.metainfo.xml
fi

# Keep Cargo.lock's own package entry in step when cargo is available.
if command -v cargo >/dev/null 2>&1; then
    (cd daemon && cargo update --workspace --offline >/dev/null 2>&1 || cargo generate-lockfile --offline >/dev/null 2>&1 || true)
fi

echo "bumped $OLD -> $NEW"
echo "next: edit CHANGELOG.md ([Unreleased] -> [$NEW] - $TODAY_ISO), fill the spec %changelog and metainfo release text, then run: python3 -m pytest tests/test_version_consistency.py"
