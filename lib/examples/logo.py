# deps: pygraphics
"""
logo.py
=======

Draws the PyDevices bus mark using only pydevices-examples's own graphics primitives -- no SVG import or renderer needed.

It runs anywhere pydevices-examples runs, including microcontrollers.

The mark is the bus: one trunk, three taps, each ending in a pad. It is
drawn *grounded* -- the mark sits on the site's own background colour the
way it does on the website header, rather than inside a badge tile. The
tiled form is only used for platform icons (favicons, avatars), which is
not what a display is.

Every segment is a rounded rectangle, because that is exactly what a
stroked line with round caps is: the trunk and taps are 4 units wide with
a 2-unit radius, so they are drawn the same way the pads are.

Coordinates are lifted from assets/img/logo.svg's 64x64 viewBox (in the
dotgithub repo, which is the master copy) and scaled to whatever display
this runs on.
"""

from board_config import display_drv
from displaydev import color565
import pygraphics


# The mark's own bounding box inside the 64x64 viewBox, used to centre it
# on displays that are not square.
MARK_X0, MARK_Y0, MARK_X1, MARK_Y1 = 14.0, 9.0, 48.0, 53.5


def main():
    BG = color565(0x08, 0x0C, 0x10)  # site's dark background (--bg)
    MARK = color565(0x22, 0xC7, 0xE2)  # site's --accent

    pygraphics.fill(display_drv, BG)

    SIZE = min(display_drv.width, display_drv.height)
    SCALE = SIZE / 64
    # Centre the mark's bounding box rather than the viewBox: the mark is
    # taller than it is wide and does not sit dead centre in the 64x64 grid,
    # so centring the box is what actually looks centred.
    LEFT = round((display_drv.width - (MARK_X1 - MARK_X0) * SCALE) / 2 - MARK_X0 * SCALE)
    TOP = round((display_drv.height - (MARK_Y1 - MARK_Y0) * SCALE) / 2 - MARK_Y0 * SCALE)

    def s(v):
        return round(v * SCALE)

    def bar(x, y, w, h, r):
        """A rounded rect in viewBox units, placed on the display."""
        x0, y0 = LEFT + s(x), TOP + s(y)
        # Derive w/h from the difference of two rounded corners rather than
        # rounding each edge on its own, so segments that should meet stay
        # met instead of drifting apart by a pixel.
        x1, y1 = LEFT + s(x + w), TOP + s(y + h)
        pygraphics.round_rect(display_drv, x0, y0, x1 - x0, y1 - y0, max(1, s(r)), MARK, True)

    # Stroke geometry: a 4-unit line with round caps occupies a 4-unit band
    # that overhangs each endpoint by its 2-unit radius.
    STROKE, CAP = 4.0, 2.0

    # Trunk: x=19, y=20..49
    bar(19 - CAP, 20 - CAP, STROKE, (49 - 20) + STROKE, CAP)

    # Three taps: x=19..39, at y=25, 37, 49
    for tap_y in (25, 37, 49):
        bar(19 - CAP, tap_y - CAP, (39 - 19) + STROKE, STROKE, CAP)

    # Source pad at the head of the trunk
    bar(14, 9, 10, 10, 3)

    # Endpoint pads, one per tap
    for pad_y in (20.5, 32.5, 44.5):
        bar(39, pad_y, 9, 9, 2.5)


main()
display_drv.show()
