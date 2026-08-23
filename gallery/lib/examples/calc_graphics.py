# deps: palettes, pygraphics
# modules: calc_engine
"""
calc_graphics
====================================================
Dark-theme pocket calculator drawn with ``pygraphics.FrameBuffer``.

Shares :class:`calc_engine.CalcEngine` with the pdwidgets and LVGL front ends.
All geometry (padding, button size, font scale, display band) is derived from
``display_drv.width`` / ``height`` so the UI scales from 320x480 up through
640x960 and similar desktop sizes.
"""

import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from calc_engine import CalcEngine
import keys
from pygraphics import RGB565, FrameBuffer
from multimer import auto as timer
from palettes import get_palette
from appdev import TouchGrid


# Button grid: 1 display row + 6 keypad rows, 4 columns.
# Row 6 draws sqrt / % as two double-wide buttons (cells 0-1 and 2-3).
# Both cells of a wide button share the same label so touch hits either half.
_LABELS = [
    "CE", "C", "BS", "/",
    "7", "8", "9", "*",
    "4", "5", "6", "-",
    "1", "2", "3", "+",
    "+/-", "0", ".", "=",
    "sqrt", "sqrt", "%", "%",
]

# fmt: off
_CODES = [
    keys.K_ESCAPE,       keys.K_c,            keys.K_BACKSPACE,    keys.K_KP_DIVIDE,
    keys.K_KP_7,         keys.K_KP_8,         keys.K_KP_9,         keys.K_KP_MULTIPLY,
    keys.K_KP_4,         keys.K_KP_5,         keys.K_KP_6,         keys.K_KP_MINUS,
    keys.K_KP_1,         keys.K_KP_2,         keys.K_KP_3,         keys.K_KP_PLUS,
    keys.K_KP_PLUSMINUS, keys.K_KP_0,         keys.K_KP_PERIOD,    keys.K_KP_ENTER,
    keys.K_s,            keys.K_KP_POWER,     keys.K_p,            keys.K_KP_PERCENT,
]
# fmt: on

_KEY_ALIASES = {
    keys.K_RETURN: "=",
    keys.K_KP_EQUALS: "=",
    keys.K_SLASH: "/",
    keys.K_ASTERISK: "*",
    keys.K_MINUS: "-",
    keys.K_EQUALS: "=",
    keys.K_PERIOD: ".",
    keys.K_PERCENT: "%",
}


def _c565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class _Calculator:
    COLS = 4
    BTN_ROWS = 6
    ROWS = 1 + BTN_ROWS  # display band + buttons
    FONT_W = 8
    FONT_H = 16

    def __init__(self):
        self.width = display_drv.width
        self.height = display_drv.height
        self.bpp = display_drv.color_depth // 8
        self.unit = min(self.width, self.height)

        # Scale factors from a 320x480 reference panel.
        self.pad = max(2, self.unit // 80)
        self.radius = max(4, self.unit // 40)
        self.row_h = self.height // self.ROWS
        self.col_w = self.width // self.COLS
        self.btn_w = self.col_w - 2 * self.pad
        self.btn_h = self.row_h - 2 * self.pad
        self.disp_w = self.width - 2 * self.pad
        self.disp_h = self.row_h - 2 * self.pad
        self.line_h = max(self.FONT_H, self.disp_h // 2)
        # Font scale: ~1 at 320px, ~2 at 640px.
        self.font_scale = max(1, self.unit // 280)
        self.expr_scale = max(1, self.font_scale)
        self.num_scale = max(1, self.font_scale + (1 if self.unit >= 480 else 0))

        self.pal = get_palette(name="material_design")
        # Dark calculator theme (iPhone / Google style).
        self.bg = _c565(0x12, 0x12, 0x14)
        self.disp_bg = _c565(0x1C, 0x1C, 0x1E)
        self.digit_bg = _c565(0x33, 0x33, 0x38)
        self.fn_bg = _c565(0x55, 0x55, 0x5A)
        self.op_bg = _c565(0xFF, 0x9F, 0x0A)
        self.eq_bg = _c565(0x0A, 0x84, 0xFF)
        self.press_bg = _c565(0xFF, 0xFF, 0xFF)
        self.expr_fg = _c565(0xAE, 0xAE, 0xB2)
        self.num_fg = _c565(0xFF, 0xFF, 0xFF)
        self.err_fg = _c565(0xFF, 0x45, 0x3A)
        self.digit_fg = _c565(0xFF, 0xFF, 0xFF)
        self.fn_fg = _c565(0xFF, 0xFF, 0xFF)
        self.op_fg = _c565(0x1C, 0x1C, 0x1E)

        self.engine = CalcEngine()
        self.button_pos = {}
        self._label_for = {}

        # Grid cells map to _CODES (row 0 is the display band -> None). Keyboard
        # aliases are appended past the grid so KEYDOWN dispatches them too; they
        # have no grid cell so the touch mapping never indexes them.
        keypad_keys = [None] * self.COLS + list(_CODES) + list(_KEY_ALIASES.keys())
        self._pending_release = None
        self._release_timer = timer.Timer(-1)
        self.keypad = TouchGrid(
            app,
            0,
            0,
            self.width,
            self.height,
            self.COLS,
            self.ROWS,
            keypad_keys,
            on_press=self._on_press,
        )

        # Scratch buffers sized for the largest button (double-wide on last row).
        max_btn_w = self.col_w * 2 - 2 * self.pad
        self.btn_ba = bytearray(max_btn_w * self.btn_h * self.bpp)
        self.btn_fb = FrameBuffer(self.btn_ba, max_btn_w, self.btn_h, RGB565)
        self.line_ba = bytearray(self.disp_w * self.line_h * self.bpp)
        self.line_fb = FrameBuffer(self.line_ba, self.disp_w, self.line_h, RGB565)

        self._draw_all()

    def _colors_for(self, label):
        if label in "0123456789.":
            return self.digit_fg, self.digit_bg
        if label in "+-*/":
            return self.op_fg, self.op_bg
        if label == "=":
            return self.digit_fg, self.eq_bg
        return self.fn_fg, self.fn_bg

    def _draw_all(self):
        display_drv.fill(self.bg)
        # Display band
        display_drv.fill_rect(
            self.pad,
            self.pad,
            self.disp_w,
            self.disp_h,
            self.disp_bg,
        )
        for i, (code, label) in enumerate(zip(_CODES, _LABELS)):
            col = i % self.COLS
            row = i // self.COLS + 1
            self.button_pos[code] = (col, row, label)
            self._label_for[code] = label
            # Skip the right half of a double-wide button (drawn with left cell).
            if label in ("sqrt", "%") and col in (1, 3):
                continue
            self._draw_button(col, row, label, pressed=False)
        self._refresh_display()
        display_drv.show()

    def _button_geom(self, col, row, label):
        x = col * self.col_w + self.pad
        y = row * self.row_h + self.pad
        w = self.btn_w
        h = self.btn_h
        if label in ("sqrt", "%"):
            w = self.col_w * 2 - 2 * self.pad
        return x, y, w, h

    def _draw_button(self, col, row, label, pressed=False):
        x, y, w, h = self._button_geom(col, row, label)
        fg, bg = self._colors_for(label)
        if pressed:
            fg, bg = self.bg, self.press_bg

        # Rebind framebuffer to this button's size.
        self.btn_fb = FrameBuffer(self.btn_ba, w, h, RGB565)
        self.btn_fb.fill(self.bg)
        r = min(self.radius, w // 4, h // 4)
        self.btn_fb.round_rect(0, 0, w, h, r, bg, True)

        text = "sqrt" if label == "sqrt" else label
        # Shrink scale if the label is wider than the button.
        scale = self.font_scale
        while scale > 1 and len(text) * self.FONT_W * scale > w - 2:
            scale -= 1
        tw = len(text) * self.FONT_W * scale
        th = self.FONT_H * scale
        tx = max(0, (w - tw) // 2)
        ty = max(0, (h - th) // 2)
        self.btn_fb.text16(text, tx, ty, fg, scale) if scale != 1 else self.btn_fb.text16(text, tx, ty, fg)
        display_drv.blit_rect(self.btn_ba[: w * h * self.bpp], x, y, w, h)

    def _right_text(self, fb, text, scale, color, y_off):
        tw = len(text) * self.FONT_W * scale
        x = max(self.pad, self.disp_w - tw - self.pad)
        fb.text16(text, x, y_off, color, scale) if scale != 1 else fb.text16(text, x, y_off, color)

    def _refresh_display(self):
        expr = self.engine.expression
        num = self.engine.display
        num_fg = self.err_fg if self.engine.is_error else self.num_fg

        # Expression (top half of display band)
        self.line_fb = FrameBuffer(self.line_ba, self.disp_w, self.line_h, RGB565)
        self.line_fb.fill(self.disp_bg)
        if expr:
            # Truncate from the left if too long.
            max_chars = max(4, (self.disp_w - 2 * self.pad) // (self.FONT_W * self.expr_scale))
            if len(expr) > max_chars:
                expr = "..." + expr[-(max_chars - 3) :]
            self._right_text(self.line_fb, expr, self.expr_scale, self.expr_fg, self.pad)
        display_drv.blit_rect(
            self.line_ba[: self.disp_w * self.line_h * self.bpp],
            self.pad,
            self.pad,
            self.disp_w,
            self.line_h,
        )

        # Main number (bottom half)
        self.line_fb.fill(self.disp_bg)
        max_chars = max(4, (self.disp_w - 2 * self.pad) // (self.FONT_W * self.num_scale))
        if len(num) > max_chars:
            num = num[-(max_chars):]
        y_off = max(0, (self.line_h - self.FONT_H * self.num_scale) // 2)
        self._right_text(self.line_fb, num, self.num_scale, num_fg, y_off)
        display_drv.blit_rect(
            self.line_ba[: self.disp_w * self.line_h * self.bpp],
            self.pad,
            self.pad + self.line_h,
            self.disp_w,
            self.line_h,
        )

    def _on_press(self, code):
        """Push callback from TouchKeypad (touch grid + keyboard). No app poll loop."""
        if code is None:
            return
        info = self.button_pos.get(code)
        if info is not None:
            col, row, label = info
            # Map double-wide right-half taps to the left cell for drawing.
            if label == "sqrt" and col == 1:
                col = 0
            if label == "%" and col == 3:
                col = 2
            self._handle_press(col, row, label)
            self._pending_release = (col, row, label)
            self._release_timer.init(
                mode=timer.Timer.ONE_SHOT, period=150, callback=self._release
            )
            return
        # Keyboard alias / digit without a grid cell — feed the engine only.
        label = _KEY_ALIASES.get(code)
        if label is None and isinstance(code, int) and 48 <= code <= 57:
            label = chr(code)
        if label is None:
            return
        self.engine.press(label)
        self._refresh_display()
        display_drv.show()

    def _release(self, _=None):
        if self._pending_release is None:
            return
        col, row, label = self._pending_release
        self._pending_release = None
        self.release_button(col, row, label)

    def _handle_press(self, col, row, label):
        self._draw_button(col, row, label, pressed=True)
        self.engine.press(label)
        self._refresh_display()
        display_drv.show()

    def release_button(self, col, row, label):
        self._draw_button(col, row, label, pressed=False)
        display_drv.show()


# Canonical idiom: build the UI (registers input callbacks), then hand control
# to the app. Identical for sync and async, interactive or not — the input
# arrives via the TouchKeypad on_press callback dispatched by the shared-timer
# auto-service; QUIT tears everything down.
calc = _Calculator()

# Canonical entry: the app keeps itself alive past the end of this script, and
# in an interactive REPL the prompt comes back while the app keeps running.