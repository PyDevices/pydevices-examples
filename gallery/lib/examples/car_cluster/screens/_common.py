# SPDX-License-Identifier: MIT
"""Shared helpers for center tab pages."""

import lvgl as lv

import lv_util
import theme

_TRACK_H = 8  # slider / bar track thickness; knob matches this


def no_scroll(obj):
    if hasattr(obj, "remove_flag"):
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
    elif hasattr(obj, "clear_flag"):
        obj.clear_flag(lv.obj.FLAG.SCROLLABLE)


def zero_pad(obj):
    obj.set_style_pad_all(0, 0)
    obj.set_style_pad_row(0, 0)
    obj.set_style_pad_column(0, 0)
    obj.set_style_margin_all(0, 0)


def content_size(page, w, h):
    """Usable page area; ``w``/``h`` come from layout (tabview content)."""
    if w > 40 and h > 40:
        return int(w), int(h)
    pw = page.get_width()
    ph = page.get_height()
    if pw > 40 and ph > 40:
        return pw, ph
    return 360, 420


def prep_page(page, w=0, h=0):
    no_scroll(page)
    page.set_size(lv.pct(100), lv.pct(100))
    theme.style_bg(page, theme.face(), radius=0)
    zero_pad(page)
    return page


def section_label(parent, text, y, *, accent=False):
    lbl = lv.label(parent)
    lbl.set_text(text)
    lbl.set_style_text_color(theme.accent_lite() if accent else theme.text_dim(), 0)
    theme.apply_font(lbl, theme.pick_font(220, parent))
    zero_pad(lbl)
    lbl.set_pos(4, y)
    return lbl


def scale_2x(lbl):
    """2× transform about the label center."""
    w = max(1, lbl.get_width())
    h = max(1, lbl.get_height())
    lbl.set_style_transform_pivot_x(w // 2, 0)
    lbl.set_style_transform_pivot_y(h // 2, 0)
    try:
        lbl.set_style_transform_scale(512, 0)
    except Exception:
        lbl.set_style_transform_scale_x(512, 0)
        lbl.set_style_transform_scale_y(512, 0)


def scale_2x_edge(lbl, *, left=True):
    """2× transform pivoting on the left or right edge."""
    w = max(1, lbl.get_width())
    h = max(1, lbl.get_height())
    lbl.set_style_transform_pivot_x(0 if left else w, 0)
    lbl.set_style_transform_pivot_y(h // 2, 0)
    try:
        lbl.set_style_transform_scale(512, 0)
    except Exception:
        lbl.set_style_transform_scale_x(512, 0)
        lbl.set_style_transform_scale_y(512, 0)


def kv_row(parent, y, key, value_text, width):
    k = lv.label(parent)
    k.set_text(key)
    k.set_style_text_color(theme.text_dim(), 0)
    theme.apply_font(k, theme.pick_font(200, parent))
    zero_pad(k)
    k.set_pos(8, y)

    v = lv.label(parent)
    v.set_text(value_text)
    v.set_style_text_color(theme.text(), 0)
    theme.apply_font(v, theme.pick_font(220, parent))
    zero_pad(v)
    v.set_pos(max(width // 2, 140), y)
    return k, v


def apply_kv_edge_scale(keys, vals, page_w, *, pad=14, dy=None, page=None):
    """Design-session layout: 2× edge-pivoted keys/values + pad/dy nudges."""
    if not keys:
        return
    if page is None:
        page = keys[0].get_parent()
    try:
        lv.obj.update_layout(page)
    except Exception:
        pass
    label_h = max(1, keys[0].get_height())
    if dy is None:
        dy = label_h
    for lbl in keys:
        scale_2x_edge(lbl, left=True)
        lbl.set_style_translate_x(pad - 8, 0)
        lbl.set_style_translate_y(dy, 0)
    for lbl in vals:
        w = max(1, lbl.get_width())
        scale_2x_edge(lbl, left=False)
        lbl.set_style_translate_x(page_w - pad - w - 152, 0)
        lbl.set_style_translate_y(dy, 0)


def spread_rows(count, top, bottom, height):
    """Even row Y positions between ``top`` and ``height - bottom``."""
    usable = max(40, height - top - bottom)
    if count <= 1:
        return [top]
    step = usable // count
    return [top + i * step for i in range(count)]


def make_button(parent, text, w, h, group=None):
    btn = lv.button(parent)
    btn.set_size(w, h)
    zero_pad(btn)
    theme.style_bg(btn, theme.panel_raised(), radius=8, border_w=1, border_color=theme.accent_dim())
    zero_pad(btn)
    focus = lv.style_t()
    focus.init()
    focus.set_outline_width(2)
    focus.set_outline_color(theme.accent())
    focus.set_outline_opa(lv.OPA.COVER)
    btn.add_style(focus, lv.STATE.FOCUSED)
    theme.retain_style(focus)
    lbl = lv.label(btn)
    lbl.set_text(text)
    lbl.set_style_text_color(theme.text(), 0)
    theme.apply_font(lbl, theme.pick_font(180, parent))
    zero_pad(lbl)
    lbl.center()
    if group is not None:
        lv_util.group_add(group, btn)
    return btn


def apply_button_theme(btn):
    btn.set_style_bg_color(theme.panel_raised(), 0)
    btn.set_style_border_color(theme.accent_dim(), 0)
    btn.set_style_outline_color(theme.accent(), lv.STATE.FOCUSED)
    try:
        btn.get_child(0).set_style_text_color(theme.text(), 0)
    except Exception:
        pass


def _style_switch(sw):
    st = lv.style_t()
    st.init()
    st.set_bg_color(theme.accent())
    st.set_bg_opa(lv.OPA.COVER)
    sw.add_style(st, lv.PART.INDICATOR | lv.STATE.CHECKED)
    theme.retain_style(st)
    st2 = lv.style_t()
    st2.init()
    st2.set_bg_color(theme.chrome_mid())
    st2.set_bg_opa(lv.OPA.COVER)
    sw.add_style(st2, lv.PART.MAIN)
    theme.retain_style(st2)
    # Keep the thumb compact
    st_k = lv.style_t()
    st_k.init()
    st_k.set_bg_color(theme.text())
    st_k.set_bg_opa(lv.OPA.COVER)
    st_k.set_pad_all(0)
    st_k.set_width(_TRACK_H)
    st_k.set_height(_TRACK_H)
    sw.add_style(st_k, lv.PART.KNOB)
    theme.retain_style(st_k)


def make_switch(parent, group=None):
    sw = lv.switch(parent)
    zero_pad(sw)
    _style_switch(sw)
    if group is not None:
        lv_util.group_add(group, sw)
    return sw


def apply_switch_theme(sw):
    sw.set_style_bg_color(theme.chrome_mid(), lv.PART.MAIN)
    sw.set_style_bg_color(theme.accent(), lv.PART.INDICATOR | lv.STATE.CHECKED)
    sw.set_style_bg_color(theme.text(), lv.PART.KNOB)


def _style_slider(sl):
    # Track
    st_main = lv.style_t()
    st_main.init()
    st_main.set_bg_color(theme.chrome_lo())
    st_main.set_bg_opa(lv.OPA.COVER)
    st_main.set_radius(_TRACK_H // 2)
    st_main.set_height(_TRACK_H)
    st_main.set_pad_all(0)
    sl.add_style(st_main, lv.PART.MAIN)
    theme.retain_style(st_main)

    # Filled portion
    st_ind = lv.style_t()
    st_ind.init()
    st_ind.set_bg_color(theme.accent())
    st_ind.set_bg_opa(lv.OPA.COVER)
    st_ind.set_radius(_TRACK_H // 2)
    sl.add_style(st_ind, lv.PART.INDICATOR)
    theme.retain_style(st_ind)

    # Knob same size as track thickness
    st_knob = lv.style_t()
    st_knob.init()
    st_knob.set_bg_color(theme.accent_lite())
    st_knob.set_bg_opa(lv.OPA.COVER)
    st_knob.set_radius(_TRACK_H // 2)
    st_knob.set_pad_all(0)
    st_knob.set_width(_TRACK_H)
    st_knob.set_height(_TRACK_H)
    st_knob.set_border_width(0)
    st_knob.set_outline_width(0)
    sl.add_style(st_knob, lv.PART.KNOB)
    theme.retain_style(st_knob)


def make_slider(parent, w, group=None):
    sl = lv.slider(parent)
    sl.set_width(w)
    sl.set_height(_TRACK_H)
    sl.set_range(0, 100)
    zero_pad(sl)
    _style_slider(sl)
    if group is not None:
        lv_util.group_add(group, sl)
    return sl


def apply_slider_theme(sl):
    sl.set_style_bg_color(theme.chrome_lo(), lv.PART.MAIN)
    sl.set_style_bg_color(theme.accent(), lv.PART.INDICATOR)
    sl.set_style_bg_color(theme.accent_lite(), lv.PART.KNOB)


def make_bar(parent, w, h):
    bar = lv.bar(parent)
    bar.set_size(w, h)
    bar.set_range(0, 100)
    zero_pad(bar)
    st = lv.style_t()
    st.init()
    st.set_bg_color(theme.chrome_lo())
    st.set_bg_opa(lv.OPA.COVER)
    st.set_radius(4)
    bar.add_style(st, lv.PART.MAIN)
    theme.retain_style(st)
    st2 = lv.style_t()
    st2.init()
    st2.set_bg_color(theme.accent())
    st2.set_bg_opa(lv.OPA.COVER)
    st2.set_radius(4)
    bar.add_style(st2, lv.PART.INDICATOR)
    theme.retain_style(st2)
    return bar


def apply_bar_theme(bar):
    bar.set_style_bg_color(theme.chrome_lo(), lv.PART.MAIN)
    bar.set_style_bg_color(theme.accent(), lv.PART.INDICATOR)
