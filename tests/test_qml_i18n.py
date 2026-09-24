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
