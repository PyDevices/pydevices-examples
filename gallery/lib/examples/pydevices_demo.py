# gallery: featured
# deps: pygraphics
"""
pydevices_demo.py — flagship board_config demo: clicks, rotation, scrolling.

Setup + callbacks; the app runs itself. Uses only published product modules
(board_config, graphics, multimer, appdev).
"""

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)

from displaydev import color565
from pygraphics import RGB565, Area, Font, FrameBuffer

TOP, BOT = 36, 20
ROW, ACCENT = 20, 4

# Cursor palette — dark default (black canvas, cream text, orange accent)
BLACK = 0
INK = color565(0xF7, 0xF7, 0xF4)
CHROME = color565(0x3B, 0x3A, 0x33)
SURFACE = color565(0x2A, 0x29, 0x26)
MUTED = color565(0xA0, 0x9C, 0x92)
ORANGE = color565(0xF5, 0x4E, 0x00)
ROW_A = color565(0x1A, 0x19, 0x16)
ROW_B = color565(0x12, 0x11, 0x0F)
INK_DARK = color565(0x26, 0x25, 0x1E)

# AI timeline pastels + brand orange/gold (Color button cycles these)
ACCENTS = (
    ORANGE,
    color565(0xDF, 0xA8, 0x8F),
    color565(0x9F, 0xC9, 0xA2),
    color565(0x9F, 0xBB, 0xE0),
    color565(0xC0, 0xA8, 0xDD),
    color565(0xC0, 0x85, 0x32),
)

TIPS = (
    "Welcome to pydevices-examples!",
    "Runs on MCU & desktop.",
    "Tap Rotate to turn",
    "the screen around.",
    "Tap Color for a new",
    "accent on these notes.",
    "This panel scrolls on",
    "its own -- just watch.",
    "Clicks come from touch",
    "or the mouse.",
    "Display: board_config",
    "Events: appdev",
    "Timers: app.on_tick",
)

state = {"rotation": 0, "scroll": 0, "color_i": 0}
rotate_btn = color_btn = None
_scroll_paused = False

FONT = Font(height=16)
BPP = display_drv.color_depth // 8
_MAX_CHARS = max(len(s) for s in TIPS)
_TEXT_BUF = bytearray(_MAX_CHARS * FONT.width * FONT.height * BPP)


def blit_text(s, x, y, fg, bg):
    w = len(s) * FONT.width
    h = FONT.height
    buf = memoryview(_TEXT_BUF)[: w * h * BPP]
    fb = FrameBuffer(buf, w, h, RGB565)
    fb.fill(bg)
    FONT.text(fb, s, 0, 0, fg)
    display_drv.blit_rect(buf, x, y, w, h)


def label_color(bg):
    return INK if bg == ORANGE else INK_DARK


def scroll_height():
    vsa = display_drv.vsa
    return vsa if vsa else 1


def pause_scroll():
    global _scroll_paused
    _scroll_paused = True


def resume_scroll():
    global _scroll_paused
    _scroll_paused = False


def setup_scroll():
    display_drv.set_vscroll(TOP, BOT)


def redraw():
    global rotate_btn, color_btn
    w = display_drv.width
    h = display_drv.height
    saved_scroll = state["scroll"]
    accent = ACCENTS[state["color_i"]]
    display_drv.vscroll = 0
    display_drv.fill(BLACK)

    half = w // 2 - 6
    rotate_btn = Area(display_drv.fill_rect(4, 4, half, TOP - 8, CHROME))
    color_btn = Area(display_drv.fill_rect(w // 2 + 2, 4, half, TOP - 8, accent))
    blit_text("Rotate", 12, 12, INK, CHROME)
    blit_text("Color", w // 2 + 12, 12, label_color(accent), accent)

    y = TOP
    for i, msg in enumerate(TIPS):
        bg = ROW_A if i % 2 else ROW_B
        display_drv.fill_rect(0, y, w, ROW, bg)
        display_drv.fill_rect(0, y, ACCENT, ROW, accent)
        blit_text(msg, ACCENT + 6, y + 4, INK, bg)
        y += ROW

    display_drv.fill_rect(0, h - BOT, w, BOT, SURFACE)
    blit_text(f"rot {state['rotation']}", 4, h - BOT + 4, MUTED, SURFACE)
    display_drv.vscroll = saved_scroll
    display_drv.show()


def _scroll_tick(_=None):
    if _scroll_paused:
        return
    state["scroll"] = (state["scroll"] + 1) % scroll_height()
    display_drv.vscroll = state["scroll"]


def _on_click(e):
    if rotate_btn is not None and rotate_btn.contains(e.pos):
        pause_scroll()
        state["rotation"] = (state["rotation"] + 90) % 360
        state["scroll"] = 0
        display_drv.rotation = state["rotation"]
        setup_scroll()
        redraw()
        resume_scroll()
    elif color_btn is not None and color_btn.contains(e.pos):
        pause_scroll()
        state["color_i"] = (state["color_i"] + 1) % len(ACCENTS)
        redraw()
        resume_scroll()


setup_scroll()
redraw()
app.every(_scroll_tick, period=40, async_=app.timer_async)
app.on(app.events.MOUSEBUTTONDOWN, _on_click)