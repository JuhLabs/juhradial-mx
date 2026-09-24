"""MX Keypad plate rendering and installed-application templates."""
import pathlib
import shutil

from PyQt6.QtCore import Qt, QRect, QRectF, QSize
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

from bridge.i18n import _

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"


def empty_key():
    return {"action": "none", "label": "", "icon": "", "custom": {}}


def render_plate(key, destination, app_icon):
    """Supersample at 2x; keep labels at 19 of the final 118 pixels."""
    image = QImage(236, 236, QImage.Format.Format_RGB32)
    image.fill(QColor("#070b14"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    icon = key.get("icon", "")
    if icon.startswith("desktop:"):
        icon = app_icon(icon[8:]) or "application-x-executable-symbolic"
    glyph = QImage(152, 152, QImage.Format.Format_ARGB32_Premultiplied)
    glyph.fill(Qt.GlobalColor.transparent)
    gp = QPainter(glyph)
    if pathlib.Path(icon).is_absolute():
        QIcon(icon).paint(gp, QRect(0, 0, 152, 152))
    elif icon:
        # The bundled family first, like the settings previews: a theme's colour
        # fallback for a missing -symbolic name would tint into a solid block.
        bundled = (ASSETS / "icons" / d / (pathlib.Path(icon).name + ".svg") for d in ("mono", "nav"))
        path = next((b for b in bundled if b.is_file()), None)
        themed = QIcon.fromTheme(icon) if path is None else QIcon()
        if path is not None:
            QSvgRenderer(str(path)).render(gp, QRectF(0, 0, 152, 152))
        elif not themed.isNull():
            themed.paint(gp, QRect(0, 0, 152, 152))
        else:  # neither bundle nor theme: never a blank plate (#34)
            fallback = ASSETS / "icons" / "mono" / "application-x-executable-symbolic.svg"
            QSvgRenderer(str(fallback)).render(gp, QRectF(0, 0, 152, 152))
    # Application icons retain their colours; glyphs use a bright plate accent.
    if not pathlib.Path(icon).is_absolute():
        gp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        gp.fillRect(glyph.rect(), QColor("#5cc3ee"))
    gp.end()
    painter.drawImage(42, 18, glyph)
    families = QFontDatabase.families()
    family = next((f for f in ("Barlow Condensed", "Oswald", "Roboto Condensed", "DejaVu Sans") if f in families), "Sans Serif")
    font = QFont(family)
    font.setPixelSize(38)
    font.setWeight(QFont.Weight.ExtraBold)
    font.setStretch(QFont.Stretch.Condensed)
    painter.setFont(font)
    painter.setPen(QColor("#efe6cf"))
    label = QFontMetrics(font).elidedText(key.get("label", "").upper(), Qt.TextElideMode.ElideRight, 216)
    painter.drawText(QRect(10, 183, 216, 46), Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    image = image.scaled(QSize(118, 118), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not image.save(str(destination), "JPEG", 90):
        raise OSError(_("Could not save a keypad plate"))


def template_keys(template, apps, actions):
    by_id = {row[0]: row for row in actions}

    def preset(action, label=None):
        row = by_id[action]
        return {"action": action, "label": label or _(row[1]), "icon": row[2], "custom": {}}

    def shortcut(keys, label, icon):
        return {"action": "custom", "label": label, "icon": icon,
                "custom": {"kind": "shortcut", "value": keys}}

    def app(tokens, label, icon):
        found = next((a for token in tokens for a in apps if token in a["id"].lower()), None)
        if found:
            return {"action": "custom", "label": found["name"], "icon": "desktop:" + found["id"],
                    "custom": {"kind": "command", "value": found["command"]}}
        return {**empty_key(), "label": label, "icon": icon}

    def mic():
        command = ""
        if shutil.which("wpctl"):
            command = "wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"
        elif shutil.which("pactl"):
            command = "pactl set-source-mute @DEFAULT_SOURCE@ toggle"
        return {"action": "custom" if command else "none", "label": _("Mic mute"),
                "icon": "audio-volume-muted-symbolic",
                "custom": {"kind": "command", "value": command} if command else {}}

    browser = lambda: app(("firefox", "chromium", "google-chrome", "brave", "epiphany"), _("Browser"), "web-browser-symbolic")
    terminal = lambda: app(("konsole", "ghostty", "ptyxis", "kgx", "gnome-terminal", "alacritty", "kitty", "foot"), _("Terminal"), "utilities-terminal-symbolic")
    if template == "everyday":
        return [browser(), app(("dolphin", "nautilus", "thunar", "nemo"), _("Files"), "folder-symbolic"), terminal(),
                app(("thunderbird", "evolution", "geary", "kmail"), _("Mail"), "mail-unread-symbolic"),
                preset("calculator"), preset("screenshot"), preset("lock_screen", _("Lock")),
                app(("systemsettings", "gnome-control-center"), _("Settings"), "preferences-system-symbolic"),
                app(("obsidian", "notes", "xpad", "joplin"), _("Notes"), "document-edit-symbolic")]
    if template == "media":
        return [preset("play_pause", _("Play")), shortcut("XF86AudioPrev", _("Previous"), "media-skip-backward-symbolic"),
                shortcut("XF86AudioNext", _("Next"), "media-skip-forward-symbolic"),
                preset("volume_down", _("Vol down")), preset("volume_up", _("Vol up")), preset("mute"),
                preset("screenshot"), mic(), app(("spotify", "elisa", "rhythmbox", "lollypop"), _("Music"), "media-playback-start-symbolic")]
    if template == "developer":
        return [terminal(), app(("code", "codium", "kate", "zed", "sublime", "gedit"), _("Editor"), "applications-development-symbolic"),
                shortcut("F12", _("Dev tools"), "web-browser-symbolic"),
                shortcut("ctrl+shift+p", _("Commands"), "system-search-symbolic"),
                shortcut("ctrl+grave", _("Terminal"), "utilities-terminal-symbolic"),
                preset("copy"), preset("paste"), preset("undo"), preset("redo")]
    if template == "meetings":
        return [mic(), {**empty_key(), "label": _("Camera"), "icon": "camera-photo-symbolic"},
                {**empty_key(), "label": _("Share"), "icon": "video-display-symbolic"},
                {**empty_key(), "label": _("Leave"), "icon": "window-close-symbolic"},
                preset("volume_down", _("Vol down")), preset("volume_up", _("Vol up")), preset("mute"),
                preset("screenshot"), preset("none")]
    return None
