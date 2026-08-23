# SPDX-License-Identifier: MIT
"""Coherent analog / digital gauges for the instrument cluster."""

import lvgl as lv

import chrome
import lv_util
import theme

_styles = []


def _retain(style):
    _styles.append(style)
    theme.retain_style(style)
    return style


def _no_scroll(obj):
    if hasattr(obj, "remove_flag"):
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
    elif hasattr(obj, "clear_flag"):
        obj.clear_flag(lv.obj.FLAG.SCROLLABLE)


def _overflow_visible(obj):
    if hasattr(obj, "add_flag"):
        try:
            obj.add_flag(lv.obj.FLAG.OVERFLOW_VISIBLE)
        except Exception:
            pass


def _style_scale(scale_obj, *, tick_w=2, minor_len=10, major_len=16):
    # Background arc under ticks
    st = lv.style_t()
    st.init()
    st.set_arc_color(theme.chrome_lo())
    st.set_arc_width(4)
    st.set_arc_opa(lv.OPA.COVER)
    scale_obj.add_style(st, lv.PART.MAIN)
    _retain(st)

    # Major ticks (LV_PART_INDICATOR)
    st_maj = lv.style_t()
    st_maj.init()
    st_maj.set_line_color(theme.tick())
    st_maj.set_line_opa(lv.OPA.COVER)
    st_maj.set_line_width(tick_w + 1)
    st_maj.set_line_rounded(True)
    st_maj.set_length(major_len)
    st_maj.set_text_color(theme.text_dim())
    scale_obj.add_style(st_maj, lv.PART.INDICATOR)
    _retain(st_maj)

    # Minor ticks (LV_PART_ITEMS)
    st_min = lv.style_t()
    st_min.init()
    st_min.set_line_color(theme.chrome_mid())
    st_min.set_line_opa(lv.OPA.COVER)
    st_min.set_line_width(tick_w)
    st_min.set_line_rounded(True)
    st_min.set_length(minor_len)
    scale_obj.add_style(st_min, lv.PART.ITEMS)
    _retain(st_min)

    # Local styles as a belt-and-suspenders (some ports read these first).
    try:
        scale_obj.set_style_length(major_len, lv.PART.INDICATOR)
        scale_obj.set_style_line_width(tick_w + 1, lv.PART.INDICATOR)
        scale_obj.set_style_line_color(theme.tick(), lv.PART.INDICATOR)
        scale_obj.set_style_line_opa(lv.OPA.COVER, lv.PART.INDICATOR)
        scale_obj.set_style_length(minor_len, lv.PART.ITEMS)
        scale_obj.set_style_line_width(tick_w, lv.PART.ITEMS)
        scale_obj.set_style_line_color(theme.chrome_mid(), lv.PART.ITEMS)
        scale_obj.set_style_line_opa(lv.OPA.COVER, lv.PART.ITEMS)
    except Exception:
        pass


def _add_zone_section(scale_obj, vmin, vmax, color_fn):
    sec = scale_obj.add_section()
    scale_obj.set_section_range(sec, int(vmin), int(vmax))
    st = lv.style_t()
    st.init()
    c = color_fn()
    st.set_arc_color(c)
    st.set_arc_width(8)
    st.set_line_color(c)
    for setter in (
        lambda: scale_obj.section_set_style(sec, lv.PART.INDICATOR, st),
        lambda: scale_obj.set_section_style_indicator(sec, st),
        lambda: scale_obj.section_set_style(sec, lv.PART.ITEMS, st),
        lambda: scale_obj.set_section_style_items(sec, st),
    ):
        try:
            setter()
            break
        except Exception:
            continue
    _retain(st)
    return sec


def _hub(parent, size):
    rad = getattr(lv, "RADIUS_CIRCLE", 0x7FFF)
    hub = lv.obj(parent)
    hub.set_size(size, size)
    hub.center()
    _no_scroll(hub)
    theme.style_bg(hub, theme.chrome_hi(), radius=rad, border_w=2, border_color=theme.accent_dim())
    inner = lv.obj(hub)
    inner.set_size(max(6, size // 2), max(6, size // 2))
    inner.center()
    _no_scroll(inner)
    theme.style_bg(inner, theme.accent(), radius=rad, border_w=1, border_color=theme.accent_lite())
    dot = lv.obj(hub)
    dot.set_size(max(3, size // 6), max(3, size // 6))
    dot.center()
    _no_scroll(dot)
    theme.style_bg(dot, theme.secondary(), radius=rad)
    return hub


def _cap_label(parent, text, align, x_ofs=0, y_ofs=0):
    lbl = lv.label(parent)
    lbl.set_text(text)
    lbl.set_style_text_color(theme.text_dim(), 0)
    theme.apply_font(lbl, theme.pick_font(max(100, parent.get_width() // 4), parent))
    lbl.align(align, x_ofs, y_ofs)
    return lbl


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


def _cap_mid(g, *, x_extra=0, y=0, bottom=False):
    """Mid-align min/max caps (design session); optional inset / vertical offset."""
    if g is None:
        return
    x_ofs = max(8, g.size // 10) + x_extra
    align_l = lv.ALIGN.BOTTOM_LEFT if bottom else lv.ALIGN.LEFT_MID
    align_r = lv.ALIGN.BOTTOM_RIGHT if bottom else lv.ALIGN.RIGHT_MID
    y_ofs = -g.size // 6 if bottom else y
    for cap, align, x in (
        (getattr(g, "cap_min_lbl", None), align_l, x_ofs),
        (getattr(g, "cap_max_lbl", None), align_r, -x_ofs),
    ):
        if cap is None:
            continue
        cap.set_style_translate_x(0, 0)
        cap.set_style_translate_y(0, 0)
        try:
            cap.set_style_transform_scale(256, 0)
        except Exception:
            cap.set_style_transform_scale_x(256, 0)
            cap.set_style_transform_scale_y(256, 0)
        cap.align(align, x, y_ofs)
        _scale_2x(cap)


class AnalogGauge:
    def __init__(
        self,
        parent,
        size,
        vmin,
        vmax,
        *,
        angle_range=270,
        rotation=135,
        ticks=41,
        major_every=5,
        label="",
        unit="",
        redline=None,
        cap_min="",
        cap_max="",
        needle_len=None,
        arc_mode=True,
        bg_angles=None,
        value_fmt=None,
        show_value=True,
        design_layout=None,
    ):
        self.vmin = vmin
        self.vmax = vmax
        self.value = vmin
        self.unit = unit
        self.label = label
        self.size = size
        self._value_fmt = value_fmt
        self._show_value = show_value
        self._design_layout = design_layout
        self._needle_len = needle_len if needle_len is not None else int(size * 0.42)

        # Size from the constructor arg — get_width() is often 0 before layout.
        ring_inset = max(4, size // 28)
        face_sz = size - 2 * ring_inset

        self.ring, self.face = chrome.make_gauge_ring(parent, size)
        self.face.set_style_pad_all(0, 0)
        _overflow_visible(self.ring)
        _overflow_visible(self.face)
        for obj in (self.ring, self.face):
            try:
                obj.set_style_clip_corner(False, 0)
            except Exception:
                pass

        # Accent ring drawn as a non-clipping child (ticks live on the face).
        inset = max(4, size // 28)
        inner_sz = max(40, face_sz - 2 * inset)
        self.inner_ring = lv.obj(self.face)
        self.inner_ring.set_size(inner_sz, inner_sz)
        self.inner_ring.center()
        self.inner_ring.set_style_pad_all(0, 0)
        _no_scroll(self.inner_ring)
        _overflow_visible(self.inner_ring)
        try:
            self.inner_ring.set_style_clip_corner(False, 0)
        except Exception:
            pass
        theme.style_bg(
            self.inner_ring,
            theme.face(),
            radius=getattr(lv, "RADIUS_CIRCLE", 0x7FFF),
            border_w=1,
            border_color=theme.accent_dim(),
        )
        self.inner_ring.set_style_pad_all(0, 0)
        # Keep accent ring under the scale so it cannot cover ticks.
        try:
            self.inner_ring.move_background()
        except Exception:
            pass

        font_lg = theme.pick_font(size, self.face)
        font_sm = theme.pick_font(max(160, size // 2), self.face)

        # Sweep arc UNDER the scale — a later sibling paints over ticks/needles (H-J).
        # Named sweep_arc: binding corrupts attribute name ``arc`` on some ports.
        self.sweep_arc = None
        if arc_mode:
            arc_sz = max(40, face_sz - max(22, size // 7))
            self.sweep_arc = lv.arc(self.face)
            self.sweep_arc.set_size(arc_sz, arc_sz)
            self.sweep_arc.center()
            self.sweep_arc.set_style_pad_all(0, 0)
            try:
                self.sweep_arc.set_style_bg_opa(lv.OPA.TRANSP, 0)
            except Exception:
                pass
            self.sweep_arc.set_range(int(vmin), int(vmax))
            if bg_angles is not None:
                self.sweep_arc.set_bg_angles(bg_angles[0], bg_angles[1])
            else:
                self.sweep_arc.set_bg_angles(rotation, (rotation + angle_range) % 360)
            self.sweep_arc.set_mode(lv.arc.MODE.NORMAL)
            st_a = lv.style_t()
            st_a.init()
            st_a.set_arc_color(theme.chrome_lo())
            st_a.set_arc_width(8)
            self.sweep_arc.add_style(st_a, lv.PART.MAIN)
            _retain(st_a)
            st_i = lv.style_t()
            st_i.init()
            st_i.set_arc_color(theme.accent())
            st_i.set_arc_width(8)
            self.sweep_arc.add_style(st_i, lv.PART.INDICATOR)
            _retain(st_i)
            self._arc_ind_style = st_i
            st_k = lv.style_t()
            st_k.init()
            st_k.set_bg_opa(lv.OPA.TRANSP)
            st_k.set_pad_all(0)
            st_k.set_width(0)
            st_k.set_height(0)
            self.sweep_arc.add_style(st_k, lv.PART.KNOB)
            _retain(st_k)
            lv_util.hide_clickable(self.sweep_arc)
        else:
            self._arc_ind_style = None

        self.scale = lv.scale(self.face)
        self.scale.set_size(face_sz, face_sz)
        self.scale.center()
        self.scale.set_style_pad_all(0, 0)
        try:
            self.scale.set_style_bg_opa(lv.OPA.TRANSP, 0)
        except Exception:
            pass
        _overflow_visible(self.scale)
        try:
            self.scale.set_style_clip_corner(False, 0)
        except Exception:
            pass
        # INNER: ticks onto the dark face (OUTER sat on chrome / under the arc).
        self.scale.set_mode(lv.scale.MODE.ROUND_INNER)
        self.scale.set_range(int(vmin), int(vmax))
        self.scale.set_angle_range(int(angle_range))
        self.scale.set_rotation(int(rotation))
        self.scale.set_total_tick_count(int(ticks))
        self.scale.set_major_tick_every(int(major_every))
        self.scale.set_label_show(False)
        maj = max(10, size // 16)
        mn = max(6, size // 26)
        _style_scale(self.scale, tick_w=2, minor_len=mn, major_len=maj)

        if redline is not None:
            _add_zone_section(self.scale, redline, vmax, theme.danger)
        elif vmax > vmin * 0.7:
            warn_at = vmin + (vmax - vmin) * 0.78
            _add_zone_section(self.scale, warn_at, vmax, theme.warn)

        self.needle_shadow = lv.line(self.scale)
        st_ns = lv.style_t()
        st_ns.init()
        st_ns.set_line_color(theme.chrome_lo())
        st_ns.set_line_width(5)
        st_ns.set_line_rounded(True)
        self.needle_shadow.add_style(st_ns, 0)
        _retain(st_ns)

        self.needle = lv.line(self.scale)
        st_n = lv.style_t()
        st_n.init()
        st_n.set_line_color(theme.needle())
        st_n.set_line_width(3)
        st_n.set_line_rounded(True)
        self.needle.add_style(st_n, 0)
        _retain(st_n)
        self._needle_style = st_n

        try:
            self.scale.move_foreground()
        except Exception:
            pass

        self.hub = _hub(self.face, max(12, size // 10))
        try:
            self.hub.move_foreground()
        except Exception:
            pass

        if label:
            self.title_lbl = lv.label(self.face)
            self.title_lbl.set_text(label)
            self.title_lbl.set_style_text_color(theme.accent_lite(), 0)
            theme.apply_font(self.title_lbl, font_sm)
            self.title_lbl.set_style_pad_all(0, 0)
            self.title_lbl.align(lv.ALIGN.TOP_MID, 0, max(2, size // 20))
        else:
            self.title_lbl = None

        if show_value:
            self.value_lbl = lv.label(self.face)
            self.value_lbl.set_text("--")
            self.value_lbl.set_style_text_color(theme.text(), 0)
            theme.apply_font(self.value_lbl, font_lg)
            self.value_lbl.set_style_pad_all(0, 0)
            self.value_lbl.align(lv.ALIGN.BOTTOM_MID, 0, -max(4, size // 14))
        else:
            self.value_lbl = None

        self.cap_min_lbl = (
            _cap_label(self.face, cap_min, lv.ALIGN.BOTTOM_LEFT, max(8, size // 10), -size // 6)
            if cap_min
            else None
        )
        self.cap_max_lbl = (
            _cap_label(self.face, cap_max, lv.ALIGN.BOTTOM_RIGHT, -max(8, size // 10), -size // 6)
            if cap_max
            else None
        )

        # Labels stay above ticks; keep scale above the arc (hub already raised).
        try:
            self.scale.move_foreground()
            if self.hub is not None:
                self.hub.move_foreground()
            if self.title_lbl is not None:
                self.title_lbl.move_foreground()
            if self.value_lbl is not None:
                self.value_lbl.move_foreground()
        except Exception:
            pass

        self.set_value(vmin)
        if design_layout:
            self.apply_design_layout(design_layout)

    def apply_design_layout(self, kind=None):
        """Bake interactive design-session label / cap placement into the gauge."""
        if kind is None:
            kind = self._design_layout
        if not kind:
            return
        self._design_layout = kind

        try:
            lv.obj.update_layout(self.face)
        except Exception:
            pass

        for lbl in (self.title_lbl, self.value_lbl, self.cap_min_lbl, self.cap_max_lbl):
            if lbl is not None:
                _scale_2x(lbl)

        title = self.title_lbl
        if title is not None:
            h = max(1, title.get_height())
            half = h + h // 2
            if kind in ("rpm", "speed"):
                ty = 2 * half
            elif kind == "temp":
                ty = half + half // 2
            else:  # fuel, oil
                ty = half
            title.set_style_translate_x(0, 0)
            title.set_style_translate_y(0, 0)
            title.align(lv.ALIGN.CENTER, 0, ty)
            _scale_2x(title)

        cap0 = self.cap_min_lbl
        cap10 = self.cap_max_lbl
        w0 = max(1, cap0.get_width()) if cap0 is not None else 0
        w10 = max(1, cap10.get_width()) if cap10 is not None else 0
        if kind == "rpm":
            _cap_mid(self, x_extra=2 * w10 + w0, bottom=True)
        elif kind == "speed":
            th = max(1, title.get_height()) if title is not None else 16
            ty = 2 * (th + th // 2)
            _cap_mid(self, x_extra=w0, y=ty)
        elif kind == "oil":
            _cap_mid(self, x_extra=w0)
        else:
            _cap_mid(self)

        if kind in ("oil", "temp", "speed") and self.value_lbl is not None:
            h = max(1, self.value_lbl.get_height())
            y = -max(4, self.size // 14) - h // 2
            self.value_lbl.set_style_translate_x(0, 0)
            self.value_lbl.set_style_translate_y(0, 0)
            self.value_lbl.align(lv.ALIGN.BOTTOM_MID, 0, y)
            _scale_2x(self.value_lbl)

    def _format_value(self, v):
        if self._value_fmt is not None:
            return self._value_fmt(v)
        iv = int(round(v))
        if self.unit:
            return "%d %s" % (iv, self.unit)
        return str(iv)

    def set_value(self, v):
        if v < self.vmin:
            v = self.vmin
        if v > self.vmax:
            v = self.vmax
        self.value = v
        iv = int(round(v))
        for needle, length in ((self.needle_shadow, self._needle_len + 1), (self.needle, self._needle_len)):
            try:
                self.scale.set_line_needle_value(needle, length, iv)
            except Exception:
                pass
        if self.sweep_arc is not None:
            self.sweep_arc.set_value(iv)
        if self.value_lbl is None:
            return
        self.value_lbl.set_text(self._format_value(v))
        if v >= self.vmax * 0.92:
            self.value_lbl.set_style_text_color(theme.danger(), 0)
        elif v >= self.vmax * 0.75:
            self.value_lbl.set_style_text_color(theme.warn(), 0)
        else:
            self.value_lbl.set_style_text_color(theme.text(), 0)
        if self._design_layout:
            _scale_2x(self.value_lbl)

    def set_pos(self, x, y):
        self.ring.set_pos(x, y)

    def widget(self):
        return self.ring

    def apply_theme(self):
        """Refresh accent-dependent colors after a scheme change."""
        self.ring.set_style_bg_color(theme.chrome_specular(), 0)
        self.ring.set_style_bg_grad_color(theme.chrome_lo(), 0)
        self.ring.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.ring.set_style_border_color(theme.chrome_specular(), 0)
        self.face.set_style_bg_color(theme.face(), 0)
        self.face.set_style_border_color(theme.chrome_lo(), 0)
        self.inner_ring.set_style_bg_color(theme.face(), 0)
        self.inner_ring.set_style_border_color(theme.accent_dim(), 0)
        self.scale.set_style_line_color(theme.tick(), lv.PART.INDICATOR)
        self.scale.set_style_line_color(theme.chrome_mid(), lv.PART.ITEMS)
        if self._arc_ind_style is not None:
            self._arc_ind_style.set_arc_color(theme.accent())
        if getattr(self, "_needle_style", None) is not None:
            self._needle_style.set_line_color(theme.needle())
        try:
            self.hub.set_style_bg_color(theme.chrome_hi(), 0)
            self.hub.set_style_border_color(theme.accent_dim(), 0)
            self.hub.get_child(0).set_style_bg_color(theme.accent(), 0)
            self.hub.get_child(0).set_style_border_color(theme.accent_lite(), 0)
            self.hub.get_child(1).set_style_bg_color(theme.secondary(), 0)
        except Exception:
            pass
        if self.title_lbl is not None:
            self.title_lbl.set_style_text_color(theme.accent_lite(), 0)
        for lbl in (self.cap_min_lbl, self.cap_max_lbl):
            if lbl is not None:
                lbl.set_style_text_color(theme.text_dim(), 0)
        self.set_value(self.value)
        if self._design_layout:
            self.apply_design_layout(self._design_layout)


class DigitalSpeed:
    def __init__(self, parent, w, h):
        self.value = 0
        self._box_w = w
        self._box_h = h
        self._num_scale = 256
        self._num_y_ofs = -h // 12
        self.box = lv.obj(parent)
        self.box.set_size(w, h)
        _no_scroll(self.box)
        theme.style_bg(self.box, theme.face(), radius=12, border_w=2, border_color=theme.accent_dim())

        font = theme.pick_font(max(w, h), self.box)
        font_sm = theme.pick_font(max(180, h // 2), self.box)

        # Full-width + text-align center: stays parent-centered as digits change.
        self.num_shadow = lv.label(self.box)
        self.num_shadow.set_text("0")
        self.num_shadow.set_style_text_color(theme.chrome_lo(), 0)
        theme.apply_font(self.num_shadow, font)
        self.num_shadow.set_width(w)
        self.num_shadow.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)

        self.num = lv.label(self.box)
        self.num.set_text("0")
        self.num.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        theme.apply_font(self.num, font)
        self.num.set_width(w)
        self.num.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        try:
            self.num.set_style_text_letter_space(6, 0)
            self.num_shadow.set_style_text_letter_space(6, 0)
        except Exception:
            pass

        self._layout_num()

        self.unit = lv.label(self.box)
        self.unit.set_text("MPH")
        self.unit.set_style_text_color(theme.secondary(), 0)
        theme.apply_font(self.unit, font_sm)
        uh = max(1, self.unit.get_height())
        self.unit.align(lv.ALIGN.BOTTOM_MID, 0, -12 - uh)

    def _center_scaled(self, lbl, scale, x_ofs=0, y_ofs=0):
        box_w, box_h = self._box_w, self._box_h
        lbl.set_style_translate_x(0, 0)
        lbl.set_style_translate_y(0, 0)
        lbl.align(lv.ALIGN.CENTER, x_ofs, y_ofs)
        w = max(1, lbl.get_width())
        h = max(1, lbl.get_height())
        lbl.set_style_transform_pivot_x(w // 2, 0)
        lbl.set_style_transform_pivot_y(h // 2, 0)
        try:
            lbl.set_style_transform_scale_x(scale, 0)
            lbl.set_style_transform_scale_y(scale, 0)
        except Exception:
            lbl.set_style_transform_scale(scale, 0)
        cx = lbl.get_x() + w // 2
        cy = lbl.get_y() + h // 2
        lbl.set_style_translate_x(box_w // 2 + x_ofs - cx, 0)
        lbl.set_style_translate_y(box_h // 2 + y_ofs - cy, 0)

    def _layout_num(self):
        y_ofs = self._num_y_ofs
        scale = self._num_scale
        self._center_scaled(self.num, scale, 0, y_ofs)
        self._center_scaled(self.num_shadow, scale, 4, y_ofs + 4)

    def set_num_scale(self, scale):
        """Transform scale for the digital digits (256 = 1×, 2048 = 8×)."""
        self._num_scale = int(scale)
        self._layout_num()

    def set_value(self, v):
        v = int(_clamp_int(v, 0, 199))
        self.value = v
        text = "%d" % v
        self.num.set_text(text)
        self.num_shadow.set_text(text)
        if v >= 100:
            self.num.set_style_text_color(theme.warn(), 0)
        else:
            self.num.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        self._layout_num()

    def set_pos(self, x, y):
        self.box.set_pos(x, y)

    def widget(self):
        return self.box

    def apply_theme(self):
        self.box.set_style_border_color(theme.accent_dim(), 0)
        self.set_value(self.value)
        self.unit.set_style_text_color(theme.secondary(), 0)


def _clamp_int(v, lo, hi):
    v = int(v)
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def make_rpm_gauge(parent, size):
    g = AnalogGauge(
        parent,
        size,
        0,
        10000,
        angle_range=270,
        rotation=135,
        ticks=51,
        major_every=5,
        label="RPM",
        unit="",
        redline=6500,
        cap_min="0",
        cap_max="10",
        arc_mode=True,
        value_fmt=lambda v: "%.1f" % (v / 1000.0),
        design_layout="rpm",
    )
    return g


def make_fuel_gauge(parent, size):
    return AnalogGauge(
        parent,
        size,
        0,
        100,
        angle_range=120,
        rotation=210,
        ticks=21,
        major_every=5,
        label="FUEL",
        unit="%",
        cap_min="E",
        cap_max="F",
        arc_mode=True,
        bg_angles=(210, 330),
        show_value=False,
        design_layout="fuel",
    )


def make_temp_gauge(parent, size):
    return AnalogGauge(
        parent,
        size,
        100,
        260,
        angle_range=150,
        rotation=195,
        ticks=33,
        major_every=4,
        label="COOLANT",
        unit="°F",
        redline=212,
        cap_min="C",
        cap_max="H",
        arc_mode=True,
        bg_angles=(195, 345),
        design_layout="temp",
    )


def make_oil_gauge(parent, size):
    return AnalogGauge(
        parent,
        size,
        0,
        80,
        angle_range=180,
        rotation=180,
        ticks=17,
        major_every=4,
        label="OIL",
        unit="psi",
        cap_min="0",
        cap_max="80",
        arc_mode=True,
        bg_angles=(180, 360),
        design_layout="oil",
    )


def make_speed_gauge(parent, size):
    return AnalogGauge(
        parent,
        size,
        0,
        125,
        angle_range=270,
        rotation=135,
        ticks=26,
        major_every=5,
        label="SPEED",
        unit="mph",
        redline=100,
        cap_min="0",
        cap_max="125",
        arc_mode=True,
        design_layout="speed",
    )


def make_digital_speed(parent, w, h):
    return DigitalSpeed(parent, w, h)
