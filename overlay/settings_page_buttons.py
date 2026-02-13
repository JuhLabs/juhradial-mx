#!/usr/bin/env python3
"""
JuhRadial MX - Buttons Page

ButtonsPage: Actions Ring configuration and button assignment UI.

SPDX-License-Identifier: GPL-3.0
"""

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk, Pango

from i18n import _
from settings_config import ConfigManager
from settings_constants import MOUSE_BUTTONS, translate_radial_label
from settings_dialogs import RadialMenuConfigDialog, SliceConfigDialog


class ButtonsPage(Gtk.ScrolledWindow):
    """Buttons configuration page - Premium UI Design"""

    # Icon mapping for each button type
    BUTTON_ICONS = {
        "middle": "input-mouse-symbolic",
        "shift_wheel": "media-playlist-shuffle-symbolic",
        "forward": "go-next-symbolic",
        "horizontal_scroll": "object-flip-horizontal-symbolic",
        "back": "go-previous-symbolic",
        "gesture": "input-touchpad-symbolic",
        "thumb": "view-app-grid-symbolic",
    }

    # Color hex values for slice indicators
    SLICE_COLORS = {
        "green": "#00e676",
        "yellow": "#ffd54f",
        "red": "#ff5252",
        "mauve": "#b388ff",
        "blue": "#4a9eff",
        "pink": "#ff80ab",
        "sapphire": "#00b4d8",
        "teal": "#0abdc6",
    }

    def __init__(self, on_button_config=None, parent_window=None, config_manager=None):
        super().__init__()
        self.on_button_config = on_button_config
        self.parent_window = parent_window
        self.config_manager = config_manager
        self.slice_rows = {}  # Store slice row widgets for updating
        self.set_policy(
            Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC
        )  # Allow horizontal scroll when needed

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)

        # =============================================
        # ACTIONS RING CARD - Shows all 8 slices
        # =============================================
        radial_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        radial_card.add_css_class("radial-menu-card")

        # Header row
        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        header_row.set_margin_bottom(12)

        # Large radial icon
        radial_icon_box = Gtk.Box()
        radial_icon_box.add_css_class("radial-icon-large")
        radial_icon_box.set_valign(Gtk.Align.CENTER)
        radial_icon = Gtk.Image.new_from_icon_name("view-app-grid-symbolic")
        radial_icon.set_pixel_size(28)
        radial_icon_box.append(radial_icon)
        header_row.append(radial_icon_box)

        # Text content
        radial_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        radial_text.set_hexpand(True)
        radial_text.set_valign(Gtk.Align.CENTER)

        radial_title = Gtk.Label(label=_("Actions Ring"))
        radial_title.set_halign(Gtk.Align.START)
        radial_title.add_css_class("radial-title")
        radial_text.append(radial_title)

        radial_subtitle = Gtk.Label(label=_("Click any action to customize"))
        radial_subtitle.set_halign(Gtk.Align.START)
        radial_subtitle.add_css_class("radial-subtitle")
        radial_text.append(radial_subtitle)

        header_row.append(radial_text)
        radial_card.append(header_row)

        # Slices container - 2 columns of 4 slices
        slices_grid = Gtk.Grid()
        slices_grid.set_column_spacing(12)
        slices_grid.set_row_spacing(8)
        slices_grid.set_column_homogeneous(True)

        # Load current slices from config
        slices = self._get_current_slices()

        # Position labels (clockwise from top)
        position_labels = [
            _("Top"),
            _("Top Right"),
            _("Right"),
            _("Bottom Right"),
            _("Bottom"),
            _("Bottom Left"),
            _("Left"),
            _("Top Left"),
        ]

        for i, slice_data in enumerate(slices):
            row = i % 4
            col = i // 4
            slice_widget = self._create_slice_row(i, slice_data, position_labels[i])
            self.slice_rows[i] = slice_widget
            slices_grid.attach(slice_widget, col, row, 1, 1)

        radial_card.append(slices_grid)
        content.append(radial_card)

        # =============================================
        # EASY-SWITCH SHORTCUTS CARD
        # =============================================
        easyswitch_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        easyswitch_card.add_css_class("easyswitch-shortcuts-card")

        # Create a row with icon, text, and switch
        easyswitch_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        easyswitch_row.add_css_class("easyswitch-row")

        # Icon box
        es_icon_box = Gtk.Box()
        es_icon_box.add_css_class("easyswitch-icon-box")
        es_icon_box.set_valign(Gtk.Align.CENTER)
        es_icon = Gtk.Image.new_from_icon_name("network-wireless-symbolic")
        es_icon.set_pixel_size(20)
        es_icon.add_css_class("easyswitch-icon")
        es_icon_box.append(es_icon)
        easyswitch_row.append(es_icon_box)

        # Text content
        es_text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        es_text_box.set_hexpand(True)
        es_text_box.set_valign(Gtk.Align.CENTER)

        es_title = Gtk.Label(label=_("Easy-Switch Shortcuts"))
        es_title.set_halign(Gtk.Align.START)
        es_title.add_css_class("easyswitch-title")
        es_text_box.append(es_title)

        es_desc = Gtk.Label(label=_("Replace Emoji with Easy-Switch 1, 2, 3 submenu"))
        es_desc.set_halign(Gtk.Align.START)
        es_desc.add_css_class("easyswitch-desc")
        es_text_box.append(es_desc)

        easyswitch_row.append(es_text_box)

        # Switch
        self.easyswitch_switch = Gtk.Switch()
        self.easyswitch_switch.set_valign(Gtk.Align.CENTER)
        self.easyswitch_switch.set_active(
            self.config_manager.get(
                "radial_menu", "easy_switch_shortcuts", default=False
            )
        )
        self.easyswitch_switch.connect("state-set", self._on_easyswitch_toggled)
        easyswitch_row.append(self.easyswitch_switch)

        easyswitch_card.append(easyswitch_row)
        content.append(easyswitch_card)

        # =============================================
        # BUTTON ASSIGNMENTS CARD
        # =============================================
        assignments_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        assignments_card.add_css_class("button-assignment-card")

        # Card header
        header = Gtk.Label(label=_("Button Assignments"))
        header.set_halign(Gtk.Align.START)
        header.add_css_class("button-assignment-header")
        assignments_card.append(header)

        # Button rows container
        self.button_rows = {}
        self.action_labels = {}

        for btn_id, btn_info in MOUSE_BUTTONS.items():
            row = self._create_button_row(btn_id, btn_info)
            self.button_rows[btn_id] = row
            assignments_card.append(row)

        content.append(assignments_card)
        self.set_child(content)

    def _create_button_row(self, btn_id, btn_info):
        """Create a premium styled button assignment row"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.add_css_class("button-row")

        # Icon box
        icon_box = Gtk.Box()
        icon_box.add_css_class("button-icon-box")
        icon_box.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name(
            self.BUTTON_ICONS.get(btn_id, "input-mouse-symbolic")
        )
        icon.set_pixel_size(20)
        icon.add_css_class("button-icon")
        icon_box.append(icon)
        row.append(icon_box)

        # Text content
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        name_label = Gtk.Label(label=btn_info["name"])
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class("button-name")
        text_box.append(name_label)

        # Action badge
        action_label = Gtk.Label(label=btn_info["action"])
        action_label.set_halign(Gtk.Align.START)
        action_label.add_css_class("button-action")
        text_box.append(action_label)
        self.action_labels[btn_id] = action_label

        row.append(text_box)

        # Arrow button
        arrow = Gtk.Button()
        arrow.set_child(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        arrow.add_css_class("button-arrow")
        arrow.add_css_class("flat")
        arrow.set_valign(Gtk.Align.CENTER)
        arrow.connect("clicked", lambda _, bid=btn_id: self._on_button_click(bid))
        row.append(arrow)

        # Make entire row clickable
        row_click = Gtk.GestureClick()
        row_click.connect(
            "released", lambda g, n, x, y, bid=btn_id: self._on_button_click(bid)
        )
        row.add_controller(row_click)

        return row

    def _on_button_click(self, button_id):
        """Handle button configuration click"""
        if self.on_button_config:
            self.on_button_config(button_id)

    def _on_configure_radial(self):
        """Open radial menu configuration"""
        if self.parent_window:
            dialog = RadialMenuConfigDialog(self.parent_window)
            dialog.present()

    def refresh_button_labels(self):
        """Refresh the button action labels after config change"""
        for btn_id, action_label in self.action_labels.items():
            if btn_id in MOUSE_BUTTONS:
                action_label.set_text(MOUSE_BUTTONS[btn_id]["action"])

    def _get_current_slices(self):
        """Get the current radial menu slices from config"""
        if self.config_manager:
            slices = self.config_manager.get("radial_menu", "slices", default=[])
            if slices:
                return slices
        # Return defaults if no config
        return ConfigManager.DEFAULT_CONFIG["radial_menu"]["slices"]

    def _create_slice_row(self, index, slice_data, position_label):
        """Create a compact slice row widget"""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("slice-row")

        # Color indicator dot
        color_name = slice_data.get("color", "teal")
        color_hex = self.SLICE_COLORS.get(color_name, "#0abdc6")

        color_dot = Gtk.DrawingArea()
        color_dot.set_size_request(10, 10)
        color_dot.set_valign(Gtk.Align.CENTER)

        def draw_dot(area, cr, width, height):
            # Parse color
            r = int(color_hex[1:3], 16) / 255.0
            g = int(color_hex[3:5], 16) / 255.0
            b = int(color_hex[5:7], 16) / 255.0
            # Draw filled circle
            cr.set_source_rgb(r, g, b)
            cr.arc(width / 2, height / 2, 4, 0, 2 * 3.14159)
            cr.fill()

        color_dot.set_draw_func(draw_dot)
        row.append(color_dot)

        # Icon
        icon_name = slice_data.get("icon", "application-x-executable-symbolic")
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        icon.add_css_class("slice-icon")
        row.append(icon)

        # Label
        label_text = translate_radial_label(
            slice_data.get("label", f"Slice {index + 1}"), slice_data.get("action_id")
        )
        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_hexpand(True)
        label.add_css_class("slice-label")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(label)

        # Edit button (arrow)
        edit_btn = Gtk.Button()
        edit_btn.set_child(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        edit_btn.add_css_class("slice-edit-btn")
        edit_btn.add_css_class("flat")
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.connect("clicked", lambda _, idx=index: self._on_edit_slice(idx))
        row.append(edit_btn)

        # Make entire row clickable
        row_click = Gtk.GestureClick()
        row_click.connect(
            "released", lambda g, n, x, y, idx=index: self._on_edit_slice(idx)
        )
        row.add_controller(row_click)

        return row

    def _on_edit_slice(self, slice_index):
        """Open dialog to edit a specific slice"""
        if self.parent_window:
            dialog = SliceConfigDialog(
                self.parent_window,
                slice_index,
                self.config_manager,
                self._on_slice_saved,
            )
            dialog.present()

    def _on_slice_saved(self):
        """Called when a slice is saved - refresh the UI"""
        # Refresh slices display
        slices = self._get_current_slices()

        for i, slice_data in enumerate(slices):
            if i in self.slice_rows:
                # Update the existing row's content
                row = self.slice_rows[i]
                # Find and update the label
                for child in row:
                    if isinstance(child, Gtk.Label):
                        child.set_text(
                            translate_radial_label(
                                slice_data.get("label", f"Slice {i + 1}"),
                                slice_data.get("action_id"),
                            )
                        )
                        break

    def _on_easyswitch_toggled(self, switch, state):
        """Handle Easy-Switch shortcuts toggle"""
        self.config_manager.set("radial_menu", "easy_switch_shortcuts", state)
        self.config_manager.save()

        # Update the Emoji slice row to show status
        if 5 in self.slice_rows:
            row = self.slice_rows[5]
            for child in row:
                if isinstance(child, Gtk.Label):
                    if state:
                        child.set_text(_("Easy-Switch"))
                    else:
                        # Restore original label from config
                        slices = self._get_current_slices()
                        if len(slices) > 5:
                            child.set_text(
                                translate_radial_label(
                                    slices[5].get("label", _("Emoji")),
                                    slices[5].get("action_id"),
                                )
                            )
                    break

        return False  # Allow switch to change state
