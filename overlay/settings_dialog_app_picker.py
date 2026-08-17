#!/usr/bin/env python3
"""
JuhRadial MX - Application Picker

AppPickerDialog lists installed applications (the same set a desktop menu
would show) so a radial slice or submenu link can launch one directly, and
resolve_and_cache_icon()/command_for_app() turn the picked Gio.DesktopAppInfo
into a slice's plain "command"/"icon" fields.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import os
import re
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Gtk, Adw, Gio, Gdk

from i18n import _
from settings_config import ConfigManager

logger = logging.getLogger(__name__)

# Desktop Entry "Exec=" field codes (XDG Desktop Entry spec, section on
# "Exec key") - stripped since slices launch with no associated file/URL.
_FIELD_CODE_RE = re.compile(r"%[fFuUdDnNickvm%]")


def command_for_app(app_info):
    """Return a plain shell command for launching app_info."""
    exec_line = app_info.get_string("Exec") or ""
    return _FIELD_CODE_RE.sub("", exec_line).strip()


def resolve_and_cache_icon(app_info):
    """Resolve app_info's icon to a real image file and cache a copy under
    the config dir, returning the cached absolute path. Returns None if the
    icon can't be resolved to a file - callers should keep whatever icon
    text was already in place."""
    gicon = app_info.get_icon()
    if gicon is None:
        return None

    src_path = None
    try:
        if isinstance(gicon, Gio.FileIcon):
            src_path = gicon.get_file().get_path()
        else:
            theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
            paintable = theme.lookup_by_gicon(
                gicon, 64, 1, Gtk.TextDirection.NONE, Gtk.IconLookupFlags(0)
            )
            icon_file = paintable.get_file() if paintable else None
            src_path = icon_file.get_path() if icon_file else None
    except Exception:
        logger.debug("Icon lookup failed for %s", app_info.get_id(), exc_info=True)
        src_path = None

    if not src_path or not os.path.isfile(src_path):
        return None

    ext = os.path.splitext(src_path)[1] or ".png"
    app_id = app_info.get_id() or app_info.get_display_name() or "app"
    safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in app_id)
    dest_dir = ConfigManager.CONFIG_DIR / "icons"
    dest_path = dest_dir / f"{safe_id}{ext}"

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_path, dest_path)
    except OSError:
        logger.debug("Failed to cache icon for %s", app_id, exc_info=True)
        return None

    return str(dest_path)


class AppPickerDialog(Adw.Window):
    """Dialog listing installed applications, like a desktop menu's app list."""

    def __init__(self, parent, on_pick):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Choose Application"))
        self.set_default_size(420, 520)
        self._on_pick = on_pick

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)
        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel_btn)
        main_box.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(_("Search applications…"))
        self.search.connect("search-changed", lambda _e: self.list_box.invalidate_filter())
        content.append(self.search)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.set_filter_func(self._filter_row)
        self.list_box.connect("row-activated", self._on_row_activated)

        self._populate_apps()

        scrolled.set_child(self.list_box)
        content.append(scrolled)

        main_box.append(content)
        self.set_content(main_box)

    def _populate_apps(self):
        apps = [a for a in Gio.AppInfo.get_all() if a.should_show()]
        apps.sort(key=lambda a: (a.get_display_name() or a.get_name() or "").lower())

        seen_ids = set()
        for app in apps:
            app_id = app.get_id()
            if app_id in seen_ids:
                continue
            seen_ids.add(app_id)

            row = Adw.ActionRow()
            row.set_title(app.get_display_name() or app.get_name() or app_id)
            row.app_info = app

            gicon = app.get_icon()
            img = (
                Gtk.Image.new_from_gicon(gicon)
                if gicon
                else Gtk.Image.new_from_icon_name("application-x-executable")
            )
            img.set_pixel_size(28)
            row.add_prefix(img)

            self.list_box.append(row)

    def _filter_row(self, row):
        query = self.search.get_text().strip().lower()
        if not query:
            return True
        return query in row.get_title().lower()

    def _on_row_activated(self, _list_box, row):
        app_info = getattr(row, "app_info", None)
        if app_info is None:
            return
        self._on_pick(app_info)
        self.close()
