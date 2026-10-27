# deps: pygraphics
"""
logo.py
=======

Draws the PyDevices mark using only pygraphics primitives -- no SVG import or renderer needed.

It runs anywhere pydevices-examples runs, including microcontrollers.

The mark is a square stone cut in two rows of facets, lit from the top left,
with a 2x4 pin header in its table. Every shape is a filled polygon, so it is
drawn here exactly the way the SVG describes it.

Coordinates are lifted from assets/img/logo.svg's 64x64 viewBox (in the
dotgithub repo, which is the master copy) and scaled to whatever display
this runs on. The ground is the site's dark background, which also shows
through the table the way it does on the website header.
"""

from array import array
from board_config import display_drv
from displaydev import color565
import pygraphics


# The square's corner at each ring, inset from the 64x64 viewBox's edge:
# the outer edge, the girdle between the two rows, and the table.
RINGS = (1.28, 8.71, 16.64)

# The 2x4 pin header in the table: four columns, two rows, square pins.
PIN_XS = (18.34, 25.69, 33.05, 40.41)
PIN_YS = (25.34, 33.40)
PIN = 5.26


def main():
    BG = color565(0x0B, 0x2A, 0x4A)  # site's dark background (--bg)
    HI = color565(0xE7, 0xED, 0xF2)  # facets facing the light
    LO = color565(0x72, 0x93, 0xB1)  # facets facing away
    PINS = color565(0x7B, 0xB6, 0xE0)

    pygraphics.fill(display_drv, BG)

    # The mark is square; fit it to the shorter side and centre it.
    MARGIN = 0.86  # fraction of the shorter side the mark may occupy
    SCALE = min(display_drv.width, display_drv.height) * MARGIN / 64
    LEFT = round((display_drv.width - 64 * SCALE) / 2)
    TOP = round((display_drv.height - 64 * SCALE) / 2)

    def shape(points, c):
        """A filled polygon in viewBox units, placed on the display."""
        coords = array("h", [])
        for x, y in points:
            coords.append(round(x * SCALE))
            coords.append(round(y * SCALE))
        pygraphics.poly(display_drv, LEFT, TOP, coords, c, True)

    def corners(a):
        b = 64 - a
        return ((a, a), (b, a), (b, b), (a, b))

    # Two rows of four trapezoids, one per side of the square. In the outer
    # row the top and left faces catch the light; the inner row bevels down
    # into the table, so it faces the other way.
    for row in range(2):
        outer, inner = corners(RINGS[row]), corners(RINGS[row + 1])
        for side in range(4):
            nxt = (side + 1) % 4
            lit = side in (0, 3)  # top, left
            if row == 1:
                lit = not lit
            shape((outer[side], outer[nxt], inner[nxt], inner[side]), HI if lit else LO)

    for y in PIN_YS:
        for x in PIN_XS:
            shape(((x, y), (x + PIN, y), (x + PIN, y + PIN), (x, y + PIN)), PINS)


main()
display_drv.show()
