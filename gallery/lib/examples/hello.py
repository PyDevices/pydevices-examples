# deps: palettes
# utils: tft_config, tft_text
"""
hello.py
========

.. figure:: ../_static/hello.jpg
    :align: center

    Test for text_font_converter.

Writes "Hello!" in random colors at random locations on the Display.
https://www.youtube.com/watch?v=atBa0BYPAAc

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `st7789py`
    - `tft_config`
    - `vga2_bold_16x32`

"""

import board_config
import appdev

app = appdev.App(board_config)

from random import getrandbits

import tft_config
import tft_text
import vga2_bold_16x32 as font

palette = tft_config.palette

WORDS_PER_ROTATION = 100


def randint(a, b):
    # MicroPython on Windows ships a minimal random module: getrandbits and
    # seed only (randint needs MICROPY_PY_RANDOM_EXTRA_FUNCS, off on that port).
    # CircuitPython, MicroPython unix, and CPython can use random.randint instead.
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
    tft = tft_config.config(tft_config.WIDE)
    # count starts full so the first poll opens a fresh rotation before drawing.
    st = {"rotation": 0, "count": WORDS_PER_ROTATION, "col_max": 0, "row_max": 0}

    def start_rotation():
        tft.rotation = st["rotation"]
        tft.draw.fill(0)
        tft.show()
        st["col_max"] = tft.width - font.WIDTH * 5
        st["row_max"] = tft.height - font.HEIGHT
        if st["col_max"] < 0 or st["row_max"] < 0:
            raise RuntimeError("This font is too big to display on this screen.")
        st["count"] = 0
        st["rotation"] = (st["rotation"] + 1) % 4

    def poll():
        if st["count"] >= WORDS_PER_ROTATION:
            start_rotation()
            return False
        tft_text.text(
            tft,
            font,
            "Hello",
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