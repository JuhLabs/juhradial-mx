"""Every file that carries the JuhRadial MX version must agree with daemon/Cargo.toml.

Guards against the packaging drift seen on master (Cargo 0.4.4 while PKGBUILD,
the RPM spec and flake.nix still said 0.4.3, and SECURITY.md said 0.4.1).
scripts/bump-version.sh updates all of these sites in one go.

A pre-release (0.4.5-beta.1 in Cargo) is written in each format's own
convention so it sorts below the final release: PKGBUILD 0.4.5beta1 (pkgver
cannot hold a hyphen), RPM and AppStream 0.4.5~beta.1 (tilde sorts first),
the shields.io badge 0.4.5--beta.1 (a single dash separates badge fields).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def cargo_version():
    match = re.search(r'^version = "(\d+\.\d+\.\d+(?:-beta\.\d+)?)"', _read("daemon/Cargo.toml"), re.M)
    assert match, "daemon/Cargo.toml has no X.Y.Z or X.Y.Z-beta.N version line"
    return match.group(1)


def is_prerelease():
    return "-" in cargo_version()


def arch_form(v):
    return v.replace("-beta.", "beta")


def tilde_form(v):
    return v.replace("-", "~", 1)


def badge_form(v):
    return v.replace("-", "--")


SITES = {
    "packaging/arch/PKGBUILD": (r"^pkgver=(\S+)$", arch_form),
    "packaging/rpm/juhradial-mx.spec": (r"^Version:\s*(\S+)$", tilde_form),
    "README.md": (r'img\.shields\.io/badge/version-(\S+?)-cyan\.svg', badge_form),
    ".github/SECURITY.md": (r"^\| (\S+)\s*\| :white_check_mark: Current release \|", str),
    "settings-qt/VERSION": (r"^(\S+)$", str),
    # The one-line installer downloads this release's tarball directly.
    "install.sh": (r'^RELEASE_VERSION="(\S+)"$', str),
}


@pytest.mark.parametrize("rel,pattern,form", [(rel, *site) for rel, site in SITES.items()])
def test_site_matches_cargo(rel, pattern, form):
    match = re.search(pattern, _read(rel), re.M)
    assert match, f"{rel}: version pattern not found"
    expected = form(cargo_version())
    assert match.group(1) == expected, f"{rel} says {match.group(1)}, expected {expected} for Cargo {cargo_version()}"


def test_readme_banner_matches_cargo():
    # The note under the badges names the release in prose; the badge alone
    # is easy to bump while this line keeps naming the previous beta.
    match = re.search(r"^> \*\*This is JuhRadial MX [^(]*\(`(\S+?)`\)\.\*\*", _read("README.md"), re.M)
    assert match, "README.md: release banner not found"
    assert match.group(1) == cargo_version(), f"README banner says {match.group(1)}, Cargo says {cargo_version()}"


@pytest.mark.parametrize("semver,arch,tilde,badge", [
    ("0.4.5", "0.4.5", "0.4.5", "0.4.5"),
    ("0.4.5-beta.1", "0.4.5beta1", "0.4.5~beta.1", "0.4.5--beta.1"),
])
def test_prerelease_forms(semver, arch, tilde, badge):
    assert (arch_form(semver), tilde_form(semver), badge_form(semver)) == (arch, tilde, badge)
    assert "-" not in arch_form(semver)


def test_flake_versions_match_cargo():
    versions = re.findall(r'version = "([^"]+)";', _read("flake.nix"))
    assert versions, "flake.nix has no version assignments"
    assert set(versions) == {cargo_version()}, f"flake.nix versions {versions} vs Cargo {cargo_version()}"


def test_rpm_changelog_has_entry_for_current_version():
    assert re.search(rf" - {re.escape(tilde_form(cargo_version()))}-1$", _read("packaging/rpm/juhradial-mx.spec"), re.M), (
        "packaging/rpm/juhradial-mx.spec %changelog lacks an entry for the current version"
    )


def test_metainfo_has_release_for_current_version():
    match = re.search(rf'<release version="{re.escape(tilde_form(cargo_version()))}"[^>]*>',
                      _read("packaging/org.juhlabs.JuhRadialMX.metainfo.xml"))
    assert match, "metainfo.xml lacks a <release> for the current version"
    assert ('type="development"' in match.group(0)) == is_prerelease(), (
        "a pre-release needs type=\"development\" on its <release>, a final release must not have it"
    )


def test_cargo_lock_matches_cargo_toml():
    lock = _read("daemon/Cargo.lock")
    match = re.search(r'name = "juhradiald"\nversion = "([^"]+)"', lock)
    assert match, "Cargo.lock has no juhradiald entry"
    assert match.group(1) == cargo_version(), "Cargo.lock is stale; run cargo build or scripts/bump-version.sh"
