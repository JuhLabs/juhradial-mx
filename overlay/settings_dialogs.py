#!/usr/bin/env python3
"""
JuhRadial MX - Dialog Windows

All dialog classes for the settings dashboard:
ButtonConfigDialog, RadialMenuConfigDialog, SliceConfigDialog, AddApplicationDialog.

SPDX-License-Identifier: GPL-3.0
"""

import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, GLib, Gio, Adw, Pango

from i18n import _
from settings_config import ConfigManager, config
from settings_constants import (
    MOUSE_BUTTONS,
    DEFAULT_BUTTON_ACTIONS,
    BUTTON_ACTIONS,
    RADIAL_ACTIONS,
    find_radial_action_index,
)
from settings_widgets import SettingsCard


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


class RadialMenuConfigDialog(Adw.Window):
    """Dialog for configuring the radial menu slices"""

    def __init__(self, parent):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Configure Radial Menu"))
        self.set_default_size(600, 700)

        # Load current profile
        self.profile = self._load_profile()

        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=_("Save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)

        main_box.append(header)

        # Scrollable content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Description
        desc = Gtk.Label(
            label=_(
                "Configure the 8 actions in your radial menu. Click on a slice to change its action."
            )
        )
        desc.set_wrap(True)
        desc.set_margin_bottom(16)
        content.append(desc)

        # Slice configuration list
        self.slice_dropdowns = {}

        for i in range(8):
            slice_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            slice_box.add_css_class("setting-row")

            # Slice number and current action
            slice_label = Gtk.Label(label=_("Slice {}").format(i + 1))
            slice_label.set_width_chars(8)
            slice_label.set_xalign(0)
            slice_box.append(slice_label)

            # Get current slice config
            slices = self.profile.get("slices", [])
            current_slice = slices[i] if i < len(slices) else {}
            current_label = current_slice.get("label", "")
            current_action_id = current_slice.get("action_id")

            # Action dropdown
            dropdown = Gtk.DropDown()
            action_names = [
                name
                for _action_id, name, _icon, _action_type, _command, _color in RADIAL_ACTIONS
            ]
            dropdown.set_model(Gtk.StringList.new(action_names))

            selected_index = -1
            if current_action_id:
                for idx, (
                    action_id,
                    _name,
                    _icon,
                    _action_type,
                    _command,
                    _color,
                ) in enumerate(RADIAL_ACTIONS):
                    if action_id == current_action_id:
                        selected_index = idx
                        break
            if selected_index < 0 and current_label:
                selected_index = find_radial_action_index(current_label)
            if selected_index >= 0:
                dropdown.set_selected(selected_index)

            dropdown.set_hexpand(True)
            self.slice_dropdowns[i] = dropdown
            slice_box.append(dropdown)

            content.append(slice_box)

        scrolled.set_child(content)
        main_box.append(scrolled)

        self.set_content(main_box)

    def _load_profile(self):
        """Load the current radial menu from config.json"""
        config_path = Path.home() / ".config" / "juhradial" / "config.json"
        try:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                    # Return the radial_menu section
                    return config_data.get("radial_menu", {})
        except Exception as e:
            print(f"Failed to load config: {e}")
        return {}

    def _on_save(self, _):
        """Save the radial menu configuration to config.json"""
        config_path = Path.home() / ".config" / "juhradial" / "config.json"

        # Build new slices config in the format the overlay expects
        slices = []
        for i in range(8):
            dropdown = self.slice_dropdowns[i]
            selected = dropdown.get_selected()
            if 0 <= selected < len(RADIAL_ACTIONS):
                action_id, label, icon, action_type, command, color = RADIAL_ACTIONS[
                    selected
                ]
                slices.append(
                    {
                        "label": label,
                        "action_id": action_id,
                        "type": action_type,
                        "command": command,
                        "color": color,
                        "icon": icon,
                    }
                )

        # Load existing config and update radial_menu.slices
        try:
            config_data = {}
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)

            if "radial_menu" not in config_data:
                config_data["radial_menu"] = {}

            config_data["radial_menu"]["slices"] = slices

            # Save
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)

            print("Radial menu configuration saved!")

            # Notify daemon to reload
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                proxy = Gio.DBusProxy.new_sync(
                    bus,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    "org.kde.juhradialmx",
                    "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon",
                    None,
                )
                proxy.call_sync("ReloadConfig", None, Gio.DBusCallFlags.NONE, 500, None)
            except GLib.Error:
                pass  # Daemon may not be running

        except Exception as e:
            print(f"Failed to save profile: {e}")

        self.close()


class SliceConfigDialog(Adw.Window):
    """Dialog for configuring a single radial menu slice"""

    # Available action types
    ACTION_TYPES = None

    # Preset actions for quick selection
    PRESET_ACTIONS = None

    # Available colors
    COLORS = ["green", "yellow", "red", "mauve", "blue", "pink", "sapphire", "teal"]

    def __init__(self, parent, slice_index, config_manager, on_save_callback=None):
        super().__init__()
        self.ACTION_TYPES = [
            ("exec", _("Run Command"), _("Execute a shell command")),
            ("url", _("Open URL"), _("Open a web address")),
            ("settings", _("Open Settings"), _("Open JuhRadial settings")),
            ("emoji", _("Emoji Picker"), _("Show emoji picker")),
            ("submenu", _("Submenu"), _("Show a submenu with more options")),
        ]
        self.PRESET_ACTIONS = [
            (
                _("Play/Pause"),
                "exec",
                "playerctl play-pause",
                "green",
                "media-playback-start-symbolic",
            ),
            (
                _("Next Track"),
                "exec",
                "playerctl next",
                "green",
                "media-skip-forward-symbolic",
            ),
            (
                _("Previous Track"),
                "exec",
                "playerctl previous",
                "green",
                "media-skip-backward-symbolic",
            ),
            (
                _("Volume Up"),
                "exec",
                "pactl set-sink-volume @DEFAULT_SINK@ +5%",
                "blue",
                "audio-volume-high-symbolic",
            ),
            (
                _("Volume Down"),
                "exec",
                "pactl set-sink-volume @DEFAULT_SINK@ -5%",
                "blue",
                "audio-volume-low-symbolic",
            ),
            (
                _("Mute"),
                "exec",
                "pactl set-sink-mute @DEFAULT_SINK@ toggle",
                "blue",
                "audio-volume-muted-symbolic",
            ),
            (_("Screenshot"), "exec", "spectacle", "blue", "camera-photo-symbolic"),
            (
                _("Screenshot Area"),
                "exec",
                "spectacle -r",
                "blue",
                "camera-photo-symbolic",
            ),
            (
                _("Lock Screen"),
                "exec",
                "loginctl lock-session",
                "red",
                "system-lock-screen-symbolic",
            ),
            (_("Files"), "exec", "dolphin", "sapphire", "folder-symbolic"),
            (_("Terminal"), "exec", "konsole", "teal", "utilities-terminal-symbolic"),
            (_("Browser"), "exec", "xdg-open https://", "blue", "web-browser-symbolic"),
            (_("New Note"), "exec", "kwrite", "yellow", "document-new-symbolic"),
            (
                _("Calculator"),
                "exec",
                "kcalc",
                "mauve",
                "accessories-calculator-symbolic",
            ),
            (_("Settings"), "settings", "", "mauve", "emblem-system-symbolic"),
            (_("Emoji Picker"), "emoji", "", "pink", "face-smile-symbolic"),
        ]
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Configure Slice {}").format(slice_index + 1))
        self.set_default_size(500, 600)

        self.slice_index = slice_index
        self.config_manager = config_manager
        self.on_save_callback = on_save_callback

        # Load current slice data
        slices = config_manager.get("radial_menu", "slices", default=[])
        if slice_index < len(slices):
            self.slice_data = slices[slice_index].copy()
        else:
            self.slice_data = ConfigManager.DEFAULT_CONFIG["radial_menu"]["slices"][
                slice_index
            ].copy()

        self._build_ui()

    def _build_ui(self):
        """Build the dialog UI"""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=_("Save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)

        main_box.append(header)

        # Scrollable content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # ===============================
        # PRESET ACTIONS SECTION
        # ===============================
        preset_label = Gtk.Label(label=_("Quick Actions"))
        preset_label.set_halign(Gtk.Align.START)
        preset_label.add_css_class("heading")
        content.append(preset_label)

        preset_flow = Gtk.FlowBox()
        preset_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        preset_flow.set_max_children_per_line(3)
        preset_flow.set_min_children_per_line(2)
        preset_flow.set_column_spacing(8)
        preset_flow.set_row_spacing(8)

        for label, action_type, command, color, icon in self.PRESET_ACTIONS:
            btn = Gtk.Button()
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            btn_icon = Gtk.Image.new_from_icon_name(icon)
            btn_icon.set_pixel_size(14)
            btn_box.append(btn_icon)
            btn_label = Gtk.Label(label=label)
            btn_label.set_ellipsize(Pango.EllipsizeMode.END)
            btn_box.append(btn_label)
            btn.set_child(btn_box)
            btn.add_css_class("preset-btn")
            btn.connect(
                "clicked",
                lambda _, l=label, t=action_type, c=command, co=color, ic=icon: (
                    self._apply_preset(l, t, c, co, ic)
                ),
            )
            preset_flow.append(btn)

        content.append(preset_flow)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.set_margin_top(8)
        sep.set_margin_bottom(8)
        content.append(sep)

        # ===============================
        # CUSTOM CONFIGURATION
        # ===============================
        custom_label = Gtk.Label(label=_("Custom Configuration"))
        custom_label.set_halign(Gtk.Align.START)
        custom_label.add_css_class("heading")
        content.append(custom_label)

        # Label entry
        label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label_title = Gtk.Label(label=_("Label"))
        label_title.set_halign(Gtk.Align.START)
        label_title.add_css_class("dim-label")
        label_box.append(label_title)

        self.label_entry = Gtk.Entry()
        self.label_entry.set_text(self.slice_data.get("label", ""))
        self.label_entry.set_placeholder_text(_("Enter action label"))
        label_box.append(self.label_entry)
        content.append(label_box)

        # Action type dropdown
        type_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        type_title = Gtk.Label(label=_("Action Type"))
        type_title.set_halign(Gtk.Align.START)
        type_title.add_css_class("dim-label")
        type_box.append(type_title)

        self.type_dropdown = Gtk.DropDown()
        type_names = [name for _, name, _ in self.ACTION_TYPES]
        self.type_dropdown.set_model(Gtk.StringList.new(type_names))

        # Set current type
        current_type = self.slice_data.get("type", "exec")
        type_ids = [tid for tid, _, _ in self.ACTION_TYPES]
        if current_type in type_ids:
            self.type_dropdown.set_selected(type_ids.index(current_type))

        self.type_dropdown.connect("notify::selected", self._on_type_changed)
        type_box.append(self.type_dropdown)
        content.append(type_box)

        # Command entry
        cmd_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.cmd_title = Gtk.Label(label=_("Command"))
        self.cmd_title.set_halign(Gtk.Align.START)
        self.cmd_title.add_css_class("dim-label")
        cmd_box.append(self.cmd_title)

        self.command_entry = Gtk.Entry()
        self.command_entry.set_text(self.slice_data.get("command", ""))
        self.command_entry.set_placeholder_text(_("e.g., playerctl play-pause"))
        cmd_box.append(self.command_entry)
        self.cmd_box = cmd_box
        content.append(cmd_box)

        # Color picker
        color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        color_title = Gtk.Label(label=_("Color"))
        color_title.set_halign(Gtk.Align.START)
        color_title.add_css_class("dim-label")
        color_box.append(color_title)

        color_flow = Gtk.FlowBox()
        color_flow.set_selection_mode(Gtk.SelectionMode.SINGLE)
        color_flow.set_max_children_per_line(8)
        color_flow.set_min_children_per_line(8)
        color_flow.set_column_spacing(8)

        self.color_buttons = {}
        current_color = self.slice_data.get("color", "teal")

        for color in self.COLORS:
            btn = Gtk.ToggleButton()
            btn.set_size_request(32, 32)
            btn.add_css_class(f"color-btn-{color}")
            if color == current_color:
                btn.set_active(True)
            btn.connect("toggled", lambda b, c=color: self._on_color_selected(c, b))
            self.color_buttons[color] = btn
            color_flow.append(btn)

        color_box.append(color_flow)
        content.append(color_box)

        # Icon selector
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        icon_title = Gtk.Label(label=_("Icon"))
        icon_title.set_halign(Gtk.Align.START)
        icon_title.add_css_class("dim-label")
        icon_box.append(icon_title)

        self.icon_entry = Gtk.Entry()
        self.icon_entry.set_text(
            self.slice_data.get("icon", "application-x-executable-symbolic")
        )
        self.icon_entry.set_placeholder_text(_("Icon name (e.g., folder-symbolic)"))
        icon_box.append(self.icon_entry)
        content.append(icon_box)

        scrolled.set_child(content)
        main_box.append(scrolled)
        self.set_content(main_box)

        # Update command visibility based on type
        self._update_command_visibility()

    def _apply_preset(self, label, action_type, command, color, icon):
        """Apply a preset action"""
        self.label_entry.set_text(label)
        self.command_entry.set_text(command)
        self.icon_entry.set_text(icon)

        # Set type dropdown
        type_ids = [tid for tid, _, _ in self.ACTION_TYPES]
        if action_type in type_ids:
            self.type_dropdown.set_selected(type_ids.index(action_type))

        # Set color
        for c, btn in self.color_buttons.items():
            btn.set_active(c == color)

    def _on_type_changed(self, dropdown, _):
        """Handle action type change"""
        self._update_command_visibility()

    def _update_command_visibility(self):
        """Show/hide command entry based on action type"""
        selected = self.type_dropdown.get_selected()
        type_id = (
            self.ACTION_TYPES[selected][0]
            if selected < len(self.ACTION_TYPES)
            else "exec"
        )

        # Command is needed for exec and url types
        needs_command = type_id in ("exec", "url")
        self.cmd_box.set_visible(needs_command)

        if type_id == "url":
            self.cmd_title.set_text(_("URL"))
            self.command_entry.set_placeholder_text(_("e.g., https://claude.ai"))
        else:
            self.cmd_title.set_text(_("Command"))
            self.command_entry.set_placeholder_text(_("e.g., playerctl play-pause"))

    def _on_color_selected(self, color, button):
        """Handle color selection - ensure only one is selected"""
        if button.get_active():
            for c, btn in self.color_buttons.items():
                if c != color and btn.get_active():
                    btn.set_active(False)

    def _on_save(self, button):
        """Save the slice configuration"""
        # Get selected type
        selected_type = self.type_dropdown.get_selected()
        type_id = (
            self.ACTION_TYPES[selected_type][0]
            if selected_type < len(self.ACTION_TYPES)
            else "exec"
        )

        # Get selected color
        selected_color = "teal"
        for color, btn in self.color_buttons.items():
            if btn.get_active():
                selected_color = color
                break

        # Build slice data
        new_slice = {
            "label": self.label_entry.get_text()
            or _("Slice {}").format(self.slice_index + 1),
            "type": type_id,
            "command": self.command_entry.get_text(),
            "color": selected_color,
            "icon": self.icon_entry.get_text() or "application-x-executable-symbolic",
        }
        # Update config
        slices = self.config_manager.get("radial_menu", "slices", default=[])

        # Ensure we have 8 slices
        while len(slices) < 8:
            default_slice = ConfigManager.DEFAULT_CONFIG["radial_menu"]["slices"][
                len(slices)
            ].copy()
            slices.append(default_slice)

        slices[self.slice_index] = new_slice

        self.config_manager.set("radial_menu", "slices", slices)

        self.config_manager.save()

        print(f"Radial menu slice {self.slice_index + 1} saved!")

        # Call callback to refresh UI
        if self.on_save_callback:
            self.on_save_callback()

        self.close()


class AddApplicationDialog(Adw.Window):
    """Dialog for adding a per-application profile"""

    def __init__(self, parent):
        super().__init__()
        self.parent_window = parent
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Add Application Profile"))
        self.set_default_size(500, 600)

        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        main_box.append(header)

        # Content
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Description
        desc = Gtk.Label(
            label=_(
                "Create a custom profile for a specific application.\nThe radial menu will use this profile when the application is active."
            )
        )
        desc.set_wrap(True)
        desc.set_margin_bottom(16)
        content.append(desc)

        # Application selection
        app_card = SettingsCard(_("Select Application"))

        # Running apps list
        running_label = Gtk.Label(label=_("Running Applications:"))
        running_label.set_halign(Gtk.Align.START)
        running_label.set_margin_top(8)
        app_card.append(running_label)

        # Scrollable app list
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(200)

        self.app_list = Gtk.ListBox()
        self.app_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.app_list.add_css_class("boxed-list")

        # Get running applications
        self._populate_running_apps()

        scrolled.set_child(self.app_list)
        app_card.append(scrolled)

        # Or enter manually
        manual_label = Gtk.Label(label=_("Or enter application class manually:"))
        manual_label.set_halign(Gtk.Align.START)
        manual_label.set_margin_top(16)
        app_card.append(manual_label)

        self.app_entry = Gtk.Entry()
        self.app_entry.set_placeholder_text(_("e.g., firefox, code, gimp"))
        self.app_entry.set_margin_top(8)
        app_card.append(self.app_entry)

        content.append(app_card)

        # Add button
        add_btn = Gtk.Button(label=_("Add Profile"))
        add_btn.add_css_class("suggested-action")
        add_btn.set_margin_top(16)
        add_btn.connect("clicked", self._on_add_clicked)
        content.append(add_btn)

        main_box.append(content)
        self.set_content(main_box)

    def _populate_running_apps(self):
        """Get list of running applications using D-Bus and process detection"""
        import subprocess
        import re

        apps = set()

        try:
            # Method 1: Get running KDE apps from D-Bus session bus
            # Apps register as org.kde.<appname>-<pid> or similar patterns
            result = subprocess.run(
                ["qdbus-qt6"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    # Match patterns like org.kde.dolphin-12345
                    match = re.match(r"org\.kde\.(\w+)-\d+", line)
                    if match:
                        app_name = match.group(1)
                        if app_name not in (
                            "KWin",
                            "plasmashell",
                            "kded",
                            "kglobalaccel",
                        ):
                            apps.add(app_name)
                    # Also match org.mozilla.firefox, org.chromium, etc.
                    match = re.match(r"org\.(\w+)\.(\w+)", line)
                    if match:
                        org, app = match.group(1), match.group(2)
                        if org in ("mozilla", "chromium", "gnome", "gtk"):
                            apps.add(app.lower())
        except Exception as e:
            print(f"D-Bus app detection failed: {e}")

        try:
            # Method 2: Check for GUI processes with known .desktop files
            # Look at running processes and match against installed apps
            desktop_dirs = [
                Path("/usr/share/applications"),
                Path.home() / ".local/share/applications",
                Path("/var/lib/flatpak/exports/share/applications"),
                Path.home() / ".local/share/flatpak/exports/share/applications",
            ]

            # Get all installed app names from .desktop files
            installed_apps = {}
            for desktop_dir in desktop_dirs:
                if desktop_dir.exists():
                    for desktop_file in desktop_dir.glob("*.desktop"):
                        try:
                            content = desktop_file.read_text()
                            # Extract Exec line to get binary name
                            for line in content.split("\n"):
                                if line.startswith("Exec="):
                                    exec_cmd = line[5:].split()[
                                        0
                                    ]  # Get first word after Exec=
                                    binary = Path(exec_cmd).name
                                    # Map binary to desktop file name (app name)
                                    app_name = desktop_file.stem
                                    # Use shorter name if it's a reverse-domain style
                                    if "." in app_name:
                                        parts = app_name.split(".")
                                        app_name = (
                                            parts[-1] if len(parts) > 2 else app_name
                                        )
                                    installed_apps[binary] = app_name
                                    break
                        except (IOError, OSError, UnicodeDecodeError):
                            pass  # Desktop file not readable

            # Get running process names
            result = subprocess.run(
                ["ps", "-eo", "comm", "--no-headers"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                running_procs = set(result.stdout.strip().split("\n"))
                for proc in running_procs:
                    proc = proc.strip()
                    if proc in installed_apps:
                        apps.add(installed_apps[proc])
                    # Also check common GUI apps directly
                    elif proc in (
                        "firefox",
                        "chrome",
                        "chromium",
                        "code",
                        "konsole",
                        "dolphin",
                        "kate",
                        "okular",
                        "gwenview",
                        "spectacle",
                        "gimp",
                        "blender",
                        "inkscape",
                        "kwrite",
                        "vlc",
                        "mpv",
                        "obs",
                        "slack",
                        "discord",
                        "telegram-desktop",
                        "signal-desktop",
                        "spotify",
                        "thunderbird",
                        "evolution",
                        "nautilus",
                        "gedit",
                    ):
                        apps.add(proc)
        except Exception as e:
            print(f"Process detection failed: {e}")

        # Add some common apps that user might want (grayed out if not detected)
        common_apps = [
            "firefox",
            "chrome",
            "code",
            "gimp",
            "blender",
            "inkscape",
            "libreoffice",
            "konsole",
            "dolphin",
            "okular",
            "gwenview",
            "kate",
            "kwrite",
            "spectacle",
            "vlc",
            "obs",
        ]

        # Combine detected apps with common apps (detected first)
        all_apps = list(apps)
        for app in common_apps:
            if app not in apps:
                all_apps.append(app)

        # Populate list
        for app in all_apps[:30]:  # Limit to 30 apps
            row = Adw.ActionRow()
            row.set_title(app)
            row.app_name = app

            # Mark as running if detected
            if app in apps:
                row.set_subtitle(_("Running"))

            # Add checkmark suffix (hidden initially)
            check = Gtk.Image.new_from_icon_name("object-select-symbolic")
            check.set_visible(False)
            row.add_suffix(check)
            row.check_icon = check

            self.app_list.append(row)

        if not all_apps:
            # Add placeholder if nothing found
            row = Adw.ActionRow()
            row.set_title(_("(Enter app name manually below)"))
            self.app_list.append(row)

        self.app_list.connect("row-selected", self._on_app_selected)

    def _on_app_selected(self, list_box, row):
        """Handle app selection"""
        # Clear all checkmarks
        child = list_box.get_first_child()
        while child:
            if hasattr(child, "check_icon"):
                child.check_icon.set_visible(False)
            child = child.get_next_sibling()

        # Show checkmark on selected
        if row and hasattr(row, "check_icon"):
            row.check_icon.set_visible(True)
            if hasattr(row, "app_name"):
                self.app_entry.set_text(row.app_name)

    def _on_add_clicked(self, button):
        """Add the application profile"""
        app_name = self.app_entry.get_text().strip()

        if not app_name:
            dialog = Adw.AlertDialog(
                heading=_("No Application Selected"),
                body=_("Please select or enter an application name."),
            )
            dialog.add_response("ok", _("OK"))
            dialog.present(self)
            return

        # Save profile
        profile_path = Path.home() / ".config" / "juhradial" / "profiles.json"

        try:
            profiles = {}
            if profile_path.exists():
                with open(profile_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)

            # Create app-specific profile (copy current radial layout)
            default_slices = config.get(
                "radial_menu",
                "slices",
                default=ConfigManager.DEFAULT_CONFIG["radial_menu"]["slices"],
            )
            profiles[app_name] = {
                "name": app_name,
                "slices": json.loads(json.dumps(default_slices)),
                "app_class": app_name,
            }

            # Save
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(profiles, f, indent=2)

            print(f"Created profile for: {app_name}")

            if hasattr(self.parent_window, "show_toast"):
                self.parent_window.show_toast(
                    _("Profile created for {}").format(app_name)
                )

            # Show success and close
            self.close()

            # Show toast in parent (if supported)
            toast = Adw.Toast(title=_("Profile created for {}").format(app_name))
            toast.set_timeout(2)
            # Note: Would need ToastOverlay in parent for this to work

        except Exception as e:
            print(f"Failed to save profile: {e}")
            dialog = Adw.AlertDialog(
                heading=_("Error"), body=_("Failed to create profile: {}").format(e)
            )
            dialog.add_response("ok", _("OK"))
            dialog.present(self)


class ApplicationProfilesGridDialog(Adw.Window):
    """Grid view dialog for per-application profiles"""

    def __init__(self, parent):
        super().__init__()
        self.parent_window = parent
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(_("Application Profiles"))
        self.set_default_size(780, 560)
        self.add_css_class("background")

        self.profile_path = Path.home() / ".config" / "juhradial" / "profiles.json"

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        close_btn = Gtk.Button(label=_("Close"))
        close_btn.add_css_class("secondary-btn")
        close_btn.connect("clicked", lambda _: self.close())
        header.pack_start(close_btn)

        refresh_btn = Gtk.Button(label=_("Refresh"))
        refresh_btn.add_css_class("primary-btn")
        refresh_btn.connect("clicked", lambda _: self._reload_grid())
        header.pack_end(refresh_btn)

        main_box.append(header)

        self.status_label = Gtk.Label()
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_margin_top(12)
        self.status_label.set_margin_start(20)
        self.status_label.set_margin_end(20)
        self.status_label.add_css_class("dim-label")
        main_box.append(self.status_label)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.set_column_spacing(12)
        self.grid.set_row_spacing(12)
        self.grid.set_margin_top(12)
        self.grid.set_margin_bottom(20)
        self.grid.set_margin_start(20)
        self.grid.set_margin_end(20)

        scrolled.set_child(self.grid)
        main_box.append(scrolled)

        self.set_content(main_box)
        self._reload_grid()

    def _load_profiles(self):
        """Load profiles dict from profiles.json"""
        if not self.profile_path.exists():
            return {}

        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"Failed to load profiles: {e}")
            return {}

    def _save_profiles(self, profiles):
        """Save profiles dict to profiles.json"""
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)

    def _create_profile_card(self, app_name, profile):
        """Create a card widget for one app profile"""
        card = SettingsCard(app_name)
        card.set_size_request(240, -1)
        card.set_margin_top(4)
        card.set_margin_bottom(4)
        card.set_margin_start(4)
        card.set_margin_end(4)

        icon = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
        icon.set_pixel_size(28)
        icon.set_halign(Gtk.Align.START)
        card.append(icon)

        slices = profile.get("slices", []) if isinstance(profile, dict) else []
        configured = 0
        for s in slices:
            if isinstance(s, dict) and s.get("type") and s.get("type") != "none":
                configured += 1

        subtitle = Gtk.Label(label=_("Slices: {}/8 configured").format(configured))
        subtitle.set_halign(Gtk.Align.START)
        subtitle.set_xalign(0.0)
        subtitle.add_css_class("dim-label")
        card.append(subtitle)

        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        edit_btn = Gtk.Button(label=_("Edit Slices"))
        edit_btn.add_css_class("primary-btn")
        edit_btn.connect("clicked", self._on_edit_profile, app_name)
        actions_row.append(edit_btn)

        remove_btn = Gtk.Button(label=_("Remove"))
        remove_btn.add_css_class("danger-btn")
        remove_btn.connect("clicked", self._on_remove_profile, app_name)
        actions_row.append(remove_btn)

        card.append(actions_row)
        return card

    def _on_edit_profile(self, _button, app_name):
        dialog = AppProfileSlicesDialog(self, app_name)
        dialog.connect("close-request", lambda *_: self._reload_grid())
        dialog.present()

    def _on_remove_profile(self, _button, app_name):
        """Remove one app profile"""
        profiles = self._load_profiles()
        if app_name not in profiles:
            return

        try:
            del profiles[app_name]
            self._save_profiles(profiles)
            self._reload_grid()
            if hasattr(self.parent_window, "show_toast"):
                self.parent_window.show_toast(
                    _("Removed profile for {}").format(app_name)
                )
        except Exception as e:
            dialog = Adw.AlertDialog(
                heading=_("Error"),
                body=_("Failed to remove profile: {}").format(e),
            )
            dialog.add_response("ok", _("OK"))
            dialog.present(self)

    def _reload_grid(self):
        """Rebuild profile grid from disk"""
        while child := self.grid.get_first_child():
            self.grid.remove(child)

        profiles = self._load_profiles()
        app_profiles = [
            (name, data)
            for name, data in profiles.items()
            if name != "default" and isinstance(data, dict)
        ]
        app_profiles.sort(key=lambda item: item[0].lower())

        if not app_profiles:
            self.status_label.set_text(
                _("No application profiles yet. Use '+ Add Application' to create one.")
            )
            return

        self.status_label.set_text(_("Profiles: {}").format(len(app_profiles)))
        for idx, (app_name, profile) in enumerate(app_profiles):
            col = idx % 3
            row = idx // 3
            self.grid.attach(
                self._create_profile_card(app_name, profile), col, row, 1, 1
            )


class AppProfileSlicesDialog(Adw.Window):
    """Configure slices for one application profile"""

    def __init__(self, parent, app_name):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.add_css_class("background")
        self.parent_dialog = parent
        self.app_name = app_name
        self.profile_path = Path.home() / ".config" / "juhradial" / "profiles.json"
        self.set_title(_("Edit Profile: {}").format(app_name))
        self.set_default_size(560, 640)

        self.profile = self._load_profile(app_name)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.add_css_class("secondary-btn")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=_("Save"))
        save_btn.add_css_class("primary-btn")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)
        main_box.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        desc = Gtk.Label(
            label=_(
                "Choose which action each slice should use when this application is active."
            )
        )
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        desc.set_xalign(0.0)
        desc.add_css_class("dim-label")
        content.append(desc)

        self.slice_dropdowns = {}
        slices = self.profile.get("slices", [])

        for i in range(8):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            row.add_css_class("setting-row")

            label = Gtk.Label(label=_("Slice {}").format(i + 1))
            label.set_width_chars(8)
            label.set_xalign(0.0)
            row.append(label)

            dropdown = Gtk.DropDown()
            action_names = [
                name
                for _action_id, name, _icon, _action_type, _command, _color in RADIAL_ACTIONS
            ]
            dropdown.set_model(Gtk.StringList.new(action_names))

            current_slice = (
                slices[i] if i < len(slices) and isinstance(slices[i], dict) else {}
            )
            current_action_id = current_slice.get("action_id")
            current_label = current_slice.get("label", "")

            selected_index = -1
            if current_action_id:
                for idx, (
                    action_id,
                    _name,
                    _icon,
                    _action_type,
                    _command,
                    _color,
                ) in enumerate(RADIAL_ACTIONS):
                    if action_id == current_action_id:
                        selected_index = idx
                        break
            if selected_index < 0 and current_label:
                selected_index = find_radial_action_index(current_label)
            if selected_index >= 0:
                dropdown.set_selected(selected_index)

            dropdown.set_hexpand(True)
            self.slice_dropdowns[i] = dropdown
            row.append(dropdown)
            content.append(row)

        scrolled.set_child(content)
        main_box.append(scrolled)
        self.set_content(main_box)

    def _load_profile(self, app_name):
        profiles = {}
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                profiles = {}

        profile = profiles.get(app_name, {}) if isinstance(profiles, dict) else {}
        if not isinstance(profile, dict):
            profile = {}

        slices = profile.get("slices", [])
        if not isinstance(slices, list):
            slices = []

        while len(slices) < 8:
            slices.append({})

        profile["name"] = app_name
        profile["app_class"] = app_name
        profile["slices"] = slices[:8]
        return profile

    def _on_save(self, _button):
        new_slices = []
        for i in range(8):
            dropdown = self.slice_dropdowns[i]
            selected = dropdown.get_selected()
            if 0 <= selected < len(RADIAL_ACTIONS):
                action_id, label, icon, action_type, command, color = RADIAL_ACTIONS[
                    selected
                ]
                new_slices.append(
                    {
                        "label": label,
                        "action_id": action_id,
                        "type": action_type,
                        "command": command,
                        "color": color,
                        "icon": icon,
                    }
                )
            else:
                new_slices.append({})

        profiles = {}
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
            except Exception:
                profiles = {}

        if not isinstance(profiles, dict):
            profiles = {}

        profiles[self.app_name] = {
            "name": self.app_name,
            "app_class": self.app_name,
            "slices": new_slices,
        }

        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)

        if hasattr(self.parent_dialog.parent_window, "show_toast"):
            self.parent_dialog.parent_window.show_toast(
                _("Updated profile for {}").format(self.app_name)
            )
        self.close()
