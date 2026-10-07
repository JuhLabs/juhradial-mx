"""Debian-family systems package every QML module on its own (issue #172).

The installer's Debian step and the .deb named nine QML packages while the
settings app imported three more modules, so on Kali most Settings tabs came
up empty. Every module the QML imports must have its package in the
installer's lists and in the .deb's dependencies, and a module that older
releases do not have must sit in the optional list, or one missing package
fails the whole apt transaction.
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "settings-qt" / "qml"
sys.path.insert(0, os.fspath(ROOT / "settings-qt"))

from bridge import compat  # noqa: E402

IMPORT = re.compile(r"^import\s+([A-Za-z][A-Za-z0-9_.]*)", re.M)
# Packages a module needs besides its own: what it imports internally.
ALSO = {
    "QtQuick": ["qml6-module-qtqml", "qml6-module-qtqml-workerscript"],
    "QtQuick.Controls.Basic": ["qml6-module-qtquick-templates"],
    "QtQuick.Dialogs": ["qml6-module-qt-labs-folderlistmodel"],
}


def imported_modules():
    modules = set()
    for path in QML.rglob("*.qml"):
        modules.update(IMPORT.findall(path.read_text(encoding="utf-8")))
    return modules


def shell_list(text, name):
    match = re.search(rf'^{name}="((?:[^"\\]|\\.)*)"', text, re.M | re.S)
    assert match, f"{name} is not a plain assignment in install.sh"
    return match.group(1).replace("\\\n", " ").split()


def installer_lists():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    return shell_list(text, "DEBIAN_QML_PKGS"), shell_list(text, "DEBIAN_QML_OPTIONAL_PKGS")


def newer_than_the_floor(module):
    """Whether `module` itself arrived after the oldest Qt the app runs on."""
    return any(spec[0] == module and compat.SINCE[name] > compat.MIN_QT
               and module not in compat.REQUIRED for name, spec in compat.OPTIONAL.items())


def test_the_app_imports_what_this_test_expects():
    # A new import must be placed in a list on purpose: extend this set with it.
    assert imported_modules() == {
        "QtQuick", "QtQuick.Window", "QtQuick.Layouts", "QtQuick.Shapes", "QtQuick.Templates",
        "QtQuick.Controls.Basic", "QtQuick.Effects", "QtQuick.VectorImage", "QtQuick.Dialogs",
    }


def test_installer_installs_every_imported_module():
    required, optional = installer_lists()
    for module in sorted(imported_modules()):
        package = compat.package_for(module, "debian")
        if newer_than_the_floor(module):
            assert package in optional, f"{module}: {package} must be optional, older releases lack it"
            assert package not in required, f"{module}: {package} would fail apt on older releases"
        else:
            assert package in required, f"{module}: {package} is missing from DEBIAN_QML_PKGS"
        for extra in ALSO.get(module, []):
            assert extra in required, f"{module} also needs {extra}"
    assert {"python3-pyqt6.qtqml", "python3-pyqt6.qtquick"} <= set(required)


def test_installer_lists_stay_plain_and_adjacent():
    # CI evaluates exactly these two assignments to install what the installer installs.
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    block = re.search(r'^DEBIAN_QML_PKGS=".*?^DEBIAN_QML_OPTIONAL_PKGS="[^"\n]*"$', text, re.M | re.S)
    assert block, "the two lists must follow each other"
    assert "$" not in block.group(0) and "`" not in block.group(0), "no expansions inside the lists"
    assert "install -y $DEBIAN_QML_PKGS" in text
    assert "for pkg in $DEBIAN_QML_OPTIONAL_PKGS" in text


def test_deb_names_every_imported_module():
    control = (ROOT / "packaging" / "deb" / "build-deb.sh").read_text(encoding="utf-8")
    named = set()
    for field in ("Depends", "Recommends"):
        line = re.search(rf"^{field}: (.*)$", control, re.M)
        named.update(p.strip() for p in line.group(1).split(","))
    required, optional = installer_lists()
    missing = sorted(set(required + optional) - named)
    assert not missing, f"packaging/deb/build-deb.sh does not name: {missing}"
