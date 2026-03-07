#!/usr/bin/env python3
"""
JuhRadial MX - Radial Menu Configuration Dialogs

RadialMenuConfigDialog and SliceConfigDialog for configuring the radial menu.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Adw, Pango

from i18n import _
from settings_config import ConfigManager, config, detect_terminal
from settings_constants import (
    RADIAL_ACTIONS,
    find_radial_action_index,
    DE_COMMAND_MAP,
    get_de_key,
)

logger = logging.getLogger(__name__)


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
        """Load the current radial menu from config"""
        return config.get("radial_menu", default={})

    def _on_save(self, _):
        """Save the radial menu configuration via ConfigManager"""
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

        config.set("radial_menu", "slices", slices)
        config.save()

        logger.info("Radial menu configuration saved")

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
        # Resolve DE-appropriate commands for preset buttons
        de_key = get_de_key(config.get("desktop_environment", default="auto"))
        de_cmds = DE_COMMAND_MAP.get(de_key, DE_COMMAND_MAP.get("generic", {}))
        screenshot_cmd = de_cmds.get("screenshot", ("exec", "flameshot gui"))
        files_cmd = de_cmds.get("files", ("exec", "xdg-open ~"))
        note_cmd = de_cmds.get("new_note", ("exec", "xdg-open"))
        emoji_cmd = de_cmds.get("emoji", ("exec", "ibus emoji"))
        terminal_cmd = detect_terminal()

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
            (_("Screenshot"), screenshot_cmd[0], screenshot_cmd[1], "blue", "camera-photo-symbolic"),
            (
                _("Lock Screen"),
                "exec",
                "loginctl lock-session",
                "red",
                "system-lock-screen-symbolic",
            ),
            (_("Files"), files_cmd[0], files_cmd[1], "sapphire", "folder-symbolic"),
            (_("Terminal"), "exec", terminal_cmd, "teal", "utilities-terminal-symbolic"),
            (_("Browser"), "exec", "xdg-open https://", "blue", "web-browser-symbolic"),
            (_("New Note"), note_cmd[0], note_cmd[1], "yellow", "document-new-symbolic"),
            (_("Emoji Picker"), emoji_cmd[0], emoji_cmd[1], "pink", "face-smile-symbolic"),
            (_("Settings"), "settings", "", "mauve", "emblem-system-symbolic"),
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
        """Handle color selection - ensure exactly one is selected"""
        if button.get_active():
            for c, btn in self.color_buttons.items():
                if c != color and btn.get_active():
                    btn.set_active(False)
        else:
            # Don't allow deselecting all colors
            any_active = any(btn.get_active() for btn in self.color_buttons.values())
            if not any_active:
                button.set_active(True)

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

        logger.info("Radial menu slice %d saved", self.slice_index + 1)

        # Call callback to refresh UI
        if self.on_save_callback:
            self.on_save_callback()

        self.close()
