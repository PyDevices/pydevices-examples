# SPDX-License-Identifier: MIT
"""Default center screen: large speedometer + odometer."""

import lvgl as lv

import gauges
import lv_util
import theme
from screens._common import apply_button_theme, content_size, make_button, prep_page


def _scale_label(lbl, scale):
    w = max(1, lbl.get_width())
    h = max(1, lbl.get_height())
    lbl.set_style_transform_pivot_x(w // 2, 0)
    lbl.set_style_transform_pivot_y(h // 2, 0)
    try:
        lbl.set_style_transform_scale(scale, 0)
    except Exception:
        lbl.set_style_transform_scale_x(scale, 0)
        lbl.set_style_transform_scale_y(scale, 0)


class SpeedScreen:
    def __init__(self, page, vehicle, group, w=0, h=0):
        self.vehicle = vehicle
        self.page = page
        w, h = content_size(prep_page(page, w, h), w, h)

        pad = 8
        body_h = h - 72
        body_w = w - 2 * pad

        self.digital = gauges.make_digital_speed(page, body_w, int(body_h * 0.78))
        self.digital.set_pos(pad, 8)

        gauge_sz = min(body_w - 16, int(body_h * 0.78))
        self.analog = gauges.make_speed_gauge(page, gauge_sz)
        self.analog.set_pos((w - gauge_sz) // 2, 8)
        lv_util.hide(self.analog.widget())

        dig = self.digital.widget()
        self.digital.set_num_scale(2048)
        self.digital.num.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        uh = max(1, self.digital.unit.get_height())
        self.digital.unit.set_style_translate_x(0, 0)
        self.digital.unit.set_style_translate_y(0, 0)
        self.digital.unit.align(lv.ALIGN.BOTTOM_MID, 0, -12 - uh)
        _scale_label(self.digital.unit, 768)

        self.odo = lv.label(page)
        self.odo.set_style_text_color(theme.text(), 0)
        theme.apply_font(self.odo, theme.pick_font(220, page))
        self.odo.set_style_pad_all(0, 0)
        self.odo.align(lv.ALIGN.BOTTOM_MID, 0, -10)

        # Same parent as odo (the speed page). Positioned later via TOP_LEFT —
        # sticky BOTTOM_* align + translate was pushing it off-screen.
        self.gear = lv.label(page)
        self.gear.set_style_text_color(theme.accent_lite(), 0)
        theme.apply_font(self.gear, theme.pick_font(240, page))
        self.gear.set_style_pad_all(0, 0)
        self.gear.set_text("GEAR  P")

        self.flags = lv.label(page)
        self.flags.set_style_text_color(theme.warn(), 0)
        theme.apply_font(self.flags, theme.pick_font(180, page))
        self.flags.set_style_pad_all(0, 0)
        self.flags.align(lv.ALIGN.BOTTOM_MID, 0, -10)

        self.toggle = make_button(page, "DIG / GAUGE", min(140, w // 3), 36, group)
        self.toggle.align_to(dig, lv.ALIGN.OUT_BOTTOM_MID, 0, max(1, self.toggle.get_height()) // 2)

        def _toggle(e):
            vehicle.toggle_speedo_mode()
            self._apply_mode()

        self.toggle.add_event_cb(_toggle, lv.EVENT.CLICKED, None)
        lv_util.add_flag(self.digital.widget(), lv.obj.FLAG.CLICKABLE)
        self.digital.widget().add_event_cb(_toggle, lv.EVENT.CLICKED, None)
        self._apply_mode()
        self.update()
        self._layout_odo_gear()

    def _layout_odo_gear(self):
        page = self.page
        self.odo.set_style_translate_x(0, 0)
        self.odo.set_style_translate_y(0, 0)
        self.odo.align(lv.ALIGN.BOTTOM_MID, 0, -10)
        _scale_label(self.odo, 512)
        self.odo.set_style_translate_x(0, 0)

        # Keep gear on the same parent as odo, place with TOP_LEFT (not sticky BOTTOM).
        if self.gear.get_parent() is not self.odo.get_parent():
            try:
                self.gear.set_parent(self.odo.get_parent())
            except Exception:
                pass
        self.gear.set_style_translate_x(0, 0)
        self.gear.set_style_translate_y(0, 0)
        try:
            lv.obj.update_layout(page)
        except Exception:
            pass
        gw = max(1, self.gear.get_width())
        gh = max(1, self.gear.get_height())
        btn_bot = self.toggle.get_y() + self.toggle.get_height()
        gap_mid = (btn_bot + self.odo.get_y()) // 2
        ty = gap_mid - gh // 2 + int(1.5 * gh) + 8 - 24
        ty = max(btn_bot + 2, min(ty, self.odo.get_y() - gh - 2))
        tx = (page.get_width() - gw) // 2
        self.gear.align(lv.ALIGN.TOP_LEFT, tx, ty)
        try:
            lv.obj.update_layout(page)
        except Exception:
            pass
        _scale_label(self.gear, 512)
        try:
            self.gear.move_foreground()
        except Exception:
            pass

    def _apply_mode(self):
        digital = self.vehicle.speedo_mode == "digital"
        if digital:
            lv_util.show(self.digital.widget())
            lv_util.hide(self.analog.widget())
        else:
            lv_util.hide(self.digital.widget())
            lv_util.show(self.analog.widget())

    def update(self):
        v = self.vehicle
        mph = int(round(v.speed_mph))
        self._apply_mode()
        if v.speedo_mode == "digital":
            self.digital.set_value(mph)
        else:
            self.analog.set_value(min(125, mph))
        self.odo.set_text("%.1f mi" % float(v.odo_miles))
        self.gear.set_text("GEAR  %s" % v.gear_label())
        self._layout_odo_gear()
        bits = []
        if v.lights.get("high_beam"):
            bits.append("HB")
        if v.lights.get("turn_left"):
            bits.append("<")
        if v.lights.get("turn_right"):
            bits.append(">")
        if v.redline:
            bits.append("REDLINE")
        self.flags.set_text("  ".join(bits) if bits else "")

    def apply_theme(self):
        self.digital.apply_theme()
        self.analog.apply_theme()
        self.gear.set_style_text_color(theme.accent_lite(), 0)
        self.odo.set_style_text_color(theme.text(), 0)
        self.flags.set_style_text_color(theme.warn(), 0)
        apply_button_theme(self.toggle)


def build(page, vehicle, group, w=0, h=0):
    return SpeedScreen(page, vehicle, group, w, h)
