# deps: palettes
# utils: tft_config, tft_write
"""
chango.py
=========

.. figure:: ../_static/chango.jpg
    :align: center

    Test for TrueType write_font_converter.

See the :ref:`write_font_converter.py<write_font_converter>` program in the utils directory.

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `st7789py`
    - `tft_config`
    - `chango_16`
    - `chango_32`
    - `chango_64`

"""

import gc
import sys

sys.path.insert(0, __file__.replace("\\", "/").rsplit("/", 1)[0])
import chango_16 as font_16
import chango_32 as font_32
import chango_64 as font_64
import board_config
import appdev

app = appdev.App(board_config)
import tft_config
import tft_write

palette = tft_config.palette

gc.collect()


def main():
    """main"""
    tft = tft_config.config(tft_config.WIDE)

    row = 0
    tft_write.write(tft, font_16, "abcdefghijklmnopqrst", 0, row, palette.RED)
    row += font_16.HEIGHT

    tft_write.write(tft, font_32, "abcdefghij", 0, row, palette.GREEN)
    row += font_32.HEIGHT

    tft_write.write(tft, font_64, "abcd", 0, row, palette.BLUE)
    row += font_64.HEIGHT

    tft.show()


main()