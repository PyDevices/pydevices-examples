# deps: palettes
# utils: tft_text, tft_config
"""
scroll.py
=========

.. figure:: ../_static/scroll.jpg
    :align: center

    Test for hardware scrolling.

Smoothly scrolls all font characters up the screen.
Only works with fonts with heights that are even multiples of the screen height,
(i.e. 8 or 16 pixels high)

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `st7789py`
    - `tft_config`
    - `vga2_bold_16x16`

"""

import board_config
import appdev

app = appdev.App(board_config)

import tft_text
import tft_config

palette = tft_config.palette
import vga2_bold_16x16 as font


def _setup():
    tft = tft_config.config(tft_config.SCROLL)
    last_line = tft.height - font.HEIGHT
    tfa = tft_config.TFA  # top free area when scrolling
    bfa = tft_config.BFA  # bottom free area when scrolling
    tft.vscrdef(tfa, tft.height - tfa - bfa, bfa)

    tft.draw.fill(palette.BLUE)
    tft.show()
    col = tft.width // 2 - 5 * font.WIDTH // 2
    st = {"scroll": 0, "character": 0}

    def poll():
        scroll = st["scroll"]
        tft.draw.fill_rect(0, scroll, tft.width, 1, palette.BLUE)

        if scroll % font.HEIGHT == 0:
            tft_text.text(
                tft,
                font,
                f"x{st['character']:02x} {chr(st['character'])}",
                col,
                (scroll + last_line) % tft.height,
                palette.WHITE,
                palette.BLUE,
            )
            st["character"] = st["character"] + 1 if st["character"] < 256 else 0

        tft.vscsad(scroll + tfa)
        tft.show()
        scroll += 1
        if scroll == tft.height:
            scroll = 0
        st["scroll"] = scroll
        return False

    return poll


poll = _setup()


def _tick(_=None):
    poll()


app.every(_tick, period=10, async_=app.timer_async)