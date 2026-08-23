# deps: palettes
# utils: tft_config
"""
feathers.py
===========
Modified by Brad Barnett from Russ Hughes's original to scroll vertically instead of horizontally
and to use palettes.wheel.WheelPalette for deeper colors from HSV instead of RGB.

.. figure:: ../_static/feathers.jpg
    :align: center

    Test hardware scrolling.

Smoothly scrolls mirrored rainbow colored random curves across the display.

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `palettes`
    - `tft_config`

"""

import board_config
import appdev

app = appdev.App(board_config)

import math
from random import getrandbits

import tft_config
from palettes.wheel import WheelPalette


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


def between(left, right, along):
    """returns a point along the curve from left to right"""
    dist = (1 - math.cos(along * math.pi)) / 2
    return left * (1 - dist) + right * dist


def _setup():
    tft = tft_config.config(tft_config.FEATHERS)

    if tft.requires_byteswap:
        needs_swap = tft.disable_auto_byteswap(True)
    else:
        needs_swap = False

    palette = WheelPalette(swapped=needs_swap, saturation=1.0)

    height = tft.height
    width = tft.width

    tfa = tft_config.TFA
    bfa = tft_config.BFA

    tft.vscrdef(tfa, height, bfa)
    tft.vscsad(0 + tfa)
    tft.draw.fill(palette.BLACK)
    tft.show()

    half = (width >> 1) - 1
    y_offsets = [i * (height // 8) - 1 for i in range(2, 9)]

    st = {
        "scroll": 0,
        "wheel": 0,
        "interval": 0,
        "increment": 0,
        "counter": 1,
        "current_x": 0,
        "last_x": 0,
    }

    def poll():
        if st["counter"] > st["interval"]:
            st["last_x"] = st["current_x"]
            st["current_x"] = randint(0, half)
            st["counter"] = 0
            st["interval"] = randint(10, 100)
            st["increment"] = 1 / st["interval"]

        scroll = st["scroll"]
        tft.draw.hline(0, scroll, width, palette.BLACK)
        tft.vscsad(scroll + tfa)

        tween = int(between(st["last_x"], st["current_x"], st["counter"] * st["increment"]))

        for i, y_offset in enumerate(y_offsets):
            tft.draw.pixel(
                half + tween, (scroll + y_offset) % height, palette[st["wheel"] + (i << 2)]
            )
            tft.draw.pixel(
                half - tween, (scroll + y_offset) % height, palette[st["wheel"] + (i << 2)]
            )

        tft.show()
        st["scroll"] = (scroll + 1) % height
        st["wheel"] = (st["wheel"] + 1) % 256
        st["counter"] += 1
        return False

    return poll


poll = _setup()


def _tick(_=None):
    poll()


app.every(_tick, period=1, async_=app.timer_async)