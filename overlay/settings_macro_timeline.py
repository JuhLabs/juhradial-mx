#!/usr/bin/env python3
"""
JuhRadial MX - Macro Timeline Widget

Visual timeline showing ordered macro actions with drag-and-drop
reordering, inline delay editing, and context menus.

SPDX-License-Identifier: GPL-3.0
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gdk, Gio, Pango

from i18n import _
from settings_theme import COLORS
from settings_macro_storage import ACTION_TYPE_ICONS, new_action

logger = logging.getLogger(__name__)

# Color coding for action types (Catppuccin palette references)
ACTION_TYPE_COLORS = {
    "key_down": COLORS.get("green", "#a6e3a1"),
    "key_up": COLORS.get("red", "#f38ba8"),
    "mouse_down": COLORS.get("blue", "#89b4fa"),
    "mouse_up": COLORS.get("mauve", "#cba6f7"),
    "mouse_click": COLORS.get("sapphire", "#74c7ec"),
    "delay": COLORS.get("yellow", "#f9e2af"),
    "text": COLORS.get("peach", "#fab387"),
    "scroll": COLORS.get("teal", "#94e2d5"),
}


def _action_summary(action: dict) -> str:
    """Human-readable one-line summary of an action."""
    atype = action.get("type", "unknown")
    if atype == "key_down":
        return _("Key Down: {}").format(action.get("key", "?"))
    if atype == "key_up":
        return _("Key Up: {}").format(action.get("key", "?"))
    if atype == "mouse_down":
        return _("Mouse Down: {}").format(action.get("button", "left").title())
    if atype == "mouse_up":
        return _("Mouse Up: {}").format(action.get("button", "left").title())
    if atype == "mouse_click":
        return _("Mouse Click: {}").format(action.get("button", "left").title())
    if atype == "delay":
        return _("Delay: {} ms").format(action.get("ms", 0))
    if atype == "text":
        text = action.get("text", "")
        preview = text[:30] + "..." if len(text) > 30 else text
        return _('Type: "{}"').format(preview)
    if atype == "scroll":
        return _("Scroll {}: {}").format(
            action.get("direction", "up").title(),
            action.get("amount", 1),
        )
    return atype


class MacroTimeline(Gtk.Box):
    """Scrollable vertical timeline of macro actions.

    Signals emitted via callbacks:
        on_selection_changed(index or None)
        on_actions_changed(actions_list)
    """

    def __init__(self, on_selection_changed=None, on_actions_changed=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._actions = []
        self._selected_index = None
        self._on_selection_changed = on_selection_changed
        self._on_actions_changed = on_actions_changed
        self._row_widgets = []

        # Header label
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)
        header_box.set_margin_top(8)
        header_box.set_margin_bottom(4)

        header_label = Gtk.Label(label=_("TIMELINE"))
        header_label.set_halign(Gtk.Align.START)
        header_label.add_css_class("section-header")
        header_box.append(header_label)

        count_label = Gtk.Label(label="0")
        count_label.add_css_class("dim-label")
        count_label.set_halign(Gtk.Align.END)
        count_label.set_hexpand(True)
        self._count_label = count_label
        header_box.append(count_label)

        self.append(header_box)

        # Scrolled window containing the action rows
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(200)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._list_box.set_margin_start(8)
        self._list_box.set_margin_end(8)
        self._list_box.set_margin_top(4)
        self._list_box.set_margin_bottom(8)

        scrolled.set_child(self._list_box)
        self.append(scrolled)

        # Empty state
        self._empty_label = Gtk.Label(
            label=_("No actions yet.\nUse the palette below or Record to add actions.")
        )
        self._empty_label.add_css_class("dim-label")
        self._empty_label.set_wrap(True)
        self._empty_label.set_justify(Gtk.Justification.CENTER)
        self._empty_label.set_margin_top(40)
        self._empty_label.set_margin_bottom(40)
        self._list_box.append(self._empty_label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_actions(self, actions: list):
        """Replace entire action list and rebuild the UI."""
        self._actions = list(actions)
        self._selected_index = None
        self._rebuild()

    def get_actions(self) -> list:
        """Return current actions list."""
        return list(self._actions)

    def append_action(self, action: dict):
        """Add an action at the end (or after selected)."""
        insert_pos = len(self._actions)
        if self._selected_index is not None:
            insert_pos = self._selected_index + 1
        self._actions.insert(insert_pos, action)
        self._rebuild()
        self._select(insert_pos)
        self._notify_changed()

    def insert_action_at(self, index: int, action: dict):
        """Insert an action at a specific index."""
        index = max(0, min(index, len(self._actions)))
        self._actions.insert(index, action)
        self._rebuild()
        self._select(index)
        self._notify_changed()

    def remove_action_at(self, index: int):
        """Remove action at index."""
        if 0 <= index < len(self._actions):
            self._actions.pop(index)
            if self._selected_index is not None:
                if self._selected_index >= len(self._actions):
                    self._selected_index = len(self._actions) - 1 if self._actions else None
                elif self._selected_index > index:
                    self._selected_index -= 1
            self._rebuild()
            self._notify_changed()

    def duplicate_action_at(self, index: int):
        """Duplicate the action at index, inserting after it."""
        if 0 <= index < len(self._actions):
            import copy
            dup = copy.deepcopy(self._actions[index])
            # Give it a new id
            import uuid
            dup["id"] = str(uuid.uuid4())
            self._actions.insert(index + 1, dup)
            self._rebuild()
            self._select(index + 1)
            self._notify_changed()

    def move_action(self, from_index: int, to_index: int):
        """Move action from one position to another."""
        if from_index == to_index:
            return
        if 0 <= from_index < len(self._actions) and 0 <= to_index < len(self._actions):
            action = self._actions.pop(from_index)
            self._actions.insert(to_index, action)
            self._rebuild()
            self._select(to_index)
            self._notify_changed()

    def clear_actions(self):
        """Remove all actions."""
        self._actions.clear()
        self._selected_index = None
        self._rebuild()
        self._notify_changed()

    def get_selected_index(self):
        """Return currently selected index or None."""
        return self._selected_index

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _notify_changed(self):
        if self._on_actions_changed:
            self._on_actions_changed(self._actions)

    def _select(self, index):
        if index is not None and 0 <= index < len(self._actions):
            self._selected_index = index
        else:
            self._selected_index = None
        self._update_selection_visuals()
        if self._on_selection_changed:
            self._on_selection_changed(self._selected_index)

    def _update_selection_visuals(self):
        for i, row in enumerate(self._row_widgets):
            if i == self._selected_index:
                row.add_css_class("timeline-row-selected")
            else:
                row.remove_css_class("timeline-row-selected")

    def _rebuild(self):
        """Rebuild the entire timeline widget list."""
        # Remove all children
        child = self._list_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self._list_box.remove(child)
            child = next_child

        self._row_widgets = []
        self._count_label.set_label(str(len(self._actions)))

        if not self._actions:
            self._list_box.append(self._empty_label)
            return

        for i, action in enumerate(self._actions):
            # Insert button between rows
            if i > 0:
                insert_btn = self._create_insert_button(i)
                self._list_box.append(insert_btn)

            row = self._create_action_row(i, action)
            self._row_widgets.append(row)
            self._list_box.append(row)

        self._update_selection_visuals()

    def _create_insert_button(self, insert_index: int) -> Gtk.Box:
        """Create the '+' button between rows for inserting actions."""
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        container.set_halign(Gtk.Align.CENTER)
        container.set_margin_top(1)
        container.set_margin_bottom(1)

        btn = Gtk.Button()
        btn.set_child(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        btn.add_css_class("flat")
        btn.add_css_class("circular")
        btn.add_css_class("dim-label")
        btn.set_tooltip_text(_("Insert action here"))
        btn.set_opacity(0.4)
        btn.connect("clicked", lambda _, idx=insert_index: self._on_insert_clicked(idx))

        # Show on hover
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda c, x, y, b=btn: b.set_opacity(1.0))
        motion.connect("leave", lambda c, b=btn: b.set_opacity(0.4))
        btn.add_controller(motion)

        container.append(btn)
        return container

    def _on_insert_clicked(self, index: int):
        """Insert a default delay action at the given index."""
        action = new_action("delay", ms=50)
        self.insert_action_at(index, action)

    def _create_action_row(self, index: int, action: dict) -> Gtk.Box:
        """Create a single action row for the timeline."""
        atype = action.get("type", "unknown")
        color = ACTION_TYPE_COLORS.get(atype, COLORS.get("text", "#cdd6f4"))
        icon_name = ACTION_TYPE_ICONS.get(atype, "dialog-question-symbolic")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.add_css_class("timeline-row")
        row.set_margin_top(2)
        row.set_margin_bottom(2)

        # Step number
        step_label = Gtk.Label(label=str(index + 1))
        step_label.add_css_class("dim-label")
        step_label.set_size_request(24, -1)
        step_label.set_halign(Gtk.Align.CENTER)
        row.append(step_label)

        # Color indicator bar
        color_bar = Gtk.DrawingArea()
        color_bar.set_size_request(4, -1)
        color_bar.set_vexpand(True)

        r = int(color[1:3], 16) / 255.0
        g = int(color[3:5], 16) / 255.0
        b = int(color[5:7], 16) / 255.0

        def draw_bar(area, cr, w, h, _r=r, _g=g, _b=b):
            cr.set_source_rgba(_r, _g, _b, 0.8)
            cr.rectangle(0, 2, w, h - 4)
            cr.fill()

        color_bar.set_draw_func(draw_bar)
        row.append(color_bar)

        # Icon
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        row.append(icon)

        # Description
        desc_label = Gtk.Label(label=_action_summary(action))
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_hexpand(True)
        desc_label.set_ellipsize(Pango.EllipsizeMode.END)
        desc_label.add_css_class("setting-label")
        row.append(desc_label)

        # Delay badge (editable)
        delay_ms = action.get("delay_after_ms", 0)
        if atype == "delay":
            delay_ms = action.get("ms", 0)

        delay_label = Gtk.Label(label=f"{delay_ms}ms")
        delay_label.add_css_class("dim-label")
        delay_label.set_size_request(50, -1)
        delay_label.set_halign(Gtk.Align.END)

        # Make delay clickable to edit
        delay_click = Gtk.GestureClick()
        delay_click.connect(
            "released",
            lambda g, n, x, y, idx=index, lbl=delay_label: self._start_delay_edit(idx, lbl),
        )
        delay_label.add_controller(delay_click)
        delay_label.set_cursor_from_name("text")
        delay_label.set_tooltip_text(_("Click to edit delay"))
        row.append(delay_label)

        # Delete button (visible on hover)
        del_btn = Gtk.Button()
        del_btn.set_child(Gtk.Image.new_from_icon_name("edit-delete-symbolic"))
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.set_opacity(0.0)
        del_btn.set_tooltip_text(_("Remove action"))
        del_btn.connect("clicked", lambda _, idx=index: self.remove_action_at(idx))
        row.append(del_btn)

        # Row click to select
        click = Gtk.GestureClick()
        click.connect("released", lambda g, n, x, y, idx=index: self._select(idx))
        row.add_controller(click)

        # Hover to show delete button
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda c, x, y, b=del_btn: b.set_opacity(1.0))
        motion.connect("leave", lambda c, b=del_btn: b.set_opacity(0.0))
        row.add_controller(motion)

        # Right-click context menu
        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.connect(
            "released",
            lambda g, n, x, y, idx=index, widget=row: self._show_context_menu(idx, widget, x, y),
        )
        row.add_controller(right_click)

        # Drag and drop
        self._setup_dnd(row, index)

        return row

    def _setup_dnd(self, row, index):
        """Set up drag-and-drop for reordering."""
        # Drag source
        drag = Gtk.DragSource()
        drag.set_actions(Gdk.DragAction.MOVE)
        drag.connect("prepare", lambda src, x, y, idx=index: self._on_drag_prepare(idx))
        drag.connect("drag-begin", lambda src, drag_obj, idx=index: self._on_drag_begin(idx, row))
        row.add_controller(drag)

        # Drop target
        drop = Gtk.DropTarget.new(int, Gdk.DragAction.MOVE)
        drop.connect("drop", lambda target, value, x, y, idx=index: self._on_drop(value, idx))
        row.add_controller(drop)

    def _on_drag_prepare(self, index):
        """Prepare drag data."""
        content = Gdk.ContentProvider.new_for_value(index)
        return content

    def _on_drag_begin(self, index, row):
        """Visual feedback when drag starts."""
        row.set_opacity(0.5)

    def _on_drop(self, from_index, to_index):
        """Handle drop - reorder actions."""
        if isinstance(from_index, int):
            self.move_action(from_index, to_index)
            return True
        return False

    def _start_delay_edit(self, index, label_widget):
        """Replace delay label with a SpinButton for inline editing."""
        action = self._actions[index]
        atype = action.get("type", "")

        if atype == "delay":
            current_ms = action.get("ms", 0)
        else:
            current_ms = action.get("delay_after_ms", 0)

        # Create spin button
        adj = Gtk.Adjustment(value=current_ms, lower=0, upper=10000, step_increment=10, page_increment=100)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        spin.set_size_request(80, -1)
        spin.add_css_class("flat")

        # Replace label with spin
        parent = label_widget.get_parent()
        if parent is None:
            return

        # Find the label and replace it
        label_widget.set_visible(False)
        parent.insert_child_after(spin, label_widget)

        def finish_edit(*args):
            new_val = int(spin.get_value())
            if atype == "delay":
                action["ms"] = new_val
            else:
                action["delay_after_ms"] = new_val
            label_widget.set_label(f"{new_val}ms")
            label_widget.set_visible(True)
            parent.remove(spin)
            self._notify_changed()

        spin.connect("activate", finish_edit)

        # Focus out also saves
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", finish_edit)
        spin.add_controller(focus)

        spin.grab_focus()

    def _show_context_menu(self, index, widget, x, y):
        """Show right-click context menu for an action row."""
        menu = Gio.Menu()
        menu.append(_("Delete"), f"timeline.delete-{index}")
        menu.append(_("Duplicate"), f"timeline.duplicate-{index}")
        menu.append(_("Insert Before"), f"timeline.insert-before-{index}")
        menu.append(_("Insert After"), f"timeline.insert-after-{index}")

        # Use a simple Gtk.PopoverMenu
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(widget)
        popover.set_has_arrow(True)

        # Create action group
        group = Gio.SimpleActionGroup()

        delete_action = Gio.SimpleAction.new(f"delete-{index}", None)
        delete_action.connect("activate", lambda a, p, idx=index: self.remove_action_at(idx))
        group.add_action(delete_action)

        dup_action = Gio.SimpleAction.new(f"duplicate-{index}", None)
        dup_action.connect("activate", lambda a, p, idx=index: self.duplicate_action_at(idx))
        group.add_action(dup_action)

        before_action = Gio.SimpleAction.new(f"insert-before-{index}", None)
        before_action.connect(
            "activate",
            lambda a, p, idx=index: self.insert_action_at(idx, new_action("delay", ms=50)),
        )
        group.add_action(before_action)

        after_action = Gio.SimpleAction.new(f"insert-after-{index}", None)
        after_action.connect(
            "activate",
            lambda a, p, idx=index: self.insert_action_at(idx + 1, new_action("delay", ms=50)),
        )
        group.add_action(after_action)

        widget.insert_action_group("timeline", group)
        popover.popup()
