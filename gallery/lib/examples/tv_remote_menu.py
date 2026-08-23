# deps: pygraphics
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
tv_remote_menu.py — 10-foot / remote-friendly menu for PyScript TV browsers.

Why large rows + D-pad only: webOS / Tizen (and Android TV web) are remote-first;
touch targets sized for phones are unusable from the sofa. Arrow keys move
focus; Enter selects; Escape / AC Back quits (same as appdev quit path).

Desktop keyboards stand in for remotes during development.
"""

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)

from displaydev import color565
import keys
from pygraphics import RGB565, Font, FrameBuffer

# Why tall rows: 10-foot UI — readable labels and large focus highlight.
ROW_H = 48
PAD = 16
TITLE_H = 40

BLACK = 0
INK = color565(0xF7, 0xF7, 0xF4)
CHROME = color565(0x3B, 0x3A, 0x33)
FOCUS = color565(0xF5, 0x4E, 0x00)
MUTED = color565(0xA0, 0x9C, 0x92)
SURFACE = color565(0x2A, 0x29, 0x26)

# Why these labels: stand-ins for TV app sections; keep short for large fonts.
ITEMS = (
    "Watch demos",
    "Settings",
    "About pydevices-examples",
    "Quit",
)

FONT = Font(height=16)
BPP = display_drv.color_depth // 8
_MAX_CHARS = max(len(s) for s in ITEMS) + 8
_TEXT_BUF = bytearray(_MAX_CHARS * FONT.width * FONT.height * BPP)

state = {"index": 0, "status": "Use arrows + Enter"}


def blit_text(s, x, y, fg, bg):
    w = len(s) * FONT.width
    h = FONT.height
    buf = memoryview(_TEXT_BUF)[: w * h * BPP]
    fb = FrameBuffer(buf, w, h, RGB565)
    fb.fill(bg)
    FONT.text(fb, s, 0, 0, fg)
    display_drv.blit_rect(buf, x, y, w, h)


def redraw():
    w = display_drv.width
    h = display_drv.height
    display_drv.fill(BLACK)
    display_drv.fill_rect(0, 0, w, TITLE_H, SURFACE)
    blit_text("TV remote menu", PAD, 12, INK, SURFACE)

    y = TITLE_H + PAD
    for i, label in enumerate(ITEMS):
        bg = FOCUS if i == state["index"] else CHROME
        fg = BLACK if i == state["index"] else INK
        display_drv.fill_rect(PAD, y, w - 2 * PAD, ROW_H - 4, bg)
        blit_text(label, PAD + 12, y + (ROW_H - 4 - FONT.height) // 2, fg, bg)
        y += ROW_H

    display_drv.fill_rect(0, h - 28, w, 28, SURFACE)
    blit_text(state["status"][:40], PAD, h - 22, MUTED, SURFACE)
    display_drv.show()


def on_key(e):
    # Why map AC_BACK like Escape: TV remotes / webOS Back should leave the app
    # the same way Android SDL Back becomes QUIT in HostEventsDevice.
    if e.key in (keys.K_ESCAPE, keys.K_AC_BACK):
        display_drv.quit()
        return
    if e.key == keys.K_UP:
        state["index"] = (state["index"] - 1) % len(ITEMS)
        state["status"] = ITEMS[state["index"]]
    elif e.key == keys.K_DOWN:
        state["index"] = (state["index"] + 1) % len(ITEMS)
        state["status"] = ITEMS[state["index"]]
    elif e.key in (keys.K_RETURN, keys.K_SPACE):
        choice = ITEMS[state["index"]]
        if choice == "Quit":
            display_drv.quit()
            return
        state["status"] = f"Selected: {choice}"
    else:
        return
    redraw()


redraw()
app.on(app.events.KEYDOWN, on_key)