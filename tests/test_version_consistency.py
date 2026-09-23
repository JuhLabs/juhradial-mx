"""Every file that carries the JuhRadial MX version must agree with daemon/Cargo.toml.

Guards against the packaging drift seen on master (Cargo 0.4.4 while PKGBUILD,
the RPM spec and flake.nix still said 0.4.3, and SECURITY.md said 0.4.1).
scripts/bump-version.sh updates all of these sites in one go.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def cargo_version():
    match = re.search(r'^version = "(\d+\.\d+\.\d+)"', _read("daemon/Cargo.toml"), re.M)
    assert match, "daemon/Cargo.toml has no version line"
    return match.group(1)


SITES = {
    "packaging/arch/PKGBUILD": r"^pkgver=(\d+\.\d+\.\d+)$",
    "packaging/rpm/juhradial-mx.spec": r"^Version:\s*(\d+\.\d+\.\d+)$",
    "README.md": r'img\.shields\.io/badge/version-(\d+\.\d+\.\d+)-cyan\.svg',
    ".github/SECURITY.md": r"^\| (\d+\.\d+\.\d+)\s*\| :white_check_mark: Current release \|",
    "settings-qt/VERSION": r"^(\d+\.\d+\.\d+)$",
}


@pytest.mark.parametrize("rel,pattern", SITES.items())
def test_site_matches_cargo(rel, pattern):
    match = re.search(pattern, _read(rel), re.M)
    assert match, f"{rel}: version pattern not found"
    assert match.group(1) == cargo_version(), f"{rel} says {match.group(1)}, Cargo.toml says {cargo_version()}"


def test_flake_versions_match_cargo():
    versions = re.findall(r'version = "(\d+\.\d+\.\d+)";', _read("flake.nix"))
    assert versions, "flake.nix has no version assignments"
    assert set(versions) == {cargo_version()}, f"flake.nix versions {versions} vs Cargo {cargo_version()}"


def test_rpm_changelog_has_entry_for_current_version():
    assert re.search(rf" - {re.escape(cargo_version())}-1$", _read("packaging/rpm/juhradial-mx.spec"), re.M), (
        "packaging/rpm/juhradial-mx.spec %changelog lacks an entry for the current version"
    )


def test_metainfo_has_release_for_current_version():
    assert f'<release version="{cargo_version()}"' in _read("packaging/org.juhlabs.JuhRadialMX.metainfo.xml"), (
        "metainfo.xml lacks a <release> for the current version"
    )


def test_cargo_lock_matches_cargo_toml():
    lock = _read("daemon/Cargo.lock")
    match = re.search(r'name = "juhradiald"\nversion = "(\d+\.\d+\.\d+)"', lock)
    assert match, "Cargo.lock has no juhradiald entry"
    assert match.group(1) == cargo_version(), "Cargo.lock is stale; run cargo build or scripts/bump-version.sh"
