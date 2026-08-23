# deps: palettes
# utils: tft_config, tft_text
"""
fonts.py
========

.. figure:: ../_static/fonts.jpg
    :align: center

    Test text_font_converter.py

Pages through all characters of four fonts on the Display.
https://www.youtube.com/watch?v=2cnAhEucPD4

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `st7789py`
    - `tft_config`
    - `vga2_8x8`
    - `vga2_8x16`
    - `vga2_bold_16x16`
    - `vga2_bold_16x32`

"""

import board_config
import appdev

app = appdev.App(board_config)

from multimer import ticks_add, ticks_diff, ticks_ms

import tft_config
import tft_text
import vga2_8x8 as font1
import vga2_8x16 as font2
import vga2_bold_16x16 as font3
import vga2_bold_16x32 as font4

palette = tft_config.palette

PAGE_PAUSE_MS = 3000


def _setup():
    tft = tft_config.config(tft_config.WIDE)
    tft.vscrdef(0, tft.height, 0)
    fonts = (font1, font2, font3, font4)
    st = {"fi": -1, "font": None, "char": 0, "col": 0, "line": 0, "resume_at": None, "after": None}

    def new_font():
        st["fi"] = (st["fi"] + 1) % len(fonts)
        st["font"] = fonts[st["fi"]]
        tft.draw.fill(palette.BLUE)
        tft.show()
        st["char"] = st["font"].FIRST
        st["col"] = 0
        st["line"] = 0

    new_font()

    def poll():
        now = ticks_ms()
        if st["resume_at"] is not None:
            if ticks_diff(now, st["resume_at"]) < 0:
                return False
            st["resume_at"] = None
            action = st["after"]
            st["after"] = None
            if action == "next_font":
                new_font()
            elif action == "clear_page":
                tft.draw.fill(palette.BLUE)
                tft.show()
                st["line"] = 0
                st["col"] = 0
            return False

        font = st["font"]
        if st["char"] >= font.LAST:
            st["resume_at"] = ticks_add(now, PAGE_PAUSE_MS)
            st["after"] = "next_font"
            return False

        tft_text.text(tft, font, chr(st["char"]), st["col"], st["line"], palette.WHITE, palette.BLUE)
        tft.show()
        st["char"] += 1
        st["col"] += font.WIDTH
        if st["col"] > tft.width - font.WIDTH:
            st["col"] = 0
            st["line"] += font.HEIGHT
            if st["line"] > tft.height - font.HEIGHT:
                st["resume_at"] = ticks_add(now, PAGE_PAUSE_MS)
                st["after"] = "clear_page"
        return False

    return poll


def main():
    poll = _setup()
    # The app keeps itself alive after main() returns; on PyScript and Jupyter
    # (app.timer_async) the host's own loop drives it, so the browser main
    # thread stays live.
    def _tick(_=None):
        poll()

    app.every(_tick, period=1, async_=app.timer_async)
main()