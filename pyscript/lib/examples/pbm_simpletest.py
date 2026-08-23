# deps: pygraphics
# utils: framebuf
# gallery: binaries
from board_config import display_drv
from pygraphics import FrameBuffer, RGB565, pbm_to_framebuffer


display_drv.fill(0xF800)
logo = pbm_to_framebuffer("examples/assets/micropython.pbm")

# Colorize mono → RGB565 via a 2-entry palette, then blit to the display.
buf = bytearray(logo.width * logo.height * 2)
fb = FrameBuffer(buf, logo.width, logo.height, RGB565)
palette = FrameBuffer(memoryview(bytearray(2 * 2)), 2, 1, RGB565)

# Set bits → white; unset bits stay 0 (used as chromakey below).
palette.pixel(0, 0, 0x0000)
palette.pixel(1, 0, 0xFFFF)
fb.fill(0x0000)
fb.blit(logo, 0, 0, -1, palette)

display_drv.blit_rect(buf, display_drv.width // 3, 0, logo.width, logo.height)
display_drv.blit_transparent(
    buf, display_drv.width // 3, display_drv.height // 2, logo.width, logo.height, 0x0
)

# Green / white on blue; transparent blit keys on the staging fill color 0x000F.
palette.pixel(0, 0, 0x0FF0)
palette.pixel(1, 0, 0xFFFF)
fb.fill(0x000F)
fb.blit(logo, 0, 0, -1, palette)

display_drv.blit_rect(buf, display_drv.width * 2 // 3, 0, logo.width, logo.height)
display_drv.blit_transparent(
    buf, display_drv.width * 2 // 3, display_drv.height // 2, logo.width, logo.height, 0x000F
)

display_drv.show()