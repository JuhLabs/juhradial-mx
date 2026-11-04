# Hebrew Language + RTL Support — Design

## Intent

JuhRadial MX ships 18 UI languages across two apps (the Qt/QML Settings app
and the GTK overlay + its old-Qt fallback settings dialog), selected by one
`language` key in `config.json`. Hebrew is not among them. The user wants
Hebrew added as a full, first-class language: translated strings *and*
right-to-left layout, not just translated text sitting inside a left-to-right
layout (which is the current state for Arabic — the only other RTL language
shipped today).

## Why now

User-requested. No external deadline.

## Goals

- Hebrew selectable as a language in both the Qt Settings app's language
  picker and the GTK overlay's (`overlay/i18n.py` `SUPPORTED_LANGUAGES`).
- Every user-facing string in both gettext domains (`juhradial`,
  `juhradial-settings`) has a Hebrew translation.
- The Qt Settings app lays out right-to-left when Hebrew (or Arabic) is
  selected: reading order, anchor sides, and row/column order mirror: not
  just translated text inside an unchanged LTR layout.
- The GTK overlay (tray menu, drag-session chrome, old-Qt fallback settings
  dialog) does the same for its own, much smaller, surface.
- A reviewable, repeatable way to check RTL layout without the user needing
  to build or run anything themselves first: screenshots per page.

## Non-goals

- Pixel-perfect RTL visual polish on the first pass. The bar is *functional*
  mirroring — correct reading order, nothing overlapping or cut off — not a
  full design pass matched to the LTR layout's visual refinement.
- Fixing Arabic's current LTR-layout gap as its own tracked goal. It will be
  fixed as a side effect of the Qt/GTK mechanism this design adds (both
  mechanisms key off `Qt.application.layoutDirection` /
  `gtk_get_locale_direction`-equivalent logic, which already covers `ar`),
  but re-auditing Arabic's translation content or raising a separate issue
  for it is out of scope.
- A human (non-LLM) professional Hebrew translation pass. The user reviews
  the LLM-generated translation themselves; this design does not include
  sending the catalog to a translation service.
- Automated RTL regression testing (e.g. pixel-diffing future screenshots in
  CI). Verification for this change is manual, screenshot-driven, one time.

## Anti-goals

Would make this a failure even if it "works":

- Hebrew text rendered correctly but the surrounding chrome (icons, control
  order, alignment) still reads left-to-right — the exact gap this design
  exists to close, not just translate around.
- A translation review workflow that dumps ~2200 raw strings on the user
  with no structure, making review impractical.
- RTL changes that visibly break the 18 existing LTR languages (e.g. always
  mirroring regardless of locale, instead of conditionally).

## Constraints

- Two independent language lists must both get the new entry, since they
  are not shared code: `settings-qt/bridge/backend.py`'s `LANGUAGES` list
  and `overlay/i18n.py`'s `SUPPORTED_LANGUAGES` dict. Both already read the
  same `config.json` `language` key, so no new config plumbing is needed —
  only the picker entries and the translation catalogs.
- Two gettext domains, with existing extraction tooling that must keep
  working for all 18 current languages, not just gain a 19th:
  - `juhradial-settings` (~1611 msgids, `settings-qt/tools/extract_strings.py`
    → `overlay/locales/juhradial-settings.pot`)
  - `juhradial` (~287 msgids, `scripts/update-translations.sh` → xgettext
    over `overlay/*.py` → `overlay/locales/juhradial.pot`)
- `tests/test_qml_i18n.py` already lints that every QML user-visible literal
  goes through `qsTr()` and smoke-tests that `qsTr()` resolves through the
  gettext-backed translator at runtime. This must stay green; it is the
  safety net that a Hebrew catalog doesn't break the translator pipeline.
- Qt Settings app has a single root `ApplicationWindow` in
  `settings-qt/qml/Main.qml` — the one place a global RTL switch can live
  and propagate via Qt's built-in `LayoutMirroring` mechanism, rather than
  touching each of the 68 QML files under `settings-qt/qml/`.
- GTK's automatic locale-based RTL detection (`gtk_get_locale_direction`)
  only fires from the process's actual `LC_ALL`/`LANGUAGE` environment.
  `overlay/i18n.py`'s `setup_i18n()` sets the process locale only for the
  `"system"` language choice; an explicit in-app language override (the
  normal case — most users pick a language in Settings rather than relying
  on their desktop locale) only swaps the gettext catalog via
  `gettext.translation(..., languages=[lang])`, which does **not** change
  `Gtk.Widget.get_default_direction()`. The GTK side needs an explicit
  `Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)` call keyed off
  the configured language, not reliance on automatic detection.

## Decided (the how)

**Translation generation and review.** Claude generates Hebrew `.po` files
for both domains via LLM translation of every msgid, seeded from the
existing `.pot` templates with `msginit`/`msgmerge`, matching the tone/
register of the existing catalogs. The user reviews by reading the `.po`
diff (msgid → msgstr pairs) rather than a raw string dump — small enough
in one pass per domain, and it's the native format `scripts/
update-translations.sh` already round-trips. The user flags wrong entries
by string; Claude fixes and recompiles `.mo`.

**Qt RTL mechanism.** In `settings-qt/qml/Main.qml`'s root
`ApplicationWindow`:

```qml
LayoutMirroring.enabled: Qt.application.layoutDirection === Qt.RightToLeft
LayoutMirroring.childrenInherit: true
```

This is Qt's standard, built-in RTL mechanism: every descendant anchor
(`anchors.left`/`anchors.right`), `RowLayout`, and `ListView`/`GridView`
flow direction mirrors automatically from this one declaration — no
per-file rewrite needed for the ~32 QML files using `anchors.left`/
`anchors.right`. `Qt.application.layoutDirection` itself follows the
active `QLocale`, which the app already sets from `config.json`'s
`language` (confirm exact call site during implementation — likely in
`settings-qt/main.py` near where the translator loads).

The ~10 QML files with hardcoded `Text.AlignLeft`/`Text.AlignRight` need a
one-by-one audit: most should drop the hardcoded alignment and let the
default (`Text.AlignLeft` relative to layout direction, i.e. "leading
edge") follow mirroring; a few may have a legitimate reason to stay fixed
(e.g. a numeric value that should always read LTR) and get a one-line
comment explaining why, left alone.

**GTK RTL mechanism.** Confirmed during builder-check follow-up: the "old-Qt
fallback settings dialog" named in Goals and the overlay's own tray/chrome
are the *same* GTK/Adwaita codebase (`overlay/settings_dialog_*.py` imports
`from gi.repository import Gtk, Adw`), not a separate Qt-Widgets surface —
there is no third toolkit or third mechanism to design for. One GTK call
covers both. In the overlay's startup path (exact entry point — likely near
where `setup_i18n()` is called — to be confirmed during implementation),
after resolving the configured language:

```python
import gi
gi.require_version("Gtk", "3.0")  # or whatever version this app targets
from gi.repository import Gtk
Gtk.Widget.set_default_direction(
    Gtk.TextDirection.RTL if lang in RTL_LANGUAGES else Gtk.TextDirection.LTR
)
```

`RTL_LANGUAGES = {"ar", "he"}` (or equivalent), defined once and reused by
both the Qt (`Qt.locale(lang).textDirection`, which already knows RTL
locales) and GTK sides where a static check is simpler than relying on
`QLocale`/`gtk_get_locale_direction` alone — needed specifically because of
the explicit-override gap above.

**Verification.** A small Python script (offscreen `QT_QPA_PLATFORM`, same
technique `tests/test_qml_i18n.py` already uses to load the QML engine
headlessly) walks every Settings page with `LANGUAGE=he` / the configured-
Hebrew path, grabs each page's window via `QQuickWindow.grabWindow()`,
saves a PNG per page. Same idea for the GTK fallback dialog and overlay
chrome (`Gtk.Widget` offscreen rendering, or a plain screenshot if offscreen
GTK rendering proves awkward — builder's call). The same script also grabs
each page once more with an unaffected LTR language (English) selected, both
before and after the `LayoutMirroring`/`set_default_direction` wiring lands —
this is the check for the anti-goal "RTL changes that visibly break the 18
existing LTR languages": a global, conditional switch is exactly the kind of
change a wrong condition (e.g. firing unconditionally) would break silently
for every other language, and nothing else in this design would catch that.
Claude reviews the PNGs first for obvious breakage (overlapping/cut-off
text, an LTR page that changed, something clearly not mirrored), fixes
what's wrong, then hands the full screenshot set to the user — as files, or
a small Artifact gallery page if that's more convenient to flip through —
for the user's own pass. Iterate until the user signs off.

Hebrew-capable fonts are already present in the implementation environment
(confirmed via `fc-list :lang=he`: Noto Sans/Serif Hebrew, David CLM, Shofar
— not just tofu/boxes), so the screenshots this verification step produces
will actually show Hebrew glyphs rather than needing a font install first.

## What's left to the builder (implementation plan)

- Exact call sites: where `config.json`'s `language` becomes
  `Qt.application.layoutDirection` in the Qt app's startup path, and the
  overlay's actual startup entry point for the GTK direction call.
- The full Hebrew `.po` content for both domains (generated as part of
  implementation, not pre-written here).
- The precise list of ~10 QML files with hardcoded alignment and the
  per-file call (drop hardcode vs. keep with a comment).
- The screenshot script's exact shape and where its output lands (temp
  dir path, optional Artifact gallery).
- Test coverage: at minimum, a unit test pinning that `LayoutMirroring.
  enabled` evaluates true for `he`/`ar` and false for the other 17
  languages (mirrors the existing style of `tests/test_qml_i18n.py`'s
  runtime checks), and that both `LANGUAGES` lists (`backend.py`,
  `overlay/i18n.py`) contain the new `he` entry. Full TDD per the project's
  standing workflow.
- Whether `RTL_LANGUAGES` lives in one shared place both apps import, or is
  duplicated per the existing pattern of two independent language lists —
  builder's call, document whichever is chosen.
- A one-line callout in the PR description that this also changes Arabic's
  layout (currently LTR-laid-out despite being an RTL language) as a side
  effect of the shared mirroring mechanism — existing Arabic users should
  see it flagged as intended, not stumble on it as an unannounced change.
