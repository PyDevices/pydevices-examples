# SPDX-License-Identifier: MIT
"""Exterior / cabin light controls."""

import lvgl as lv

import theme
from screens._common import apply_switch_theme, content_size, make_switch, prep_page, section_label


class LightsScreen:
    def __init__(self, page, vehicle, group, w=0, h=0):
        self.vehicle = vehicle
        w, h = content_size(prep_page(page, w, h), w, h)
        font = theme.pick_font(200, page)

        # Even spacing of 9 rows (brightness row anchors left unused).
        n = 9
        y0, y_last = 32, min(436, h - 48)
        step = (y_last - y0) / (n - 1)
        anchors = [int(round(y0 + i * step)) for i in range(n)]

        ext = section_label(page, "EXTERIOR", 4)
        ext.align(lv.ALIGN.TOP_MID, -4, 4)

        self.switches = {}
        ext_rows = (
            ("autodim", "Auto dim"),
            ("delayed_off", "Delayed off"),
            ("drl", "Daytime running"),
            ("fog", "Fog lamps"),
            ("high_beam", "High beam"),
        )
        for i, (key, label) in enumerate(ext_rows):
            y = anchors[i]
            lbl = lv.label(page)
            lbl.set_text(label)
            lbl.set_style_text_color(theme.text(), 0)
            theme.apply_font(lbl, font)
            lbl.set_pos(8, y + 8)
            sw = make_switch(page, group)
            sw.set_pos(w - 72, y + 4)
            if vehicle.lights.get(key):
                sw.add_state(lv.STATE.CHECKED)
            else:
                sw.remove_state(lv.STATE.CHECKED)

            def _make(k, switch):
                def _cb(e):
                    on = switch.has_state(lv.STATE.CHECKED)
                    vehicle.lights[k] = bool(on)
                    if k == "autodim" and on:
                        theme.set_brightness(0.75)
                    elif k == "cabin" and on:
                        theme.set_brightness(1.0)

                return _cb

            sw.add_event_cb(_make(key, sw), lv.EVENT.VALUE_CHANGED, None)
            self.switches[key] = sw

        cab = section_label(page, "CABIN", anchors[5])
        cab.align(lv.ALIGN.TOP_MID, 0, anchors[5])

        y = anchors[6]
        lbl = lv.label(page)
        lbl.set_text("Cabin lights")
        lbl.set_style_text_color(theme.text(), 0)
        theme.apply_font(lbl, font)
        lbl.set_pos(8, y + 8)
        sw = make_switch(page, group)
        sw.set_pos(w - 72, y + 4)
        if vehicle.lights.get("cabin"):
            sw.add_state(lv.STATE.CHECKED)

        def _cabin_cb(e, s=sw):
            vehicle.lights["cabin"] = bool(s.has_state(lv.STATE.CHECKED))
            if vehicle.lights["cabin"]:
                theme.set_brightness(1.0)

        sw.add_event_cb(_cabin_cb, lv.EVENT.VALUE_CHANGED, None)
        self.switches["cabin"] = sw

        self.status = lv.label(page)
        self.status.set_style_text_color(theme.accent_lite(), 0)
        theme.apply_font(self.status, font)
        self.status.align(lv.ALIGN.BOTTOM_LEFT, 8, -6)
        self.update()

    def update(self):
        lit = [k for k, on in self.vehicle.lights.items() if on and k != "brightness"]
        self.status.set_text("Active: " + (", ".join(lit) if lit else "none"))

    def apply_theme(self):
        for sw in self.switches.values():
            apply_switch_theme(sw)
        self.status.set_style_text_color(theme.accent_lite(), 0)


def build(page, vehicle, group, w=0, h=0):
    return LightsScreen(page, vehicle, group, w, h)
