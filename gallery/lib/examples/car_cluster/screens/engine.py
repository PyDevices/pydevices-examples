# SPDX-License-Identifier: MIT
"""Engine information screen."""

import lvgl as lv

import theme
from screens._common import (
    apply_bar_theme,
    apply_kv_edge_scale,
    content_size,
    kv_row,
    make_bar,
    prep_page,
    spread_rows,
)


class EngineScreen:
    def __init__(self, page, vehicle, group, w=0, h=0):
        self.vehicle = vehicle
        w, h = content_size(prep_page(page, w, h), w, h)
        self._page_w = w
        self._page = page

        keys = (
            "Coolant",
            "Oil temp",
            "Oil pres.",
            "Battery",
            "Intake air",
            "Hours",
            "RPM",
        )
        ys = spread_rows(len(keys), top=8, bottom=56, height=h)
        self.keys = []
        self.vals = []
        for lab, y in zip(keys, ys):
            k, v = kv_row(page, y, lab, "--", w)
            self.keys.append(k)
            self.vals.append(v)

        # Design session: 2× edge scale + extra vertical nudge (label_h + 16).
        try:
            lv.obj.update_layout(page)
        except Exception:
            pass
        label_h = max(1, self.keys[0].get_height())
        apply_kv_edge_scale(self.keys, self.vals, w, dy=label_h + 16, page=page)

        # No ENGINE LOAD header — keep the load bar only.
        load_y = h - 44
        self.load_bar = make_bar(page, w - 24, 18)
        self.load_bar.set_pos(8, load_y)
        self.update()

    def update(self):
        v = self.vehicle
        texts = (
            "%.1f °F" % v.coolant_f,
            "%.0f °F" % v.oil_temp_f,
            "%.1f psi" % v.oil_psi,
            "%.1f V" % v.battery_v,
            "%.0f °F" % v.iat_f,
            "%.1f h" % v.engine_hours,
            "%d" % int(v.rpm),
        )
        for lbl, text in zip(self.vals, texts):
            lbl.set_text(text)
        try:
            lv.obj.update_layout(self._page)
        except Exception:
            pass
        label_h = max(1, self.keys[0].get_height())
        apply_kv_edge_scale(self.keys, self.vals, self._page_w, dy=label_h + 16, page=self._page)
        if v.coolant_f >= 212:
            self.vals[0].set_style_text_color(theme.danger(), 0)
        else:
            self.vals[0].set_style_text_color(theme.text(), 0)
        self.load_bar.set_value(int(v.throttle * 100), 0)

    def apply_theme(self):
        apply_bar_theme(self.load_bar)


def build(page, vehicle, group, w=0, h=0):
    return EngineScreen(page, vehicle, group, w, h)
