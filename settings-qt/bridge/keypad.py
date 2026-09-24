"""MX Keypad plate rendering and installed-application templates."""
import json
import pathlib
import re
import shutil

from PyQt6.QtCore import Qt, QRect, QRectF, QSize
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QImageReader, QLinearGradient, QPainter
from PyQt6.QtSvg import QSvgRenderer

from bridge.i18n import _

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
ART = ASSETS / "keypad" / "art"
_ART_REF = re.compile(r"(artsy|minimal)/[a-z0-9-]+")


def art_catalogue():
    """The bundled key art: {"sets": [{id, name}], "art": [{id, name, sets}]}."""
    try:
        data = json.loads((ART / "art.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sets": [], "art": []}
    return data if isinstance(data, dict) else {"sets": [], "art": []}


def art_path(ref):
    """The file of a bundled art reference "<set>/<id>", or None. Keys store
    the reference, not the path, so they survive a move of the install."""
    if not isinstance(ref, str) or not _ART_REF.fullmatch(ref):
        return None
    path = ART / (ref + ".jpg")
    return path if path.is_file() else None


def empty_key():
    return {"action": "none", "label": "", "icon": "", "custom": {}}


def render_plate(key, destination, app_icon):
    """Supersample at 2x; keep labels at 19 of the final 118 pixels."""
    image = QImage(236, 236, QImage.Format.Format_RGB32)
    image.fill(QColor("#070b14"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    plate = key.get("plate", "")
    if plate and _draw_ready_plate(painter, plate):
        painter.end()
        _save_plate(image, destination)
        _save_animation(plate, pathlib.Path(destination))
        return
    art = art_path(key.get("art", ""))
    if art is not None:
        _draw_art(painter, art, key["art"].startswith("minimal/"), bool(key.get("label", "").strip()))
    else:
        _draw_glyph(painter, key.get("icon", ""), app_icon)
    families = QFontDatabase.families()
    family = next((f for f in ("Barlow Condensed", "Oswald", "Roboto Condensed", "DejaVu Sans") if f in families), "Sans Serif")
    font = QFont(family)
    font.setPixelSize(38)
    font.setWeight(QFont.Weight.ExtraBold)
    font.setStretch(QFont.Stretch.Condensed)
    painter.setFont(font)
    painter.setPen(QColor("#efe6cf"))
    text = key.get("label", "").upper()
    if art is None and not key.get("icon") and text:
        # Label only (no glyph): the name is the whole key, as big as it fits.
        box = QRect(12, 12, 212, 212)
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        for size in range(76, 29, -4):
            font.setPixelSize(size)
            fit = QFontMetrics(font).boundingRect(box, flags, text)
            if fit.width() <= box.width() and fit.height() <= box.height():
                break
        else:  # a word too long even at the smallest size: break inside it
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWrapAnywhere
        painter.setFont(font)
        painter.drawText(box, flags, text)
    else:
        label = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, 216)
        painter.drawText(QRect(10, 183, 216, 46), Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    _save_plate(image, destination)


def _draw_glyph(painter, icon, app_icon):
    """The key's glyph or application icon above the label."""
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


def _draw_art(painter, path, minimal, labelled):
    """Bundled key art, laid out like the pack plates: the artsy set fills the
    key and darkens under the label; the minimal set sits smaller above it."""
    picture = QImage(str(path))
    if picture.isNull():
        return
    if minimal:
        side = 170 if labelled else 212
        scaled = picture.scaled(QSize(side, side), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        # Lighten: the art's black ground takes the plate colour, no box shows.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
        painter.drawImage((236 - scaled.width()) // 2, 8 if labelled else 12, scaled)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        return
    scaled = picture.scaled(QSize(236, 236), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
    painter.drawImage(0, 0, scaled, (scaled.width() - 236) // 2, (scaled.height() - 236) // 2, 236, 236)
    if labelled:
        band = QLinearGradient(0, 132, 0, 236)
        band.setColorAt(0.0, QColor(7, 11, 20, 0))
        band.setColorAt(0.5, QColor(7, 11, 20, 215))
        band.setColorAt(1.0, QColor(7, 11, 20, 245))
        painter.fillRect(0, 132, 236, 104, band)


def _draw_ready_plate(painter, path):
    """A ready key image (an imported pack's plate, the user's own picture):
    cover-fit and centre-cropped to the key, label and all. False when it does
    not load, so the key falls back to its glyph and label."""
    picture = QImage(str(path))
    if picture.isNull():
        return False
    scaled = picture.scaled(QSize(236, 236), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
    painter.drawImage(0, 0, scaled, (scaled.width() - 236) // 2, (scaled.height() - 236) // 2, 236, 236)
    return True


# An animated picture plays on its key: the service streams these frames.
MAX_FRAMES = 240
MIN_DELAY_MS = 33


def _save_animation(path, destination):
    """Frames of an animated picture (GIF, animated WebP) beside the plate:
    <stem>-a000.jpg, ... and <stem>.anim with one delay in ms per line.
    Nothing is written for a still picture."""
    reader = QImageReader(str(path))
    if not reader.supportsAnimation():
        return
    written = []
    delays = []
    while len(delays) < MAX_FRAMES:
        frame = reader.read()
        if frame.isNull():
            break
        delay = reader.nextImageDelay()
        # Browsers show 0-10 ms GIF delays at 100 ms; so does the keypad.
        delays.append(100 if delay <= 10 else max(MIN_DELAY_MS, delay))
        image = QImage(236, 236, QImage.Format.Format_RGB32)
        image.fill(QColor("#070b14"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scaled = frame.scaled(QSize(236, 236), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(0, 0, scaled, (scaled.width() - 236) // 2, (scaled.height() - 236) // 2, 236, 236)
        painter.end()
        out = destination.with_name(f"{destination.stem}-a{len(written):03d}.jpg")
        _save_plate(image, out)
        written.append(out)
    if len(written) < 2:
        for out in written:
            out.unlink(missing_ok=True)
        return
    destination.with_name(destination.stem + ".anim").write_text("".join(f"{d}\n" for d in delays))


def _save_plate(image, destination):
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
