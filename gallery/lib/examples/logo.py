# deps: pygraphics
"""
logo.py
=======

Draws the PyDevices logo using only pydevices-examples's own graphics primitives -- no SVG import or renderer needed.

Shapes are stacked the same way the original logo.py stacked circles: draw
a big filled shape, then a smaller filled shape of a different color on
top of it, and so on. That means this runs anywhere pydevices-examples runs,
including microcontrollers.

Coordinates are lifted from assets/img/logo.svg's 64x64 viewBox (in the
PyDevices.github.io repo) and scaled to whatever display this runs on.
"""

import math

from board_config import display_drv
from displaydev import color565
import pygraphics


def _channels(c):
    return (c >> 8) & 0xF8, (c >> 3) & 0xFC, (c << 3) & 0xF8


def _lerp_color(c1, c2, t):
    r1, g1, b1 = _channels(c1)
    r2, g2, b2 = _channels(c2)
    r, g, b = int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t)
    return (r & 0xF8) << 8 | (g & 0xFC) << 3 | (b & 0xF8) >> 3


def _gradient_round_rect(canvas, x, y, w, h, r, c1, c2):
    """
    Vertical-gradient fill of a rounded rect, top to bottom. Works out the
    same per-row inset round_rect()'s Bresenham corners produce (solved
    directly here, since only the footprint is needed) and blends the row's
    color with the same channel math pygraphics.gradient_rect() uses --
    gradient_rect() alone only knows about plain rectangles.
    """
    r = max(0, min(r, w // 2, h // 2))
    for j in range(h):
        if j < r:
            d = r - j
        elif j >= h - r:
            d = r - (h - 1 - j)
        else:
            d = 0
        inset = r - int(math.sqrt(max(0, r * r - d * d))) if d else 0
        t = j / (h - 1) if h > 1 else 0
        pygraphics.fill_rect(canvas, x + inset, y + j, w - 2 * inset, 1, _lerp_color(c1, c2, t))


def main():
    BG = color565(0x10, 0x0E, 0x0B)  # site's dark background (--bg)
    GRADIENT_TOP = color565(0xFF, 0x8A, 0x3D)  # #ff8a3d
    GRADIENT_BOTTOM = color565(0xF5, 0x4E, 0x00)  # #f54e00 / site's --accent
    WHITE = color565(0xFF, 0xF9, 0xF4)  # site's --accent-ink

    pygraphics.fill(display_drv, BG)

    SIZE = min(display_drv.width, display_drv.height)
    SCALE = SIZE / 64
    LEFT = (display_drv.width - SIZE) // 2
    TOP = (display_drv.height - SIZE) // 2

    def s(v):
        return round(v * SCALE)

    def pt(x, y):
        return LEFT + s(x), TOP + s(y)

    def rect(x, y, w, h):
        # Derive w/h from the difference of two rounded corners rather than
        # rounding w/h on their own, so nested rects (body vs. screen) keep
        # an even gap on every side instead of drifting apart from rounding
        # each edge independently.
        x0, y0 = pt(x, y)
        x1, y1 = pt(x + w, y + h)
        return x0, y0, x1 - x0, y1 - y0

    # Badge: big filled rounded square (x=1 y=1 w=62 h=62 r=16), gradient
    # top to bottom
    badge_x, badge_y, badge_w, badge_h = rect(1, 1, 62, 62)
    _gradient_round_rect(display_drv, badge_x, badge_y, badge_w, badge_h, s(16), GRADIENT_TOP, GRADIENT_BOTTOM)

    # Monitor body: white rounded rect stacked on top of the badge -- this
    # is the outer edge of the screen outline's 3.4-wide stroke
    # (x=14 y=16 w=36 h=24 r=3.5, offset by +/-1.7 on each side)
    body_x, body_y, body_w, body_h = rect(12.3, 14.3, 39.4, 27.4)
    pygraphics.round_rect(display_drv, body_x, body_y, body_w, body_h, s(5.2), WHITE, True)

    # Screen: rounded rect stacked on top of the body, sampling the badge's
    # own gradient at this y-range so it reads as "seeing through" the
    # monitor body to the badge behind it -- what's left uncovered around
    # it is the white bezel (the stroke's inner edge)
    screen_x, screen_y, screen_w, screen_h = rect(15.7, 17.7, 32.6, 20.6)
    t0 = (screen_y - badge_y) / badge_h
    t1 = (screen_y + screen_h - badge_y) / badge_h
    screen_c1 = _lerp_color(GRADIENT_TOP, GRADIENT_BOTTOM, t0)
    screen_c2 = _lerp_color(GRADIENT_TOP, GRADIENT_BOTTOM, t1)
    _gradient_round_rect(display_drv, screen_x, screen_y, screen_w, screen_h, s(1.8), screen_c1, screen_c2)

    # Stand: neck (x=32, y=40 to 48) then base bar (x=24 to 40, y=48), both
    # the same 3.4-wide stroke as the monitor outline
    stroke = max(1, s(3.4))
    neck_x, neck_y0 = pt(32, 40)
    _, neck_y1 = pt(32, 48)
    pygraphics.fill_rect(display_drv, neck_x - stroke // 2, neck_y0, stroke, neck_y1 - neck_y0, WHITE)

    base_x0, base_y = pt(24, 48)
    base_x1, _ = pt(40, 48)
    pygraphics.round_rect(
        display_drv,
        base_x0,
        base_y - stroke // 2,
        base_x1 - base_x0,
        stroke,
        stroke // 2,
        WHITE,
        True,
    )

    # 3 dots on the screen (cy=28, r=2.4)
    dot_r = max(1, s(2.4))
    for dot_x in (23.5, 32, 40.5):
        dx, dy = pt(dot_x, 28)
        pygraphics.circle(display_drv, dx, dy, dot_r, WHITE, True)


main()
display_drv.show()
