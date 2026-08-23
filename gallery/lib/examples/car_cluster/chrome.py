# SPDX-License-Identifier: MIT
"""Nested 3D chrome bezels and focus styles for the cluster shell."""

import lvgl as lv

import theme

# Bezel shells registered for shininess / scheme restyle.
_chrome_shells = []


def _circle_radius():
    return getattr(lv, "RADIUS_CIRCLE", 0x7FFF)


def _no_scroll(obj):
    if hasattr(obj, "remove_flag"):
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
    elif hasattr(obj, "clear_flag"):
        obj.clear_flag(lv.obj.FLAG.SCROLLABLE)


def style_root(obj):
    theme.style_bg(obj, theme.bg(), radius=0)


def style_panel(obj, radius=8):
    theme.style_bg(obj, theme.panel(), radius=radius, border_w=1, border_color=theme.chrome_mid())


def make_focus_style():
    """Accent ring for STATE.FOCUSED (rail / menu controls)."""
    style = lv.style_t()
    style.init()
    style.set_outline_width(2)
    style.set_outline_pad(2)
    style.set_outline_color(theme.accent())
    style.set_outline_opa(lv.OPA.COVER)
    style.set_border_width(2)
    style.set_border_color(theme.accent_lite())
    style.set_border_opa(lv.OPA.COVER)
    return theme.retain_style(style)


def _add_specular_strip(parent, radius, pad=2):
    """Thin bright top edge to sell polished metal."""
    strip = lv.obj(parent)
    _no_scroll(strip)
    strip.set_size(lv.pct(100), max(3, pad + 1))
    strip.align(lv.ALIGN.TOP_MID, 0, 0)
    theme.style_chrome(
        strip,
        radius=max(2, radius - 2),
        border_w=0,
        highlight=True,
        vertical=True,
    )
    try:
        strip.set_style_bg_opa(lv.OPA._70, 0)
    except Exception:
        strip.set_style_bg_opa(180, 0)
    return strip


def make_bezel(parent, x, y, w, h, depth=3, radius=10, pad=3):
    """Stacked frames for a plastic/chrome edge. Returns (outer, content)."""
    outer = lv.obj(parent)
    outer.set_pos(x, y)
    outer.set_size(w, h)
    _no_scroll(outer)
    # Outer shell: specular→dark vertical metal.
    theme.style_chrome(
        outer,
        radius=radius,
        border_w=2,
        border_color=theme.chrome_hi(),
        highlight=True,
        vertical=True,
    )
    _add_specular_strip(outer, radius, pad=pad)

    cur = outer
    inner_r = radius
    metal_layers = []
    for i in range(depth):
        child = lv.obj(cur)
        _no_scroll(child)
        cur.set_style_pad_all(pad if i == 0 else max(1, pad - 1), 0)
        child.set_size(lv.pct(100), lv.pct(100))
        child.align(lv.ALIGN.CENTER, 0, 0)
        inner_r = max(2, inner_r - 2)
        if i == depth - 1:
            theme.style_bg(
                child, theme.face(), radius=inner_r, border_w=1, border_color=theme.chrome_lo()
            )
        elif i % 2 == 0:
            # Bright band
            theme.style_chrome(
                child,
                radius=inner_r,
                border_w=1,
                border_color=theme.chrome_mid(),
                highlight=(i == 0),
                vertical=True,
            )
            metal_layers.append(child)
        else:
            # Dark recess with horizontal sheen for contrast.
            theme.style_chrome(
                child,
                radius=inner_r,
                border_w=1,
                border_color=theme.chrome_specular(),
                highlight=False,
                vertical=False,
            )
            metal_layers.append(child)
        cur = child

    content = cur
    # No content padding — callers position with set_pos against the full inner area.
    content.set_style_pad_all(0, 0)
    _chrome_shells.append({"kind": "bezel", "outer": outer, "layers": metal_layers})
    return outer, content


def make_center_bezel(parent, x, y, w, h):
    """Thicker, shinier bezel for the center instrument column."""
    return make_bezel(parent, x, y, w, h, depth=4, radius=14, pad=4)


def make_gauge_ring(parent, size):
    """Circular chrome ring + dark face for a gauge. Returns (ring, face)."""
    rad = _circle_radius()
    ring = lv.obj(parent)
    ring.set_size(size, size)
    _no_scroll(ring)
    # Outer metal: bright top → dark bottom.
    theme.style_chrome(
        ring,
        radius=rad,
        border_w=2,
        border_color=theme.chrome_specular(),
        highlight=True,
        vertical=True,
    )

    # Mid ring with opposite sheen (dark→bright) for a machined edge.
    mid_inset = max(3, size // 36)
    mid = lv.obj(ring)
    mid.set_size(size - 2 * mid_inset, size - 2 * mid_inset)
    mid.center()
    _no_scroll(mid)
    theme.style_chrome(
        mid,
        radius=rad,
        border_w=1,
        border_color=theme.chrome_hi(),
        highlight=False,
        vertical=True,
    )
    # Flip mid gradient visually by swapping ends via local props after style.
    mid.set_style_bg_color(theme.chrome_lo(), 0)
    mid.set_style_bg_grad_color(theme.chrome_specular(), 0)

    inset = max(5, size // 22)
    face = lv.obj(ring)
    face.set_size(size - 2 * inset, size - 2 * inset)
    face.center()
    _no_scroll(face)
    theme.style_bg(face, theme.face(), radius=rad, border_w=1, border_color=theme.chrome_lo())
    _chrome_shells.append({"kind": "gauge", "ring": ring, "mid": mid, "face": face})
    return ring, face


def apply_theme():
    """Refresh chrome gradients after shininess / brightness / scheme changes."""
    for entry in _chrome_shells:
        kind = entry.get("kind")
        if kind == "bezel":
            outer = entry.get("outer")
            if outer is not None:
                theme.apply_chrome_local(outer, highlight=True, border_color=theme.chrome_hi())
            for i, layer in enumerate(entry.get("layers") or ()):
                theme.apply_chrome_local(
                    layer,
                    highlight=(i == 0),
                    vertical=(i % 2 == 0),
                    border_color=theme.chrome_mid() if i % 2 == 0 else theme.chrome_specular(),
                )
        elif kind == "gauge":
            ring = entry.get("ring")
            mid = entry.get("mid")
            face = entry.get("face")
            if ring is not None:
                theme.apply_chrome_local(ring, highlight=True, border_color=theme.chrome_specular())
            if mid is not None:
                mid.set_style_bg_color(theme.chrome_lo(), 0)
                mid.set_style_bg_grad_color(theme.chrome_specular(), 0)
                mid.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
                mid.set_style_border_color(theme.chrome_hi(), 0)
            if face is not None:
                face.set_style_bg_color(theme.face(), 0)
                face.set_style_border_color(theme.chrome_lo(), 0)


def style_rail_button(btn, selected=False, *, initial=False):
    """Update rail button colors without stacking new styles.

    Calling ``theme.style_bg`` / ``add_style`` on every FOCUSED select accumulates
    style nodes and hard-locks LVGL under arrow-key storms (nesting=1). Mutate
    local style properties instead; use ``initial=True`` once at construction.
    """
    bg = theme.panel_raised() if not selected else theme.accent_dim()
    border = theme.accent() if selected else theme.chrome_mid()
    if initial:
        theme.style_bg(btn, bg, radius=8, border_w=1, border_color=border)
        focus = make_focus_style()
        btn.add_style(focus, lv.STATE.FOCUSED)
    btn.set_style_bg_color(bg, 0)
    btn.set_style_bg_opa(lv.OPA.COVER, 0)
    btn.set_style_border_width(1, 0)
    btn.set_style_border_color(border, 0)
    btn.set_style_radius(8, 0)
    btn.set_style_pad_all(2, 0)
    btn.set_style_pad_row(2, 0)
    btn.set_style_outline_width(2, lv.STATE.FOCUSED)
    btn.set_style_outline_pad(2, lv.STATE.FOCUSED)
    btn.set_style_outline_color(theme.accent(), lv.STATE.FOCUSED)
    btn.set_style_outline_opa(lv.OPA.COVER, lv.STATE.FOCUSED)
    btn.set_style_border_color(theme.accent_lite(), lv.STATE.FOCUSED)
