# deps: palettes, pygraphics
"""
Simple test example to demonstrate the use of pygraphics.
"""

from board_config import display_drv
from array import array  # for defining a polygon
from palettes import get_palette
import pygraphics


# If byte swapping is required and the display bus is capable of having byte swapping disabled,
# disable it and set a flag so we can swap the color bytes as they are created.
if display_drv.requires_byteswap:
    needs_swap = display_drv.disable_auto_byteswap(True)
else:
    needs_swap = False

WIDTH = display_drv.width
HEIGHT = display_drv.height
FONT_WIDTH = 8

# Define color palette
pal = get_palette(swapped=needs_swap)

# Define objects
triangle = array("h", [0, 0, WIDTH // 2, -HEIGHT // 4, WIDTH - 1, 0])


# Main loop
def main(animate=False, text1="Shapes", text2="simpletest", poly=triangle):
    y_range = range(HEIGHT - 1, -1, -1) if animate else [HEIGHT - 1]
    for y in y_range:
        pygraphics.fill(display_drv, pal.BLACK)
        pygraphics.poly(display_drv, 0, y, poly, pal.YELLOW, True)
        pygraphics.fill_rect(
            display_drv,
            WIDTH // 6,
            HEIGHT // 3,
            WIDTH * 2 // 3,
            HEIGHT // 3,
            pal.GREY,
        )
        pygraphics.line(display_drv, 0, 0, WIDTH - 1, HEIGHT - 1, pal.GREEN)
        pygraphics.rect(display_drv, 0, 0, 15, 15, pal.RED, True)
        pygraphics.rect(display_drv, WIDTH - 15, HEIGHT - 15, 15, 15, pal.BLUE, True)
        pygraphics.hline(display_drv, WIDTH // 8, HEIGHT // 2, WIDTH * 3 // 4, pal.MAGENTA)
        pygraphics.vline(display_drv, WIDTH // 2, HEIGHT // 4, HEIGHT // 2, pal.CYAN)
        pygraphics.pixel(display_drv, WIDTH // 2, HEIGHT * 1 // 8, pal.WHITE)
        pygraphics.ellipse(
            display_drv,
            WIDTH // 2,
            HEIGHT // 2,
            WIDTH // 4,
            HEIGHT // 8,
            pal.BLACK,
            True,
            0b1111,
        )
        pygraphics.text(
            display_drv, text1, (WIDTH - FONT_WIDTH * len(text1)) // 2, HEIGHT // 2 - 8, pal.WHITE
        )
        pygraphics.text(
            display_drv, text2, (WIDTH - FONT_WIDTH * len(text2)) // 2, HEIGHT // 2, pal.WHITE
        )

    pygraphics.hline(display_drv, 0, 0, WIDTH, pal.BLACK)
    pygraphics.vline(display_drv, 0, 0, HEIGHT, pal.BLACK)


launch = lambda: main(animate=False)  # noqa: E731

main()
display_drv.show()
