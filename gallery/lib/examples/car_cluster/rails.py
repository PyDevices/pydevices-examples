# SPDX-License-Identifier: MIT
"""Dual 4+4 focusable steering-wheel style menu rails."""

import lvgl as lv

import chrome
import lv_util
import theme

# Left rail (0-3), right rail (4-7) — indices match tabview pages.
RAIL_ITEMS = (
    # left
    ("SPD", "Speed", getattr(lv.SYMBOL, "HOME", "")),
    ("TR-A", "Trip A", getattr(lv.SYMBOL, "LOOP", "")),
    ("TR-B", "Trip B", getattr(lv.SYMBOL, "LOOP", "")),
    ("ENG", "Engine", getattr(lv.SYMBOL, "CHARGE", "")),
    # right
    ("LGT", "Lights", getattr(lv.SYMBOL, "EYE_OPEN", "")),
    ("TIR", "Tires", getattr(lv.SYMBOL, "SETTINGS", "")),
    ("AST", "Assist", getattr(lv.SYMBOL, "GPS", "")),
    ("THM", "Theme", getattr(lv.SYMBOL, "TINT", "")),
)


class Rails:
    def __init__(self, parent, tabview, left_group, right_group, rail_w, height, pad=4):
        self.tabview = tabview
        self.left_group = left_group
        self.right_group = right_group
        self.buttons = []
        self._icon_lbls = []
        self._text_lbls = []
        self._selected = 0
        self._selecting = False
        self._pending_tab = None
        self.left = lv.obj(parent)
        self.right = lv.obj(parent)
        for col in (self.left, self.right):
            col.set_size(rail_w, height)
            if hasattr(col, "remove_flag"):
                col.remove_flag(lv.obj.FLAG.SCROLLABLE)
            theme.style_bg(col, theme.panel(), radius=8, border_w=0)
            col.set_style_pad_all(pad, 0)
            col.set_style_pad_row(pad, 0)
            col.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            col.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)

        font = theme.pick_font(160, parent)
        font_icon = theme.pick_font(200, parent)
        btn_h = max(48, (height - pad * 5) // 4)

        for i, (short, _long, sym) in enumerate(RAIL_ITEMS):
            col = self.left if i < 4 else self.right
            group = left_group if i < 4 else right_group
            btn = lv.button(col)
            btn.set_size(lv.pct(100), btn_h)
            btn.set_style_pad_all(2, 0)
            btn.set_style_pad_row(2, 0)
            chrome.style_rail_button(btn, selected=(i == 0), initial=True)
            btn.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            btn.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)

            if sym:
                icon = lv.label(btn)
                icon.set_text(sym)
                icon.set_style_text_color(theme.accent_lite(), 0)
                theme.apply_font(icon, font_icon)
                icon.set_style_pad_all(0, 0)
                self._icon_lbls.append(icon)
            else:
                self._icon_lbls.append(None)

            lbl = lv.label(btn)
            lbl.set_text(short)
            lbl.set_style_text_color(theme.text(), 0)
            theme.apply_font(lbl, font)
            lbl.set_style_pad_all(0, 0)
            self._text_lbls.append(lbl)

            # Exactly one group per control.
            lv_util.group_add(group, btn)

            def _make(idx):
                def _cb(e):
                    self.select(idx)

                return _cb

            btn.add_event_cb(_make(i), lv.EVENT.CLICKED, None)
            # Arrow focus switches the center page; set_active is deferred via
            # drain_pending() on an app tick (and skipped while lv._nesting!=0).
            btn.add_event_cb(_make(i), lv.EVENT.FOCUSED, None)
            self.buttons.append(btn)

    def place(self, left_x, right_x, y):
        self.left.set_pos(left_x, y)
        self.right.set_pos(right_x, y)

    def select(self, index, anim=False, *, force=False):
        index = int(index) % len(self.buttons)
        # FOCUSED/CLICKED → select must not call tabview.set_active inline: that
        # re-enters the LVGL event/focus path inside task_handler and wedges the
        # soft timer under key storms. Style here; apply the tab on drain_pending().
        if self._selecting:
            return
        if not force and index == self._selected:
            return
        self._selecting = True
        try:
            nest = getattr(getattr(lv, "_nesting", None), "value", None)
            self._selected = index
            self._pending_tab = (index, 1 if anim else 0)
            # While nested in an LVGL FOCUSED callback, only record pending.
            # Restyling / add_style while nesting!=0 hard-locks under key storms.
            if nest:
                return
            self._apply_selection_styles(index)
        finally:
            self._selecting = False

    def _apply_selection_styles(self, index):
        for i, btn in enumerate(self.buttons):
            chrome.style_rail_button(btn, selected=(i == index))
            icon = self._icon_lbls[i]
            if icon is not None:
                icon.set_style_text_color(
                    theme.text() if i == index else theme.accent_lite(), 0
                )

    def drain_pending(self):
        """Apply a deferred tabview change outside the LVGL event callback stack.

        Called from an app tick. Soft-timer ticks are delivered via
        ``micropython.schedule`` and can run while LVGL is mid-render (the VM
        resumes inside ``flush_cb``); ``lv._nesting`` != 0 there, and calling
        ``set_active`` would re-enter LVGL — the intermittent hard-wedge seen
        under Enter-key soak. Defer to the next tick instead.
        """
        pending = self._pending_tab
        if pending is None:
            return
        try:
            if lv._nesting.value != 0:
                return
        except AttributeError:
            pass
        self._pending_tab = None
        index, anim_en = pending
        # Apply deferred rail restyle outside the FOCUSED callback.
        self._apply_selection_styles(index)
        try:
            if self.tabview.get_tab_act() == index:
                return
        except Exception:
            pass
        try:
            self.tabview.set_active(index, anim_en)
        except TypeError:
            self.tabview.set_active(index, False)

    def apply_theme(self):
        self.select(self._selected, anim=False, force=True)

    @property
    def selected(self):
        return self._selected
