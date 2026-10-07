"""What the installed Qt can load, and the QML variants that follow from it.

The settings app runs on Qt 6.4 and newer. Four things it draws with arrived
later, and Debian-family distributions package every QML module on its own, so
any of them can be absent on a new Qt as well:

    effects   QtQuick.Effects MultiEffect       Qt 6.5   frosted cards, ring glow
    curve     Shape.CurveRenderer               Qt 6.6   smooth arcs
    vector    QtQuick.VectorImage               Qt 6.8   spot illustrations
    shadow    QtQuick.Effects RectangularShadow Qt 6.9   shadows and glows
    dialogs   QtQuick.Dialogs FileDialog        Qt 6.2   import and export pickers

`install()` asks the engine itself (an import that resolves is the only proof)
and selects a stand-in for each one that is missing: a file under
`+no<name>/` next to the QML file it replaces (Qt file selectors). A missing
module then costs polish, never a blank page (issue #172).

`python3 compat.py` prints the same answers for the launcher and for bug
reports, and exits 1 when a module the app cannot start without is missing.
"""
import os
import re
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtQml import QQmlComponent, QQmlFileSelector

# name -> (imports, a declaration that only compiles when the feature exists)
OPTIONAL = {
    "effects": ("QtQuick.Effects", "MultiEffect {}"),
    "curve": ("QtQuick.Shapes", "Shape { preferredRendererType: Shape.CurveRenderer }"),
    "vector": ("QtQuick.VectorImage", "VectorImage {}"),
    "shadow": ("QtQuick.Effects", "RectangularShadow {}"),
    "dialogs": ("QtQuick.Dialogs", "FileDialog {}"),
}
# Without these the window cannot be built at all.
REQUIRED = {
    "QtQuick.Window": "Window {}",
    "QtQuick.Controls.Basic": "Button {}",
    "QtQuick.Layouts": "RowLayout {}",
    "QtQuick.Shapes": "Shape {}",
}
# Qt version a feature first shipped in: below it there is nothing to install.
SINCE = {"effects": (6, 5), "curve": (6, 6), "vector": (6, 8), "shadow": (6, 9), "dialogs": (6, 2)}
# The oldest Qt the QML is written for (Ubuntu 24.04, Linux Mint 22, Debian 12).
MIN_QT = (6, 4)


def _loads(engine, module, declaration):
    component = QQmlComponent(engine)
    component.setData(f"import QtQuick\nimport {module}\n{declaration}\n".encode(), QUrl())
    return component.status() == QQmlComponent.Status.Ready


def probe(engine):
    """{feature: bool} for every optional feature."""
    return {name: _loads(engine, *spec) for name, spec in OPTIONAL.items()}


def missing_required(engine):
    """QML modules the app cannot start without and this engine cannot import."""
    return [module for module, declaration in REQUIRED.items() if not _loads(engine, module, declaration)]


def selectors(caps):
    return ["no" + name for name, present in caps.items() if not present]


def install(engine, theme=None):
    """Probe `engine`, select the stand-ins and tell the theme. Returns the caps.

    Call it before a Python QTranslator is installed on the application: a
    failed import builds its message with tr() on the QML loader thread, and
    a Python translator called from there waits for the GIL this thread holds
    inside QQmlComponent.setData. That never returns.

    JUH_STANDINS=shadow,effects (names from OPTIONAL) treats those as missing,
    to look at or test the stand-ins on a Qt that has everything.
    """
    caps = probe(engine)
    for name in os.environ.get("JUH_STANDINS", "").split(","):
        if name.strip() in caps:
            caps[name.strip()] = False
    # Parented to the engine: the selector has to live as long as it does.
    QQmlFileSelector(engine, engine).setExtraSelectors(selectors(caps))
    if theme is not None:
        theme.setEffectsAvailable(caps["effects"])
    return caps


# ---- which package brings a QML module -------------------------------------

def _os_release(path="/etc/os-release"):
    fields = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                key, sep, value = line.strip().partition("=")
                if sep:
                    fields[key] = value.strip('"')
    except OSError:
        pass  # no os-release: the family stays unknown and no package is named
    return fields


def distro_family(os_release=None):
    """"debian", "fedora", "arch", "suse" or "" from os-release ID and ID_LIKE."""
    fields = _os_release() if os_release is None else os_release
    ids = (fields.get("ID", "") + " " + fields.get("ID_LIKE", "")).lower().split()
    for family, names in (("debian", ("debian", "ubuntu")), ("fedora", ("fedora", "rhel")),
                          ("arch", ("arch",)), ("suse", ("suse", "opensuse"))):
        if any(name in ids for name in names):
            return family
    return ""


def package_for(module, family=None):
    """The distribution package that ships QML `module`, or "" when unknown."""
    family = distro_family() if family is None else family
    if family == "debian":
        # One package per module; the Controls styles all sit in -controls.
        name = "QtQuick.Controls" if module.startswith("QtQuick.Controls") else module
        return "qml6-module-" + name.lower().replace(".", "-")
    return {"fedora": "qt6-qtdeclarative", "arch": "qt6-declarative", "suse": "qt6-declarative-imports"}.get(family, "")


def install_command(packages, family=None):
    family = distro_family() if family is None else family
    tool = {"debian": "sudo apt install", "fedora": "sudo dnf install",
            "arch": "sudo pacman -S", "suse": "sudo zypper install"}.get(family)
    packages = sorted(set(p for p in packages if p))
    return f"{tool} {' '.join(packages)}" if tool and packages else ""


_NOT_INSTALLED = re.compile(r'module "([^"]+)" is not installed')


def hint_for_error(text, family=None):
    """The install command for the QML modules a load error names, or ""."""
    modules = _NOT_INSTALLED.findall(text or "")
    return install_command([package_for(m, family) for m in modules], family)


def report(engine, qt_version):
    """(lines, ok): the state of this Qt for a terminal or a bug report."""
    version = tuple(int(x) for x in qt_version.split(".")[:2])
    if version < MIN_QT:
        return [f"Qt {qt_version}: the settings app needs Qt {MIN_QT[0]}.{MIN_QT[1]} or newer"], False
    caps = probe(engine)
    required = missing_required(engine)
    lines = [f"Qt {qt_version}"]
    for module in required:
        lines.append(f"  missing  {module} (required)")
    # A feature this Qt has but cannot load is a package that was not installed.
    installable = [name for name, present in caps.items() if not present and version >= SINCE[name]]
    for name, present in caps.items():
        state = "ok     " if present else ("missing" if name in installable else "n/a    ")
        note = "" if present or name in installable else f" (needs Qt {SINCE[name][0]}.{SINCE[name][1]}, a stand-in is used)"
        lines.append(f"  {state}  {name}: {OPTIONAL[name][0]}{note}")
    packages = [package_for(m) for m in required] + [package_for(OPTIONAL[n][0]) for n in installable]
    command = install_command(packages)
    if command:
        lines.append(f"  fix: {command}")
    return lines, not required


def main():
    from PyQt6.QtCore import QCoreApplication, qVersion
    from PyQt6.QtQml import QQmlEngine

    _ = QCoreApplication(sys.argv)  # _ keeps the reference for the engine's lifetime
    lines, ok = report(QQmlEngine(), qVersion())
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
