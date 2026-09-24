#!/usr/bin/env bash
# Bump the JuhRadial MX version in every file that carries it.
#
# Usage: scripts/bump-version.sh 0.4.5
#        scripts/bump-version.sh 0.4.5-beta.1   (a pre-release)
#
# Each site gets its own format's form of the version, so a pre-release sorts
# below the final release everywhere (0.4.5-beta.1 shown in brackets):
#   daemon/Cargo.toml                          version = "..." (SemVer: 0.4.5-beta.1)
#   packaging/arch/PKGBUILD                    pkgver=... (no hyphen allowed: 0.4.5beta1)
#   packaging/rpm/juhradial-mx.spec            Version: ... (tilde: 0.4.5~beta.1, + a %changelog stub)
#   packaging/org.juhlabs.JuhRadialMX.metainfo.xml   <release version="..." date="..."> stub
#                                              (tilde, type="development" for a pre-release)
#   flake.nix                                  version = "..." (both packages, SemVer)
#   README.md                                  version badge (shields.io escapes "-" as "--")
#   .github/SECURITY.md                        "Current release" row (SemVer)
#   settings-qt/VERSION                        the Qt settings app's own version string (SemVer)
#
# CHANGELOG.md is deliberately not touched: renaming [Unreleased] to the
# version heading is a release-time editorial step.
set -euo pipefail

if [ $# -ne 1 ] || ! [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-beta\.[0-9]+)?$ ]]; then
    echo "usage: $0 X.Y.Z | X.Y.Z-beta.N" >&2
    exit 2
fi

NEW="$1"
NEW_ARCH="${NEW/-beta./beta}"
NEW_TILDE="${NEW/-/\~}"
NEW_BADGE="${NEW//-/--}"
RELEASE_TYPE=""
case "$NEW" in *-*) RELEASE_TYPE=' type="development"' ;; esac
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OLD="$(sed -n 's/^version = "\([^"]*\)"/\1/p' daemon/Cargo.toml | head -1)"
if [ -z "$OLD" ]; then
    echo "could not read the current version from daemon/Cargo.toml" >&2
    exit 1
fi

TODAY_ISO="$(date -u +%Y-%m-%d)"
TODAY_RPM="$(LC_ALL=C date -u '+%a %b %d %Y')"

sed -i "0,/^version = \"$OLD\"/s//version = \"$NEW\"/" daemon/Cargo.toml
sed -i "s/^pkgver=.*/pkgver=$NEW_ARCH/" packaging/arch/PKGBUILD
sed -i "s/^Version:\([[:space:]]*\).*/Version:\1$NEW_TILDE/" packaging/rpm/juhradial-mx.spec
sed -i "s/version = \"[0-9A-Za-z.-]*\";/version = \"$NEW\";/g" flake.nix
sed -i "s#img.shields.io/badge/version-[0-9A-Za-z.-]*-cyan.svg\" alt=\"Version [0-9A-Za-z.-]*\"#img.shields.io/badge/version-$NEW_BADGE-cyan.svg\" alt=\"Version $NEW\"#" README.md
printf '%s\n' "$NEW" > settings-qt/VERSION

# SECURITY.md: the previous "Current release" row loses the label, the new
# version is inserted as the current one right under the table header.
if ! grep -q "^| $NEW " .github/SECURITY.md; then
    sed -i 's/^\(| [0-9A-Za-z.-]* *| :white_check_mark:\) Current release |/\1 |/' .github/SECURITY.md
    sed -i "/^| ------- | ------------------ |\$/a | $NEW   | :white_check_mark: Current release |" .github/SECURITY.md
fi

# RPM %changelog stub (only when this version has no entry yet).
if ! grep -q " - $NEW_TILDE-1\$" packaging/rpm/juhradial-mx.spec; then
    sed -i "/^%changelog\$/a * $TODAY_RPM Julian Hermstad <dev@juhlabs.com> - $NEW_TILDE-1\n- Release $NEW (see CHANGELOG.md)\n" packaging/rpm/juhradial-mx.spec
fi

# AppStream release stub (only when this version has no entry yet).
if ! grep -q "<release version=\"$NEW_TILDE\"" packaging/org.juhlabs.JuhRadialMX.metainfo.xml; then
    sed -i "0,/^  <releases>\$/s//  <releases>\n    <release version=\"$NEW_TILDE\" date=\"$TODAY_ISO\"$RELEASE_TYPE>\n      <description>\n        <p>Release $NEW. See CHANGELOG.md for details.<\/p>\n      <\/description>\n    <\/release>/" packaging/org.juhlabs.JuhRadialMX.metainfo.xml
fi

# Keep Cargo.lock's own package entry in step when cargo is available.
if command -v cargo >/dev/null 2>&1; then
    (cd daemon && cargo update --workspace --offline >/dev/null 2>&1 || cargo generate-lockfile --offline >/dev/null 2>&1 || true)
fi

echo "bumped $OLD -> $NEW"
echo "next: edit CHANGELOG.md ([Unreleased] -> [$NEW] - $TODAY_ISO), fill the spec %changelog and metainfo release text, then run: python3 -m pytest tests/test_version_consistency.py"
