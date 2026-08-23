# deps: lvgl
# modules: calc_engine
"""
calc_lvgl
====================================================
Dark-theme pocket calculator built with LVGL.

Shares :class:`calc_engine.CalcEngine` with the graphics and pdwidgets front
ends. Button sizes, gaps, radii, and font choice are derived from
``display_drv.width`` / ``height`` so the UI scales from 320x480 through
640x960 and similar desktop sizes.

Import order matters: ``display_driver`` must be imported after ``board_config``
so LVGL's display/input devices are wired before widgets are created.
"""

import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

import display_driver  # wires LVGL display/input into the app
import lvgl as lv
from board_config import display_drv
from display_driver import app
from calc_engine import CalcEngine

# Button grid (last row: two wide buttons).
_BUTTON_ROWS = (
    ("CE", "C", "BS", "/"),
    ("7", "8", "9", "*"),
    ("4", "5", "6", "-"),
    ("1", "2", "3", "+"),
    ("+/-", "0", ".", "="),
    ("sqrt", "%"),
)

_engine = None
_expr_lbl = None
_num_lbl = None
_disp_panel = None
_max_expr_chars = 28
# LVGL style_t objects must stay alive while attached to widgets (GC → segfault).
_styles = []


def _hex(rgb):
    return lv.color_hex(rgb)


def _pick_font(unit, ref_obj=None):
    """Pick a readable font; fall back to theme / default when Montserrat is absent.

    Never pass ``None`` into ``theme_get_font_*`` — that segfaults in the C binding.
    """
    if unit >= 560:
        candidates = (28, 24, 22, 20, 18, 16, 14, 12)
    elif unit >= 400:
        candidates = (22, 20, 18, 16, 14, 12)
    else:
        candidates = (16, 14, 12)
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


def _apply_font(obj, font):
    if font is not None:
        obj.set_style_text_font(font, 0)


def _style_bg(obj, color, radius=0):
    style = lv.style_t()
    style.init()
    style.set_bg_color(color)
    style.set_bg_opa(lv.OPA.COVER)
    style.set_radius(radius)
    style.set_border_width(0)
    style.set_pad_all(0)
    obj.add_style(style, 0)
    _styles.append(style)
    return style


def _btn_colors(label):
    if label in "0123456789.":
        return 0x333338, 0xFFFFFF
    if label in "+-*/":
        return 0xFF9F0A, 0x1C1C1E
    if label == "=":
        return 0x0A84FF, 0xFFFFFF
    return 0x55555A, 0xFFFFFF


def _refresh():
    expr = _engine.expression
    num = _engine.display
    if _expr_lbl is not None:
        # Keep the history line from overflowing the panel.
        if len(expr) > _max_expr_chars:
            expr = "..." + expr[-(_max_expr_chars - 3) :]
        _expr_lbl.set_text(expr)
    if _num_lbl is not None:
        _num_lbl.set_text(num)
        if _engine.is_error:
            _num_lbl.set_style_text_color(_hex(0xFF453A), 0)
        else:
            _num_lbl.set_style_text_color(_hex(0xFFFFFF), 0)


def _on_btn(e, key):
    try:
        _engine.press(key)
    except ValueError:
        return
    _refresh()


def build_ui():
    global _engine, _expr_lbl, _num_lbl, _disp_panel, _max_expr_chars

    inst = display_driver.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        _styles.clear()
        _engine = CalcEngine()
        W = display_drv.width
        H = display_drv.height
        unit = min(W, H)
        pad = max(4, unit // 64)
        radius = max(6, unit // 36)
        disp_h = max(64, H // 5)
        body_h = H - disp_h
        btn_rows = 6
        row_h = max(28, (body_h - pad) // btn_rows)
        # Approximate glyph width for default/theme fonts (~8–14 px).
        glyph_w = max(8, unit // 40)
        _max_expr_chars = max(8, (W - 4 * pad) // glyph_w)

        scr = lv.screen_active()
        font = _pick_font(unit, scr)
        font_sm = _pick_font(max(200, unit // 2), scr)
        _style_bg(scr, _hex(0x121214))

        # Display panel
        _disp_panel = lv.obj(scr)
        _disp_panel.set_size(W - 2 * pad, disp_h - pad)
        _disp_panel.align(lv.ALIGN.TOP_MID, 0, pad // 2)
        _style_bg(_disp_panel, _hex(0x1C1C1E), radius)
        if hasattr(_disp_panel, "remove_flag"):
            _disp_panel.remove_flag(lv.obj.FLAG.SCROLLABLE)
        elif hasattr(_disp_panel, "clear_flag"):
            _disp_panel.clear_flag(lv.obj.FLAG.SCROLLABLE)

        _expr_lbl = lv.label(_disp_panel)
        _expr_lbl.set_text("")
        _expr_lbl.set_style_text_color(_hex(0xAEAEB2), 0)
        _apply_font(_expr_lbl, font_sm)
        _expr_lbl.set_style_text_align(lv.TEXT_ALIGN.RIGHT, 0)
        _expr_lbl.set_width(W - 4 * pad)
        _expr_lbl.align(lv.ALIGN.TOP_RIGHT, -pad, pad)

        _num_lbl = lv.label(_disp_panel)
        _num_lbl.set_text("0")
        _num_lbl.set_style_text_color(_hex(0xFFFFFF), 0)
        _apply_font(_num_lbl, font)
        _num_lbl.set_style_text_align(lv.TEXT_ALIGN.RIGHT, 0)
        _num_lbl.set_width(W - 4 * pad)
        _num_lbl.align(lv.ALIGN.BOTTOM_RIGHT, -pad, -pad)

        # Button grid
        y0 = disp_h
        for r, row in enumerate(_BUTTON_ROWS):
            n = len(row)
            cell_w = (W - pad) // n
            for c, label in enumerate(row):
                bg_rgb, fg_rgb = _btn_colors(label)
                btn = lv.button(scr)
                btn.set_size(cell_w - pad, row_h - pad)
                btn.set_pos(pad // 2 + c * cell_w, y0 + r * row_h + pad // 2)
                _style_bg(btn, _hex(bg_rgb), radius)

                # Pressed state highlight (keep style ref alive)
                style_pr = lv.style_t()
                style_pr.init()
                style_pr.set_bg_color(_hex(0xFFFFFF))
                style_pr.set_bg_opa(lv.OPA.COVER)
                btn.add_style(style_pr, lv.STATE.PRESSED)
                _styles.append(style_pr)

                lbl = lv.label(btn)
                shown = "sqrt" if label == "sqrt" else label
                lbl.set_text(shown)
                lbl.set_style_text_color(_hex(fg_rgb), 0)
                _apply_font(lbl, font_sm)
                lbl.center()

                # Bind key via default-arg closure (MicroPython-safe).
                def _make_cb(k):
                    def _cb(e):
                        _on_btn(e, k)

                    return _cb

                btn.add_event_cb(_make_cb(label), lv.EVENT.CLICKED, None)

        _refresh()
    finally:
        if inst is not None:
            inst.enable()


build_ui()

# Canonical entry: display_driver wired LVGL into its own app at import, and
# the app keeps itself alive past the end of this script.
