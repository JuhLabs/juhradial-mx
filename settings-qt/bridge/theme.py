"""Theme + design-token singleton for the JuhRadial MX Qt/QML settings app.

One source of truth for the whole UI: colours (accent + wallpaper swap per
theme; dark scaffold fixed) AND the design tokens (spacing, radii, type scale,
motion) so every QML file reads `Theme.*` instead of hard-coding values. The
radial wheel is an INDEPENDENT setting (not derived from the colour theme).
Flipping the theme emits `changed`, re-binding the whole tree at once.
"""
import json
import os
import pathlib
import sys
from PyQt6.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
# The settings-window theme is UI-only state; keep it OUT of config.json so the
# single config writer (Backend) never clobbers it and vice-versa.
_XDG_CONFIG = pathlib.Path(os.environ.get("XDG_CONFIG_HOME",
                                          str(pathlib.Path.home() / ".config")))
UI_STATE = _XDG_CONFIG / "juhradial" / "ui_state.json"

# Fixed dark scaffold (design brief)
BG_BASE = "#0A0A0A"
SURFACE_SOLID = "#15171C"
TEXT = "#FFFFFF"
TEXT_BODY = "#E8EAED"
TEXT_MUTED = "#9AA3B2"


def _argb(hex_rgb, alpha):
    a = max(0, min(255, round(alpha * 255)))
    return f"#{a:02X}{hex_rgb.lstrip('#')}"


# name, key (wallpaper wp_<key>.png), accent, hover, active
THEMES = [
    ("Azure", "azure", "#4C9AFF", "#6FB0FF", "#3B82F6"),
    ("Sky", "sky", "#38BDF8", "#5CCBFA", "#0EA5E9"),
    ("Indigo", "indigo", "#635BFF", "#857EFF", "#4F46E5"),
    ("Violet", "violet", "#A78BFA", "#BDA6FB", "#8B5CF6"),
    ("Emerald", "emerald", "#2FBF71", "#4FD08A", "#22A65E"),
    ("Teal", "teal", "#16C0A8", "#3AD2BC", "#0EA493"),
    ("Cyan", "cyan", "#22C8E0", "#4FD7EA", "#0FAFC6"),
    ("Brass", "brass", "#D8A53A", "#E6BB5C", "#BE8E2A"),
    ("Amber", "amber", "#F5B22A", "#F8C355", "#DB9A18"),
    ("Coral", "coral", "#F97316", "#FB8A3C", "#EA630A"),
    ("Rose", "rose", "#F43F5E", "#F76A82", "#E11D48"),
    ("Magenta", "magenta", "#EC4899", "#F06BAE", "#DB2777"),
]

# Independent radial-wheel skins (settings-qt/assets/wheels/wheel_<key>.png)
WHEELS = [
    ("Azure", "azure"), ("Obsidian", "obsidian"), ("Chrome", "chrome"),
    ("Glass", "glass"), ("Emerald", "emerald"), ("Violet", "violet"),
    ("Ember", "ember"), ("Crimson", "crimson"),
]


class Theme(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._i = self._load_index()

    # ---- persistence (separate UI-state file; never touches config.json) ----
    def _load_index(self):
        try:
            i = int(json.loads(UI_STATE.read_text()).get("settings_theme", 0))
            if 0 <= i < len(THEMES):
                return i
        except Exception:
            pass
        return 0

    def _save_index(self):
        try:
            state = {}
            if UI_STATE.exists():
                state = json.loads(UI_STATE.read_text())
            state["settings_theme"] = self._i
            UI_STATE.parent.mkdir(parents=True, exist_ok=True)
            tmp = UI_STATE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, indent=2))
            os.replace(tmp, UI_STATE)
        except Exception as e:
            print(f"theme save failed: {e}", file=sys.stderr)

    def _t(self):
        return THEMES[self._i]

    @pyqtSlot(int)
    def setIndex(self, i):
        if 0 <= i < len(THEMES) and i != self._i:
            self._i = i
            self._save_index()
            self.changed.emit()

    @pyqtSlot(result="QVariantList")
    def themeList(self):
        return [{"name": n, "accent": a, "wallpaper": self._wp(k)}
                for (n, k, a, _h, _ac) in THEMES]

    def _wp(self, key):
        p = ASSETS / "wallpapers" / f"wp_{key}.jpg"
        return p.as_uri() if p.exists() else ""

    # ---- radial wheel (independent of colour theme) ----
    @pyqtSlot(result="QVariantList")
    def wheelList(self):
        out = []
        for name, key in WHEELS:
            p = ASSETS / "wheels" / f"wheel_{key}.png"
            out.append({"name": name, "key": key,
                        "image": p.as_uri() if p.exists() else ""})
        return out

    @pyqtSlot(str, result=str)
    def wheelImage(self, key):
        p = ASSETS / "wheels" / f"wheel_{key}.png"
        return p.as_uri() if p.exists() else ""

    @pyqtSlot(str, result=str)
    def sliceButton(self, action_id):
        """Custom circular button image for a radial action, or "" if none.

        When present the editor shows this in place of the generic ring+icon.
        """
        p = ASSETS / "slices" / f"btn_{action_id}.png"
        return p.as_uri() if p.exists() else ""

    @pyqtProperty(int, notify=changed)
    def index(self):
        return self._i

    @pyqtProperty(str, notify=changed)
    def name(self):
        return self._t()[0]

    @pyqtProperty(str, notify=changed)
    def accent(self):
        return self._t()[2]

    @pyqtProperty(str, notify=changed)
    def accentHover(self):
        return self._t()[3]

    @pyqtProperty(str, notify=changed)
    def accentActive(self):
        return self._t()[4]

    @pyqtProperty(str, notify=changed)
    def accentSubtle(self):
        return _argb(self._t()[2], 0.16)

    @pyqtProperty(str, notify=changed)
    def accentGlow(self):
        return _argb(self._t()[2], 0.45)

    @pyqtProperty(str, notify=changed)
    def accentFaint(self):
        return _argb(self._t()[2], 0.08)

    @pyqtProperty(str, notify=changed)
    def wallpaper(self):
        return self._wp(self._t()[1])

    # ---- fixed scaffold tokens ----
    @pyqtProperty(str, constant=True)
    def danger(self):
        return "#F43F5E"

    @pyqtProperty(str, constant=True)
    def dangerSubtle(self):
        return _argb("#F43F5E", 0.16)

    @pyqtProperty(str, constant=True)
    def bgBase(self):
        return BG_BASE

    @pyqtProperty(str, constant=True)
    def surfaceSolid(self):
        return SURFACE_SOLID

    @pyqtProperty(str, constant=True)
    def surfaceGlass(self):
        return _argb("#14161C", 0.72)

    @pyqtProperty(str, constant=True)
    def surfaceGlassHi(self):
        return _argb("#1B1E26", 0.80)

    @pyqtProperty(str, constant=True)
    def surfaceRail(self):
        return _argb("#0F1116", 0.88)

    @pyqtProperty(str, constant=True)
    def surfaceInset(self):
        return _argb("#000000", 0.28)

    @pyqtProperty(str, constant=True)
    def border(self):
        return _argb("#FFFFFF", 0.10)

    @pyqtProperty(str, constant=True)
    def borderStrong(self):
        return _argb("#FFFFFF", 0.18)

    @pyqtProperty(str, constant=True)
    def textPrimary(self):
        return TEXT

    @pyqtProperty(str, constant=True)
    def textBody(self):
        return TEXT_BODY

    @pyqtProperty(str, constant=True)
    def textMuted(self):
        return TEXT_MUTED

    # ---- design tokens: spacing / radii / type scale / motion ----
    @pyqtProperty(int, constant=True)
    def gap(self):
        return 14

    @pyqtProperty(int, constant=True)
    def gapL(self):
        return 16

    @pyqtProperty(int, constant=True)
    def gapS(self):
        return 8

    @pyqtProperty(int, constant=True)
    def pad(self):
        return 22

    @pyqtProperty(int, constant=True)
    def padCard(self):
        return 18

    @pyqtProperty(int, constant=True)
    def radiusCard(self):
        return 18

    @pyqtProperty(int, constant=True)
    def radiusCtl(self):
        return 10

    @pyqtProperty(int, constant=True)
    def radiusPill(self):
        return 9

    @pyqtProperty(str, constant=True)
    def fontUI(self):
        return "Inter"

    @pyqtProperty(str, constant=True)
    def fontDisplay(self):
        return "Inter Display"

    @pyqtProperty(str, constant=True)
    def fontMono(self):
        return "Geist Mono"

    @pyqtProperty(int, constant=True)
    def fsH1(self):
        return 27

    @pyqtProperty(int, constant=True)
    def fsH2(self):
        return 20

    @pyqtProperty(int, constant=True)
    def fsH3(self):
        return 16

    @pyqtProperty(int, constant=True)
    def fsBody(self):
        return 14

    @pyqtProperty(int, constant=True)
    def fsSmall(self):
        return 12

    @pyqtProperty(int, constant=True)
    def fsMicro(self):
        return 11

    @pyqtProperty(int, constant=True)
    def dShort(self):
        return 130

    @pyqtProperty(int, constant=True)
    def dMed(self):
        return 220

    @pyqtProperty(int, constant=True)
    def dLong(self):
        return 340
