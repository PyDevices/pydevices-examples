"""The generic Tier-0 panel: everything an instance already declares.

Nothing here is specific to one script. The labels, the patch list and the
engine status all come from the adapter, so the same panel edits a TR-808 and
a hand-written soundtrack patch. Per-script panels are a later, separate thing
and they replace this module rather than the surface under it.

Only LVGL is imported. There is no `vstui` and no `vstaudio` in this file,
which is what lets it run on a desktop against a mock adapter.
"""

import lvgl as lv

BG = lv.color_hex(0x14181D)
PANEL_BG = lv.color_hex(0x1C2128)
TRACK = lv.color_hex(0x2A313B)
ACCENT = lv.color_hex(0x4FD1C5)
ACCENT_DIM = lv.color_hex(0x2C7A73)
TEXT = lv.color_hex(0xE6EDF3)
MUTED = lv.color_hex(0x8B96A5)
GOOD = lv.color_hex(0x3FB950)
BAD = lv.color_hex(0xF85149)

MACRO_COUNT = 16
_COLUMN_ROWS = 8
_ROW_HEIGHT = 40


class Panel:
    """The built widget tree, and the handful of things that update it."""

    def __init__(self, adapter, screen=None, group=None):
        self.adapter = adapter
        self.screen = screen if screen is not None else lv.screen_active()
        self.group = group if group is not None else lv.group_get_default()
        self._sliders = []
        self._value_labels = []
        self._patch_dropdown = None
        self._status_dot = None
        # True while a widget is being updated from engine state, so the
        # VALUE_CHANGED that update provokes is not published straight back as
        # a fresh edit. Without it every echo starts a new gesture and the two
        # sides chase each other.
        self._echoing = False
        self._build()
        adapter.on_external_change(self._apply_external)

    # ---- construction ---------------------------------------------------

    def _focus_and_edit(self, _event):
        """FOCUSED handler shared by every editable control.

        LVGL's pointer handling already moves group focus to whatever was
        clicked, but a focus change always drops the group out of edit mode
        first - so setting editing on PRESSED is silently clobbered a moment
        later by that same focus move. Doing it on FOCUSED runs after the
        focus machinery has settled, so it sticks, and the wheel adjusts the
        control that was clicked instead of navigating away from it.
        """
        self.group.set_editing(True)

    def _build(self):
        adapter = self.adapter
        screen = self.screen
        screen.set_style_bg_color(BG, 0)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_pad_all(0, 0)
        screen.set_style_pad_row(0, 0)
        screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        header = lv.obj(screen)
        header.remove_style_all()
        header.set_width(lv.pct(100))
        header.set_height(64)
        header.set_style_bg_color(PANEL_BG, 0)
        header.set_style_bg_opa(lv.OPA.COVER, 0)
        header.set_style_pad_hor(14, 0)
        header.set_style_pad_column(14, 0)
        header.set_flex_flow(lv.FLEX_FLOW.ROW)
        header.set_flex_align(
            lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
        )
        header.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(header)
        title.set_text(adapter.script_name)
        title.set_style_text_color(TEXT, 0)
        title.set_flex_grow(1)

        # No selector at all when there is nothing to select. An effect has
        # no patches, and neither does a script that never declared any.
        if adapter.patches:
            patch = lv.dropdown(header)
            patch.set_options("\n".join(adapter.patches))
            patch.set_selected(min(adapter.patch_index,
                                   len(adapter.patches) - 1))
            patch.set_width(190)
            patch.add_event_cb(self._focus_and_edit, lv.EVENT.FOCUSED, None)
            patch.add_event_cb(self._on_patch, lv.EVENT.VALUE_CHANGED, None)
            self._patch_dropdown = patch

        reload_button = lv.button(header)
        reload_button.set_style_bg_color(ACCENT_DIM, 0)
        reload_label = lv.label(reload_button)
        reload_label.set_text("Reload")
        reload_label.set_style_text_color(TEXT, 0)
        reload_label.center()
        reload_button.add_event_cb(self._focus_and_edit, lv.EVENT.FOCUSED, None)
        reload_button.add_event_cb(self._on_reload, lv.EVENT.CLICKED, None)

        bypass_row = lv.obj(header)
        bypass_row.remove_style_all()
        bypass_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        bypass_row.set_flex_align(
            lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
        )
        bypass_row.set_style_pad_column(8, 0)
        bypass_row.set_width(lv.SIZE_CONTENT)
        bypass_row.set_height(lv.SIZE_CONTENT)
        bypass_row.remove_flag(lv.obj.FLAG.SCROLLABLE)

        bypass_label = lv.label(bypass_row)
        bypass_label.set_text("Bypass")
        bypass_label.set_style_text_color(MUTED, 0)

        bypass = lv.switch(bypass_row)
        if adapter.bypass:
            bypass.add_state(lv.STATE.CHECKED)
        bypass.add_event_cb(self._focus_and_edit, lv.EVENT.FOCUSED, None)
        bypass.add_event_cb(self._on_bypass, lv.EVENT.VALUE_CHANGED, None)
        self._bypass_switch = bypass

        dot = lv.obj(header)
        dot.remove_style_all()
        dot.set_size(14, 14)
        dot.set_style_radius(lv.RADIUS_CIRCLE, 0)
        dot.set_style_bg_opa(lv.OPA.COVER, 0)
        dot.remove_flag(lv.obj.FLAG.SCROLLABLE)
        dot.remove_flag(lv.obj.FLAG.CLICKABLE)
        self._status_dot = dot
        self.refresh_status()

        content = lv.obj(screen)
        content.remove_style_all()
        content.set_width(lv.pct(100))
        content.set_flex_grow(1)
        content.set_flex_flow(lv.FLEX_FLOW.ROW)
        content.set_style_pad_all(16, 0)
        content.set_style_pad_column(28, 0)
        content.remove_flag(lv.obj.FLAG.SCROLLABLE)

        # One column while they fit, two when they do not. Sixteen rows split
        # evenly; four get the full width to themselves rather than leaving
        # half the panel blank.
        rows = adapter.macro_count
        if rows == 0:
            empty = lv.label(content)
            empty.set_text("No macro controls - this plug-in declares none.")
            empty.set_style_text_color(MUTED, 0)
            empty.center()
        else:
            columns = [_column(content)]
            per_column = rows
            if rows > _COLUMN_ROWS:
                per_column = (rows + 1) // 2
                columns.append(_column(content))
            for index in range(rows):
                self._macro_row(columns[index // per_column], index)

        footer = lv.label(screen)
        footer.set_text(
            "Click a control, then swipe or scroll: sideways adjusts it, "
            "up and down moves between controls."
        )
        footer.set_style_text_color(MUTED, 0)
        footer.set_style_pad_hor(14, 0)
        footer.set_style_pad_ver(4, 0)

    def _macro_row(self, parent, index):
        adapter = self.adapter
        row = lv.obj(parent)
        row.remove_style_all()
        row.set_width(lv.pct(100))
        # A fixed height rather than an even share of the column: with four
        # macros an even share is a 90-pixel row holding a 14-pixel slider.
        row.set_height(_ROW_HEIGHT)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_flex_align(
            lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
        )
        row.set_style_pad_column(10, 0)
        row.remove_flag(lv.obj.FLAG.SCROLLABLE)

        label = lv.label(row)
        label.set_text(adapter.macro_labels[index])
        label.set_style_text_color(MUTED, 0)
        label.set_width(136)

        value = adapter.macro_values[index]
        slider = lv.slider(row)
        slider.set_range(0, 127)
        slider.set_value(value, 0)
        slider.set_flex_grow(1)
        slider.set_height(14)
        slider.set_style_bg_color(TRACK, lv.PART.MAIN)
        slider.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
        slider.set_style_radius(lv.RADIUS_CIRCLE, lv.PART.MAIN)
        slider.set_style_bg_color(ACCENT, lv.PART.INDICATOR)
        slider.set_style_bg_opa(lv.OPA.COVER, lv.PART.INDICATOR)
        slider.set_style_radius(lv.RADIUS_CIRCLE, lv.PART.INDICATOR)
        slider.set_style_bg_color(TEXT, lv.PART.KNOB)
        slider.set_style_bg_opa(lv.OPA.COVER, lv.PART.KNOB)
        slider.set_style_pad_all(0, lv.PART.KNOB)
        slider.add_event_cb(self._focus_and_edit, lv.EVENT.FOCUSED, None)

        readout = lv.label(row)
        readout.set_text(str(value))
        readout.set_style_text_color(TEXT, 0)
        readout.set_width(32)
        readout.set_style_text_align(lv.TEXT_ALIGN.RIGHT, 0)

        def on_change(_event, macro=index, widget=slider, out=readout):
            current = widget.get_value()
            out.set_text(str(current))
            if self._echoing:
                return
            self.adapter.set_macro(macro, current)

        slider.add_event_cb(on_change, lv.EVENT.VALUE_CHANGED, None)
        self._sliders.append(slider)
        self._value_labels.append(readout)

    # ---- events ---------------------------------------------------------

    def _on_patch(self, _event):
        if self._echoing:
            return
        self.adapter.set_patch(self._patch_dropdown.get_selected())

    def _on_bypass(self, _event):
        if self._echoing:
            return
        self.adapter.set_bypass(
            self._bypass_switch.has_state(lv.STATE.CHECKED)
        )

    def _on_reload(self, _event):
        self.adapter.request_reload()

    def _apply_external(self, kind, index, value):
        self._echoing = True
        try:
            # A macro or patch the panel does not draw can still be
            # automated - the parameters are all still there - so an echo for
            # one is ignored rather than an index error.
            if kind == "macro" and index < len(self._sliders):
                self._sliders[index].set_value(value, 0)
                self._value_labels[index].set_text(str(value))
            elif (kind == "patch" and self._patch_dropdown is not None
                    and index < len(self.adapter.patches)):
                self._patch_dropdown.set_selected(value)
        finally:
            self._echoing = False

    def refresh_status(self):
        """Repaint the engine-status dot from the adapter."""
        if self._status_dot is None:
            return
        healthy = self.adapter.engine_ready and self.adapter.engine_error == 0
        self._status_dot.set_style_bg_color(GOOD if healthy else BAD, 0)


def _column(parent):
    column = lv.obj(parent)
    column.remove_style_all()
    column.set_flex_grow(1)
    column.set_height(lv.pct(100))
    column.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    column.set_style_pad_row(4, 0)
    column.remove_flag(lv.obj.FLAG.SCROLLABLE)
    return column


def build(adapter, screen=None, group=None):
    """Build the panel and return it."""
    return Panel(adapter, screen=screen, group=group)
