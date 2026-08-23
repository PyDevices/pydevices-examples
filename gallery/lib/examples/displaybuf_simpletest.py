# deps: pygraphics
# utils: color_setup
"""
displaybuf_simpletest.py - Simple test program for displaybuf.py
"""

from color_setup import ssd
from array import array  # for defining a polygon


FONT_WIDTH = 8

# Define colors (max 16 colors if using lookup tables / GS4_HMSB mode)
# Note:  ssd.color and ssd.colors_registered should not be used with Nano-GUI or
# Micro-GUI because those packages have their own mechanisms for managing colors.
WHITE = ssd.color(255, 255, 255)
RED = ssd.color(255, 0, 0)
GREEN = ssd.color(0, 255, 0)
BLUE = ssd.color(0, 0, 255)
CYAN = ssd.color(0, 255, 255)
MAGENTA = ssd.color(255, 0, 255)
YELLOW = ssd.color(255, 255, 0)
BLACK = ssd.color(0, 0, 0)
LIGHT_GREY = ssd.color(192, 192, 192)
GREY = ssd.color(96, 96, 96)
DARK_GREY = ssd.color(64, 64, 64)
GREY = ssd.color(128, 128, 128, GREY)  # Example of how to redefine a color in the lookup table
if ssd.colors_registered:  # Will be 0 if not using lookup tables / GS4_HMSB mode.
    print(f"{ssd.colors_registered} colors registered.")


# Main loop
def main(scroll=False, animate=False, text1="displaybuf", text2="simpletest"):
    WIDTH = ssd.width
    HEIGHT = ssd.height
    poly = array("h", [0, 0, WIDTH // 2, -HEIGHT // 4, WIDTH - 1, 0])
    y_range = range(HEIGHT - 1, -1, -1) if animate else [HEIGHT - 1]
    for y in y_range:
        ssd.fill(BLACK)
        ssd.poly(0, y, poly, YELLOW, True)
        ssd.fill_rect(WIDTH // 6, HEIGHT // 3, WIDTH * 2 // 3, HEIGHT // 3, GREY)
        ssd.line(0, 0, WIDTH - 1, HEIGHT - 1, GREEN)
        ssd.rect(0, 0, 15, 15, RED, True)
        ssd.rect(WIDTH - 15, HEIGHT - 15, 15, 15, BLUE, True)
        ssd.hline(WIDTH // 8, HEIGHT // 2, WIDTH * 3 // 4, MAGENTA)
        ssd.vline(WIDTH // 2, HEIGHT // 4, HEIGHT // 2, CYAN)
        ssd.pixel(WIDTH // 2, HEIGHT * 1 // 8, WHITE)
        ssd.ellipse(WIDTH // 2, HEIGHT // 2, WIDTH // 4, HEIGHT // 8, BLACK, True, 0b1111)
        ssd.text(text1, (WIDTH - FONT_WIDTH * len(text1)) // 2, HEIGHT // 2 - 8, WHITE)
        ssd.text(text2, (WIDTH - FONT_WIDTH * len(text2)) // 2, HEIGHT // 2, WHITE)
        ssd.show()

    ssd.hline(0, 0, WIDTH, BLACK)
    ssd.vline(0, 0, HEIGHT, BLACK)

    scroll_range = range(min(WIDTH, HEIGHT)) if scroll else []
    for _ in scroll_range:
        ssd.scroll(1, 1)
        ssd.show()


main()
