# deps: palettes, pygraphics
# utils: displaybuf
# gallery: binaries
"""
font_simpletest.py -- Simple test of the Font class.
inspired by Russ Hughes's hello.py

Cycles three rendering paths in succession (no env vars):

  string_blit  — off-screen string FrameBuffer + one blit_rect (opaque bg)
  per_pixel    — Font.text directly on display_drv (transparent, slowest bus)
  displaybuf   — full-screen DisplayBuffer + dirty show (utils)
"""

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from random import getrandbits
from pygraphics import Font, FrameBuffer, RGB565
from palettes import get_palette

MODES = ("string_blit", "per_pixel", "displaybuf")


def randint(a, b):
    # MicroPython on Windows ships a minimal random module: getrandbits and
    # seed only (randint needs MICROPY_PY_RANDOM_EXTRA_FUNCS, off on that port).
    span = b - a + 1
    if span <= 1:
        return a
    bits = 0
    n = span - 1
    while n:
        bits += 1
        n >>= 1
    return a + getrandbits(bits) % span


def _setup():
    pal = get_palette()
    write_text = "Hello!"
    text_len = len(write_text)
    directory = "examples/assets/"
    fonts = [
        Font(f"{directory}font_8x8.bin"),
        Font(f"{directory}font_8x14.bin"),
        Font(f"{directory}font_8x16.bin"),
    ]
    max_width = max([font.width for font in fonts])
    max_height = max([font.height for font in fonts])

    # mode_idx cycles after a full 4-rotation pedagogical block.
    st = {
        "mode_idx": 0,
        "mode": MODES[0],
        "canvas": display_drv,
        "bpp": display_drv.color_depth // 8,
        "rotation": 0,
        "count": 0,
        "iters_per_rot": 96,
        "rots_done": 0,
        "scale": 1,
        "col_max": 0,
        "row_max": 0,
    }

    def enter_mode(mode):
        st["mode"] = mode
        st["rotation"] = 0
        st["rots_done"] = 0
        st["iters_per_rot"] = 96 if mode == "string_blit" else 32
        st["count"] = st["iters_per_rot"]  # force start_rotation on next poll
        if mode == "displaybuf":
            from displaybuf import DisplayBuffer

            st["canvas"] = DisplayBuffer(display_drv)
        else:
            st["canvas"] = display_drv
        st["bpp"] = st["canvas"].color_depth // 8

    def write(font, string, x, y, fg_color, bg_color, scale):
        mode = st["mode"]
        canvas = st["canvas"]
        if mode == "string_blit":
            buffer_width = font.width * scale * len(string)
            buffer_height = font.height * scale
            buffer = bytearray(buffer_width * buffer_height * st["bpp"])
            fb = FrameBuffer(buffer, buffer_width, buffer_height, RGB565)
            fb.fill(bg_color)
            font.text(fb, string, 0, 0, fg_color, scale)
            display_drv.blit_rect(buffer, x, y, buffer_width, buffer_height)
            display_drv.show()
        elif mode == "per_pixel":
            font.text(display_drv, string, x, y, fg_color, scale)
            display_drv.show()
        else:
            dirty = font.text(canvas, string, x, y, fg_color, scale)
            canvas.show(dirty)
            display_drv.show()

    def start_rotation():
        canvas = st["canvas"]
        st["scale"] = st["rotation"] + 1
        canvas.rotation = st["rotation"] * 90
        width, height = canvas.width, canvas.height
        st["col_max"] = width - max_width * st["scale"] * text_len
        st["row_max"] = height - max_height * st["scale"]
        if st["col_max"] < 0 or st["row_max"] < 0:
            raise RuntimeError("This font is too big to display on this screen.")
        st["count"] = 0
        st["rotation"] = (st["rotation"] + 1) % 4
        st["rots_done"] += 1

    def poll():
        if st["rots_done"] >= 4 and st["count"] >= st["iters_per_rot"]:
            st["mode_idx"] = (st["mode_idx"] + 1) % len(MODES)
            enter_mode(MODES[st["mode_idx"]])
        if st["count"] >= st["iters_per_rot"]:
            start_rotation()
            return False
        write(
            fonts[randint(0, len(fonts) - 1)],
            write_text,
            randint(0, st["col_max"]),
            randint(0, st["row_max"]),
            pal[randint(0, len(pal) - 1)],
            pal[randint(0, len(pal) - 1)],
            st["scale"],
        )
        st["count"] += 1
        return False

    enter_mode(MODES[0])
    return poll


def main():
    poll = _setup()

    def _tick(_=None):
        poll()

    app.every(_tick, period=1, async_=app.timer_async)


main()