# deps: pygraphics
# gallery: binaries
# Loads the full bitmap into memory before blitting it to the display.
# Will raise a MemoryError on low memory boards such as RP2040.
# See bmp565_scroll_sprite.py for an example of streaming one line at
# a time instead of the full bitmap.
#
# Shows both blit styles: a full-window slice, then ``bmp[:]`` with a
# short pause between (same patterns formerly in bmp565_blit.py).
from board_config import display_drv
from pygraphics import BMP565, hline

try:
    from time import sleep_ms
except ImportError:
    from time import sleep

    def sleep_ms(milliseconds):
        sleep(milliseconds / 1000)


try:
    bmp = BMP565("examples/assets/warrior.bmp")
except MemoryError:
    raise MemoryError("this board doesn't have enough RAM to load the full image")

print(f"{bmp.width=}, {bmp.height=}, {bmp.bpp=}")

display_drv.fill(0x0)
display_drv.show()
display_drv.blit_rect(bmp[0 : bmp.width, 0 : bmp.height], 0, 0, bmp.width, bmp.height)
display_drv.show()
sleep_ms(1000)

display_drv.fill(0x0)
display_drv.show()
sleep_ms(250)

hline(bmp, 0, bmp.height // 2, bmp.width, 0xFFFF)
display_drv.blit_rect(bmp[:], 0, 0, bmp.width, bmp.height)
display_drv.show()
sleep_ms(1000)
