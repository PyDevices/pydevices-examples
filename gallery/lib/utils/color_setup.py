"""
color_setup.py - color setup for DisplayBuffer with displaydev (nano-gui bridge).

Fetches micropython-nano-gui into utils/gui/ when needed.

Usage:
    from color_setup import ssd
    <your code here>
"""

import sys

from board_config import display_drv
from displaybuf import DisplayBuffer as SSD

import pygraphics

# Peter Hinch's GUI modules import framebuf directly. Use the same FrameBuffer
# implementation as DisplayBuffer so Writer glyph buffers can be blitted to ssd.
sys.modules["framebuf"] = pygraphics

# SSD.RGB565 is supported by all implementations, so set it as the default format
# Micropython also supports SSD.GS4_HMSB and SSD.GS8
# format = SSD.GS4_HMSB  # 4-bit (16 item) lookup table of 16-bit RGB565 colors; w*h/2 buffer
# format = SSD.GS8  # 256 8-bit RGB332 colors; w*h buffer
format = SSD.RGB565  # all 65,536 16-bit RGB565 colors; w*h*2 buffer

ssd = SSD(display_drv, format)

# DisplayBuffer.show() blits to the driver texture; display_drv.show() presents
# the frame where needed and is a no-op on MCU BusDisplay.
_orig_show = ssd.show


def show(area=None):
    _orig_show(area)
    display_drv.show()


ssd.show = show

# After SSD exists: gui.core.colors imports SSD from this module.
# Best-effort: displaybuf-only callers may not need gui/; nano demos need it present.
from fetch_ph_gui import fetch_ph_gui  # noqa: E402

fetch_ph_gui("micropython-nano-gui")
