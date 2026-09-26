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
    ("DESKTOP", [
        "show_desktop",
        "switch_desktop_left",
        "switch_desktop_right",
        "task_switcher",
        "close_window",
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
        "lock_screen",
        "calculator",
    ]),
    ("MOUSE", [
        "smartshift",
        "scroll_left_right",
    ]),
    ("OTHER", [
        "custom",
    ]),
]

# The thumb wheel (horizontal_scroll) is a rotational control the daemon drives
# from config.thumbwheel.mode; only these actions map onto a wheel mode (see
# _on_save's mirror). Its dialog is restricted to this set so users cannot pick
# an action the wheel cannot honor.
_THUMBWHEEL_ACTIONS = {
    "scroll_left_right",
    "zoom_in",
    "zoom_out",
    "volume_up",
    "volume_down",
    "none",
}

# Icon names for the DE-portable preset actions (freedesktop symbolic names).
# Only the preset rows carry a prefix icon; other rows are left unchanged.
_ACTION_ICONS = {
    "show_desktop": "user-desktop-symbolic",
    "switch_desktop_left": "go-previous-symbolic",
    "switch_desktop_right": "go-next-symbolic",
    "task_switcher": "view-app-grid-symbolic",
    "close_window": "window-close-symbolic",
    "lock_screen": "system-lock-screen-symbolic",
    "calculator": "accessories-calculator-symbolic",
}


# Translated group names (called at dialog build time so _ is live)
def _group_label(key):
    return {
        "COMMON": _("Common"),
        "NAVIGATION": _("Navigation"),
        "DESKTOP": _("Desktop & Windows"),
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

        # Directional gestures live on the gesture button only. The grouped
        # action list below stays the plain-click action (buttons.gesture).
        self._direction_rows = {}
        self._direction_switch = None
        self._threshold_spin = None
        if self.button_id == "gesture":
            groups_box.append(self._build_direction_group())

        # Find current action
        current_action = button_info.get("action", "")

        for group_key, action_ids in _ACTION_GROUPS:
            # Filter to actions that exist in BUTTON_ACTIONS
            group_actions = [
                (aid, action_map[aid]) for aid in action_ids if aid in action_map
            ]
            # The thumb wheel can only honor a rotational subset of actions.
            if self.button_id == "horizontal_scroll":
                group_actions = [
                    (aid, aname)
                    for aid, aname in group_actions
                    if aid in _THUMBWHEEL_ACTIONS
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

                # Prefix icon for the DE-portable preset actions
                prefix_icon_name = _ACTION_ICONS.get(action_id)
                if prefix_icon_name:
                    prefix_icon = Gtk.Image.new_from_icon_name(prefix_icon_name)
                    prefix_icon.set_pixel_size(16)
                    row.add_prefix(prefix_icon)

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

    def _build_direction_group(self):
        """Hold-and-drag actions for the gesture button.

        Written to buttons.gesture_directions. The daemon keeps the single-action
        behaviour whenever "enabled" is false or the section is absent, and a
        drag below threshold_px is a click, which runs buttons.gesture.
        """
        saved = config.get("buttons", "gesture_directions", default=None) or {}
        # Saving merges into this, so keys this dialog does not edit (click,
        # anything newer) survive a round trip through the fallback app.
        self._saved_directions = dict(saved)
        enabled = bool(saved.get("enabled", False))

        group = Adw.PreferencesGroup()
        group.set_title(_("Directional Gestures"))
        group.set_description(
            _("Hold the gesture button and drag to run a different action per "
              "direction. A press without dragging runs the action chosen below.")
        )

        enable_row = Adw.ActionRow()
        enable_row.set_title(_("Enable directional gestures"))
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.set_active(enabled)
        enable_row.add_suffix(switch)
        enable_row.set_activatable_widget(switch)
        group.add(enable_row)
        self._direction_switch = switch

        # radial_menu needs a press position the drag path never collects.
        choices = [(aid, aname) for aid, aname in BUTTON_ACTIONS if aid != "radial_menu"]
        ids = [aid for aid, _name in choices]
        names = Gtk.StringList.new([aname for _aid, aname in choices])
        fallback = ids.index("none") if "none" in ids else 0
        for key, label in (
            ("up", _("Drag up")),
            ("down", _("Drag down")),
            ("left", _("Drag left")),
            ("right", _("Drag right")),
            ("up_left", _("Drag up-left")),
            ("up_right", _("Drag up-right")),
            ("down_left", _("Drag down-left")),
            ("down_right", _("Drag down-right")),
        ):
            row = Adw.ComboRow(title=label)
            row.set_model(names)
            current = saved.get(key, "none")
            row.set_selected(ids.index(current) if current in ids else fallback)
            row.set_sensitive(enabled)
            group.add(row)
            self._direction_rows[key] = (row, ids)

        threshold_row = Adw.ActionRow()
        threshold_row.set_title(_("Drag distance"))
        threshold_row.set_subtitle(_("Sensor counts at 1000 DPI below which a press is a click, scaled to the mouse's DPI (15 is about 0.4 mm)"))
        spin = Gtk.SpinButton.new_with_range(1, 400, 1)
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_value(int(saved.get("threshold_px", 15)))
        spin.set_sensitive(enabled)
        threshold_row.add_suffix(spin)
        group.add(threshold_row)
        self._threshold_spin = spin

        def _on_toggle(sw, _pspec):
            for row, _ids in self._direction_rows.values():
                row.set_sensitive(sw.get_active())
            spin.set_sensitive(sw.get_active())

        switch.connect("notify::active", _on_toggle)
        return group

    def _collect_directions(self):
        directions = dict(getattr(self, "_saved_directions", None) or {})
        directions.update({
            "enabled": bool(self._direction_switch.get_active()),
            "threshold_px": int(self._threshold_spin.get_value()),
        })
        for key, (row, ids) in self._direction_rows.items():
            directions[key] = ids[row.get_selected()]
        return directions

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
        if self._direction_switch is not None:
            self._direction_switch.set_active(False)
            for row, ids in self._direction_rows.values():
                row.set_selected(ids.index("none") if "none" in ids else 0)
            self._threshold_spin.set_value(15)

        default_action = DEFAULT_BUTTON_ACTIONS.get(self.button_id, "Middle Click")

        for row in self._all_rows:
            if hasattr(row, "action_name") and row.action_name == default_action:
                self._on_row_activated(row)
                break

    def _on_save(self, button):
        changed = False

        if self._direction_switch is not None:
            buttons_config = config.get("buttons", default={})
            buttons_config["gesture_directions"] = self._collect_directions()
            config.set("buttons", buttons_config)
            changed = True

        if self.selected_action:
            changed = True
            action_id, action_name = self.selected_action

            # Update the MOUSE_BUTTONS dict
            if self.button_id in MOUSE_BUTTONS:
                MOUSE_BUTTONS[self.button_id]["action"] = action_name

            # Save to config
            buttons_config = config.get("buttons", default={})
            buttons_config[self.button_id] = action_id
            config.set("buttons", buttons_config)

            # The thumb wheel (horizontal_scroll) is a rotational control the
            # daemon drives from config.thumbwheel.mode, not from
            # buttons.horizontal_scroll (which it never reads). Mirror the choice
            # into thumbwheel.mode so assigning it here actually takes effect
            # instead of leaving the wheel on its previous mode (e.g. zoom).
            if self.button_id == "horizontal_scroll":
                tw_mode = {
                    "scroll_left_right": "scroll",
                    "zoom_in": "zoom",
                    "zoom_out": "zoom",
                    "volume_up": "volume",
                    "volume_down": "volume",
                    "none": "off",
                }.get(action_id)
                if tw_mode is not None:
                    config.set("thumbwheel", "mode", tw_mode)

            logger.info("Button %s configured to: %s", self.button_id, action_name)

        if changed:
            config.save()

        self.close()
