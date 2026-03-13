#!/usr/bin/env python3
"""
JuhRadial MX - Macro Editor Dialog

Full macro editing experience: name, description, repeat mode,
standard delay, timeline, action palette, and recorder.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, Adw

from i18n import _
from settings_macro_storage import (
    new_macro_template,
    save_macro,
)
from settings_macro_timeline import MacroTimeline
from settings_macro_actions import ActionPalette
from settings_macro_recorder import MacroRecorderDialog

logger = logging.getLogger(__name__)


def _mouse_button_name(btn_num):
    """Human-readable name for a GDK mouse button number."""
    names = {
        1: _("Left Click"), 2: _("Middle Click"), 3: _("Right Click"),
        4: _("Side (Button 4)"), 5: _("Extra (Button 5)"),
        8: _("Back"), 9: _("Forward"), 10: _("Button 10"), 11: _("Button 11"),
    }
    return names.get(btn_num, _("Mouse Button %d") % btn_num)


# Repeat modes for the dropdown
REPEAT_MODES = [
    ("once", "Once"),
    ("while_holding", "While Holding"),
    ("toggle", "Toggle On/Off"),
    ("repeat_n", "Repeat N Times"),
    ("sequence", "Sequence"),
]

# Sequence tab names
SEQUENCE_TABS = [
    ("press", "Press Actions"),
    ("hold", "Hold Actions"),
    ("release", "Release Actions"),
]


class MacroEditorDialog(Adw.Window):
    """Full-featured macro editor dialog.

    Args:
        parent: Parent window
        macro: Macro dict to edit (None for new macro)
        on_saved: Callback when macro is saved
    """

    def __init__(self, parent, macro=None, on_saved=None):
        super().__init__()
        self._parent = parent
        self._on_saved = on_saved
        self._macro = macro if macro else new_macro_template()
        self._is_new = macro is None
        self._sequence_timelines = {}

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title(
            _("New Macro") if self._is_new else _("Edit Macro")
        )
        self.set_default_size(720, 780)

        self._build_ui()
        self._load_macro_data()

    def _build_ui(self):
        """Build the complete dialog UI."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class("background")

        # Header bar with Save/Cancel
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_show_start_title_buttons(False)

        cancel_btn = Gtk.Button(label=_("Cancel"))
        cancel_btn.add_css_class("flat")
        cancel_btn.connect("clicked", lambda _: self.close())
        header.pack_start(cancel_btn)

        save_btn = Gtk.Button(label=_("Save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)

        content.append(header)

        # Scrollable body
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.set_margin_start(20)
        body.set_margin_end(20)
        body.set_margin_top(16)
        body.set_margin_bottom(16)

        # ---- Name & Description ----
        meta_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        meta_card.add_css_class("settings-card")

        card_title = Gtk.Label(label=_("Macro Details"))
        card_title.set_halign(Gtk.Align.START)
        card_title.add_css_class("card-title")
        meta_card.append(card_title)

        # Name
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name_box.add_css_class("setting-row")
        name_label = Gtk.Label(label=_("Name"))
        name_label.add_css_class("setting-label")
        name_label.set_halign(Gtk.Align.START)
        name_label.set_size_request(100, -1)
        name_box.append(name_label)

        self._name_entry = Gtk.Entry()
        self._name_entry.set_hexpand(True)
        self._name_entry.set_placeholder_text(_("Macro name"))
        name_box.append(self._name_entry)
        meta_card.append(name_box)

        # Description
        desc_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        desc_box.add_css_class("setting-row")
        desc_label = Gtk.Label(label=_("Description"))
        desc_label.add_css_class("setting-label")
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_size_request(100, -1)
        desc_label.set_valign(Gtk.Align.START)
        desc_box.append(desc_label)

        self._desc_entry = Gtk.Entry()
        self._desc_entry.set_hexpand(True)
        self._desc_entry.set_placeholder_text(_("Optional description"))
        desc_box.append(self._desc_entry)
        meta_card.append(desc_box)

        # Bind Trigger
        bind_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bind_box.add_css_class("setting-row")
        bind_label = Gtk.Label(label=_("Trigger"))
        bind_label.add_css_class("setting-label")
        bind_label.set_halign(Gtk.Align.START)
        bind_label.set_size_request(100, -1)
        bind_box.append(bind_label)

        self._bind_display = Gtk.Label(label=_("Not bound"))
        self._bind_display.add_css_class("setting-value")
        self._bind_display.set_hexpand(True)
        self._bind_display.set_halign(Gtk.Align.START)
        bind_box.append(self._bind_display)

        self._bind_btn = Gtk.Button(label=_("Bind"))
        self._bind_btn.add_css_class("flat")
        self._bind_btn.connect("clicked", self._on_bind_clicked)
        bind_box.append(self._bind_btn)

        self._unbind_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
        self._unbind_btn.set_tooltip_text(_("Remove binding"))
        self._unbind_btn.add_css_class("flat")
        self._unbind_btn.connect("clicked", self._on_unbind_clicked)
        bind_box.append(self._unbind_btn)

        meta_card.append(bind_box)

        body.append(meta_card)

        # ---- Repeat Mode & Standard Delay ----
        mode_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        mode_card.add_css_class("settings-card")

        mode_title = Gtk.Label(label=_("Playback"))
        mode_title.set_halign(Gtk.Align.START)
        mode_title.add_css_class("card-title")
        mode_card.append(mode_title)

        # Repeat mode dropdown
        mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        mode_row.add_css_class("setting-row")

        mode_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        mode_text.set_hexpand(True)
        mode_label = Gtk.Label(label=_("Repeat Mode"))
        mode_label.add_css_class("setting-label")
        mode_label.set_halign(Gtk.Align.START)
        mode_text.append(mode_label)
        mode_desc = Gtk.Label(label=_("How the macro repeats when triggered"))
        mode_desc.add_css_class("setting-value")
        mode_desc.set_halign(Gtk.Align.START)
        mode_text.append(mode_desc)
        mode_row.append(mode_text)

        # Dropdown
        mode_strings = Gtk.StringList()
        for _mode_id, display in REPEAT_MODES:
            mode_strings.append(_(display))
        self._mode_dropdown = Gtk.DropDown(model=mode_strings)
        self._mode_dropdown.set_size_request(180, -1)
        self._mode_dropdown.connect("notify::selected", self._on_repeat_mode_changed)
        mode_row.append(self._mode_dropdown)
        mode_card.append(mode_row)

        # Repeat count (shown only for repeat_n)
        self._repeat_count_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._repeat_count_row.add_css_class("setting-row")

        count_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        count_text.set_hexpand(True)
        count_label = Gtk.Label(label=_("Repeat Count"))
        count_label.add_css_class("setting-label")
        count_label.set_halign(Gtk.Align.START)
        count_text.append(count_label)
        self._repeat_count_row.append(count_text)

        adj = Gtk.Adjustment(value=3, lower=1, upper=999, step_increment=1, page_increment=10)
        self._repeat_spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        self._repeat_spin.set_size_request(100, -1)
        self._repeat_count_row.append(self._repeat_spin)
        self._repeat_count_row.set_visible(False)
        mode_card.append(self._repeat_count_row)

        # Standard delay
        delay_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        delay_row.add_css_class("setting-row")

        delay_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        delay_text.set_hexpand(True)
        delay_label = Gtk.Label(label=_("Standard Delay"))
        delay_label.add_css_class("setting-label")
        delay_label.set_halign(Gtk.Align.START)
        delay_text.append(delay_label)
        delay_desc = Gtk.Label(label=_("Auto-insert delay between actions"))
        delay_desc.add_css_class("setting-value")
        delay_desc.set_halign(Gtk.Align.START)
        delay_text.append(delay_desc)
        delay_row.append(delay_text)

        delay_control = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        delay_control.set_valign(Gtk.Align.CENTER)

        self._delay_switch = Gtk.Switch()
        self._delay_switch.set_valign(Gtk.Align.CENTER)
        delay_control.append(self._delay_switch)

        delay_adj = Gtk.Adjustment(value=50, lower=1, upper=5000, step_increment=5, page_increment=50)
        self._delay_spin = Gtk.SpinButton(adjustment=delay_adj, climb_rate=1, digits=0)
        self._delay_spin.set_size_request(80, -1)
        delay_control.append(self._delay_spin)

        ms_label = Gtk.Label(label=_("ms"))
        ms_label.add_css_class("dim-label")
        delay_control.append(ms_label)

        delay_row.append(delay_control)
        mode_card.append(delay_row)

        body.append(mode_card)

        # ---- Timeline ----
        timeline_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        timeline_card.add_css_class("settings-card")
        timeline_card.set_vexpand(True)

        # Sequence tabs (shown only for sequence mode)
        self._sequence_tabs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._sequence_tabs_box.set_visible(False)

        self._tab_stack = Gtk.Stack()
        self._tab_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        tab_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_bar.set_halign(Gtk.Align.CENTER)
        tab_bar.set_margin_top(8)
        tab_bar.set_margin_bottom(8)

        self._tab_buttons = {}
        for tab_id, tab_label in SEQUENCE_TABS:
            btn = Gtk.ToggleButton(label=_(tab_label))
            btn.add_css_class("flat")
            if tab_id == "press":
                btn.set_active(True)
            btn.connect("toggled", lambda b, tid=tab_id: self._on_tab_toggled(tid, b))
            tab_bar.append(btn)
            self._tab_buttons[tab_id] = btn

            # Create a timeline for each tab
            timeline = MacroTimeline(
                on_selection_changed=self._on_selection_changed,
                on_actions_changed=lambda actions, tid=tab_id: self._on_seq_actions_changed(tid, actions),
            )
            self._sequence_timelines[tab_id] = timeline
            self._tab_stack.add_named(timeline, tab_id)

        self._sequence_tabs_box.append(tab_bar)
        self._sequence_tabs_box.append(self._tab_stack)
        timeline_card.append(self._sequence_tabs_box)

        # Main timeline (shown for non-sequence modes)
        self._main_timeline = MacroTimeline(
            on_selection_changed=self._on_selection_changed,
            on_actions_changed=self._on_actions_changed,
        )
        self._main_timeline_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._main_timeline_box.append(self._main_timeline)
        timeline_card.append(self._main_timeline_box)

        # Record button row
        record_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        record_row.set_halign(Gtk.Align.CENTER)
        record_row.set_margin_top(8)
        record_row.set_margin_bottom(8)

        record_btn = Gtk.Button()
        record_btn.add_css_class("destructive-action")
        record_btn_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        record_icon = Gtk.Image.new_from_icon_name("media-record-symbolic")
        record_btn_content.append(record_icon)
        record_label = Gtk.Label(label=_("Record"))
        record_label.add_css_class("heading")
        record_btn_content.append(record_label)
        record_btn.set_child(record_btn_content)
        record_btn.set_size_request(140, 40)
        record_btn.connect("clicked", self._on_record)
        record_row.append(record_btn)

        # Clear all button
        clear_btn = Gtk.Button(label=_("Clear All"))
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", self._on_clear_timeline)
        record_row.append(clear_btn)

        timeline_card.append(record_row)

        body.append(timeline_card)

        # ---- Action Palette ----
        palette_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        palette_card.add_css_class("settings-card")

        self._action_palette = ActionPalette(
            parent_window=self,
            on_action_added=self._on_palette_action,
        )
        palette_card.append(self._action_palette)
        body.append(palette_card)

        scrolled.set_child(body)
        content.append(scrolled)

        self.set_content(content)

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    def _load_macro_data(self):
        """Populate UI from macro dict."""
        self._name_entry.set_text(self._macro.get("name", ""))
        self._desc_entry.set_text(self._macro.get("description", ""))
        self._load_bind_display()

        # Repeat mode
        mode = self._macro.get("repeat_mode", "once")
        mode_index = 0
        for i, (mid, _label) in enumerate(REPEAT_MODES):
            if mid == mode:
                mode_index = i
                break
        self._mode_dropdown.set_selected(mode_index)
        self._update_mode_visibility(mode)

        # Repeat count
        self._repeat_spin.set_value(self._macro.get("repeat_count", 3))

        # Standard delay
        self._delay_switch.set_active(self._macro.get("use_standard_delay", True))
        self._delay_spin.set_value(self._macro.get("standard_delay_ms", 50))

        # Actions
        actions = self._macro.get("actions", [])
        if mode == "sequence":
            # Distribute actions into sequence tabs
            seq_data = self._macro.get("sequence_actions", {})
            for tab_id in ("press", "hold", "release"):
                tab_actions = seq_data.get(tab_id, [])
                self._sequence_timelines[tab_id].set_actions(tab_actions)
        else:
            self._main_timeline.set_actions(actions)

    def _on_save(self, btn):
        """Save macro and close."""
        self._macro["name"] = self._name_entry.get_text().strip() or _("Untitled Macro")
        self._macro["description"] = self._desc_entry.get_text().strip()

        # Repeat mode
        idx = self._mode_dropdown.get_selected()
        if 0 <= idx < len(REPEAT_MODES):
            self._macro["repeat_mode"] = REPEAT_MODES[idx][0]

        self._macro["repeat_count"] = int(self._repeat_spin.get_value())
        self._macro["use_standard_delay"] = self._delay_switch.get_active()
        self._macro["standard_delay_ms"] = int(self._delay_spin.get_value())

        # Actions
        mode = self._macro.get("repeat_mode", "once")
        if mode == "sequence":
            self._macro["sequence_actions"] = {
                tab_id: tl.get_actions()
                for tab_id, tl in self._sequence_timelines.items()
            }
            self._macro["actions"] = []
        else:
            self._macro["actions"] = self._main_timeline.get_actions()
            self._macro.pop("sequence_actions", None)

        if save_macro(self._macro):
            logger.info("Macro saved: %s", self._macro.get("name"))
            if self._on_saved:
                self._on_saved(self._macro)
        self.close()

    # ------------------------------------------------------------------
    # Repeat mode UI
    # ------------------------------------------------------------------

    def _on_repeat_mode_changed(self, dropdown, _pspec):
        idx = dropdown.get_selected()
        if 0 <= idx < len(REPEAT_MODES):
            mode = REPEAT_MODES[idx][0]
            self._macro["repeat_mode"] = mode
            self._update_mode_visibility(mode)

    def _update_mode_visibility(self, mode):
        """Show/hide repeat count and sequence tabs based on mode."""
        self._repeat_count_row.set_visible(mode == "repeat_n")
        is_sequence = mode == "sequence"
        self._sequence_tabs_box.set_visible(is_sequence)
        self._main_timeline_box.set_visible(not is_sequence)

    def _on_tab_toggled(self, tab_id, button):
        """Handle sequence tab toggle."""
        if button.get_active():
            self._tab_stack.set_visible_child_name(tab_id)
            # Deactivate other tabs
            for tid, btn in self._tab_buttons.items():
                if tid != tab_id:
                    btn.set_active(False)

    # ------------------------------------------------------------------
    # Timeline callbacks
    # ------------------------------------------------------------------

    def _on_selection_changed(self, index):
        """Handle timeline selection change."""
        pass  # Could highlight the action in palette

    def _on_actions_changed(self, actions):
        """Handle main timeline actions change."""
        self._macro["actions"] = actions

    def _on_seq_actions_changed(self, tab_id, actions):
        """Handle sequence tab actions change."""
        if "sequence_actions" not in self._macro:
            self._macro["sequence_actions"] = {}
        self._macro["sequence_actions"][tab_id] = actions

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def _on_record(self, btn):
        """Open the recorder dialog."""
        recorder = MacroRecorderDialog(
            self, on_recording_complete=self._on_recording_complete
        )
        recorder.present()

    def _on_recording_complete(self, actions):
        """Add recorded actions to the active timeline."""
        timeline = self._get_active_timeline()
        for action in actions:
            timeline.append_action(action)

    # ------------------------------------------------------------------
    # Action palette
    # ------------------------------------------------------------------

    def _on_palette_action(self, action):
        """Add action from palette to the active timeline."""
        timeline = self._get_active_timeline()
        timeline.append_action(action)

    def _on_clear_timeline(self, btn):
        """Clear all actions from the active timeline."""
        timeline = self._get_active_timeline()
        timeline.clear_actions()

    def _get_active_timeline(self):
        """Return the currently visible timeline widget."""
        mode = self._macro.get("repeat_mode", "once")
        if mode == "sequence":
            visible_name = self._tab_stack.get_visible_child_name()
            return self._sequence_timelines.get(visible_name, self._main_timeline)
        return self._main_timeline

    # ------------------------------------------------------------------
    # Bind trigger
    # ------------------------------------------------------------------

    def _on_bind_clicked(self, btn):
        """Open a capture dialog to bind a mouse button or key."""
        dialog = Adw.Window()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_title(_("Bind Trigger"))
        dialog.set_default_size(360, 200)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.add_css_class("background")

        hdr = Adw.HeaderBar()
        hdr.set_show_end_title_buttons(True)
        box.append(hdr)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        inner.set_margin_start(24)
        inner.set_margin_end(24)
        inner.set_margin_top(24)
        inner.set_margin_bottom(24)
        inner.set_valign(Gtk.Align.CENTER)
        inner.set_vexpand(True)

        icon = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
        icon.set_pixel_size(48)
        icon.add_css_class("dim-label")
        inner.append(icon)

        prompt = Gtk.Label(label=_("Press any mouse button or key..."))
        prompt.add_css_class("title-3")
        inner.append(prompt)

        hint = Gtk.Label(label=_("This button will trigger the macro"))
        hint.add_css_class("dim-label")
        inner.append(hint)

        box.append(inner)
        dialog.set_content(box)

        # Capture keyboard
        key_ctrl = Gtk.EventControllerKey()

        def on_key(ctrl, keyval, keycode, state):
            name = Gdk.keyval_name(keyval)
            if name:
                self._macro["assigned_trigger"] = f"key:{name}"
                self._bind_display.set_label(name)
            dialog.close()
            return True

        key_ctrl.connect("key-pressed", on_key)
        dialog.add_controller(key_ctrl)

        # Capture mouse click
        click_ctrl = Gtk.GestureClick()
        click_ctrl.set_button(0)  # Listen to all buttons

        def on_click(gesture, n_press, x, y):
            btn_num = gesture.get_current_button()
            name = _mouse_button_name(btn_num)
            self._macro["assigned_trigger"] = f"mouse:{btn_num}"
            self._bind_display.set_label(name)
            dialog.close()

        click_ctrl.connect("pressed", on_click)
        dialog.add_controller(click_ctrl)

        dialog.present()

    def _on_unbind_clicked(self, btn):
        """Remove the trigger binding."""
        self._macro["assigned_trigger"] = None
        self._bind_display.set_label(_("Not bound"))

    def _load_bind_display(self):
        """Update bind display from macro data."""
        trigger = self._macro.get("assigned_trigger")
        if not trigger:
            self._bind_display.set_label(_("Not bound"))
            return
        if trigger.startswith("key:"):
            self._bind_display.set_label(trigger[4:])
        elif trigger.startswith("mouse:"):
            btn_num = int(trigger[6:])
            self._bind_display.set_label(_mouse_button_name(btn_num))
        else:
            self._bind_display.set_label(trigger)
