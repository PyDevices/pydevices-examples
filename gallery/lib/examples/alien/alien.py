# deps: palettes
# utils: tft_config, tft_bitmap
"""
alien.py
=========

.. figure:: ../_static/alien.jpg
    :align: center

    Bounce a bitmap of an alien around the display.

The alien_bitmap module was created using the :ref:`image_converter.py<image_converter>` utility.

.. literalinclude:: ../../../examples/alien/make_alien_bitmap.sh

.. note:: This example requires the following modules:

  .. hlist::
     :columns: 3

     - `st7789py`
     - `tft_config`
     - `alien_bitmap`

The alien.png PNG file is from the Erik Flowers Weather Icons available from
https://github.com/erikflowers/weather-icons and is licensed under SIL OFL 1.1
(http://scripts.sil.org/OFL).

"""

import board_config
import appdev

app = appdev.App(board_config)

import tft_config
import tft_bitmap

palette = tft_config.palette
import sys

sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import alien_bitmap as alien

SPEED_X = 3
SPEED_Y = 2
TICKS = 100


def main():
    """
    Runs the main loop for the bounce animation.
    """

    tft = tft_config.config(tft_config.WIDE)
    width, height = tft.width, tft.height
    st = {
        "col": width // 2 - alien.WIDTH // 2,
        "row": height // 2 - alien.HEIGHT // 2,
        "xd": SPEED_X,
        "yd": SPEED_Y,
    }
    st["last_col"], st["old_row"] = st["col"], st["row"]

    def _tick(_=None):
        # Do not call app.poll() from on_tick: sync backends (librt/sdl2)
        # re-enter the timer path and hang. Auto-service handles QUIT.
        if app.quit_requested if app else False:
            return
        tft.draw.fill_rect(st["last_col"], st["old_row"], alien.WIDTH, alien.HEIGHT, 0)
        # Move and clamp *before* blit — PSDisplay blit_rect rejects OOB (and
        # reversing after the step can leave col/row negative for one frame).
        col = st["col"] + st["xd"]
        row = st["row"] + st["yd"]
        max_col = width - alien.WIDTH
        max_row = height - alien.HEIGHT
        if col <= 0:
            col = 0
            st["xd"] = abs(st["xd"])
        elif col >= max_col:
            col = max_col
            st["xd"] = -abs(st["xd"])
        if row <= 0:
            row = 0
            st["yd"] = abs(st["yd"])
        elif row >= max_row:
            row = max_row
            st["yd"] = -abs(st["yd"])
        st["col"], st["row"] = col, row
        tft_bitmap.bitmap(tft, alien, col, row)
        tft.show()
        st["last_col"], st["old_row"] = col, row

    app.every(_tick, period=10, async_=app.timer_async)
main()