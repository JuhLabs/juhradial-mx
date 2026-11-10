"""Hebrew catalog completeness: every msgid in both domains has a non-empty
msgstr (and, for plural entries, a non-empty msgstr[0] and msgstr[1]).

Run: python3 -m pytest tests/test_translations_he.py -q
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCALES = REPO / "overlay" / "locales"
_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unescape(s):
    return s.encode().decode("unicode_escape")


def _po_entries(path):
    """{msgid: [msgstr, msgstr[1], ...]} for every entry in a .po file.
    Comments are skipped; a blank line closes the current entry; a bare
    quoted-string line continues whichever keyword (msgid/msgstr[N]) was
    last seen, joining gettext's wrapped long strings back together."""
    entries = {}
    msgid, msgstrs, key = None, {}, None
    for raw in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw.strip()
        if line.startswith("#"):
            continue
        if not line:
            if msgid is not None:
                entries[msgid] = [msgstrs[k] for k in sorted(msgstrs)]
            msgid, msgstrs, key = None, {}, None
            continue
        if line.startswith('"') and key is not None:
            text = _unescape("".join(m.group(1) for m in _STR.finditer(line)))
            if key == "msgid":
                msgid = (msgid or "") + text
            else:
                msgstrs[key] = msgstrs.get(key, "") + text
            continue
        if line.startswith("msgid_plural "):
            key = None  # plural source text isn't needed for coverage
        elif line.startswith("msgid "):
            msgid, key = _unescape(_STR.search(line).group(1)), "msgid"
        elif line.startswith("msgstr["):
            idx = int(line[line.index("[") + 1:line.index("]")])
            msgstrs[idx] = _unescape(_STR.search(line).group(1))
            key = idx
        elif line.startswith("msgstr "):
            msgstrs[0] = _unescape(_STR.search(line).group(1))
            key = 0
    return entries


def test_hebrew_juhradial_catalog_is_fully_translated():
    entries = _po_entries(LOCALES / "he" / "LC_MESSAGES" / "juhradial.po")
    entries.pop("", None)  # the PO header entry
    missing = [k for k, v in entries.items() if not all(v)]
    assert not missing, f"{len(missing)} untranslated: {missing[:5]}"
    assert len(entries) >= 280


def test_hebrew_settings_catalog_is_fully_translated():
    entries = _po_entries(LOCALES / "he" / "LC_MESSAGES" / "juhradial-settings.po")
    entries.pop("", None)
    missing = [k for k, v in entries.items() if not all(v)]
    assert not missing, f"{len(missing)} untranslated: {missing[:5]}"
    assert len(entries) >= 1590
    plural_entries = {k: v for k, v in entries.items() if len(v) > 1}
    assert len(plural_entries) >= 13
    assert all(all(v) for v in plural_entries.values())
