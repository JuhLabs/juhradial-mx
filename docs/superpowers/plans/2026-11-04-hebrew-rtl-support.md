# Hebrew Language + RTL Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Hebrew as a full language (translated strings + right-to-left layout) across the Qt Settings app and the overlay package (GTK settings dashboard + PyQt6 tray menu), without disturbing the 18 existing LTR languages.

**Architecture:** One RTL mechanism per toolkit, each keyed off the same `language` value from `config.json`: Qt Quick's built-in `LayoutMirroring` for the Qt Settings app's QML, `Gtk.Widget.set_default_direction` for the GTK settings dashboard, and `QApplication.setLayoutDirection` for the overlay's PyQt6 tray `QMenu`. Each app defines its own small `RTL_LANGUAGES` set (duplicated per the existing two-independent-language-lists pattern) and a pure function that resolves a configured language to that toolkit's direction enum, so the mechanism itself is unit-testable without needing a real window.

**Tech Stack:** PyQt6 (Qt Quick/QML Settings app, overlay tray + radial menu), GTK4/Adwaita (overlay settings dashboard), Python `gettext` (both translation domains), `pytest`.

**Spec:** `docs/superpowers/specs/2026-11-04-hebrew-rtl-support-design.md` — **read this plan's own "GTK RTL mechanism" and Goals corrections in the spec first**; they record a real finding from plan writing (the overlay's tray menu and radial pie-menu chrome are PyQt6, not GTK, contradicting the spec's original builder-check conclusion) and the scope decision that followed it.

## Global Constraints

- `RTL_LANGUAGES = frozenset({"ar", "he"})`, defined once per app (one copy in `settings-qt/bridge/i18n.py`, one copy in `overlay/i18n.py`) — not a shared cross-package import, matching the existing duplicated `LANGUAGES`/`SUPPORTED_LANGUAGES` pattern.
- Hebrew language code is `"he"`, display name `"עברית"`, inserted alphabetically after `"fr"`/before `"hi"` in `settings-qt/bridge/backend.py`'s `LANGUAGES`, and after `"hi"` in `overlay/i18n.py`'s `SUPPORTED_LANGUAGES`.
- `tests/test_qml_i18n.py` must stay green throughout — it is the existing safety net for the Qt Settings app's translator pipeline.
- `settings-qt/qml/Main.qml` has a single root `ApplicationWindow` (`id: win`) — the one place the Qt Quick `LayoutMirroring` switch goes; no per-file QML rewrite for `anchors.left`/`anchors.right`.
- The GTK settings dashboard (`overlay/settings_dashboard.py` + `settings_page_*.py`/`settings_dialog_*.py`) is GTK4/Adwaita (`gi.require_version("Gtk", "4.0")`). The overlay's tray icon, `QMenu`, and radial pie-menu chrome (`overlay/juhradial-overlay.py`, `overlay/overlay_tray.py`, `RadialMenuPaintingMixin`) are PyQt6 Widgets and import zero `gi`/GTK. These are two different toolkits sharing one `overlay/i18n.py`; neither GTK call reaches the other toolkit's widgets.
- The hand-painted radial pie-menu chrome itself is **out of scope** for RTL mirroring this pass (scope decision made during planning — see the amended spec). Only the tray `QMenu` gets PyQt6 RTL.
- `msginit`/`msgmerge`/`msgfmt` are required for Task 4 and are not installed in this sandbox (`gettext` package available via `dnf`, not yet installed as of plan-writing). Task 4's first step is the install.
- `juhradial.pot` currently has 287 `msgid` entries (286 real + the header); `juhradial-settings.pot` has 1598 (1597 real + header), including 13 `msgid_plural` entries. Exact counts as measured during planning — re-measure if either `.pot` has changed before Task 4 runs (`grep -c '^msgid ' overlay/locales/<domain>.pot`).
- Hebrew's `Plural-Forms` header: `"nplurals=2; plural=(n != 1);\n"` (the same two-slot convention this codebase already uses for every other language's plural entries, English-style, not CLDR-accurate Hebrew grammar — matches the existing catalogs' own simplification).
- The Qt Settings app's language picker already requires a restart to apply (`Backend.languageNeedsRestart`) — layout direction is computed once at process startup in `settings-qt/main.py`, consistent with that existing behavior; no live-reload wiring needed there.

## Review Focus

- Switching between Hebrew and another language *without* a process restart must not leave a toolkit's default direction stuck RTL (`Gtk.Widget.set_default_direction` / `QApplication.setLayoutDirection` are both global, static, and don't auto-reset) — Task 3's `setup_i18n()` test exercises an explicit he→en switch in one process.
- The 13 `msgid_plural` entries in `juhradial-settings.pot` need real `msgstr[0]`/`msgstr[1]` Hebrew text, not just overall msgid coverage — a flat "does *a* msgstr exist" check can pass while a plural slot stays empty. Task 4's coverage test checks every plural slot individually.
- A partially-filled Hebrew catalog (a `msgid` with `msgstr ""`) must still show the English source text, never a blank label — already guaranteed by `fallback=True` + `GettextTranslator`'s "never return empty string" contract (`settings-qt/bridge/i18n.py`), re-verified against the real `he` catalog's RED state in Task 4.
- The GTK settings dashboard launched fresh (not reached via an in-app language change) with `"language": "he"` already in `config.json` must come up RTL on first paint, not only after an explicit reload — Task 3's test calls `setup_i18n()` directly (the same path the module-import-time side effect takes), not only `reload_language()`.
- Both `LANGUAGES` lists (`backend.py`, `overlay/i18n.py`) must each gain exactly one `he` entry, keeping the two independently-maintained pickers in sync — pinned by Task 1's tests.

---

### Task 1: Hebrew language-picker entries + `RTL_LANGUAGES` constants

**Files:**
- Modify: `settings-qt/bridge/backend.py:581-586` (`LANGUAGES`)
- Modify: `settings-qt/bridge/i18n.py` (add `RTL_LANGUAGES`, `is_rtl_language`)
- Modify: `overlay/i18n.py` (add `"he"` to `SUPPORTED_LANGUAGES`, add `RTL_LANGUAGES`)
- Test: `tests/test_qml_i18n.py` (Qt-side additions)
- Test: `tests/test_overlay_i18n.py` (new file, overlay-side additions)

**Interfaces:**
- Produces: `settings_qt.bridge.i18n.RTL_LANGUAGES: frozenset[str]`, `settings_qt.bridge.i18n.is_rtl_language(language: str) -> bool`; `overlay.i18n.RTL_LANGUAGES: frozenset[str]`. Tasks 2 and 3 consume these.

- [ ] **Step 1: Write the failing Qt-side tests**

Append to `tests/test_qml_i18n.py`:

```python
def test_hebrew_is_in_the_backend_language_list():
    from bridge.backend import LANGUAGES
    assert ("he", "עברית") in LANGUAGES


def test_is_rtl_language():
    from bridge.i18n import is_rtl_language, RTL_LANGUAGES
    from bridge.backend import LANGUAGES

    assert RTL_LANGUAGES == {"ar", "he"}
    for lang, _name in LANGUAGES:
        assert is_rtl_language(lang) == (lang in ("he", "ar"))
```

- [ ] **Step 2: Run the Qt-side tests, confirm they fail**

Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_qml_i18n.py -k "hebrew_is_in_the_backend or is_rtl_language" -v` (from `settings-qt/`, i.e. with `settings-qt` on `sys.path` as the file's own header already arranges)
Expected: FAIL — `AssertionError` (`he` not in `LANGUAGES`) then `ImportError: cannot import name 'is_rtl_language'`.

- [ ] **Step 3: Add the Hebrew entry and `RTL_LANGUAGES`/`is_rtl_language` to the Qt side**

In `settings-qt/bridge/backend.py:581-586`, insert `("he", "עברית")` between the `("fr", "Français")` and `("hi", "हिन्दी")` tuples.

In `settings-qt/bridge/i18n.py`, after the `CONFIG_PATH` assignment, add:

```python
RTL_LANGUAGES = frozenset({"ar", "he"})


def is_rtl_language(language: str) -> bool:
    """True for an explicit RTL language code."""
    return language in RTL_LANGUAGES
```

- [ ] **Step 4: Run the Qt-side tests, confirm they pass**

Run: same command as Step 2
Expected: PASS (2 passed)

- [ ] **Step 5: Write the failing overlay-side tests**

Create `tests/test_overlay_i18n.py`:

```python
"""Overlay package language entries: the Hebrew picker entry and
RTL_LANGUAGES shared by the GTK settings dashboard and the PyQt6 tray app.

Run: python3 -m pytest tests/test_overlay_i18n.py -q
"""
import sys

sys.path.insert(0, "overlay")

from i18n import SUPPORTED_LANGUAGES, RTL_LANGUAGES


def test_hebrew_is_a_supported_language():
    assert SUPPORTED_LANGUAGES.get("he") == "עברית"


def test_rtl_languages_set():
    assert RTL_LANGUAGES == {"ar", "he"}
    for lang in SUPPORTED_LANGUAGES:
        if lang == "system":
            continue
        assert (lang in RTL_LANGUAGES) == (lang in ("he", "ar"))
```

- [ ] **Step 6: Run the overlay-side tests, confirm they fail**

Run: `python3 -m pytest tests/test_overlay_i18n.py -v` (from the repo root)
Expected: FAIL — `AssertionError` (`"he"` missing from `SUPPORTED_LANGUAGES`) then `ImportError: cannot import name 'RTL_LANGUAGES'`.

- [ ] **Step 7: Add the Hebrew entry and `RTL_LANGUAGES` to the overlay side**

In `overlay/i18n.py`'s `SUPPORTED_LANGUAGES` dict, add `"he": "עברית",` immediately after the `"hi": "हिन्दी",` line.

After the `SUPPORTED_LANGUAGES` dict, add:

```python
RTL_LANGUAGES = frozenset({"ar", "he"})
```

- [ ] **Step 8: Run the overlay-side tests, confirm they pass**

Run: same command as Step 6
Expected: PASS (2 passed)

- [ ] **Step 9: Commit**

```bash
git add settings-qt/bridge/backend.py settings-qt/bridge/i18n.py overlay/i18n.py \
        tests/test_qml_i18n.py tests/test_overlay_i18n.py
git commit -m "feat(i18n): add Hebrew language entry and RTL_LANGUAGES constants"
```

---

### Task 2: Qt Settings app RTL mechanism

**Files:**
- Modify: `settings-qt/bridge/i18n.py` (add `layout_direction_for`)
- Modify: `settings-qt/main.py` (import + one call near `install_translator`)
- Modify: `settings-qt/qml/Main.qml` (root `LayoutMirroring`)
- Modify: `settings-qt/qml/components/Slider.qml:94`, `settings-qt/qml/pages/ScrollPage.qml:140-144`, `settings-qt/qml/pages/DevicesPage.qml:168` (one-line comments, no behavior change)
- Test: `tests/test_qml_i18n.py`

**Interfaces:**
- Consumes: `bridge.i18n.RTL_LANGUAGES`, `bridge.i18n.is_rtl_language` (Task 1); `bridge.i18n.configured_language(config_path=CONFIG_PATH) -> str | None` (already exists — `None` means "system").
- Produces: `settings_qt.bridge.i18n.layout_direction_for(language: str | None) -> PyQt6.QtCore.Qt.LayoutDirection`. No later task consumes this directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_qml_i18n.py`:

```python
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
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_qml_i18n.py -k "layout_direction_for or layout_mirroring" -v`
Expected: FAIL — `ImportError: cannot import name 'layout_direction_for'` on the first test.

- [ ] **Step 3: Implement `layout_direction_for`**

In `settings-qt/bridge/i18n.py`, after `is_rtl_language`, add:

```python
def layout_direction_for(language):
    """Qt.LayoutDirection for the configured language: RTL_LANGUAGES decides
    an explicit override outright; None ("system", from configured_language)
    defers to the system locale's own direction."""
    from PyQt6.QtCore import QLocale, Qt

    if language is None:
        return QLocale.system().textDirection()
    return (Qt.LayoutDirection.RightToLeft if is_rtl_language(language)
            else Qt.LayoutDirection.LeftToRight)
```

- [ ] **Step 4: Wire it into the Qt Settings app startup and the QML root**

In `settings-qt/main.py`, change the import line:

```python
from bridge.i18n import install_translator  # noqa: E402
```

to:

```python
from bridge.i18n import install_translator, configured_language, layout_direction_for  # noqa: E402
```

Right after `_ = install_translator(app)  # qsTr() -> gettext catalogs; _ keeps the reference for the app's lifetime` in `main()`, add:

```python
    app.setLayoutDirection(layout_direction_for(configured_language()))
```

In `settings-qt/qml/Main.qml`, inside the root `ApplicationWindow` block, right after `font.family: Theme.fontUI`, add:

```qml
    LayoutMirroring.enabled: Qt.application.layoutDirection === Qt.RightToLeft
    LayoutMirroring.childrenInherit: true
```

- [ ] **Step 5: Run the tests, confirm they pass**

Run: same command as Step 2
Expected: PASS (3 passed)

- [ ] **Step 6: Comment the three numeric readouts that stay LTR-aligned on purpose**

No test — comment-only, no behavior change (the text and its anchors still mirror via `LayoutMirroring`; only the explicit `Text.AlignRight` they already carry is being explained, not altered).

In `settings-qt/qml/components/Slider.qml`, immediately above line 94 (`horizontalAlignment: Text.AlignRight`), add:

```qml
                // Numeric value readout: stays right-aligned even when the page mirrors for RTL.
```

In `settings-qt/qml/pages/ScrollPage.qml`, the existing comment at line 140 (`// Right-aligned mono readout: every number on the page lines up.`) already explains the component above line 144's `horizontalAlignment: Text.AlignRight`; extend it in place to:

```qml
    // Right-aligned mono readout: every number on the page lines up, even when
    // the page mirrors for RTL.
```

In `settings-qt/qml/pages/DevicesPage.qml`, immediately above line 168 (`horizontalAlignment: Text.AlignRight`), add:

```qml
            // Numeric readout: stays right-aligned even when the page mirrors for RTL.
```

- [ ] **Step 7: Commit**

```bash
git add settings-qt/bridge/i18n.py settings-qt/main.py settings-qt/qml/Main.qml \
        settings-qt/qml/components/Slider.qml settings-qt/qml/pages/ScrollPage.qml \
        settings-qt/qml/pages/DevicesPage.qml tests/test_qml_i18n.py
git commit -m "feat(settings-qt): mirror QML layout for Hebrew/Arabic via LayoutMirroring"
```

---

### Task 3: Overlay package RTL mechanism (GTK settings dashboard + PyQt6 tray)

**Files:**
- Modify: `overlay/i18n.py` (add `gtk_direction_for`, `qt_direction_for`, `apply_platform_direction`, wire into `setup_i18n`)
- Modify: `overlay/juhradial-overlay.py` (apply direction once the tray `QApplication` exists)
- Test: `tests/test_overlay_i18n.py`

**Interfaces:**
- Consumes: `overlay.i18n.RTL_LANGUAGES` (Task 1); `overlay.i18n.get_configured_language() -> str` (already exists, returns `"system"` or an explicit code, never `None`).
- Produces: `overlay.i18n.gtk_direction_for(lang: str) -> Gtk.TextDirection`, `overlay.i18n.qt_direction_for(lang: str) -> PyQt6.QtCore.Qt.LayoutDirection`, `overlay.i18n.apply_platform_direction(lang: str) -> None`. No later task consumes these directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_overlay_i18n.py`:

```python
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

import pytest


@pytest.fixture(autouse=True)
def _restore_gtk_direction():
    original = Gtk.Widget.get_default_direction()
    yield
    Gtk.Widget.set_default_direction(original)


def test_gtk_direction_for_explicit_languages():
    from i18n import gtk_direction_for

    assert gtk_direction_for("he") == Gtk.TextDirection.RTL
    assert gtk_direction_for("ar") == Gtk.TextDirection.RTL
    assert gtk_direction_for("en") == Gtk.TextDirection.LTR


def test_gtk_direction_for_system_follows_locale_direction():
    from i18n import gtk_direction_for

    assert gtk_direction_for("system") == Gtk.get_locale_direction()


def test_qt_direction_for_explicit_languages():
    from PyQt6.QtCore import Qt
    from i18n import qt_direction_for

    assert qt_direction_for("he") == Qt.LayoutDirection.RightToLeft
    assert qt_direction_for("ar") == Qt.LayoutDirection.RightToLeft
    assert qt_direction_for("en") == Qt.LayoutDirection.LeftToRight


def test_qt_direction_for_system_follows_locale_direction():
    from PyQt6.QtCore import QLocale
    from i18n import qt_direction_for

    assert qt_direction_for("system") == QLocale.system().textDirection()


def test_setup_i18n_sets_and_resets_gtk_direction_on_language_switch(monkeypatch, tmp_path):
    import i18n as i18n_module

    cfg = tmp_path / "config.json"
    monkeypatch.setattr(i18n_module, "CONFIG_FILE", cfg)

    cfg.write_text('{"language": "he"}')
    i18n_module.setup_i18n()
    assert Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL

    cfg.write_text('{"language": "en"}')
    i18n_module.setup_i18n()
    assert Gtk.Widget.get_default_direction() == Gtk.TextDirection.LTR
```

- [ ] **Step 2: Run the tests, confirm they fail**

Run: `python3 -m pytest tests/test_overlay_i18n.py -k "direction" -v` (from the repo root)
Expected: FAIL — `ImportError: cannot import name 'gtk_direction_for'` on the first test.

- [ ] **Step 3: Implement the direction functions and wire them into `setup_i18n`**

In `overlay/i18n.py`, after the `RTL_LANGUAGES` constant (Task 1), add:

```python
def gtk_direction_for(lang: str):
    """Gtk.TextDirection for the configured language: RTL_LANGUAGES decides
    an explicit override outright; "system" defers to the process locale
    GTK itself would read (setup_i18n already ran locale.setlocale for that
    branch). Imports gi lazily so a process that never touches GTK (the
    PyQt6 tray app) never gains it as a hard dependency."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    if lang == "system":
        return Gtk.get_locale_direction()
    return Gtk.TextDirection.RTL if lang in RTL_LANGUAGES else Gtk.TextDirection.LTR


def qt_direction_for(lang: str):
    """PyQt6 Qt.LayoutDirection for the configured language, mirroring
    gtk_direction_for's rule for the overlay's own QApplication (tray menu).
    Imports PyQt6.QtCore lazily, same reasoning as gtk_direction_for."""
    from PyQt6.QtCore import QLocale, Qt

    if lang == "system":
        return QLocale.system().textDirection()
    return (Qt.LayoutDirection.RightToLeft if lang in RTL_LANGUAGES
            else Qt.LayoutDirection.LeftToRight)


def apply_platform_direction(lang: str) -> None:
    """Set the default direction of every GUI toolkit this process has
    already loaded. Checked via sys.modules, not import, so a process using
    only one toolkit never gains the other as a dependency: the GTK settings
    dashboard never imports PyQt6, the PyQt6 tray app never imports GTK."""
    import sys

    if "gi.repository.Gtk" in sys.modules:
        from gi.repository import Gtk
        Gtk.Widget.set_default_direction(gtk_direction_for(lang))
    if "PyQt6.QtWidgets" in sys.modules:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(qt_direction_for(lang))
```

In `setup_i18n()`, right after `lang = get_configured_language()`, add:

```python
    apply_platform_direction(lang)
```

- [ ] **Step 4: Run the tests, confirm they pass**

Run: same command as Step 2
Expected: PASS (5 passed)

- [ ] **Step 5: Apply the direction once the overlay's own `QApplication` exists**

`setup_i18n()`'s module-import-time call (`_ = setup_i18n()` at the bottom of `overlay/i18n.py`) runs before `juhradial-overlay.py` constructs its `QApplication`, so `apply_platform_direction`'s `QApplication.instance()` check is `None` at that point and the Qt branch no-ops. Re-run `setup_i18n()` once the app exists.

In `overlay/juhradial-overlay.py`, right after `app.setDesktopFileName("juhradial-mx")` inside the `if __name__ == "__main__":` block, add:

```python
    from i18n import setup_i18n

    _ = setup_i18n()  # re-run now that QApplication exists, to set this app's text direction
```

- [ ] **Step 6: Commit**

```bash
git add overlay/i18n.py overlay/juhradial-overlay.py tests/test_overlay_i18n.py
git commit -m "feat(overlay): set GTK and PyQt6 default direction from the configured language"
```

---

### Task 4: Hebrew translation catalogs

**Files:**
- Create: `overlay/locales/he/LC_MESSAGES/juhradial.po`, `overlay/locales/he/LC_MESSAGES/juhradial.mo`
- Create: `overlay/locales/he/LC_MESSAGES/juhradial-settings.po`, `overlay/locales/he/LC_MESSAGES/juhradial-settings.mo`
- Test: `tests/test_translations_he.py` (new file)

**Interfaces:**
- Consumes: `overlay/locales/juhradial.pot`, `overlay/locales/juhradial-settings.pot` (already exist, regenerated by `scripts/update-translations.sh` / `settings-qt/tools/extract_strings.py` respectively — not touched by this task).
- Produces: the two `.po`/`.mo` catalog pairs. No later task consumes them programmatically (Task 5 screenshots them).

- [ ] **Step 1: Install gettext tooling if missing**

Run: `command -v msginit msgmerge msgfmt || sudo dnf install gettext`
Expected: all three print a path (install may prompt for a sudo password the first time).

- [ ] **Step 2: Write the failing coverage test**

Create `tests/test_translations_he.py`:

```python
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
```

- [ ] **Step 3: Run the test, confirm it fails**

Run: `python3 -m pytest tests/test_translations_he.py -v`
Expected: FAIL — both tests raise `FileNotFoundError` (no `he/LC_MESSAGES/*.po` yet).

- [ ] **Step 4: Seed the Hebrew `.po` files from the `.pot` templates**

```bash
mkdir -p overlay/locales/he/LC_MESSAGES
msginit --no-translator --locale=he --input=overlay/locales/juhradial.pot \
    --output=overlay/locales/he/LC_MESSAGES/juhradial.po
msginit --no-translator --locale=he --input=overlay/locales/juhradial-settings.pot \
    --output=overlay/locales/he/LC_MESSAGES/juhradial-settings.po
```

Open each generated `.po`'s header and confirm the `Plural-Forms` line reads `"nplurals=2; plural=(n != 1);\n"` (msginit derives this from the `he` locale; if it differs, replace it with that exact value — the Global Constraints section pins it to match every other catalog's plural slot count).

- [ ] **Step 5: Run the test, confirm it still fails, now for content not for missing files**

Run: same command as Step 3
Expected: FAIL — `AssertionError` listing every msgid as untranslated (msginit seeds every `msgstr` as `""`).

- [ ] **Step 6: Fill in the Hebrew translations**

For every `msgid` (and both plural slots of the 13 `msgid_plural` entries) in both `.po` files, write idiomatic Hebrew matching the tone/register of the existing catalogs (compare `overlay/locales/ar/LC_MESSAGES/*.po` and `overlay/locales/de/LC_MESSAGES/*.po` for register — technical, direct, matching the English source's level of formality). This is the content-generation step the spec calls for; there is no code signature here, only the two `.po` files' `msgstr` lines.

- [ ] **Step 7: Compile the `.mo` files**

```bash
msgfmt --output=overlay/locales/he/LC_MESSAGES/juhradial.mo \
    overlay/locales/he/LC_MESSAGES/juhradial.po
msgfmt --output=overlay/locales/he/LC_MESSAGES/juhradial-settings.mo \
    overlay/locales/he/LC_MESSAGES/juhradial-settings.po
```

- [ ] **Step 8: Run the test, confirm it passes**

Run: same command as Step 3
Expected: PASS (2 passed)

- [ ] **Step 9: Commit**

```bash
git add overlay/locales/he tests/test_translations_he.py
git commit -m "feat(i18n): add Hebrew translation catalogs for both domains"
```

- [ ] **Step 10: Hand the `.po` diffs to the user for review**

Per the spec's "Decided" translation-review flow: show the user `git diff --stat overlay/locales/he` and the two `.po` files' msgid→msgstr pairs (small enough to read in one pass per domain). If they flag specific strings, fix those entries, recompile the `.mo` files (Step 7's commands), re-run the test (Step 8), and amend the commit.

---

### Task 5: RTL verification screenshots

**Files:**
- Create: `scripts/rtl_screenshots.py`
- Create (script output, not committed): PNGs under a scratch directory

**Interfaces:**
- Consumes: `settings-qt/tools/shot.py` (existing, unmodified); `overlay/settings_dashboard.py`'s `JUH_SHOT`/`JUH_SHOT_PAGE` env vars (existing, unmodified); Tasks 1-4's language entries and catalogs.
- Produces: nothing later tasks consume — this is the plan's final, manual-verification step (the spec's non-goal explicitly excludes automated screenshot regression testing).

- [ ] **Step 1: Write the screenshot-driving script**

Create `scripts/rtl_screenshots.py`:

```python
#!/usr/bin/env python3
"""Capture Qt Settings pages, GTK dashboard pages, and a tray-menu replica
in Hebrew and English, for manual RTL review (one-time, not a CI check).

    python3 scripts/rtl_screenshots.py --out-dir /path/to/dir
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
QT_PAGES = list(range(12))  # settings-qt/tools/shot.py's own 0-11 docstring
GTK_PAGES = ["buttons", "settings"]
LANGS = ["en", "he"]


def shoot_qt(out_dir):
    for page in QT_PAGES:
        for lang in LANGS:
            xdg = out_dir / "xdg" / lang
            (xdg / "juhradial").mkdir(parents=True, exist_ok=True)
            (xdg / "juhradial" / "config.json").write_text(json.dumps({"language": lang}))
            out = out_dir / f"qt_page{page}_{lang}.png"
            subprocess.run(
                [sys.executable, str(REPO / "settings-qt" / "tools" / "shot.py"),
                 "--page", str(page), "--out", str(out),
                 "--env", f"XDG_CONFIG_HOME={xdg}"],
                check=False, timeout=60)


def shoot_gtk(out_dir):
    config = pathlib.Path.home() / ".config" / "juhradial" / "config.json"
    backup = config.read_bytes() if config.exists() else None
    try:
        for page in GTK_PAGES:
            for lang in LANGS:
                cfg = json.loads(backup) if backup else {}
                cfg["language"] = lang
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text(json.dumps(cfg))
                out = out_dir / f"gtk_{page}_{lang}.png"
                env = dict(os.environ, JUH_SHOT=str(out), JUH_SHOT_PAGE=page)
                subprocess.run([sys.executable, str(REPO / "overlay" / "settings_dashboard.py")],
                               cwd=str(REPO / "overlay"), env=env, check=False, timeout=30)
    finally:
        if backup is not None:
            config.write_bytes(backup)
        elif config.exists():
            config.unlink()


def shoot_tray_menu(out_dir):
    """A representative QMenu, not the live tray (which needs a running
    daemon/D-Bus session) - enough to check RTL item order/alignment."""
    sys.path.insert(0, str(REPO / "overlay"))
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    from PyQt6.QtWidgets import QApplication, QMenu
    import i18n

    app = QApplication.instance() or QApplication([])
    for lang in LANGS:
        i18n.get_configured_language = lambda lang=lang: lang
        _ = i18n.setup_i18n()
        app.setLayoutDirection(i18n.qt_direction_for(lang))
        menu = QMenu()
        menu.addAction(_("Settings"))
        menu.addAction(_("Easy-Switch"))
        menu.addSeparator()
        menu.addAction(_("Exit"))
        menu.show()
        app.processEvents()
        menu.grab().save(str(out_dir / f"tray_menu_{lang}.png"))
        menu.close()
    app.setLayoutDirection(app.layoutDirection().__class__.LeftToRight)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    shoot_qt(out_dir)
    shoot_gtk(out_dir)
    shoot_tray_menu(out_dir)
    print(f"screenshots in {out_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `python3 scripts/rtl_screenshots.py --out-dir /tmp/claude-rtl-shots` (adjust the path to this session's scratchpad directory)
Expected: exits 0; `/tmp/claude-rtl-shots` contains 24 `qt_page*_{en,he}.png`, 4 `gtk_*_{en,he}.png`, and 2 `tray_menu_{en,he}.png` files. The GTK dashboard step temporarily edits and restores the real `~/.config/juhradial/config.json`; if the script is interrupted mid-run, restore it manually from a backup taken before Step 2 (`cp ~/.config/juhradial/config.json /tmp/config.json.bak` first).

- [ ] **Step 3: Review the PNGs**

Open each `he` screenshot next to its `en` counterpart. Check for: overlapping or cut-off text, controls still anchored to the LTR side when they should have mirrored, an `en` screenshot that changed from before this branch (the anti-goal check — compare against a pre-branch run of the same script on `master` if one isn't already on hand), and that the three numeric readouts (Task 2 Step 6) still read left-to-right inside an otherwise-mirrored row. Fix anything wrong, re-run Step 2, re-review.

- [ ] **Step 4: Hand off to the user**

Share the screenshot directory (or publish a small Artifact gallery page if that's more convenient to flip through) and ask the user to review. Iterate on their feedback before merging.

When this branch becomes a PR, its description must include a one-line callout that this change also mirrors Arabic's layout (Arabic was translated but rendered LTR before this branch — `LayoutMirroring`/`gtk_direction_for`/`qt_direction_for` all key off the same `RTL_LANGUAGES` set, so `ar` gets the same mirroring `he` does, as a side effect of the shared mechanism) — existing Arabic users should see this flagged as intended, not stumble on it as an unannounced change.

- [ ] **Step 5: Commit the script**

```bash
git add scripts/rtl_screenshots.py
git commit -m "chore(i18n): add RTL verification screenshot script"
```
