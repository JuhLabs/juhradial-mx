#!/usr/bin/env python3
"""
JuhRadial MX - Macros Page

Two-column macro studio:

  * Left  — MACROS · LIBRARY (selectable list + count badge) and a
            RUN BEHAVIOR card whose toggles reflect the selected macro's
            real fields (repeat_mode / use_standard_delay).
  * Right — TIMELINE · BUILD & RUN: a transport (Record / Play / Stop /
            Edit) wired to the real daemon (ExecuteMacro / StopMacro) and
            recorder, a stats row derived from the macro, a Cairo timeline
            that visualises the selected macro's real steps along a ms axis,
            and an ADD STEP palette that appends real actions.

All macro CRUD, recording, import, and D-Bus calls are preserved; only the
layout is restructured (a re-skin). No control here is a silent no-op: every
button either drives the daemon or edits/persists real macro data.

SPDX-License-Identifier: GPL-3.0
"""

import logging
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk, Gio, GLib, Adw, Pango

from i18n import _
import settings_theme
from settings_macro_storage import (
    load_all_macros,
    delete_macro,
    duplicate_macro,
    save_macro,
    REPEAT_MODE_LABELS,
    REPEAT_MODE_ICONS,
)
from settings_dialog_macro import MacroEditorDialog
from settings_macro_actions import ActionPalette
from settings_macro_recorder import MacroRecorderDialog

logger = logging.getLogger(__name__)


# Nominal per-action duration (ms) used only to lay steps along the visual
# time axis. Delays carry their own explicit duration.
_ACTION_MS = {
    "key_down": 60,
    "key_up": 40,
    "mouse_down": 50,
    "mouse_up": 40,
    "mouse_click": 90,
    "scroll": 80,
}

_MODIFIER_NAMES = {
    "Control_L": "Ctrl", "Control_R": "Ctrl",
    "Shift_L": "Shift", "Shift_R": "Shift",
    "Alt_L": "Alt", "Alt_R": "Alt",
    "Super_L": "Super", "Super_R": "Super",
    "ISO_Level3_Shift": "AltGr",
}

# Short label for the REPEAT stat / behaviour summary.
_REPEAT_SHORT = {
    "once": "Off",
    "while_holding": "Held",
    "toggle": "Toggle",
    "repeat_n": "N times",
    "sequence": "Sequence",
}


def _hex_rgb(hex_color, default=(0.31, 0.94, 0.79)):
    """Parse '#rrggbb' to an (r, g, b) float tuple."""
    try:
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
    except Exception:
        return default


def _mouse_button_name(btn_num):
    """Short human name for a GDK mouse button number."""
    names = {
        1: _("Left"), 2: _("Middle"), 3: _("Right"),
        4: _("Side"), 5: _("Extra"), 8: _("Back"), 9: _("Forward"),
    }
    return names.get(btn_num, _("Btn %d") % btn_num)


def _binding_chip_label(trigger):
    """Compact uppercase binding label for the list chip, e.g. 'MOUSE · BACK'."""
    if not trigger:
        return _("UNBOUND")
    if trigger.startswith("key:"):
        return "KEY · " + trigger[4:].upper()
    if trigger.startswith("mouse:"):
        try:
            return "MOUSE · " + _mouse_button_name(int(trigger[6:])).upper()
        except ValueError:
            return "MOUSE"
    return str(trigger).upper()


def _binding_full_label(trigger):
    """Readable binding label for the stats readout."""
    if not trigger:
        return _("Unbound")
    if trigger.startswith("key:"):
        return trigger[4:]
    if trigger.startswith("mouse:"):
        try:
            return _mouse_button_name(int(trigger[6:]))
        except ValueError:
            return _("Mouse")
    return str(trigger)


class MacrosPage(Gtk.ScrolledWindow):
    """Macro studio: library + run behaviour + live timeline."""

    def __init__(self, parent_window=None):
        super().__init__()
        self._parent_window = parent_window
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        self._macros = []
        self._selected_id = None
        self._selected_macro = None
        self._row_widgets = {}
        self._daemon_proxy = None
        self._sub_ids = []
        self._syncing = False

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        outer.set_margin_top(22)
        outer.set_margin_bottom(22)
        outer.set_margin_start(22)
        outer.set_margin_end(22)

        outer.append(self._build_header())

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        body.set_valign(Gtk.Align.START)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        left.set_size_request(372, -1)
        left.append(self._build_library_card())
        left.append(self._build_behavior_card())
        body.append(left)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        right.set_hexpand(True)
        right.append(self._build_timeline_card())
        body.append(right)

        outer.append(body)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1180)
        clamp.set_tightening_threshold(900)
        clamp.set_child(outer)
        self.set_child(clamp)

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)
        self.connect("destroy", self._on_destroy)

        self._refresh_list()

    def set_parent_window(self, window):
        """Set parent window reference (deferred from constructor)."""
        self._parent_window = window
        self._action_palette._parent_window = window

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    def _build_header(self):
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)

        eyebrow = Gtk.Label(label=_("AUTOMATE  ·  MACROS"))
        eyebrow.set_halign(Gtk.Align.START)
        eyebrow.add_css_class("section-eyebrow")
        text_box.append(eyebrow)

        title = Gtk.Label(label=_("Macros"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("page-display-title")
        text_box.append(title)

        subtitle = Gtk.Label(
            label=_("Record multi-step sequences and replay them from any button.")
        )
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("setting-desc")
        text_box.append(subtitle)
        head.append(text_box)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.set_valign(Gtk.Align.CENTER)

        import_btn = Gtk.Button()
        import_btn.add_css_class("secondary-btn")
        imp_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        imp_inner.append(Gtk.Image.new_from_icon_name("document-open-symbolic"))
        imp_inner.append(Gtk.Label(label=_("Import")))
        import_btn.set_child(imp_inner)
        import_btn.set_tooltip_text(_("Import a .json macro file"))
        import_btn.connect("clicked", self._on_import_macro)
        controls.append(import_btn)

        new_btn = Gtk.Button()
        new_btn.add_css_class("suggested-action")
        new_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        new_inner.append(Gtk.Image.new_from_icon_name("list-add-symbolic"))
        new_inner.append(Gtk.Label(label=_("New macro")))
        new_btn.set_child(new_inner)
        new_btn.connect("clicked", self._on_new_macro)
        controls.append(new_btn)

        head.append(controls)
        return head

    # ------------------------------------------------------------------
    # Left column — library
    # ------------------------------------------------------------------
    def _build_library_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("settings-card")

        chead = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctitle = Gtk.Label(label=_("MACROS  ·  LIBRARY"))
        ctitle.set_halign(Gtk.Align.START)
        ctitle.set_hexpand(True)
        ctitle.add_css_class("section-eyebrow")
        chead.append(ctitle)
        self._count_badge = Gtk.Label(label="0")
        self._count_badge.add_css_class("live-badge")
        chead.append(self._count_badge)
        card.append(chead)

        self._list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.append(self._list_box)

        return card

    def _build_behavior_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("settings-card")
        self._behavior_card = card

        title = Gtk.Label(label=_("RUN BEHAVIOR"))
        title.set_halign(Gtk.Align.START)
        title.add_css_class("section-eyebrow")
        card.append(title)

        # "Repeat while held" -> repeat_mode == while_holding (real field).
        held_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        held_row.add_css_class("setting-row")
        held_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        held_text.set_hexpand(True)
        hl = Gtk.Label(label=_("Repeat while held"))
        hl.set_halign(Gtk.Align.START)
        hl.add_css_class("setting-label")
        held_text.append(hl)
        hd = Gtk.Label(label=_("Loop the sequence until the trigger is released"))
        hd.set_halign(Gtk.Align.START)
        hd.add_css_class("setting-desc")
        held_text.append(hd)
        held_row.append(held_text)
        self._held_switch = Gtk.Switch()
        self._held_switch.set_valign(Gtk.Align.CENTER)
        self._held_switch.connect("state-set", self._on_held_toggled)
        held_row.append(self._held_switch)
        card.append(held_row)

        # "Auto-delay between steps" -> use_standard_delay (real field).
        delay_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        delay_row.add_css_class("setting-row")
        delay_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        delay_text.set_hexpand(True)
        dl = Gtk.Label(label=_("Auto-delay between steps"))
        dl.set_halign(Gtk.Align.START)
        dl.add_css_class("setting-label")
        delay_text.append(dl)
        self._delay_desc = Gtk.Label(label=_("Insert a standard pause between each step"))
        self._delay_desc.set_halign(Gtk.Align.START)
        self._delay_desc.add_css_class("setting-desc")
        delay_text.append(self._delay_desc)
        delay_row.append(delay_text)
        self._delay_switch = Gtk.Switch()
        self._delay_switch.set_valign(Gtk.Align.CENTER)
        self._delay_switch.connect("state-set", self._on_delay_toggled)
        delay_row.append(self._delay_switch)
        card.append(delay_row)

        return card

    # ------------------------------------------------------------------
    # Right column — timeline / transport / stats / add step
    # ------------------------------------------------------------------
    def _build_timeline_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("settings-card")
        card.set_hexpand(True)
        self._timeline_card = card

        chead = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ctitle = Gtk.Label(label=_("TIMELINE  ·  BUILD & RUN"))
        ctitle.set_halign(Gtk.Align.START)
        ctitle.set_hexpand(True)
        ctitle.add_css_class("section-eyebrow")
        chead.append(ctitle)
        self._state_badge = Gtk.Label(label=_("READY"))
        self._state_badge.add_css_class("live-badge")
        chead.append(self._state_badge)
        card.append(chead)

        # Transport row (Record / Play / Stop / Edit) — all real.
        self._transport = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._rec_btn = self._make_transport_btn(
            "media-record-symbolic", _("Record"), self._on_record, danger=True
        )
        self._transport.append(self._rec_btn)

        self._play_btn = self._make_transport_btn(
            "media-playback-start-symbolic", _("Run"), self._on_play, primary=True
        )
        self._transport.append(self._play_btn)

        self._stop_btn = self._make_transport_btn(
            "media-playback-stop-symbolic", _("Stop"), self._on_stop
        )
        self._transport.append(self._stop_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self._transport.append(spacer)

        self._edit_btn = self._make_transport_btn(
            "document-edit-symbolic", _("Edit"), self._on_edit_selected
        )
        self._transport.append(self._edit_btn)
        card.append(self._transport)

        # Stats readouts.
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        stats.set_homogeneous(True)
        self._ro_duration = self._make_readout(stats, _("TOTAL DURATION"))
        self._ro_steps = self._make_readout(stats, _("STEPS"))
        self._ro_repeat = self._make_readout(stats, _("REPEAT"))
        self._ro_bound = self._make_readout(stats, _("BOUND TO"))
        card.append(stats)

        # Timeline strip header + Cairo visualization.
        strip_head = Gtk.Label(label=_("SEQUENCE  ·  ARMED TRACK"))
        strip_head.set_halign(Gtk.Align.START)
        strip_head.add_css_class("section-eyebrow")
        strip_head.set_margin_top(2)
        card.append(strip_head)

        self._timeline = Gtk.DrawingArea()
        self._timeline.set_content_height(156)
        self._timeline.set_hexpand(True)
        self._timeline.add_css_class("waveform-trace")
        self._timeline.set_draw_func(self._draw_timeline)
        card.append(self._timeline)

        # Add-step palette (KEY / MOUSE / DELAY / TEXT / SCROLL) — real actions.
        add_head = Gtk.Label(label=_("ADD STEP"))
        add_head.set_halign(Gtk.Align.START)
        add_head.add_css_class("section-eyebrow")
        add_head.set_margin_top(2)
        card.append(add_head)

        self._action_palette = ActionPalette(
            parent_window=self._parent_window,
            on_action_added=self._on_step_added,
        )
        card.append(self._action_palette)

        return card

    def _make_transport_btn(self, icon_name, label, callback, primary=False, danger=False):
        btn = Gtk.Button()
        if primary:
            btn.add_css_class("suggested-action")
        elif danger:
            btn.add_css_class("danger-btn")
        else:
            btn.add_css_class("secondary-btn")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        inner.append(Gtk.Image.new_from_icon_name(icon_name))
        inner.append(Gtk.Label(label=label))
        btn.set_child(inner)
        btn.connect("clicked", callback)
        return btn

    def _make_readout(self, parent, label_text):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        lbl = Gtk.Label(label=label_text)
        lbl.set_halign(Gtk.Align.START)
        lbl.add_css_class("haptic-readout-label")
        box.append(lbl)
        val = Gtk.Label(label="--")
        val.set_halign(Gtk.Align.START)
        val.set_ellipsize(Pango.EllipsizeMode.END)
        val.add_css_class("haptic-readout-num")
        box.append(val)
        parent.append(box)
        return val

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------
    def _refresh_list(self):
        """Reload macros from disk and rebuild the library list."""
        child = self._list_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._list_box.remove(child)
            child = nxt
        self._row_widgets = {}

        self._macros = load_all_macros()
        self._count_badge.set_label(str(len(self._macros)))

        if not self._macros:
            self._selected_id = None
            self._selected_macro = None
            self._show_empty_state()
            self._update_selection_ui()
            return

        for macro in self._macros:
            row = self._create_macro_row(macro)
            self._row_widgets[macro.get("id", "")] = row
            self._list_box.append(row)

        # Preserve selection across refresh; default to the first macro.
        ids = [m.get("id", "") for m in self._macros]
        if self._selected_id not in ids:
            self._selected_id = ids[0]
        self._select_macro(self._selected_id)

    def _show_empty_state(self):
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        empty.set_halign(Gtk.Align.CENTER)
        empty.set_margin_top(28)
        empty.set_margin_bottom(28)

        icon = Gtk.Image.new_from_icon_name("input-keyboard-symbolic")
        icon.set_pixel_size(40)
        icon.add_css_class("dim-label")
        empty.append(icon)

        t = Gtk.Label(label=_("No macros yet"))
        t.add_css_class("title-3")
        empty.append(t)

        d = Gtk.Label(label=_("Record a sequence or build one step by step."))
        d.add_css_class("dim-label")
        d.set_wrap(True)
        d.set_justify(Gtk.Justification.CENTER)
        empty.append(d)

        new_btn = Gtk.Button(label=_("New macro"))
        new_btn.add_css_class("suggested-action")
        new_btn.set_halign(Gtk.Align.CENTER)
        new_btn.connect("clicked", self._on_new_macro)
        empty.append(new_btn)

        self._list_box.append(empty)

    def _create_macro_row(self, macro):
        macro_id = macro.get("id", "")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("timeline-row")

        repeat_mode = macro.get("repeat_mode", "once")
        icon_box = Gtk.Box()
        icon_box.add_css_class("button-icon-box")
        icon_box.set_valign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name(
            REPEAT_MODE_ICONS.get(repeat_mode, "media-playback-start-symbolic")
        )
        icon.set_pixel_size(18)
        icon.add_css_class("button-icon")
        icon_box.append(icon)
        row.append(icon_box)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)

        name = Gtk.Label(label=macro.get("name", _("Untitled")))
        name.set_halign(Gtk.Align.START)
        name.add_css_class("button-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(name)

        n_steps = len(macro.get("actions", []))
        meta = _("{} steps  ·  {}").format(
            n_steps, _(REPEAT_MODE_LABELS.get(repeat_mode, "Once"))
        )
        sub = Gtk.Label(label=meta)
        sub.set_halign(Gtk.Align.START)
        sub.add_css_class("setting-desc")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        text_box.append(sub)
        row.append(text_box)

        chip = Gtk.Label(label=_binding_chip_label(macro.get("assigned_trigger")))
        chip.add_css_class("device-badge")
        chip.set_valign(Gtk.Align.CENTER)
        row.append(chip)

        # Per-row actions: duplicate + delete (hover affordances).
        dup_btn = Gtk.Button()
        dup_btn.set_child(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        dup_btn.add_css_class("flat")
        dup_btn.add_css_class("circular")
        dup_btn.set_valign(Gtk.Align.CENTER)
        dup_btn.set_tooltip_text(_("Duplicate"))
        dup_btn.connect("clicked", lambda _b, mid=macro_id: self._on_duplicate(mid))
        row.append(dup_btn)

        del_btn = Gtk.Button()
        del_btn.set_child(Gtk.Image.new_from_icon_name("edit-delete-symbolic"))
        del_btn.add_css_class("flat")
        del_btn.add_css_class("circular")
        del_btn.set_valign(Gtk.Align.CENTER)
        del_btn.set_tooltip_text(_("Delete"))
        del_btn.connect(
            "clicked",
            lambda _b, mid=macro_id, nm=macro.get("name", ""): self._on_delete(mid, nm),
        )
        row.append(del_btn)

        click = Gtk.GestureClick()
        click.connect("released", lambda _g, _n, _x, _y, mid=macro_id: self._select_macro(mid))
        row.add_controller(click)

        return row

    def _select_macro(self, macro_id):
        self._selected_id = macro_id
        self._selected_macro = next(
            (m for m in self._macros if m.get("id", "") == macro_id), None
        )
        for mid, row in self._row_widgets.items():
            if mid == macro_id:
                row.add_css_class("timeline-row-selected")
            else:
                row.remove_css_class("timeline-row-selected")
        self._update_selection_ui()

    def _update_selection_ui(self):
        """Sync the right column + behaviour card to the selected macro."""
        macro = self._selected_macro
        has = macro is not None

        self._behavior_card.set_sensitive(has)
        self._transport.set_sensitive(has)
        self._action_palette.set_sensitive(has)

        if not has:
            for ro in (self._ro_duration, self._ro_steps, self._ro_repeat, self._ro_bound):
                ro.set_label("--")
            self._held_switch.set_active(False)
            self._delay_switch.set_active(False)
            self._timeline.queue_draw()
            return

        actions = macro.get("actions", [])
        total = self._total_duration_ms(macro)
        self._ro_duration.set_label(self._format_duration(total))
        self._ro_steps.set_label(str(len(actions)))
        self._ro_repeat.set_label(_(_REPEAT_SHORT.get(macro.get("repeat_mode", "once"), "Off")))
        self._ro_bound.set_label(_binding_full_label(macro.get("assigned_trigger")))

        # Behaviour switches mirror real fields; suppress write-back while we
        # set them programmatically (set_active fires state-set).
        std_on = macro.get("use_standard_delay", True)
        self._syncing = True
        self._held_switch.set_active(macro.get("repeat_mode") == "while_holding")
        self._delay_switch.set_active(std_on)
        self._syncing = False
        self._delay_desc.set_label(
            _("Standard pause: {} ms between steps").format(macro.get("standard_delay_ms", 50))
            if std_on else _("Insert a standard pause between each step")
        )

        # Play is meaningless with no steps.
        self._play_btn.set_sensitive(bool(actions))

        self._timeline.queue_draw()

    # ------------------------------------------------------------------
    # Timeline visualization (Cairo)
    # ------------------------------------------------------------------
    def _action_ms(self, action):
        t = action.get("type", "")
        if t == "delay":
            return max(1, int(action.get("ms", action.get("delay_after_ms", 0)) or 0))
        if t == "text":
            return max(120, len(action.get("text", "")) * 24)
        return _ACTION_MS.get(t, 50)

    def _total_duration_ms(self, macro):
        actions = macro.get("actions", [])
        total = sum(self._action_ms(a) for a in actions)
        if macro.get("use_standard_delay", True) and len(actions) > 1:
            total += int(macro.get("standard_delay_ms", 50)) * (len(actions) - 1)
        return total

    @staticmethod
    def _format_duration(ms):
        if ms >= 1000:
            return f"{ms / 1000:.2f}s"
        return f"{ms} ms"

    @staticmethod
    def _chip_for(action):
        """Return (label, sub) for a step chip, or None to skip (delays/key-up)."""
        t = action.get("type", "")
        if t in ("delay", "key_up"):
            return None
        if t == "key_down":
            key = action.get("key", "")
            return (_MODIFIER_NAMES.get(key, key)[:8] or "Key", "KEY")
        if t == "mouse_click":
            return (action.get("button", "left").title()[:6] + " Clk", "MOUSE")
        if t == "mouse_down":
            return (action.get("button", "left").title()[:6] + " Dn", "MOUSE")
        if t == "mouse_up":
            return (action.get("button", "left").title()[:6] + " Up", "MOUSE")
        if t == "text":
            txt = action.get("text", "")
            return ("type:" + (txt[:5] + "…" if len(txt) > 5 else txt), "TEXT")
        if t == "scroll":
            return ("Scroll " + str(action.get("direction", "")).title()[:4], "SCROLL")
        return (t[:8], "STEP")

    def _draw_timeline(self, area, cr, width, height):
        w, h = float(width), float(height)
        accent = _hex_rgb(settings_theme.COLORS.get("accent", "#4FEFC9"))
        ar, ag, ab = accent

        pad = 16.0
        track_y = h * 0.42          # chip baseline
        ruler_y = h - 26.0          # ms axis baseline

        # Track baseline.
        cr.set_line_width(1.0)
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.move_to(pad, track_y)
        cr.line_to(w - pad, track_y)
        cr.stroke()

        macro = self._selected_macro
        actions = macro.get("actions", []) if macro else []

        if not actions:
            cr.set_source_rgba(1, 1, 1, 0.34)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(12)
            msg = _("No steps yet — record or add a step below")
            ext = cr.text_extents(msg)
            cr.move_to((w - ext.width) / 2, track_y - 6)
            cr.show_text(msg)
            return

        total = max(1, self._total_duration_ms(macro))
        usable = w - 2 * pad

        # Build chip placements at their real time midpoint, then resolve
        # overlaps left-to-right and re-fit to the usable width.
        std = int(macro.get("standard_delay_ms", 50)) if macro.get("use_standard_delay", True) else 0
        chip_w = 56.0
        gap = 8.0
        placements = []
        t = 0
        first = True
        for a in actions:
            if not first and std:
                t += std
            first = False
            d = self._action_ms(a)
            chip = self._chip_for(a)
            if chip is not None:
                mid = (t + d / 2.0) / total
                placements.append([mid, chip])
            t += d

        if placements:
            # Resolve overlaps.
            cursor = pad
            for p in placements:
                desired = pad + p[0] * usable - chip_w / 2.0
                left = max(desired, cursor)
                p.append(left)
                cursor = left + chip_w + gap
            # Re-fit if we ran past the right edge.
            overflow = cursor - gap - (w - pad)
            if overflow > 0 and len(placements) > 1:
                shrink = usable / (cursor - gap - pad)
                base = pad
                cw = chip_w * shrink
                for i, p in enumerate(placements):
                    p[2] = base + i * (cw + gap * shrink)
                chip_w = cw

            chip_h = 40.0
            top = track_y - chip_h / 2.0
            for p in placements:
                label, sub = p[1]
                x = p[2]
                self._draw_chip(cr, x, top, chip_w, chip_h, label, sub, accent)

        # Center playhead: vertical line + diamond.
        cx = w / 2.0
        cr.set_line_width(1.0)
        cr.set_source_rgba(ar, ag, ab, 0.45)
        cr.move_to(cx, track_y - 30)
        cr.line_to(cx, ruler_y + 4)
        cr.stroke()
        ds = 5.0
        cr.set_source_rgba(ar, ag, ab, 0.95)
        cr.move_to(cx, track_y - 30 - ds)
        cr.line_to(cx + ds, track_y - 30)
        cr.line_to(cx, track_y - 30 + ds)
        cr.line_to(cx - ds, track_y - 30)
        cr.close_path()
        cr.fill()

        # ms ruler.
        cr.set_line_width(1.0)
        cr.set_source_rgba(1, 1, 1, 0.10)
        cr.move_to(pad, ruler_y)
        cr.line_to(w - pad, ruler_y)
        cr.stroke()

        step = self._nice_step(total)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(9)
        tick = 0
        while tick <= total:
            x = pad + (tick / total) * usable
            cr.set_source_rgba(1, 1, 1, 0.18)
            cr.move_to(x, ruler_y - 3)
            cr.line_to(x, ruler_y + 3)
            cr.stroke()
            cr.set_source_rgba(1, 1, 1, 0.42)
            lbl = str(tick)
            ext = cr.text_extents(lbl)
            lx = min(max(x - ext.width / 2, pad), w - pad - ext.width)
            cr.move_to(lx, ruler_y + 15)
            cr.show_text(lbl)
            tick += step

    def _draw_chip(self, cr, x, y, w, h, label, sub, accent):
        ar, ag, ab = accent
        r = 9.0
        # Body.
        self._rounded_rect(cr, x, y, w, h, r)
        cr.set_source_rgba(0.10, 0.13, 0.17, 0.96)
        cr.fill_preserve()
        cr.set_line_width(1.0)
        cr.set_source_rgba(ar, ag, ab, 0.38)
        cr.stroke()
        # Connector dot on the baseline.
        cr.set_source_rgba(ar, ag, ab, 0.8)
        cr.arc(x + w / 2.0, y + h, 2.4, 0, 2 * math.pi)
        cr.fill()
        # Labels (clipped to the chip).
        cr.save()
        self._rounded_rect(cr, x, y, w, h, r)
        cr.clip()
        cr.set_source_rgba(0.95, 0.97, 0.98, 1.0)
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(11)
        cr.move_to(x + 8, y + 18)
        cr.show_text(label)
        cr.set_source_rgba(ar, ag, ab, 0.92)
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(8)
        cr.move_to(x + 8, y + 31)
        cr.show_text(sub)
        cr.restore()

    @staticmethod
    def _rounded_rect(cr, x, y, w, h, r):
        cr.new_path()
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        cr.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        cr.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
        cr.close_path()

    @staticmethod
    def _nice_step(total):
        target = total / 6.0
        for s in (10, 25, 50, 100, 250, 500, 1000, 2000, 5000):
            if target <= s:
                return s
        return 10000

    # ------------------------------------------------------------------
    # Run behaviour toggles (persist real macro fields)
    # ------------------------------------------------------------------
    def _on_held_toggled(self, switch, state):
        macro = self._selected_macro
        if macro is None or self._syncing:
            return False
        new_mode = "while_holding" if state else "once"
        if macro.get("repeat_mode") == new_mode:
            return False
        macro["repeat_mode"] = new_mode
        save_macro(macro)
        self._ro_repeat.set_label(_(_REPEAT_SHORT.get(new_mode, "Off")))
        self._refresh_row_meta(macro)
        return False

    def _on_delay_toggled(self, switch, state):
        macro = self._selected_macro
        if macro is None or self._syncing:
            return False
        if macro.get("use_standard_delay", True) == state:
            return False
        macro["use_standard_delay"] = state
        save_macro(macro)
        self._delay_desc.set_label(
            _("Standard pause: {} ms between steps").format(macro.get("standard_delay_ms", 50))
            if state else _("Insert a standard pause between each step")
        )
        self._ro_duration.set_label(self._format_duration(self._total_duration_ms(macro)))
        self._timeline.queue_draw()
        return False

    def _refresh_row_meta(self, macro):
        """Cheap in-place refresh of a single library row's repeat icon/meta."""
        row = self._row_widgets.get(macro.get("id", ""))
        if row is None:
            return
        # Rebuilding the whole list keeps the icon + meta consistent.
        self._refresh_list()

    # ------------------------------------------------------------------
    # Transport (real daemon + recorder)
    # ------------------------------------------------------------------
    def _on_record(self, _btn):
        if self._selected_macro is None:
            return
        recorder = MacroRecorderDialog(
            self._parent_window or self.get_root(),
            on_recording_complete=self._on_recording_complete,
        )
        recorder.present()

    def _on_recording_complete(self, actions):
        macro = self._selected_macro
        if macro is None or not actions:
            return
        macro.setdefault("actions", []).extend(actions)
        save_macro(macro)
        self._update_selection_ui()
        self._refresh_row_meta(macro)

    def _on_step_added(self, action):
        macro = self._selected_macro
        if macro is None:
            return
        macro.setdefault("actions", []).append(action)
        save_macro(macro)
        self._update_selection_ui()

    def _on_play(self, _btn):
        if self._selected_id is None:
            return
        proxy = self._get_daemon_proxy()
        if not proxy:
            logger.warning("Cannot run macro: D-Bus proxy unavailable")
            return
        try:
            proxy.call_sync(
                "ExecuteMacro",
                GLib.Variant("(s)", (self._selected_id,)),
                Gio.DBusCallFlags.NONE, 2000, None,
            )
            logger.info("ExecuteMacro: %s", self._selected_id)
        except Exception as e:
            logger.error("Failed to run macro: %s", e)
            self._daemon_proxy = None

    def _on_stop(self, _btn):
        proxy = self._get_daemon_proxy()
        if not proxy:
            return
        try:
            proxy.call_sync("StopMacro", None, Gio.DBusCallFlags.NONE, 2000, None)
            logger.info("StopMacro")
        except Exception as e:
            logger.error("Failed to stop macro: %s", e)
            self._daemon_proxy = None

    def _on_edit_selected(self, _btn):
        if self._selected_macro is not None:
            self._on_edit_macro(self._selected_macro)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def _on_new_macro(self, _btn):
        # Create an empty macro inline and select it, so the timeline (Record /
        # Add step / Run) is immediately usable. Name/trigger/playback live in
        # the Edit dialog (pencil button), not a blocking new-window.
        from settings_macro_storage import new_macro_template
        macro = new_macro_template()
        macro["name"] = _("New Macro")
        if save_macro(macro):
            self._selected_id = macro.get("id")
            self._refresh_list()

    def _on_edit_macro(self, macro):
        parent = self._parent_window or self.get_root()
        if parent:
            MacroEditorDialog(parent, macro=macro, on_saved=self._on_macro_saved).present()

    def _on_duplicate(self, macro_id):
        result = duplicate_macro(macro_id)
        if result:
            self._selected_id = result.get("id", self._selected_id)
            self._refresh_list()

    def _on_delete(self, macro_id, macro_name):
        parent = self._parent_window or self.get_root()
        if not parent:
            return
        dialog = Adw.MessageDialog(
            transient_for=parent,
            modal=True,
            heading=_("Delete Macro?"),
            body=_('Are you sure you want to delete "%s"?\nThis cannot be undone.') % macro_name,
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_response(_dlg, response):
            if response == "delete":
                delete_macro(macro_id)
                if self._selected_id == macro_id:
                    self._selected_id = None
                self._refresh_list()

        dialog.connect("response", on_response)
        dialog.present()

    def _on_import_macro(self, _btn):
        parent = self._parent_window or self.get_root()
        if not parent:
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
            file_dialog.open(parent, None, self._on_import_file_selected)
        except Exception as e:
            logger.warning("Could not open file dialog: %s", e)

    def _on_import_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                import json
                import uuid
                path = file.get_path()
                with open(path, "r", encoding="utf-8") as f:
                    macro = json.load(f)
                macro["id"] = str(uuid.uuid4())
                macro["name"] = macro.get("name", _("Imported Macro"))
                if save_macro(macro):
                    self._selected_id = macro["id"]
                    self._refresh_list()
        except Exception as e:
            logger.warning("Failed to import macro: %s", e)

    def _on_macro_saved(self, macro):
        self._selected_id = macro.get("id", self._selected_id)
        self._refresh_list()

    # ------------------------------------------------------------------
    # Daemon proxy + playback-state signals
    # ------------------------------------------------------------------
    def _get_daemon_proxy(self):
        if self._daemon_proxy is None:
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self._daemon_proxy = Gio.DBusProxy.new_sync(
                    bus, Gio.DBusProxyFlags.NONE, None,
                    "org.kde.juhradialmx",
                    "/org/kde/juhradialmx/Daemon",
                    "org.kde.juhradialmx.Daemon",
                    None,
                )
            except Exception:
                self._daemon_proxy = None
        return self._daemon_proxy

    def _on_map(self, *_a):
        if self._sub_ids:
            return
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception:
            return
        # Empty sender so a daemon restart does not silence us (see CLAUDE.md).
        self._sub_ids.append(bus.signal_subscribe(
            None, "org.kde.juhradialmx.Daemon", "MacroPlaybackStarted",
            "/org/kde/juhradialmx/Daemon", None, Gio.DBusSignalFlags.NONE,
            self._on_playback_started, None,
        ))
        self._sub_ids.append(bus.signal_subscribe(
            None, "org.kde.juhradialmx.Daemon", "MacroPlaybackStopped",
            "/org/kde/juhradialmx/Daemon", None, Gio.DBusSignalFlags.NONE,
            self._on_playback_stopped, None,
        ))
        self._bus = bus

    def _on_unmap(self, *_a):
        bus = getattr(self, "_bus", None)
        if bus is not None:
            for sid in self._sub_ids:
                bus.signal_unsubscribe(sid)
        self._sub_ids = []

    def _on_playback_started(self, *_a):
        self._state_badge.set_label(_("RUNNING"))

    def _on_playback_stopped(self, *_a):
        self._state_badge.set_label(_("READY"))

    def _on_destroy(self, *_a):
        self._on_unmap()
