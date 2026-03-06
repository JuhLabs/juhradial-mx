#!/usr/bin/env python3
"""
JuhRadial MX - Button Configuration Dialog

ButtonConfigDialog for configuring mouse button actions.

SPDX-License-Identifier: GPL-3.0
"""

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


class ButtonConfigDialog(Adw.Window):
    """Dialog for configuring a mouse button action"""

    def __init__(self, parent, button_id, button_info):
        super().__init__()
        self.button_id = button_id
        self.button_info = button_info
        self.selected_action = None
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Configure {}").format(button_info["name"]))
        self.set_default_size(420, 550)

        # Main content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class("background")

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
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

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        content.append(sep)

        # Scrollable action list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.set_margin_start(16)
        self.list_box.set_margin_end(16)
        self.list_box.set_margin_top(16)
        self.list_box.set_margin_bottom(16)

        # Find current action
        current_action = button_info.get("action", "")

        for action_id, action_name in BUTTON_ACTIONS:
            row = Adw.ActionRow()
            row.set_title(action_name)
            row.set_activatable(True)
            row.action_id = action_id
            row.action_name = action_name

            # Radio-style indicator
            radio = Gtk.CheckButton()
            radio.set_active(action_name == current_action)
            radio.set_sensitive(False)  # Visual only
            row.add_prefix(radio)
            row.radio = radio

            if action_name == current_action:
                self.selected_action = (action_id, action_name)
                self.list_box.select_row(row)

            self.list_box.append(row)

        self.list_box.connect("row-selected", self._on_row_selected)
        scrolled.set_child(self.list_box)
        content.append(scrolled)

        self.set_content(content)

    def _on_row_selected(self, list_box, row):
        if row is None:
            return

        # Update radio buttons visually
        child = list_box.get_first_child()
        while child:
            if hasattr(child, "radio"):
                child.radio.set_active(child == row)
            child = child.get_next_sibling()

        if hasattr(row, "action_id"):
            self.selected_action = (row.action_id, row.action_name)

    def _on_restore_default(self, button):
        """Restore button to default action"""
        default_action = DEFAULT_BUTTON_ACTIONS.get(self.button_id, "Middle Click")

        # Find and select the default action row
        child = self.list_box.get_first_child()
        while child:
            if hasattr(child, "action_name") and child.action_name == default_action:
                self.list_box.select_row(child)
                break
            child = child.get_next_sibling()

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

            print(f"Button {self.button_id} configured to: {action_name}")

        self.close()
