"""The settings app on older Qt and on partly installed Qt (issues #168, #172).

settings-qt/bridge/compat.py asks the engine what it can load and selects a
stand-in (a file under +no<name>/) for each optional feature that is missing.
These tests hold three things in place:

1. the answers: package names, the install command, the distro family;
2. the structure: only a file with a stand-in may import an optional module,
   so no page can go blank because one is missing;
3. the result: every page loads with every stand-in forced on.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtQml")

ROOT = Path(__file__).resolve().parents[1]
QT_DIR = ROOT / "settings-qt"
QML = QT_DIR / "qml"
sys.path.insert(0, os.fspath(QT_DIR))

from bridge import compat  # noqa: E402

IMPORT = re.compile(r"^import\s+([A-Za-z][A-Za-z0-9_.]*)", re.M)


def qml_files(variants):
    return [p for p in sorted(QML.rglob("*.qml")) if p.parent.name.startswith("+") == variants]


def test_debian_packages_follow_the_module_name():
    assert compat.package_for("QtQuick.VectorImage", "debian") == "qml6-module-qtquick-vectorimage"
    assert compat.package_for("QtQuick.Dialogs", "debian") == "qml6-module-qtquick-dialogs"
    assert compat.package_for("QtCore", "debian") == "qml6-module-qtcore"
    assert compat.package_for("Qt.labs.folderlistmodel", "debian") == "qml6-module-qt-labs-folderlistmodel"
    # Every Controls style ships in the one -controls package.
    assert compat.package_for("QtQuick.Controls.Basic", "debian") == "qml6-module-qtquick-controls"
    assert compat.package_for("QtQuick.Shapes", "fedora") == "qt6-qtdeclarative"
    assert compat.package_for("QtQuick.Shapes", "arch") == "qt6-declarative"
    assert compat.package_for("QtQuick.Shapes", "suse") == "qt6-declarative-imports"
    assert compat.package_for("QtQuick.Shapes", "") == ""


def test_the_hint_installs_every_module_the_error_names():
    # The two lines Kali printed for the blank tabs of issue #172.
    error = ('file:///usr/share/juhradial/settings-qt/qml/components/SpotImage.qml:2:1: '
             'module "QtQuick.VectorImage" is not installed\n'
             'file:///usr/share/juhradial/settings-qt/qml/pages/SettingsPage.qml:4:1: '
             'module "QtQuick.Dialogs" is not installed')
    assert compat.hint_for_error(error, "debian") == \
        "sudo apt install qml6-module-qtquick-dialogs qml6-module-qtquick-vectorimage"
    assert compat.hint_for_error(error, "fedora") == "sudo dnf install qt6-qtdeclarative"
    assert compat.hint_for_error(error, "") == ""
    assert compat.hint_for_error("Type Foo unavailable", "debian") == ""
    assert compat.hint_for_error("", "debian") == ""


@pytest.mark.parametrize("fields, family", [
    ({"ID": "kali", "ID_LIKE": "debian"}, "debian"),
    ({"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}, "debian"),
    ({"ID": "ubuntu", "ID_LIKE": "debian"}, "debian"),
    ({"ID": "debian"}, "debian"),
    ({"ID": "fedora"}, "fedora"),
    ({"ID": "bazzite", "ID_LIKE": "fedora"}, "fedora"),
    ({"ID": "nobara", "ID_LIKE": "rhel centos fedora"}, "fedora"),
    ({"ID": "arch"}, "arch"),
    ({"ID": "cachyos", "ID_LIKE": "arch"}, "arch"),
    ({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}, "suse"),
    ({"ID": "nixos"}, ""),
    ({}, ""),
])
def test_distro_family_comes_from_id_and_id_like(fields, family):
    assert compat.distro_family(fields) == family


def test_selectors_name_what_is_missing():
    caps = dict.fromkeys(compat.OPTIONAL, True)
    assert compat.selectors(caps) == []
    caps.update(vector=False, dialogs=False)
    assert compat.selectors(caps) == ["novector", "nodialogs"]
    # Every feature has the Qt release it arrived in, for the report.
    assert set(compat.SINCE) == set(compat.OPTIONAL)


def _engine():
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlEngine
    app = QGuiApplication.instance() or QGuiApplication([])
    return app, QQmlEngine()


def test_report_refuses_a_qt_below_the_floor():
    _app, engine = _engine()
    lines, ok = compat.report(engine, "6.3.2")
    assert not ok
    assert "6.4" in lines[0]


def test_report_on_this_qt_matches_the_probe():
    from PyQt6.QtCore import qVersion
    _app, engine = _engine()
    lines, ok = compat.report(engine, qVersion())
    assert ok == (not compat.missing_required(engine))
    for name, present in compat.probe(engine).items():
        line = next(line for line in lines if f" {name}: " in line)
        assert line.strip().startswith("ok") == present, line


def test_forcing_a_stand_in_reaches_the_theme(monkeypatch):
    from bridge.theme import Theme
    _app, engine = _engine()
    theme = Theme(probe_desktop=False)
    monkeypatch.setenv("JUH_STANDINS", "effects, shadow")
    caps = compat.install(engine, theme)
    assert caps["effects"] is False and caps["shadow"] is False
    # No blur without QtQuick.Effects: the cards are solid whatever the setting says.
    assert theme.effects is False
    assert theme.reduceTransparency is True
    assert theme.reduceTransparencySetting == theme._reduce


def test_only_files_with_a_stand_in_import_an_optional_module():
    """A page that imports QtQuick.Effects, VectorImage or Dialogs itself goes
    blank where that module is missing; a wrapper with a +no<name>/ twin does
    not. QtCore and the labs modules are not in the installer's package lists
    at all."""
    optional = {}
    for name, (module, _declaration) in compat.OPTIONAL.items():
        if module != "QtQuick.Shapes":  # required: only its curve renderer is optional
            optional.setdefault(module, []).append(name)
    problems = []
    for path in qml_files(variants=False):
        for module in IMPORT.findall(path.read_text(encoding="utf-8")):
            rel = path.relative_to(QML).as_posix()
            if module == "QtCore" or module.startswith(("Qt.labs", "Qt5Compat")):
                problems.append(f"{rel}: imports {module}, which the installers do not install")
            if module in optional and not any(
                    (path.parent / f"+no{name}" / path.name).is_file() for name in optional[module]):
                problems.append(f"{rel}: imports {module} without a stand-in under "
                                + " or ".join(f"+no{name}/" for name in optional[module]))
    assert not problems, "\n".join(problems)


def test_stand_ins_need_nothing_optional_themselves():
    optional = {module for module, _declaration in compat.OPTIONAL.values()} - {"QtQuick.Shapes"}
    for path in qml_files(variants=True):
        assert path.parent.name[1:].removeprefix("no") in compat.OPTIONAL, f"unknown selector: {path.parent.name}"
        assert (path.parent.parent / path.name).is_file(), f"{path}: stand-in without a base file"
        used = set(IMPORT.findall(path.read_text(encoding="utf-8"))) & optional
        assert not used, f"{path.relative_to(QML)}: a stand-in imports {sorted(used)}"


def test_every_page_loads_with_every_stand_in():
    """What Qt 6.4 and a Debian without the optional packages see, on any Qt."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", JUH_STANDINS=",".join(compat.OPTIONAL))
    result = subprocess.run([sys.executable, os.fspath(QT_DIR / "tools" / "qml_check.py")],
                            capture_output=True, text=True, env=env, timeout=240)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ALL OK" in result.stdout, output
    assert "stand-ins: " + ", ".join("no" + name for name in compat.OPTIONAL) in result.stdout, output


def test_the_launcher_and_the_tray_share_the_floor():
    floor = f"({compat.MIN_QT[0]}, {compat.MIN_QT[1]})"
    tray = (ROOT / "overlay" / "overlay_actions.py").read_text(encoding="utf-8")
    assert f'qVersion().split(".")[:2]) < {floor}' in tray
    launcher = (ROOT / "scripts" / "juhradial-settings.sh").read_text(encoding="utf-8")
    # The launcher asks compat.py; a second version number there would drift.
    assert "bridge/compat.py" in launcher
    assert "qVersion" not in launcher
