# deps: palettes
# utils: tft_text, tft_config
"""
tiny_hello.py
=============

.. figure:: ../_static/tiny_hello.jpg
    :align: center

    Test text_font_converter on small displays.

Writes "Hello!" in a tiny font in random colors at random locations on the Display.

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `st7789py`
    - `tft_config`
    - `vga1_8x8`

"""

import board_config
import appdev

app = appdev.App(board_config)

from random import getrandbits

from multimer import ticks_add, ticks_diff, ticks_ms
import tft_text
import tft_config

try:
    import pydevices_test_mode

    _iterations = 4 if pydevices_test_mode.ENABLED else 128
except ImportError:
    _iterations = 128

palette = tft_config.palette
import vga1_8x8 as font

tft = tft_config.config(tft_config.WIDE)


def randint(a, b):
    span = b - a + 1
    if span <= 1:
        return a
    bits = 0
    n = span - 1
    while n:
        bits += 1
        n >>= 1
    return a + getrandbits(bits) % span


def center(text, fg=palette.WHITE, bg=palette.BLACK):
    """
    Centers the given text on the display.
    """
    length = len(text)
    tft_text.text(
        tft,
        font,
        text,
        tft.width // 2 - length // 2 * font.WIDTH,
        tft.height // 2 - font.HEIGHT,
        fg,
        bg,
    )


def _setup():
    intro_colors = (palette.RED, palette.GREEN, palette.BLUE)
    st = {
        "phase": "intro",
        "intro_i": 0,
        "resume_at": None,
        "rotation": 0,
        "count": _iterations,
        "col_max": 0,
        "row_max": 0,
    }

    def show_intro(color):
        tft.draw.fill(color)
        tft.draw.rect(0, 0, tft.width, tft.height, palette.WHITE)
        center("Hello!", palette.WHITE, color)
        tft.show()

    def start_rotation():
        tft.rotation = st["rotation"]
        tft.draw.fill(0)
        tft.show()
        st["col_max"] = tft.width - font.WIDTH * 6
        st["row_max"] = tft.height - font.HEIGHT
        st["count"] = 0
        st["rotation"] = (st["rotation"] + 1) % 4

    def poll():
        now = ticks_ms()
        if st["phase"] == "intro":
            if st["resume_at"] is not None and ticks_diff(now, st["resume_at"]) < 0:
                return False
            if st["intro_i"] >= len(intro_colors):
                st["phase"] = "main"
                return False
            show_intro(intro_colors[st["intro_i"]])
            st["intro_i"] += 1
            st["resume_at"] = ticks_add(now, 1000)
            return False
        if st["count"] >= _iterations:
            start_rotation()
            return False
        tft_text.text(
            tft,
            font,
            "Hello!",
            randint(0, st["col_max"]),
            randint(0, st["row_max"]),
            palette.color565(getrandbits(8), getrandbits(8), getrandbits(8)),
            palette.color565(getrandbits(8), getrandbits(8), getrandbits(8)),
        )
        tft.show()
        st["count"] += 1
        return False

    return poll


def main():
    """
    The big show!
    """
    poll = _setup()
    # The app keeps itself alive after main() returns; on PyScript and Jupyter
    # (app.timer_async) the host's own loop drives it, so the browser main
    # thread stays live.
    def _tick(_=None):
        poll()

    app.every(_tick, period=1, async_=app.timer_async)
main()