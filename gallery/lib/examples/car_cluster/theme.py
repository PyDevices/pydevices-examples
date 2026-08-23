# SPDX-License-Identifier: MIT
"""Material accent schemes, chrome shininess, and shared style retention."""

import lvgl as lv

_styles = []
_listeners = []

# Named schemes: Material palette accents for the cluster.
SCHEMES = (
    {"name": "Cyan", "accent": lv.PALETTE.CYAN, "secondary": lv.PALETTE.BLUE_GREY},
    {"name": "Amber", "accent": lv.PALETTE.AMBER, "secondary": lv.PALETTE.ORANGE},
    {"name": "Indigo", "accent": lv.PALETTE.INDIGO, "secondary": lv.PALETTE.DEEP_PURPLE},
    {"name": "Teal", "accent": lv.PALETTE.TEAL, "secondary": lv.PALETTE.GREEN},
    {"name": "Deep Orange", "accent": lv.PALETTE.DEEP_ORANGE, "secondary": lv.PALETTE.RED},
    {"name": "Light Blue", "accent": lv.PALETTE.LIGHT_BLUE, "secondary": lv.PALETTE.BLUE},
)

_scheme_index = 5  # Light Blue
_shininess = 0.5
_gauge_scale = 1.0
_brightness = 0.92


def retain_style(style):
    _styles.append(style)
    return style


def on_change(cb):
    if cb not in _listeners:
        _listeners.append(cb)


def notify():
    for cb in _listeners:
        try:
            cb()
        except Exception:
            pass


def scheme_name():
    return SCHEMES[_scheme_index]["name"]


def scheme_count():
    return len(SCHEMES)


def set_scheme(index):
    global _scheme_index
    n = len(SCHEMES)
    _scheme_index = int(index) % n
    notify()


def set_shininess(value):
    global _shininess
    if value < 0.0:
        value = 0.0
    if value > 1.0:
        value = 1.0
    _shininess = value
    notify()


def set_gauge_scale(value):
    global _gauge_scale
    if value < 0.85:
        value = 0.85
    if value > 1.15:
        value = 1.15
    _gauge_scale = value
    notify()


def set_brightness(value):
    global _brightness
    if value < 0.3:
        value = 0.3
    if value > 1.0:
        value = 1.0
    _brightness = value
    notify()


def shininess():
    return _shininess


def gauge_scale():
    return _gauge_scale


def brightness():
    return _brightness


def scheme_index():
    return _scheme_index


def _hex(rgb):
    return lv.color_hex(rgb & 0xFFFFFF)


def _blend_toward(rgb, target, amount):
    r = (rgb >> 16) & 0xFF
    g = (rgb >> 8) & 0xFF
    b = rgb & 0xFF
    tr = (target >> 16) & 0xFF
    tg = (target >> 8) & 0xFF
    tb = target & 0xFF
    r = int(r + (tr - r) * amount)
    g = int(g + (tg - g) * amount)
    b = int(b + (tb - b) * amount)
    return (r << 16) | (g << 8) | b


def _dim_rgb(rgb, factor):
    r = int(((rgb >> 16) & 0xFF) * factor)
    g = int(((rgb >> 8) & 0xFF) * factor)
    b = int((rgb & 0xFF) * factor)
    if r > 255:
        r = 255
    if g > 255:
        g = 255
    if b > 255:
        b = 255
    return (r << 16) | (g << 8) | b


def _accent_palette():
    return SCHEMES[_scheme_index]["accent"]


def _secondary_palette():
    return SCHEMES[_scheme_index]["secondary"]


def secondary():
    return lv.palette_main(_secondary_palette())


def secondary_dim():
    return lv.palette_darken(_secondary_palette(), 1)


def bg():
    # Slightly lifted from near-black so chrome/bezels read against it.
    return _hex(_dim_rgb(0x14161C, _brightness))


def panel():
    return _hex(_dim_rgb(0x1A1E28, _brightness))


def panel_raised():
    return _hex(_dim_rgb(0x222833, _brightness))


def chrome_hi():
    # Bright rim — shininess pushes toward polished silver.
    base = _blend_toward(0x4A5160, 0xE8EEF5, _shininess * 0.95)
    return _hex(_dim_rgb(base, _brightness))


def chrome_mid():
    base = _blend_toward(0x2A303C, 0xA8B2C0, _shininess * 0.85)
    return _hex(_dim_rgb(base, _brightness))


def chrome_lo():
    base = _blend_toward(0x0C0E12, 0x3A4250, _shininess * 0.55)
    return _hex(_dim_rgb(base, _brightness))


def chrome_specular():
    """Near-white highlight for metallic top edges."""
    base = _blend_toward(0x6A7384, 0xFFFFFF, min(1.0, _shininess * 1.05))
    return _hex(_dim_rgb(base, _brightness))


def accent():
    return lv.palette_main(_accent_palette())


def accent_dim():
    return lv.palette_darken(_accent_palette(), 2)


def accent_lite():
    return lv.palette_lighten(_accent_palette(), 1)


def danger():
    return lv.palette_main(lv.PALETTE.RED)


def warn():
    return lv.palette_main(lv.PALETTE.AMBER)


def ok():
    return lv.palette_main(lv.PALETTE.GREEN)


def text():
    return _hex(_dim_rgb(0xF2F4F8, _brightness))


def text_dim():
    return _hex(_dim_rgb(0x8A93A3, _brightness))


def tick():
    return _hex(_dim_rgb(0xB8C0CC, _brightness))


def needle():
    return accent_lite()


def face():
    return _hex(_dim_rgb(0x0E1016, _brightness))


def pick_font(unit, ref_obj=None):
    if unit >= 520:
        candidates = (28, 24, 16, 14)
    elif unit >= 360:
        candidates = (24, 16, 14)
    elif unit >= 200:
        candidates = (18, 16, 14)
    else:
        candidates = (16, 14, 24)
    for size in candidates:
        font = getattr(lv, "font_montserrat_" + str(size), None)
        if font is not None:
            return font
    if ref_obj is not None:
        for getter in ("theme_get_font_large", "theme_get_font_normal", "theme_get_font_small"):
            fn = getattr(lv, getter, None)
            if fn is None:
                continue
            try:
                font = fn(ref_obj)
                if font is not None:
                    return font
            except Exception:
                pass
    fn = getattr(lv, "font_get_default", None)
    if fn is not None:
        try:
            return fn()
        except Exception:
            pass
    return None


def apply_font(obj, font):
    if font is not None:
        obj.set_style_text_font(font, 0)


def style_bg(obj, color, radius=0, border_w=0, border_color=None):
    style = lv.style_t()
    style.init()
    style.set_bg_color(color)
    style.set_bg_opa(lv.OPA.COVER)
    style.set_radius(radius)
    style.set_border_width(border_w)
    if border_color is not None and border_w:
        style.set_border_color(border_color)
        style.set_border_opa(lv.OPA.COVER)
    style.set_pad_all(0)
    obj.add_style(style, 0)
    return retain_style(style)


def style_chrome(
    obj,
    *,
    radius=0,
    border_w=1,
    border_color=None,
    vertical=True,
    highlight=False,
):
    """Metallic fill: bright→dark gradient, optional specular top."""
    style = lv.style_t()
    style.init()
    hi = chrome_specular() if highlight else chrome_hi()
    lo = chrome_lo()
    style.set_bg_color(hi)
    style.set_bg_grad_color(lo)
    style.set_bg_grad_dir(lv.GRAD_DIR.VER if vertical else lv.GRAD_DIR.HOR)
    style.set_bg_opa(lv.OPA.COVER)
    style.set_radius(radius)
    style.set_border_width(border_w)
    if border_w:
        style.set_border_color(border_color if border_color is not None else chrome_mid())
        style.set_border_opa(lv.OPA.COVER)
    style.set_pad_all(0)
    obj.add_style(style, 0)
    return retain_style(style)


def apply_chrome_local(obj, *, highlight=False, vertical=True, border_color=None):
    """Update chrome colors in place (theme / shininess changes)."""
    hi = chrome_specular() if highlight else chrome_hi()
    obj.set_style_bg_color(hi, 0)
    obj.set_style_bg_grad_color(chrome_lo(), 0)
    obj.set_style_bg_grad_dir(lv.GRAD_DIR.VER if vertical else lv.GRAD_DIR.HOR, 0)
    obj.set_style_bg_opa(lv.OPA.COVER, 0)
    if border_color is not None:
        obj.set_style_border_color(border_color, 0)
    else:
        obj.set_style_border_color(chrome_mid(), 0)
