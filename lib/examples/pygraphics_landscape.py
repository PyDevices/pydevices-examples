# deps: pygraphics
"""
A landscape drawn with pygraphics: a banded sky, a sun, two snow-capped
mountains, a red house on the grass, and a caption.

The picture scales to whatever display the board config provides, from a
small OLED to a desktop window, and is drawn in horizontal bands so it fits
the memory of a small board: each band is drawn into a FrameBuffer and
copied to the display before the next one.
"""

from board_config import display_drv
import board_config
import appdev
import sys
import time

import pygraphics
from pygraphics import RGB565, FrameBuffer

app = appdev.App(board_config)

# The picture is designed at 320x240 and scaled to the display.
W, H = display_drv.width, display_drv.height
SX, SY = W / 320, H / 240
S = min(SX, SY)
BAND = max(1, min(H, 12800 // W))  # rows per band: about 25 KB of RGB565

# Colours go to the panel in its own byte order, so nothing is swapped later.
SWAP = getattr(display_drv, "requires_byteswap", False)
if SWAP:
    display_drv.disable_auto_byteswap(True)


def rgb(r, g, b):
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8) if SWAP else c


SKY = [rgb(10, 20, 90), rgb(20, 50, 140), rgb(40, 90, 190),
       rgb(70, 130, 220), rgb(110, 170, 240), rgb(160, 205, 250)]
SUN, SUN_RING = rgb(255, 220, 0), rgb(255, 150, 0)
ROCK, SNOW = rgb(110, 110, 130), rgb(250, 250, 250)
GRASS, GRASS_DARK = rgb(40, 160, 60), rgb(20, 110, 40)
WALL, ROOF, DOOR = rgb(220, 60, 50), rgb(120, 40, 30), rgb(80, 50, 20)
WHITE, BLACK = rgb(255, 255, 255), rgb(0, 0, 0)


def x(v):
    return int(v * SX)


def y(v, y0):
    return int(v * SY) - y0


def scene(fb, y0):
    """The whole picture, drawn y0 rows up; the band clips what falls outside."""
    for i, c in enumerate(SKY):
        fb.fill_rect(0, y(i * 27, y0), W, int(27 * SY) + 1, c)
    fb.circle(x(255), y(58, y0), int(34 * S), SUN_RING, True)
    fb.circle(x(255), y(58, y0), int(28 * S), SUN, True)
    fb.triangle(x(-20), y(170, y0), x(90), y(60, y0), x(200), y(170, y0), ROCK, True)
    fb.triangle(x(70), y(80, y0), x(90), y(60, y0), x(110), y(80, y0), SNOW, True)
    fb.triangle(x(110), y(170, y0), x(210), y(85, y0), x(330), y(170, y0), ROCK, True)
    fb.triangle(x(192), y(100, y0), x(210), y(85, y0), x(228), y(100, y0), SNOW, True)
    fb.fill_rect(0, y(162, y0), W, H - int(162 * SY), GRASS)
    fb.fill_rect(0, y(162, y0), W, max(1, int(4 * SY)), GRASS_DARK)
    fb.fill_rect(x(220), y(160, y0), x(70), int(50 * SY), WALL)
    fb.triangle(x(212), y(160, y0), x(255), y(126, y0), x(298), y(160, y0), ROOF, True)
    fb.fill_rect(x(248), y(182, y0), max(1, x(14)), int(28 * SY), DOOR)
    if W >= 160:  # captions need room; a tiny display gets the picture alone
        fb.round_rect(8, 8 - y0, 136, 26, 6, BLACK, True)
        fb.text16("pygraphics", 16, 13 - y0, WHITE)
        fb.text(sys.implementation.name, 10, H - 24 - y0, WHITE)
        fb.text("pygraphics " + pygraphics.implementation(), 10, H - 12 - y0, WHITE)
    fb.rect(0, -y0, W, H, WHITE)


def draw():
    buf = bytearray(W * BAND * 2)
    fb = FrameBuffer(buf, W, BAND, RGB565)
    t0 = time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)
    for y0 in range(0, H, BAND):
        rows = min(BAND, H - y0)
        scene(fb, y0)
        display_drv.blit_rect(memoryview(buf)[: W * rows * 2], 0, y0, W, rows)
    display_drv.show()
    t1 = time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)
    print("landscape %dx%d drawn in %d ms" % (W, H, t1 - t0))


draw()
app.run()
