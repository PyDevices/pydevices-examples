# SPDX-License-Identifier: MIT
"""Color scheme, chrome shininess, and brightness."""

import lvgl as lv

import theme
from screens._common import (
    apply_button_theme,
    apply_slider_theme,
    content_size,
    make_button,
    make_slider,
    prep_page,
    section_label,
    zero_pad,
)


def _scale_2x(lbl):
    w = max(1, lbl.get_width())
    h = max(1, lbl.get_height())
    lbl.set_style_transform_pivot_x(w // 2, 0)
    lbl.set_style_transform_pivot_y(h // 2, 0)
    try:
        lbl.set_style_transform_scale(512, 0)
    except Exception:
        lbl.set_style_transform_scale_x(512, 0)
        lbl.set_style_transform_scale_y(512, 0)


def _center_label(lbl, y):
    """Horizontally center a label at ``y`` with no translate/x offset."""
    parent = lbl.get_parent()
    try:
        lv.obj.update_layout(parent)
    except Exception:
        pass
    lbl.set_style_translate_x(0, 0)
    lbl.set_style_translate_y(0, 0)
    # Clear any sticky align/pos (section_label starts at x=4).
    pw = max(1, parent.get_width())
    lw = max(1, lbl.get_width())
    lbl.set_pos((pw - lw) // 2, y)
    _scale_2x(lbl)
    # Re-measure after scale pivot setup; keep layout center (scale is visual).
    lw = max(1, lbl.get_width())
    lbl.set_pos((pw - lw) // 2, y)
    lbl.set_style_translate_x(0, 0)


class ThemeScreen:
    def __init__(self, page, vehicle, group, w=0, h=0):
        self.vehicle = vehicle
        w, h = content_size(prep_page(page, w, h), w, h)
        self._sliders = []
        self._label_ys = []
        self._buttons = []

        # 6 evenly spaced bands: scheme name, PREV/NEXT, chrome header+slider,
        # brightness header+slider.
        n = 6
        y0, y_last = 36, h - 40
        step = (y_last - y0) / (n - 1)
        anchors = [int(round(y0 + i * step)) for i in range(n)]
        hdr = section_label(page, "COLOR SCHEME", 12, accent=True)
        _center_label(hdr, 12)
        self._labels = [hdr]
        self._label_ys = [12]

        self.scheme_lbl = lv.label(page)
        self.scheme_lbl.set_style_text_color(theme.accent_lite(), 0)
        theme.apply_font(self.scheme_lbl, theme.pick_font(240, page))
        zero_pad(self.scheme_lbl)
        self._scheme_y = anchors[0] + 8
        _center_label(self.scheme_lbl, self._scheme_y)
        self._labels.append(self.scheme_lbl)
        self._label_ys.append(self._scheme_y)

        prev_b = make_button(page, "PREV", 96, 38, group)
        next_b = make_button(page, "NEXT", 96, 38, group)
        self._buttons.extend((prev_b, next_b))
        btn_w, btn_gap = 96, 8
        x0 = (w - (btn_w * 2 + btn_gap)) // 2
        prev_b.set_pos(x0, anchors[1])
        next_b.set_pos(x0 + btn_w + btn_gap, anchors[1])

        def _prev(e):
            theme.set_scheme(theme.scheme_index() - 1)

        def _next(e):
            theme.set_scheme(theme.scheme_index() + 1)

        prev_b.add_event_cb(_prev, lv.EVENT.CLICKED, None)
        next_b.add_event_cb(_next, lv.EVENT.CLICKED, None)

        controls = (
            ("Chrome shininess", theme.shininess, theme.set_shininess),
            ("Brightness", theme.brightness, theme.set_brightness),
        )
        for i, (label, getter, setter) in enumerate(controls):
            ay_hdr = anchors[2 + i * 2]
            ay_sl = anchors[3 + i * 2]
            sec = section_label(page, label.upper(), ay_hdr)
            # Nudge headers down 2× their height so they sit closer to their sliders.
            try:
                lv.obj.update_layout(page)
            except Exception:
                pass
            hy = ay_hdr + 2 * max(1, sec.get_height())
            _center_label(sec, hy)
            self._labels.append(sec)
            self._label_ys.append(hy)
            sl = make_slider(page, w - 24, group)
            sl.set_pos(8, ay_sl)
            sl.set_range(0, 100)
            sl.set_value(int(getter() * 100), 0)
            self._sliders.append(sl)

            def _bind(slider, setter_fn):
                def _cb(e):
                    setter_fn(slider.get_value() / 100.0)

                return _cb

            sl.add_event_cb(_bind(sl, setter), lv.EVENT.VALUE_CHANGED, None)

        self.apply_theme()

    def apply_theme(self):
        self.scheme_lbl.set_text(
            "%s  (%d/%d)" % (theme.scheme_name(), theme.scheme_index() + 1, theme.scheme_count())
        )
        for lbl, y in zip(self._labels, self._label_ys):
            lbl.set_style_text_color(theme.accent_lite(), 0)
            _center_label(lbl, y)
        for btn in self._buttons:
            apply_button_theme(btn)
        for sl in self._sliders:
            apply_slider_theme(sl)

    def update(self):
        # Scheme label only — avoid restyling all sliders every vehicle tick.
        self.scheme_lbl.set_text(
            "%s  (%d/%d)" % (theme.scheme_name(), theme.scheme_index() + 1, theme.scheme_count())
        )
        _center_label(self.scheme_lbl, self._scheme_y)


def build(page, vehicle, group, w=0, h=0):
    return ThemeScreen(page, vehicle, group, w, h)
