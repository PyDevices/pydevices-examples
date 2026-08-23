import os
import sys

from board_config import display_drv
from palettes import get_palette
import tft_text

from pygraphics import Draw

sep = os.sep if hasattr(os, "sep") else "/"  # PyScipt doesn't have os.sep

if sys.implementation.name == "esp32":
    from machine import freq

    freq(240_000_000)

BUFFERED = False

if BUFFERED:
    from displaybuf import DisplayBuffer

    from multimer import auto as timer


font_dir = sep.join(tft_text.__file__.split(sep)[:-1]) + sep + "fonts"
sys.path.append(font_dir)

TFA = 0
BFA = 0

if display_drv.height > display_drv.width:
    TALL = display_drv.rotation
    WIDE = display_drv.rotation + 90
else:
    WIDE = display_drv.rotation
    TALL = display_drv.rotation + 90

SCROLL = TALL  # orientation for scroll.py
FEATHERS = TALL  # orientation for feathers.py


palette = get_palette()


def deinit(display_drv, display_off=False):
    display_drv.deinit()
    if display_off:
        display_drv.brightness = 0


def config(rotation=None, buffer_size=0, options=0):
    if rotation is not None:
        display_drv.rotation = rotation
    if BUFFERED:
        display = DisplayBuffer(display_drv)
        _orig_show = display.show

        def show(area=None):
            _orig_show(area)
            display_drv.show()

        display.show = show
        display.draw = display
        tim = timer.Timer()
        tim.init(
            mode=timer.Timer.PERIODIC,
            period=33,
            callback=lambda t: display.show(),
        )
        return display
    display_drv.draw = Draw(display_drv)
    return display_drv
