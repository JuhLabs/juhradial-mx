#!/usr/bin/env python3
"""
JuhRadial MX - Macros Page

Lists saved macros with edit/delete/duplicate controls and a
"New Macro" button. Each row opens the macro editor dialog.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gio, Adw, Pango

from i18n import _
from settings_theme import COLORS
from settings_widgets import PageHeader
from settings_macro_storage import (
    load_all_macros,
    delete_macro,
    duplicate_macro,
    REPEAT_MODE_LABELS,
    REPEAT_MODE_ICONS,
)
from settings_dialog_macro import MacroEditorDialog

logger = logging.getLogger(__name__)


class MacrosPage(Gtk.ScrolledWindow):
    """Macro list and management page."""

    def __init__(self, parent_window=None):
        super().__init__()
        self._parent_window = parent_window
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(20)
        content.set_margin_end(20)

        # Page header
        header = PageHeader(
            "applications-science-symbolic",
            _("Macros"),
            _("Create and manage macro sequences"),
        )
        content.append(header)

        # Action bar: New + Import
        action_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        action_bar.set_halign(Gtk.Align.START)

        new_btn = Gtk.Button()
        new_btn.add_css_class("suggested-action")
        new_btn_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        new_icon = Gtk.Image.new_from_icon_name("list-add-symbolic")
        new_btn_content.append(new_icon)
        new_label = Gtk.Label(label=_("New Macro"))
        new_btn_content.append(new_label)
        new_btn.set_child(new_btn_content)
        new_btn.connect("clicked", self._on_new_macro)
        action_bar.append(new_btn)

        import_btn = Gtk.Button()
        import_btn.add_css_class("secondary-btn")
        import_btn_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        imp_icon = Gtk.Image.new_from_icon_name("document-open-symbolic")
        import_btn_content.append(imp_icon)
        imp_label = Gtk.Label(label=_("Import"))
        import_btn_content.append(imp_label)
        import_btn.set_child(import_btn_content)
        import_btn.set_tooltip_text(
            _("Import a .json macro file.\n"
              "Format: {name, actions: [{type, key/ms/text, delay_after_ms}], repeat_mode}\n"
              "Action types: key_down, key_up, delay, text, mouse_click, scroll")
        )
        import_btn.connect("clicked", self._on_import_macro)
        action_bar.append(import_btn)

        content.append(action_bar)

        # Import format hint
        hint = Gtk.Label(
            label=_("Tip: Export a macro to see the JSON format, then edit and re-import."),
        )
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        hint.set_halign(Gtk.Align.START)
        content.append(hint)

        # Macro list container
        self._list_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._list_card.add_css_class("settings-card")
        content.append(self._list_card)

        # Wrap in Adw.Clamp for responsive centering
        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_tightening_threshold(700)
        clamp.set_child(content)
        self.set_child(clamp)

        # Initial load
        self._refresh_list()

    def set_parent_window(self, window):
        """Set parent window reference (deferred from constructor)."""
        self._parent_window = window

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh_list(self):
        """Reload macros from disk and rebuild the list UI."""
        # Clear existing children
        child = self._list_card.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._list_card.remove(child)
            child = next_child

        macros = load_all_macros()

        if not macros:
            self._show_empty_state()
            return

        # Card title
        title = Gtk.Label(label=_("Saved Macros"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("card-title")
        self._list_card.append(title)

        for macro in macros:
            row = self._create_macro_row(macro)
            self._list_card.append(row)

    def _show_empty_state(self):
        """Show empty state when no macros exist."""
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_halign(Gtk.Align.CENTER)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_margin_top(40)
        empty_box.set_margin_bottom(40)

        icon = Gtk.Image.new_from_icon_name("applications-science-symbolic")
        icon.set_pixel_size(48)
        icon.set_opacity(0.4)
        empty_box.append(icon)

        empty_title = Gtk.Label(label=_("No Macros"))
        empty_title.add_css_class("title-2")
        empty_box.append(empty_title)

        empty_desc = Gtk.Label(
            label=_("Create your first macro to automate key sequences,\nmouse actions, and more.")
        )
        empty_desc.add_css_class("dim-label")
        empty_desc.set_wrap(True)
        empty_desc.set_justify(Gtk.Justification.CENTER)
        empty_box.append(empty_desc)

        self._list_card.append(empty_box)

    def _create_macro_row(self, macro: dict) -> Gtk.Box:
        """Create a row for a single macro."""
        macro_id = macro.get("id", "")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("button-row")

        # Repeat mode icon
        repeat_mode = macro.get("repeat_mode", "once")
        icon_name = REPEAT_MODE_ICONS.get(repeat_mode, "media-playback-start-symbolic")
        icon_box = Gtk.Box()
        icon_box.add_css_class("button-icon-box")
        icon_box.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        icon.add_css_class("button-icon")
        icon_box.append(icon)
        row.append(icon_box)

        # Text content
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        name_label = Gtk.Label(label=macro.get("name", _("Untitled")))
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class("button-name")
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(name_label)

        # Subtitle: description or action count + repeat mode
        desc = macro.get("description", "")
        if not desc:
            action_count = len(macro.get("actions", []))
            mode_label = _(REPEAT_MODE_LABELS.get(repeat_mode, "Once"))
            desc = _("{} actions - {}").format(action_count, mode_label)

        subtitle = Gtk.Label(label=desc)
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("button-action")
        subtitle.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(subtitle)

        row.append(text_box)

        # Trigger badge (if assigned)
        trigger = macro.get("assigned_trigger")
        if trigger:
            trigger_badge = Gtk.Label(label=str(trigger))
            trigger_badge.add_css_class("device-badge")
            trigger_badge.set_valign(Gtk.Align.CENTER)
            row.append(trigger_badge)

        # Action buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btn_box.set_valign(Gtk.Align.CENTER)

        # Duplicate
        dup_btn = Gtk.Button()
        dup_btn.set_child(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        dup_btn.add_css_class("flat")
        dup_btn.add_css_class("circular")
        dup_btn.set_tooltip_text(_("Duplicate"))
        dup_btn.connect("clicked", lambda _, mid=macro_id: self._on_duplicate(mid))
        btn_box.append(dup_btn)

        # Delete
        del_btn = Gtk.Button()
        del_btn.set_child(Gtk.Image.new_from_icon_name("edit-delete-symbolic"))
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.set_tooltip_text(_("Delete"))
        del_btn.connect("clicked", lambda _, mid=macro_id, nm=macro.get("name", ""): self._on_delete(mid, nm))
        btn_box.append(del_btn)

        row.append(btn_box)

        # Arrow/edit button
        edit_btn = Gtk.Button()
        edit_btn.set_child(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        edit_btn.add_css_class("button-arrow")
        edit_btn.add_css_class("flat")
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.connect("clicked", lambda _, m=macro: self._on_edit_macro(m))
        row.append(edit_btn)

        # Make entire row clickable
        click = Gtk.GestureClick()
        click.connect("released", lambda g, n, x, y, m=macro: self._on_edit_macro(m))
        row.add_controller(click)

        return row

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_new_macro(self, btn):
        """Create a new macro and open editor."""
        if self._parent_window:
            dialog = MacroEditorDialog(
                self._parent_window,
                macro=None,
                on_saved=self._on_macro_saved,
            )
            dialog.present()

    def _on_edit_macro(self, macro):
        """Open editor for an existing macro."""
        if self._parent_window:
            dialog = MacroEditorDialog(
                self._parent_window,
                macro=macro,
                on_saved=self._on_macro_saved,
            )
            dialog.present()

    def _on_duplicate(self, macro_id):
        """Duplicate a macro."""
        result = duplicate_macro(macro_id)
        if result:
            self._refresh_list()

    def _on_delete(self, macro_id, macro_name):
        """Delete a macro with confirmation."""
        if not self._parent_window:
            return

        dialog = Adw.MessageDialog(
            transient_for=self._parent_window,
            modal=True,
            heading=_("Delete Macro?"),
            body=_('Are you sure you want to delete "%s"?\nThis cannot be undone.') % macro_name,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(dlg, response):
            if response == "delete":
                delete_macro(macro_id)
                self._refresh_list()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_import_macro(self, btn):
        """Import a macro from a JSON file."""
        if not self._parent_window:
            return

        try:
            file_dialog = Gtk.FileDialog()
            file_dialog.set_title(_("Import Macro"))

            json_filter = Gtk.FileFilter()
            json_filter.set_name(_("JSON files"))
            json_filter.add_pattern("*.json")
            filter_model = Gio.ListStore.new(Gtk.FileFilter.__gtype__)
            filter_model.append(json_filter)
            file_dialog.set_filters(filter_model)

            file_dialog.open(self._parent_window, None, self._on_import_file_selected)
        except Exception as e:
            logger.warning("Could not open file dialog: %s", e)

    def _on_import_file_selected(self, dialog, result):
        """Handle file selection for import."""
        try:
            file = dialog.open_finish(result)
            if file:
                import json
                path = file.get_path()
                with open(path, "r", encoding="utf-8") as f:
                    macro = json.load(f)
                # Give it a new id to avoid conflicts
                import uuid
                macro["id"] = str(uuid.uuid4())
                macro["name"] = macro.get("name", _("Imported Macro"))

                from settings_macro_storage import save_macro
                if save_macro(macro):
                    self._refresh_list()
        except Exception as e:
            logger.warning("Failed to import macro: %s", e)

    def _on_macro_saved(self, macro):
        """Callback when a macro is saved from the editor."""
        self._refresh_list()
