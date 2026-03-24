#!/usr/bin/env python3
"""
JuhRadial MX - Button Configuration Dialog

ButtonConfigDialog for configuring mouse button actions.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw

from i18n import _
from settings_config import config
from settings_constants import (
    MOUSE_BUTTONS,
    DEFAULT_BUTTON_ACTIONS,
    BUTTON_ACTIONS,
)

logger = logging.getLogger(__name__)

# Grouped action layout for the dialog.
# Order matters - most-used groups first. Actions within each group
# are displayed in the order listed here.
_ACTION_GROUPS = [
    ("COMMON", [
        "radial_menu",
        "virtual_desktops",
        "none",
    ]),
    ("NAVIGATION", [
        "back",
        "forward",
        "middle_click",
    ]),
    ("CLIPBOARD", [
        "copy",
        "paste",
        "undo",
        "redo",
    ]),
    ("MEDIA", [
        "play_pause",
        "volume_up",
        "volume_down",
        "mute",
    ]),
    ("SYSTEM", [
        "screenshot",
        "zoom_in",
        "zoom_out",
    ]),
    ("MOUSE", [
        "smartshift",
        "scroll_left_right",
    ]),
    ("OTHER", [
        "custom",
    ]),
]

# Translated group names (called at dialog build time so _ is live)
def _group_label(key):
    return {
        "COMMON": _("Common"),
        "NAVIGATION": _("Navigation"),
        "CLIPBOARD": _("Clipboard"),
        "MEDIA": _("Media"),
        "SYSTEM": _("System"),
        "MOUSE": _("Mouse"),
        "OTHER": _("Other"),
    }.get(key, key)


class ButtonConfigDialog(Adw.Window):
    """Dialog for configuring a mouse button action"""

    def __init__(self, parent, button_id, button_info):
        super().__init__()
        self.button_id = button_id
        self.button_info = button_info
        self.selected_action = None
        self._all_rows = []
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Configure {}").format(button_info["name"]))
        self.set_default_size(420, 620)

        # Build action lookup from BUTTON_ACTIONS constant
        action_map = {aid: aname for aid, aname in BUTTON_ACTIONS}

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class("background")

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.add_css_class("flat")
        cancel_btn.connect("clicked", lambda _btn: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=_("Save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)

        content.append(header)

        # Current button info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_margin_start(24)
        info_box.set_margin_end(24)
        info_box.set_margin_top(16)
        info_box.set_margin_bottom(8)

        # Header with title and restore button
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        button_label = Gtk.Label(label=button_info["name"])
        button_label.add_css_class("title-2")
        button_label.set_halign(Gtk.Align.START)
        button_label.set_hexpand(True)
        header_row.append(button_label)

        # Restore default button
        restore_btn = Gtk.Button(label=_("Restore Default"))
        restore_btn.add_css_class("flat")
        restore_btn.add_css_class("dim-label")
        restore_btn.connect("clicked", self._on_restore_default)
        header_row.append(restore_btn)

        info_box.append(header_row)

        current_label = Gtk.Label(
            label=_("Current: {}").format(button_info.get("action", _("Not set")))
        )
        current_label.add_css_class("dim-label")
        current_label.set_halign(Gtk.Align.START)
        info_box.append(current_label)

        content.append(info_box)

        # Scrollable grouped action list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        groups_box.set_margin_start(16)
        groups_box.set_margin_end(16)
        groups_box.set_margin_top(12)
        groups_box.set_margin_bottom(16)

        # Find current action
        current_action = button_info.get("action", "")

        for group_key, action_ids in _ACTION_GROUPS:
            # Filter to actions that exist in BUTTON_ACTIONS
            group_actions = [
                (aid, action_map[aid]) for aid in action_ids if aid in action_map
            ]
            if not group_actions:
                continue

            group = Adw.PreferencesGroup()
            group.set_title(_group_label(group_key))

            for action_id, action_name in group_actions:
                row = Adw.ActionRow()
                row.set_title(action_name)
                row.set_activatable(True)
                row.action_id = action_id
                row.action_name = action_name

                # Checkmark indicator (GNOME HIG pattern)
                check_icon = Gtk.Image.new_from_icon_name(
                    "object-select-symbolic"
                )
                check_icon.set_pixel_size(16)
                check_icon.add_css_class("accent")
                check_icon.set_visible(action_name == current_action)
                row.add_suffix(check_icon)
                row.check_icon = check_icon

                if action_name == current_action:
                    self.selected_action = (action_id, action_name)

                self._all_rows.append(row)
                group.add(row)

            # Each group gets its own list box via PreferencesGroup
            groups_box.append(group)

        # Connect click handling on all rows
        for row in self._all_rows:
            row.connect("activated", self._on_row_activated)

        scrolled.set_child(groups_box)
        content.append(scrolled)

        self.set_content(content)

    def _on_row_activated(self, row):
        """Handle row click - update checkmark and selection"""
        # Clear all checkmarks
        for r in self._all_rows:
            if hasattr(r, "check_icon"):
                r.check_icon.set_visible(False)

        # Show checkmark on selected row
        if hasattr(row, "check_icon"):
            row.check_icon.set_visible(True)

        if hasattr(row, "action_id"):
            self.selected_action = (row.action_id, row.action_name)

    def _on_restore_default(self, button):
        """Restore button to default action"""
        default_action = DEFAULT_BUTTON_ACTIONS.get(self.button_id, "Middle Click")

        for row in self._all_rows:
            if hasattr(row, "action_name") and row.action_name == default_action:
                self._on_row_activated(row)
                break

    def _on_save(self, button):
        if self.selected_action:
            action_id, action_name = self.selected_action

            # Update the MOUSE_BUTTONS dict
            if self.button_id in MOUSE_BUTTONS:
                MOUSE_BUTTONS[self.button_id]["action"] = action_name

            # Save to config
            buttons_config = config.get("buttons", default={})
            buttons_config[self.button_id] = action_id
            config.set("buttons", buttons_config)
            config.save()

            logger.info("Button %s configured to: %s", self.button_id, action_name)

        self.close()
