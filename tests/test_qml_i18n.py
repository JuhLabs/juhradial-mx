#!/usr/bin/env python3
"""Qt settings UI i18n (0.4.4 GTK was translated; the Qt port shipped with 0
qsTr, audit P1 #8).

1. Lint: user-visible string literals in QML must go through qsTr(). Pages
   not converted yet are listed in ALLOWLIST; each tab pass removes its page.
2. Runtime: qsTr() in a real QQmlApplicationEngine resolves through the
   gettext-backed translator, and an untranslated string comes back unchanged
   (never empty, which would blank the UI).

Run: QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_qml_i18n.py -q
"""

import gettext
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtQml")

REPO = Path(__file__).resolve().parents[1]
QML = REPO / "settings-qt" / "qml"
sys.path.insert(0, os.fspath(REPO / "settings-qt"))

# Pages whose tab pass has not converted them yet (remove as they land).
ALLOWLIST = set()

PROPS = r"(?:text|title|subtitle|label|desc|body|placeholder|placeholderText|tip|error|ToolTip\.text|Accessible\.name|Accessible\.description)"
LITERAL = re.compile(r'^\s*(?:property\s+string\s+)?' + PROPS + r'\s*:\s*(.*)$')
CALL = re.compile(r'(?:toast\.show|Backend\.notify|undoToast)\(\s*"([^"]*)"')
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def bare_literals(text):
    """Line numbers of user-visible literals not wrapped in qsTr()."""
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        if "i18n-ignore" in line:
            continue
        code = line.split("//", 1)[0] if '"' not in line.split("//", 1)[0][-1:] else line
        m = LITERAL.match(code)
        if m:
            rhs = m.group(1)
            # strip qsTr("...") calls and comparisons ("x" === id)
            rhs = re.sub(r'qsTr\(\s*"(?:[^"\\]|\\.)*"', 'qsTr(', rhs)
            rhs = re.sub(r'[=!]==\s*"(?:[^"\\]|\\.)*"|"(?:[^"\\]|\\.)*"\s*[=!]==', '', rhs)
            for s in STRING.findall(rhs):
                if re.search(r"[A-Za-z]{2,}", s) and not s.startswith(("image://", "#", "qrc:", "file:")):
                    hits.append(n)
                    break
        for s in CALL.findall(code):
            if re.search(r"[A-Za-z]{2,}", s):
                hits.append(n)
    return hits


def test_linter_catches_and_exempts():
    assert bare_literals('    text: "Save"') == [1]
    assert bare_literals('    text: qsTr("Save")') == []
    assert bare_literals('    text: kind === "danger" ? qsTr("Bad") : ""') == []
    assert bare_literals('    title: "JuhRadial MX"  // i18n-ignore') == []
    assert bare_literals('    text: "%"') == []
    assert bare_literals('        toast.show("Saved", "info")') == [1]
    assert bare_literals('    property string title: "Pick"') == [1]


def test_every_converted_qml_file_is_translatable():
    offenders = {}
    for f in sorted(QML.rglob("*.qml")):
        rel = f.relative_to(QML).as_posix()
        if rel in ALLOWLIST:
            continue
        hits = bare_literals(f.read_text(encoding="utf-8"))
        if hits:
            offenders[rel] = hits
    assert offenders == {}, f"wrap these in qsTr(): {offenders}"


def test_allowlist_has_no_stale_entries():
    for rel in ALLOWLIST:
        assert (QML / rel).exists(), rel


class _FakeCatalog(gettext.NullTranslations):
    def gettext(self, message):
        return {"Undo": "Angre", "Settings": "Innstillinger"}.get(message, message)

    def pgettext(self, context, message):
        return self.gettext(message)


def test_qstr_resolves_through_the_gettext_translator(tmp_path):
    from PyQt6.QtCore import QCoreApplication, QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine
    from bridge.i18n import GettextTranslator

    app = QGuiApplication.instance() or QGuiApplication([])
    qml = tmp_path / "T.qml"
    qml.write_text('import QtQuick\nItem {\n property string a: qsTr("Undo")\n'
                   ' property string b: qsTr("Not in the catalog")\n'
                   ' property var m: ListModel { ListElement { label: qsTr("Settings") } }\n}\n')
    tr = GettextTranslator(_FakeCatalog())
    app.installTranslator(tr)
    try:
        engine = QQmlApplicationEngine()
        engine.load(QUrl.fromLocalFile(str(qml)))
        root = engine.rootObjects()[0]
        assert root.property("a") == "Angre"
        assert root.property("b") == "Not in the catalog"
        assert root.property("m").get(0).property("label").toString() == "Innstillinger"
    finally:
        QCoreApplication.removeTranslator(tr)


def test_plurals_read_right_without_a_catalog():
    from bridge.i18n import GettextTranslator
    tr = GettextTranslator(gettext.NullTranslations())
    assert tr.translate("x", "%n step(s)", None, 1) == "%n step"
    assert tr.translate("x", "%n step(s)", None, 3) == "%n steps"
    assert tr.translate("x", "Undo", None, -1) is None


def test_translator_domain_falls_back_to_the_overlay_catalog(tmp_path):
    from bridge import i18n

    def mo(domain, msgs):
        # Minimal GNU .mo writer (magic, rev 0, N, orig, trans, hash 0,0).
        import struct
        keys = sorted(msgs)
        ids = b"".join(k.encode() + b"\0" for k in keys)
        strs = b"".join(msgs[k].encode() + b"\0" for k in keys)
        n = len(keys)
        off_o, off_t = 28, 28 + n * 8
        base = 28 + n * 16
        o_tab, t_tab, pos = [], [], base
        for k in keys:
            o_tab.append((len(k.encode()), pos)); pos += len(k.encode()) + 1
        for k in keys:
            t_tab.append((len(msgs[k].encode()), pos)); pos += len(msgs[k].encode()) + 1
        data = struct.pack("<7I", 0x950412DE, 0, n, off_o, off_t, 0, 0)
        data += b"".join(struct.pack("<2I", *e) for e in o_tab)
        data += b"".join(struct.pack("<2I", *e) for e in t_tab)
        d = tmp_path / "nb" / "LC_MESSAGES"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{domain}.mo").write_bytes(data + ids + strs)

    mo(i18n.DOMAIN, {"Undo": "Angre"})
    mo(i18n.FALLBACK_DOMAIN, {"Haptics": "Haptikk"})
    t = i18n.load_translation("nb", [tmp_path])
    assert t.gettext("Undo") == "Angre"
    assert t.gettext("Haptics") == "Haptikk"
    assert t.gettext("Missing") == "Missing"


def test_configured_language(tmp_path):
    from bridge import i18n
    cfg = tmp_path / "config.json"
    for raw, want in [('{"language": "de"}', "de"), ('{"language": "system"}', None),
                      ('{"language": ""}', None), ("{}", None), ("not json", None)]:
        cfg.write_text(raw)
        assert i18n.configured_language(cfg) == want
    assert i18n.configured_language(tmp_path / "missing.json") is None


def test_template_holds_the_runtime_table_labels():
    # Button actions, haptic patterns, macro templates... reach the UI through
    # _(variable), which the literal scan cannot see.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "extract_strings", REPO / "settings-qt" / "tools" / "extract_strings.py")
    extract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extract)
    from bridge import backend
    found = extract.collect()
    for name, fields in extract.TABLES["bridge/backend.py"].items():
        table = getattr(backend, name)
        cells = (table.values() if fields is None
                 else [row[i] for row in table for i in fields])
        missing = [c for c in cells if c and extract._escape(c) not in found]
        assert not missing, f"{name}: {missing}"
    assert "Disabled" in found and "Sharp click" in found


def test_empty_python_string_is_not_the_catalog_header(monkeypatch):
    # Search rows with no section call _(""); gettext("") returns the header.
    from bridge import i18n
    monkeypatch.setattr(i18n, "_translation", i18n.load_translation("de"))
    assert "Project-Id-Version" in i18n._translation.gettext("")
    assert i18n._("") == ""
    assert i18n._("Disabled") == "Deaktiviert"


def test_hebrew_is_in_the_backend_language_list():
    from bridge.backend import LANGUAGES
    assert ("he", "עברית") in LANGUAGES


def test_is_rtl_language():
    from bridge.i18n import is_rtl_language, RTL_LANGUAGES
    from bridge.backend import LANGUAGES

    assert RTL_LANGUAGES == {"ar", "he"}
    for lang, _name in LANGUAGES:
        assert is_rtl_language(lang) == (lang in ("he", "ar"))


def test_layout_direction_for_explicit_languages():
    from PyQt6.QtCore import Qt
    from bridge.i18n import layout_direction_for
    from bridge.backend import LANGUAGES

    for lang, _name in LANGUAGES:
        expected = (Qt.LayoutDirection.RightToLeft if lang in ("he", "ar")
                    else Qt.LayoutDirection.LeftToRight)
        assert layout_direction_for(lang) == expected, lang


def test_layout_direction_for_system_follows_locale():
    from PyQt6.QtCore import QLocale
    from bridge.i18n import layout_direction_for

    assert layout_direction_for(None) == QLocale.system().textDirection()


def test_layout_mirroring_follows_application_direction(tmp_path):
    from PyQt6.QtCore import QUrl, Qt
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine
    from bridge.i18n import layout_direction_for
    from bridge.backend import LANGUAGES

    app = QGuiApplication.instance() or QGuiApplication([])
    qml = tmp_path / "M.qml"
    qml.write_text(
        "import QtQuick\n"
        "Item {\n"
        " LayoutMirroring.enabled: Qt.application.layoutDirection === Qt.RightToLeft\n"
        " LayoutMirroring.childrenInherit: true\n"
        " property bool mirrored: LayoutMirroring.enabled\n"
        "}\n")
    try:
        for lang, _name in LANGUAGES:
            app.setLayoutDirection(layout_direction_for(lang))
            engine = QQmlApplicationEngine()
            engine.load(QUrl.fromLocalFile(str(qml)))
            root = engine.rootObjects()[0]
            assert root.property("mirrored") == (lang in ("he", "ar")), lang
            engine.deleteLater()
    finally:
        app.setLayoutDirection(Qt.LayoutDirection.LeftToRight)


# --- RTL geometry of components that place children with an explicit x: ---
# LayoutMirroring mirrors anchors and Row/Grid order but never an explicit x
# binding, so each such binding has to mirror its own math. These load the
# real component files (the bug lives in their geometry), hosted under an
# Item with LayoutMirroring on or off.

COMPONENTS = QML / "components"
_APP = None


def _host(tmp_path, mirrored, body):
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine
    from bridge import compat
    from bridge.theme import Theme

    global _APP  # the app must outlive this call, or the engine has none
    _APP = QGuiApplication.instance() or QGuiApplication([])
    qml = tmp_path / f"Host_{int(mirrored)}.qml"
    qml.write_text(
        "import QtQuick\nimport QtQuick.Window\n"
        f'import "{QUrl.fromLocalFile(str(COMPONENTS)).toString()}"\n'
        "Window {\n width: 400; height: 80; visible: true\n"
        " Item {\n  anchors.fill: parent\n"
        f"  LayoutMirroring.enabled: {'true' if mirrored else 'false'}\n"
        "  LayoutMirroring.childrenInherit: true\n"
        f"{body}\n }}\n}}\n")
    engine = QQmlApplicationEngine()
    theme = Theme(probe_desktop=False)
    engine.rootContext().setContextProperty("Theme", theme)
    backend = _stub_backend()
    engine.rootContext().setContextProperty("Backend", backend)
    compat.install(engine, theme)  # registers +noshadow/+noeffects stand-ins, like main.py
    engine.load(QUrl.fromLocalFile(str(qml)))
    assert engine.rootObjects(), "host QML failed to load"
    engine._keep = (theme, backend)
    _settle()
    return engine


def _stub_backend():
    from PyQt6.QtCore import QObject, pyqtProperty, pyqtSlot

    class StubBackend(QObject):
        # Only what DpiControl reads: the sensor range and its snap.
        @pyqtProperty("QVariantMap", constant=True)
        def dpiRange(self):
            return {"min": 200, "max": 8000, "step": 50}

        @pyqtSlot(int, result=int)
        def snapDpi(self, v):
            return v
    return StubBackend()


def _settle(ms=600):
    # Let positioners polish and Behavior animations (knob x, pill x) finish.
    import time
    from PyQt6.QtCore import QCoreApplication
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def _find(engine, name):
    from PyQt6.QtQuick import QQuickItem
    obj = engine.rootObjects()[0].findChild(QQuickItem, name)
    assert obj is not None, name
    return obj


@pytest.mark.parametrize("mirrored", [False, True])
def test_slider_knob_sits_at_the_end_of_the_fill(tmp_path, mirrored):
    engine = _host(tmp_path, mirrored,
                   '  Slider { objectName: "sl"; width: 300; from: 0; to: 100;'
                   ' value: 20; showValue: true; suffix: "%" }')
    sl = _find(engine, "sl")
    track, fill, knob, label, ma = sl.childItems()
    assert track.width() < sl.width()  # the value label takes a share
    assert knob.width() == knob.height() == 18
    knob_c = knob.x() + knob.width() / 2
    fill_l, fill_r = fill.x(), fill.x() + fill.width()
    if mirrored:
        # anchors mirrored: track hugs the right, fill grows leftward from it
        assert fill_r == pytest.approx(track.x() + track.width())
        assert label.x() < track.x()
        leading = fill_l
    else:
        assert fill_l == pytest.approx(track.x())
        leading = fill_r
    assert abs(knob_c - leading) <= knob.width() / 2, (mirrored, knob_c, fill_l, fill_r)
    # and the knob is over the track, at the fill's moving end
    assert track.x() <= knob_c <= track.x() + track.width()

    # pressing at the fill's moving end reads back the same value (drag math)
    from PyQt6.QtCore import QMetaObject, Q_ARG, QVariant
    QMetaObject.invokeMethod(ma, "setAt", Q_ARG(QVariant, leading))
    assert sl.property("shown") == pytest.approx(20, abs=0.5), mirrored
    engine.deleteLater()


@pytest.mark.parametrize("mirrored", [False, True])
def test_dpi_ticks_line_up_with_the_slider_knob(tmp_path, mirrored):
    from PyQt6.QtQuick import QQuickItem
    engine = _host(tmp_path, mirrored,
                   '  DpiControl { objectName: "dc"; width: 400; value: 800;'
                   ' presets: [800, 3200] }')
    sl = None
    for o in engine.rootObjects()[0].findChildren(QQuickItem):
        if o.property("stepSize") is not None and o.property("pageStep") == 500:
            sl = o
            break
    assert sl is not None
    rng = sl.property("to") - sl.property("from")
    assert rng > 0
    _track, fill, knob = sl.childItems()[:3]
    knob_c = knob.x() + knob.width() / 2
    # the knob rides the fill's moving end (left end once mirrored) ...
    leading = fill.x() if mirrored else fill.x() + fill.width()
    assert abs(knob_c - leading) <= knob.width() / 2, (mirrored, knob_c, leading)
    ticks = [c for c in sl.childItems() if c.width() == 2 and c.height() == 7]
    assert len(ticks) == 2
    tick_c = {round(c.x() + 1) for c in ticks}
    # ... and the 800 tick sits under the knob (value 800)
    assert min(abs(t - knob_c) for t in tick_c) <= 1.5, (mirrored, knob_c, tick_c)
    engine.deleteLater()


@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("current", ["a", "c"])
def test_segmented_pill_sits_under_the_selected_segment(tmp_path, mirrored, current):
    engine = _host(tmp_path, mirrored,
                   '  SegmentedControl { objectName: "seg"; width: 300;'
                   f' currentId: "{current}";'
                   ' model: [{id: "a", name: "A"}, {id: "b", name: "B"}, {id: "c", name: "C"}] }')
    seg = _find(engine, "seg")
    pill = [c for c in seg.childItems() if c.width() == pytest.approx(100 - 4)]
    assert len(pill) == 1
    pill = pill[0]
    row = seg.childItems()[-1]
    segs = {c.property("modelData")["id"]: c
            for c in row.childItems() if c.property("modelData") is not None}
    assert set(segs) == {"a", "b", "c"}
    # the Row really mirrors: "a" is leftmost in LTR, rightmost in RTL
    assert (segs["a"].x() > segs["c"].x()) == mirrored
    sel = segs[current]
    assert pill.x() == pytest.approx(sel.x() + 2), (mirrored, current, pill.x(), sel.x())
    engine.deleteLater()
