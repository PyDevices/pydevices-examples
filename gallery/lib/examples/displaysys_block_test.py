"""displaysys_block_test.py"""

from random import getrandbits

try:
    from random import choice
except ImportError:

    def choice(sequence):
        return sequence[0]


from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
import gc
import time


try:
    import pydevices_test_mode  # type: ignore[import-not-found]

    TEST_DURATION_S = (
        pydevices_test_mode.DURATION_S if pydevices_test_mode.ENABLED else None
    )
except ImportError:
    TEST_DURATION_S = None


def randint(a, b):
    span = b - a + 1
    if span <= 1:
        return a
    bits = 0
    n = span - 1
    while n:
        bits += 1
        n >>= 1
    return a + getrandbits(bits) % span


gc.collect()
if display_drv.requires_byteswap:
    needs_swap = display_drv.disable_auto_byteswap(True)
else:
    needs_swap = False

block_size = 32
blocks = []
max_x = display_drv.width - block_size - 1
max_y = display_drv.height - block_size - 1

for pixel_color in [0x0000, 0xFFFF, 0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F]:
    pixel_bytes = (
        pixel_color.to_bytes(2, "big") if needs_swap else pixel_color.to_bytes(2, "little")
    )
    blocks.append(memoryview(bytearray(pixel_bytes * (block_size * block_size))))

print("Drawing blocks on display")
_count = 0
_start_time = time.time()


def _tick(_=None):
    global _count
    display_drv.blit_rect(
        choice(blocks),
        randint(0, max_x),
        randint(0, max_y),
        block_size,
        block_size,
    )
    _count += 1
    if _count % 2000 == 0:
        rate = _count / (time.time() - _start_time)
        print(f"blocks/sec: {rate:5.2f}")
    if TEST_DURATION_S is not None and time.time() - _start_time >= TEST_DURATION_S:
        app.request_quit()


app.every(_tick, period=1, async_=app.timer_async)