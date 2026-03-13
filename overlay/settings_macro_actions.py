#!/usr/bin/env python3
"""
JuhRadial MX - Macro Action Palette

Horizontal palette bar for manually building macros. Provides buttons
for adding keystrokes, mouse clicks, delays, text, and scroll actions
to the timeline.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, GLib, Adw

from i18n import _
from settings_theme import COLORS
from settings_macro_storage import new_action

logger = logging.getLogger(__name__)


class ActionPalette(Gtk.Box):
    """Horizontal action palette for adding macro actions.

    Calls on_action_added(action_dict) when the user creates an action.
    """

    def __init__(self, parent_window=None, on_action_added=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._parent_window = parent_window
        self._on_action_added = on_action_added

        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(8)
        self.set_margin_bottom(8)

        # Section header
        header = Gtk.Label(label=_("ADD ACTION"))
        header.set_halign(Gtk.Align.START)
        header.add_css_class("section-header")
        self.append(header)

        # Button row
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_homogeneous(False)

        # Keystroke button
        key_btn = self._make_palette_button(
            "input-keyboard-symbolic",
            _("Keystroke"),
            _("Record a key press and release"),
            self._on_keystroke,
        )
        btn_row.append(key_btn)

        # Mouse click button
        mouse_btn = self._make_palette_button(
            "input-mouse-symbolic",
            _("Mouse"),
            _("Add a mouse button action"),
            self._on_mouse_click,
        )
        btn_row.append(mouse_btn)

        # Delay button
        delay_btn = self._make_palette_button(
            "preferences-system-time-symbolic",
            _("Delay"),
            _("Add a delay between actions"),
            self._on_delay,
        )
        btn_row.append(delay_btn)

        # Text button
        text_btn = self._make_palette_button(
            "insert-text-symbolic",
            _("Text"),
            _("Type a string of text"),
            self._on_text,
        )
        btn_row.append(text_btn)

        # Scroll button
        scroll_btn = self._make_palette_button(
            "input-touchpad-symbolic",
            _("Scroll"),
            _("Add a scroll action"),
            self._on_scroll,
        )
        btn_row.append(scroll_btn)

        self.append(btn_row)

    def _make_palette_button(self, icon_name, label, tooltip, callback):
        """Create a styled palette button with icon and label."""
        btn = Gtk.Button()
        btn.add_css_class("palette-action-btn")
        btn.set_tooltip_text(tooltip)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        box.append(icon)

        lbl = Gtk.Label(label=label)
        lbl.add_css_class("caption")
        box.append(lbl)

        btn.set_child(box)
        btn.connect("clicked", lambda _: callback())
        return btn

    def _emit_action(self, action):
        """Send action to the timeline."""
        if self._on_action_added:
            self._on_action_added(action)

    # ------------------------------------------------------------------
    # Keystroke
    # ------------------------------------------------------------------

    def _on_keystroke(self):
        """Open key capture dialog."""
        dialog = KeyCaptureDialog(self._parent_window)
        dialog.connect("response", self._on_key_captured)
        dialog.present()

    def _on_key_captured(self, dialog, response):
        if response == "add" and dialog.captured_key:
            key_name = dialog.captured_key
            keycode = dialog.captured_keycode
            # Add key_down + key_up pair
            self._emit_action(new_action("key_down", key=key_name, keycode=keycode))
            self._emit_action(new_action("key_up", key=key_name, keycode=keycode))

    # ------------------------------------------------------------------
    # Mouse click
    # ------------------------------------------------------------------

    def _on_mouse_click(self):
        """Open mouse button selector dialog."""
        dialog = MouseActionDialog(self._parent_window)
        dialog.connect("response", self._on_mouse_action_selected)
        dialog.present()

    def _on_mouse_action_selected(self, dialog, response):
        if response == "add":
            button = dialog.selected_button
            mode = dialog.selected_mode
            if mode == "click":
                self._emit_action(new_action("mouse_click", button=button))
            elif mode == "down":
                self._emit_action(new_action("mouse_down", button=button))
            elif mode == "up":
                self._emit_action(new_action("mouse_up", button=button))

    # ------------------------------------------------------------------
    # Delay
    # ------------------------------------------------------------------

    def _on_delay(self):
        """Add a delay action with a quick entry."""
        dialog = DelayInputDialog(self._parent_window)
        dialog.connect("response", self._on_delay_entered)
        dialog.present()

    def _on_delay_entered(self, dialog, response):
        if response == "add":
            self._emit_action(new_action("delay", ms=dialog.delay_ms))

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def _on_text(self):
        """Open text entry dialog."""
        dialog = TextInputDialog(self._parent_window)
        dialog.connect("response", self._on_text_entered)
        dialog.present()

    def _on_text_entered(self, dialog, response):
        if response == "add" and dialog.text_value:
            self._emit_action(new_action("text", text=dialog.text_value))

    # ------------------------------------------------------------------
    # Scroll
    # ------------------------------------------------------------------

    def _on_scroll(self):
        """Open scroll config dialog."""
        dialog = ScrollActionDialog(self._parent_window)
        dialog.connect("response", self._on_scroll_configured)
        dialog.present()

    def _on_scroll_configured(self, dialog, response):
        if response == "add":
            self._emit_action(
                new_action("scroll", direction=dialog.direction, amount=dialog.amount)
            )


# ======================================================================
# Sub-dialogs for action configuration
# ======================================================================


class KeyCaptureDialog(Adw.MessageDialog):
    """Modal dialog that captures a single key press."""

    def __init__(self, parent):
        super().__init__(
            transient_for=parent,
            modal=True,
            heading=_("Press Any Key"),
            body=_("Press the key you want to add to the macro.\nPress Escape to cancel."),
        )
        self.captured_key = None
        self.captured_keycode = 0

        self.add_response("cancel", _("Cancel"))
        self.add_response("add", _("Add"))
        self.set_response_enabled("add", False)
        self.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        # Key display area
        self._key_label = Gtk.Label(label=_("Waiting..."))
        self._key_label.add_css_class("title-1")
        self._key_label.set_margin_top(16)
        self._key_label.set_margin_bottom(16)
        self.set_extra_child(self._key_label)

        # Key event controller
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.response("cancel")
            return True

        key_name = Gdk.keyval_name(keyval)
        if key_name:
            self.captured_key = key_name
            self.captured_keycode = keycode
            self._key_label.set_label(key_name)
            self.set_response_enabled("add", True)
        return True


class MouseActionDialog(Adw.MessageDialog):
    """Dialog for selecting mouse button and action mode."""

    def __init__(self, parent):
        super().__init__(
            transient_for=parent,
            modal=True,
            heading=_("Mouse Action"),
            body=_("Choose button and action type."),
        )
        self.selected_button = "left"
        self.selected_mode = "click"

        self.add_response("cancel", _("Cancel"))
        self.add_response("add", _("Add"))
        self.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(8)

        # Button selector
        btn_label = Gtk.Label(label=_("Button"))
        btn_label.set_halign(Gtk.Align.START)
        btn_label.add_css_class("heading")
        content.append(btn_label)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_group = None
        for btn_name in ["left", "middle", "right"]:
            rb = Gtk.CheckButton(label=_(btn_name.title()))
            if btn_group is None:
                btn_group = rb
            else:
                rb.set_group(btn_group)
            if btn_name == "left":
                rb.set_active(True)
            rb.connect(
                "toggled",
                lambda w, name=btn_name: setattr(self, "selected_button", name) if w.get_active() else None,
            )
            btn_box.append(rb)
        content.append(btn_box)

        # Mode selector
        mode_label = Gtk.Label(label=_("Mode"))
        mode_label.set_halign(Gtk.Align.START)
        mode_label.add_css_class("heading")
        mode_label.set_margin_top(8)
        content.append(mode_label)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mode_group = None
        for mode_name, mode_display in [("click", _("Click")), ("down", _("Down")), ("up", _("Up"))]:
            rb = Gtk.CheckButton(label=mode_display)
            if mode_group is None:
                mode_group = rb
            else:
                rb.set_group(mode_group)
            if mode_name == "click":
                rb.set_active(True)
            rb.connect(
                "toggled",
                lambda w, name=mode_name: setattr(self, "selected_mode", name) if w.get_active() else None,
            )
            mode_box.append(rb)
        content.append(mode_box)

        self.set_extra_child(content)


class DelayInputDialog(Adw.MessageDialog):
    """Dialog for entering a delay value in milliseconds."""

    def __init__(self, parent):
        super().__init__(
            transient_for=parent,
            modal=True,
            heading=_("Add Delay"),
            body=_("Enter delay duration in milliseconds."),
        )
        self.delay_ms = 50

        self.add_response("cancel", _("Cancel"))
        self.add_response("add", _("Add"))
        self.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        content.set_halign(Gtk.Align.CENTER)
        content.set_margin_top(8)

        adj = Gtk.Adjustment(value=50, lower=1, upper=10000, step_increment=10, page_increment=100)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        spin.set_size_request(120, -1)
        spin.connect("value-changed", lambda s: setattr(self, "delay_ms", int(s.get_value())))
        content.append(spin)

        ms_label = Gtk.Label(label=_("ms"))
        ms_label.add_css_class("heading")
        content.append(ms_label)

        # Quick preset buttons
        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        presets.set_margin_top(8)
        presets.set_halign(Gtk.Align.CENTER)
        for ms_val in [10, 25, 50, 100, 250, 500, 1000]:
            preset_btn = Gtk.Button(label=f"{ms_val}ms")
            preset_btn.add_css_class("flat")
            preset_btn.connect(
                "clicked",
                lambda _, v=ms_val, s=spin: (s.set_value(v), setattr(self, "delay_ms", v)),
            )
            presets.append(preset_btn)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.append(content)
        vbox.append(presets)
        self.set_extra_child(vbox)


class TextInputDialog(Adw.MessageDialog):
    """Dialog for entering text to type."""

    def __init__(self, parent):
        super().__init__(
            transient_for=parent,
            modal=True,
            heading=_("Type Text"),
            body=_("Enter text to type in the macro."),
        )
        self.text_value = ""

        self.add_response("cancel", _("Cancel"))
        self.add_response("add", _("Add"))
        self.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        entry = Gtk.Entry()
        entry.set_placeholder_text(_("Enter text..."))
        entry.set_margin_top(8)
        entry.connect(
            "changed", lambda e: setattr(self, "text_value", e.get_text())
        )
        self.set_extra_child(entry)


class ScrollActionDialog(Adw.MessageDialog):
    """Dialog for configuring a scroll action."""

    def __init__(self, parent):
        super().__init__(
            transient_for=parent,
            modal=True,
            heading=_("Scroll Action"),
            body=_("Choose scroll direction and amount."),
        )
        self.direction = "up"
        self.amount = 3

        self.add_response("cancel", _("Cancel"))
        self.add_response("add", _("Add"))
        self.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(8)

        # Direction
        dir_label = Gtk.Label(label=_("Direction"))
        dir_label.set_halign(Gtk.Align.START)
        dir_label.add_css_class("heading")
        content.append(dir_label)

        dir_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dir_group = None
        for dir_name in ["up", "down", "left", "right"]:
            rb = Gtk.CheckButton(label=_(dir_name.title()))
            if dir_group is None:
                dir_group = rb
            else:
                rb.set_group(dir_group)
            if dir_name == "up":
                rb.set_active(True)
            rb.connect(
                "toggled",
                lambda w, name=dir_name: setattr(self, "direction", name) if w.get_active() else None,
            )
            dir_box.append(rb)
        content.append(dir_box)

        # Amount
        amt_label = Gtk.Label(label=_("Amount (clicks)"))
        amt_label.set_halign(Gtk.Align.START)
        amt_label.add_css_class("heading")
        amt_label.set_margin_top(4)
        content.append(amt_label)

        adj = Gtk.Adjustment(value=3, lower=1, upper=100, step_increment=1, page_increment=5)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        spin.set_size_request(100, -1)
        spin.connect("value-changed", lambda s: setattr(self, "amount", int(s.get_value())))
        content.append(spin)

        self.set_extra_child(content)
