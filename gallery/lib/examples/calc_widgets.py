# deps: pdwidgets
# modules: calc_engine
"""
calc_widgets
====================================================
Dark-theme pocket calculator built with ``pdwidgets``.

Shares :class:`calc_engine.CalcEngine` with the graphics and LVGL front ends.
Layout, font scales, radii, and padding are derived from display size so the
UI scales from 320x480 through 640x960 and similar desktop sizes.

Input and frame rendering are driven by the shared ``appdev.App``:
``pd.Display`` wires them in at construction, so the example just builds the UI
and lets the app run itself.
"""

import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

import board_config
import board_config
import appdev

app = appdev.App(board_config)
import pdwidgets as pd
from calc_engine import CalcEngine

pd.DEBUG = False

display = pd.Display(board_config.display_drv, app)
pal = display.pal

W = display.width
H = display.height
unit = min(W, H)

# Scale from a 320x480 reference.
pad = max(3, unit // 64)
radius = max(4, unit // 40)
disp_h = max(56, H // 5)
btn_rows = 6
btn_cols = 4
body_h = H - disp_h
col_w = W // btn_cols
row_h = body_h // btn_rows
num_scale = max(2, unit // 160)
expr_scale = max(1, unit // 280)
btn_text = 16 if unit >= 400 else 14
# TEXT_SIZE only allows 8/14/16; clamp.
if btn_text not in (8, 14, 16):
    btn_text = 16

# Dark calculator palette (override the default cream theme for this screen).
BG = pal.color565(0x12, 0x12, 0x14)
DISP_BG = pal.color565(0x1C, 0x1C, 0x1E)
DIGIT_BG = pal.color565(0x33, 0x33, 0x38)
FN_BG = pal.color565(0x55, 0x55, 0x5A)
OP_BG = pal.color565(0xFF, 0x9F, 0x0A)
EQ_BG = pal.color565(0x0A, 0x84, 0xFF)
EXPR_FG = pal.color565(0xAE, 0xAE, 0xB2)
NUM_FG = pal.color565(0xFF, 0xFF, 0xFF)
ERR_FG = pal.color565(0xFF, 0x45, 0x3A)
ON_OP = pal.color565(0x1C, 0x1C, 0x1E)
ON_BTN = pal.color565(0xFF, 0xFF, 0xFF)

BUTTON_ROWS = (
    ("CE", "C", "BS", "/"),
    ("7", "8", "9", "*"),
    ("4", "5", "6", "-"),
    ("1", "2", "3", "+"),
    ("+/-", "0", ".", "="),
    ("sqrt", "%"),  # two wide buttons
)

engine = CalcEngine()

screen = pd.Screen(display, bg=BG, visible=False)

# ----- Display band --------------------------------------------------------
top = pd.Widget(screen, w=W, h=disp_h, align=pd.ALIGN.TOP, bg=DISP_BG, padding=(pad, pad, pad, pad))
expr_box = pd.TextBox(
    top,
    w=top.width - 2 * pad,
    h=max(14, disp_h // 3),
    align=pd.ALIGN.TOP_RIGHT,
    x=-pad,
    y=pad // 2,
    fg=EXPR_FG,
    bg=DISP_BG,
    scale=expr_scale,
    value="",
)
max_expr = max(6, (expr_box.width // expr_box.char_width) - 1)
expr_box.format = ">" + str(max_expr)

num_box = pd.TextBox(
    top,
    w=top.width - 2 * pad,
    h=max(20, disp_h // 2),
    align=pd.ALIGN.BOTTOM_RIGHT,
    x=-pad,
    y=-pad // 2,
    fg=NUM_FG,
    bg=DISP_BG,
    scale=num_scale,
    value="0",
)
max_num = max(6, (num_box.width // num_box.char_width) - 1)
num_box.format = ">" + str(max_num)

# ----- Button grid ---------------------------------------------------------
button_box = pd.Widget(
    screen,
    w=W,
    h=body_h,
    align=pd.ALIGN.BOTTOM,
    bg=BG,
    padding=(0, 0, 0, 0),
)


def _btn_colors(label):
    if label in "0123456789.":
        return ON_BTN, DIGIT_BG
    if label in "+-*/":
        return ON_OP, OP_BG
    if label == "=":
        return ON_BTN, EQ_BG
    return ON_BTN, FN_BG


def _refresh():
    expr = engine.expression
    if len(expr) > max_expr:
        expr = "..." + expr[-(max_expr - 3) :]
    expr_box.value = expr
    num = engine.display
    if len(num) > max_num:
        num = num[-max_num:]
    num_box.value = num
    num_box.fg = ERR_FG if engine.is_error else NUM_FG
    num_box.invalidate()


def _on_key(key):
    if not key:
        return
    # Map common keyboard characters onto engine keys.
    if key in ("\r", "\n"):
        key = "="
    elif key == "\x1b":
        key = "CE"
    elif key == "\x08":
        key = "BS"
    elif key == "c":
        key = "C"
    elif key == "s":
        key = "sqrt"
    elif key == " ":
        key = "+/-"
    try:
        engine.press(key)
    except ValueError:
        return
    _refresh()


buttons = []
for r, row in enumerate(BUTTON_ROWS):
    n = len(row)
    # Wide buttons on the last row (sqrt / %) each span half the width.
    cell_w = W // n if n < btn_cols else col_w
    for c, label in enumerate(row):
        fg, bg = _btn_colors(label)
        shown = "sqrt" if label == "sqrt" else label
        btn = pd.Button(
            button_box,
            label=shown,
            value=label,
            radius=radius,
            x=cell_w * c + pad // 2,
            y=row_h * r + pad // 2,
            w=cell_w - pad,
            h=row_h - pad,
            fg=fg,
            bg=bg,
            text_color=fg,
            text_height=btn_text,
            shadow=0,
        )
        btn.add_event_cb(pd.events.MOUSEBUTTONUP, lambda sender, e: _on_key(sender.value))
        buttons.append(btn)

screen.add_event_cb(pd.events.KEYDOWN, lambda sender, e: _on_key(getattr(e, "unicode", "") or ""))

_refresh()
screen.visible = True

# Canonical entry: pdwidgets wires input + rendering into the shared app at
# Display construction, and the app keeps itself alive past the end of this
# script — as a program or at an interactive REPL alike.