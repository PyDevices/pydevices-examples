# SPDX-License-Identifier: MIT
"""Root cluster layout: side gauges + center bezel with dual rails + tabview."""

import lvgl as lv

import chrome
import gauges
import rails
import theme
from screens import BUILDERS, TAB_NAMES


class ClusterUI:
    def __init__(self, vehicle, focus_nav=None):
        self.vehicle = vehicle
        self.focus_nav = focus_nav
        if focus_nav is not None:
            self.left_group = focus_nav.left
            self.center_group = focus_nav.center
            self.right_group = focus_nav.right
        else:
            g = lv.group_get_default()
            if g is None:
                g = lv.group_create()
                g.set_default()
            self.left_group = g
            self.center_group = g
            self.right_group = g
        self.screens = []
        self.gauges = {}
        self.rails = None
        self.tabview = None
        self._build()

    def _build(self):
        scr = lv.screen_active()
        chrome.style_root(scr)
        W = scr.get_width()
        H = scr.get_height()

        # Outer perimeter bezel
        margin = 6
        outer, shell = chrome.make_bezel(scr, margin, margin, W - 2 * margin, H - 2 * margin, depth=3, radius=12, pad=3)
        self.outer = outer
        sw = shell.get_width()
        sh = shell.get_height()
        if sw < 100:
            sw = W - 40
        if sh < 100:
            sh = H - 40

        # Center column: slightly narrower than tall, nearly full height
        center_h = sh - 8
        center_w = int(center_h * 0.90)  # slightly narrower than tall
        # Side columns share remaining width
        side_w = (sw - center_w - 16) // 2
        if side_w < 120:
            # shrink center to keep gauges usable
            side_w = max(110, (sw - 16) // 4)
            center_w = sw - 2 * side_w - 16
        cx = side_w + 8
        cy = 4

        # Left stack: RPM (large) + Fuel (smaller)
        left = lv.obj(shell)
        left.set_pos(4, 4)
        left.set_size(side_w, sh - 8)
        theme.style_bg(left, theme.bg(), radius=0)
        if hasattr(left, "remove_flag"):
            left.remove_flag(lv.obj.FLAG.SCROLLABLE)

        gs = theme.gauge_scale()
        col_h = sh - 8
        rpm_sz = int(min(side_w - 8, col_h * 0.58) * gs)
        fuel_sz = int(min(side_w - 8, col_h * 0.36) * gs)
        # Even vertical gaps: top / between / bottom.
        left_gap = max(4, (col_h - rpm_sz - fuel_sz) // 3)
        self.gauges["rpm"] = gauges.make_rpm_gauge(left, rpm_sz)
        self.gauges["rpm"].set_pos((side_w - rpm_sz) // 2, left_gap)
        self.gauges["fuel"] = gauges.make_fuel_gauge(left, fuel_sz)
        self.gauges["fuel"].set_pos((side_w - fuel_sz) // 2, left_gap + rpm_sz + left_gap)

        # Right stack: Temp + Oil
        right = lv.obj(shell)
        right.set_pos(sw - side_w - 4, 4)
        right.set_size(side_w, sh - 8)
        theme.style_bg(right, theme.bg(), radius=0)
        if hasattr(right, "remove_flag"):
            right.remove_flag(lv.obj.FLAG.SCROLLABLE)

        temp_sz = int(min(side_w - 8, col_h * 0.48) * gs)
        oil_sz = int(min(side_w - 8, col_h * 0.40) * gs)
        right_gap = max(4, (col_h - temp_sz - oil_sz) // 3)
        self.gauges["temp"] = gauges.make_temp_gauge(right, temp_sz)
        self.gauges["temp"].set_pos((side_w - temp_sz) // 2, right_gap)
        self.gauges["oil"] = gauges.make_oil_gauge(right, oil_sz)
        self.gauges["oil"].set_pos((side_w - oil_sz) // 2, right_gap + temp_sz + right_gap)

        # Center chrome
        c_outer, c_content = chrome.make_center_bezel(shell, cx, cy, center_w, center_h)
        self.center_outer = c_outer
        cw = c_content.get_width()
        ch = c_content.get_height()
        if cw < 80:
            cw = center_w - 24
        if ch < 80:
            ch = center_h - 24

        rail_w = max(56, cw // 7)
        mid_w = cw - 2 * rail_w - 8
        content_h = ch - 4  # slight inset; gear lives on Speed screen only

        # Tabview with hidden bar — pages fill content area
        self.tabview = lv.tabview(c_content)
        self.tabview.set_size(mid_w, content_h)
        self.tabview.set_pos(rail_w + 4, 0)
        bar = self.tabview.get_tab_bar()
        bar.add_flag(lv.obj.FLAG.HIDDEN)
        try:
            self.tabview.set_tab_bar_size(0)
        except Exception:
            pass

        try:
            content = self.tabview.get_content()
            page_w = content.get_width()
            page_h = content.get_height()
        except Exception:
            page_w = mid_w
            page_h = content_h
        if page_w < 40:
            page_w = mid_w
        if page_h < 40:
            page_h = content_h

        pages = []
        for name in TAB_NAMES:
            page = self.tabview.add_tab(name)
            page.set_size(lv.pct(100), lv.pct(100))
            pages.append(page)

        self.rails = rails.Rails(
            c_content,
            self.tabview,
            self.left_group,
            self.right_group,
            rail_w,
            content_h,
            pad=3,
        )
        self.rails.place(0, cw - rail_w, 0)

        for i, builder in enumerate(BUILDERS):
            self.screens.append(
                builder(pages[i], self.vehicle, self.center_group, page_w, page_h)
            )

        self.rails.select(0, anim=False)
        self.rails.drain_pending()

        # Seed defaults
        self.gauges["fuel"].set_value(int(self.vehicle.fuel_frac * 100))
        self.gauges["temp"].set_value(self.vehicle.coolant_f)
        self.gauges["oil"].set_value(self.vehicle.oil_psi)
        self.gauges["rpm"].set_value(self.vehicle.rpm)

        theme.on_change(self._on_theme_change)

    def _on_theme_change(self):
        chrome.apply_theme()
        for g in self.gauges.values():
            if hasattr(g, "apply_theme"):
                g.apply_theme()
        if self.rails is not None and hasattr(self.rails, "apply_theme"):
            self.rails.apply_theme()
        for scr in self.screens:
            if hasattr(scr, "apply_theme"):
                scr.apply_theme()

    def update(self):
        v = self.vehicle
        self.gauges["rpm"].set_value(v.rpm)
        self.gauges["fuel"].set_value(int(v.fuel_frac * 100))
        self.gauges["temp"].set_value(v.coolant_f)
        self.gauges["oil"].set_value(v.oil_psi)
        for scr in self.screens:
            if hasattr(scr, "update"):
                scr.update()
