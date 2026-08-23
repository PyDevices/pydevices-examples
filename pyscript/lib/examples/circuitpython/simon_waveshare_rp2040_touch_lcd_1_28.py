"""Simon memory game for Waveshare RP2040-Touch-LCD-1.28 (CircuitPython)."""

import time
import random
import board
import busio
import digitalio
import displayio
import terminalio
from fourwire import FourWire
from adafruit_display_text import label
from gc9a01 import GC9A01
from cst816 import CST816

# Keep USB happy: settle before heavy SPI/I2C bring-up.
time.sleep(1.0)

displayio.release_displays()

# Sticky backlight (GPIO, not PWM).
_bl = digitalio.DigitalInOut(board.LCD_BL)
_bl.switch_to_output(value=True)

spi = busio.SPI(clock=board.LCD_CLK, MOSI=board.LCD_DIN)
display_bus = FourWire(
    spi,
    command=board.LCD_DC,
    chip_select=board.LCD_CS,
    reset=board.LCD_RST,
    baudrate=10_000_000,
)
display = GC9A01(
    display_bus,
    width=240,
    height=240,
    rotation=0,
    reverse_bytes_in_word=True,
)

i2c = busio.I2C(board.IMU_SCL, board.IMU_SDA, frequency=100_000)
touch = CST816(i2c, rst_pin=board.GP22)

# Colors (RGB565 tuple for displayio Palette / ColorConverter)
BLACK = 0x000000
WHITE = 0xFFFFFF
GREY = 0x808080
DIM = (0x006400, 0x800000, 0x808000, 0x000080)  # G R Y B
LIT = (0x00FF00, 0xFF0000, 0xFFFF00, 0x0000FF)

W = H = 240
CX = CY = 120
INNER_R = 34
GAP = 4
HALF_GAP = 2

# Pad rectangles as (x, y, w, h) — same L-shapes as MicroPython Simon.
_STRIP = INNER_R - HALF_GAP
PADS = (
    ((0, 0, CX - INNER_R, CY - HALF_GAP), (CX - INNER_R, 0, _STRIP, CY - INNER_R)),
    ((CX + INNER_R, 0, W - (CX + INNER_R), CY - HALF_GAP), (CX + HALF_GAP, 0, _STRIP, CY - INNER_R)),
    ((0, CY + HALF_GAP, CX - INNER_R, H - (CY + HALF_GAP)), (CX - INNER_R, CY + INNER_R, _STRIP, H - (CY + INNER_R))),
    ((CX + INNER_R, CY + HALF_GAP, W - (CX + INNER_R), H - (CY + HALF_GAP)), (CX + HALF_GAP, CY + INNER_R, _STRIP, H - (CY + INNER_R))),
)

INPUT_MS = 5.0
FLASH_MS = 0.28
GAP_MS = 0.08
MAX_LEN = 20

IDLE, SHOW, INPUT, FAIL = 0, 1, 2, 3

# Build displayio tree: bg + 8 pad rects + hub + labels
main = displayio.Group()
bg_bitmap = displayio.Bitmap(W, H, 1)
bg_palette = displayio.Palette(1)
bg_palette[0] = BLACK
main.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))

pad_grids = []
for i in range(4):
    pair = []
    for x, y, w, h in PADS[i]:
        bmp = displayio.Bitmap(max(w, 1), max(h, 1), 1)
        pal = displayio.Palette(1)
        pal[0] = DIM[i]
        tg = displayio.TileGrid(bmp, pixel_shader=pal, x=x, y=y)
        main.append(tg)
        pair.append(pal)
    pad_grids.append(pair)

hub_s = INNER_R * 2
hub_bmp = displayio.Bitmap(hub_s, hub_s, 1)
hub_pal = displayio.Palette(1)
hub_pal[0] = BLACK
main.append(displayio.TileGrid(hub_bmp, pixel_shader=hub_pal, x=CX - INNER_R, y=CY - INNER_R))

hub_line0 = label.Label(terminalio.FONT, text=" SIMON ", color=WHITE, anchor_point=(0.5, 0.5), anchored_position=(CX, CY - 6))
hub_line1 = label.Label(terminalio.FONT, text="  tap  ", color=GREY, anchor_point=(0.5, 0.5), anchored_position=(CX, CY + 8))
main.append(hub_line0)
main.append(hub_line1)

display.root_group = main

state = IDLE
sequence = []
step = 0
deadline = 0.0
busy = False
best = 0
_was_down = False


def _set_pad(i, lit=False):
    c = LIT[i] if lit else DIM[i]
    for pal in pad_grids[i]:
        pal[0] = c


def _hub(msg, sub=""):
    hub_line0.text = (" " + str(msg)[:5] + " ").center(7)
    hub_line1.text = (" " + str(sub)[:5] + " ").center(7)


def draw_board(hub_msg="SIMON", hub_sub="tap"):
    for i in range(4):
        _set_pad(i, False)
    _hub(hub_msg, hub_sub)


def flash(i):
    _set_pad(i, True)
    time.sleep(FLASH_MS)
    _set_pad(i, False)
    time.sleep(GAP_MS)


def hit_pad(x, y):
    dx = x - CX
    dy = y - CY
    if dx * dx + dy * dy < INNER_R * INNER_R:
        return -1
    if abs(dx) <= HALF_GAP or abs(dy) <= HALF_GAP:
        return -1
    if dy < 0:
        return 0 if dx < 0 else 1
    return 2 if dx < 0 else 3


def play_sequence():
    global state, step, deadline, busy
    busy = True
    state = SHOW
    score = len(sequence)
    _hub(str(score), "watch")
    time.sleep(0.25)
    for pad in sequence:
        flash(pad)
    step = 0
    deadline = time.monotonic() + INPUT_MS
    state = INPUT
    _hub(str(score), "go")
    busy = False


def new_game():
    global sequence, step
    sequence = [random.randint(0, 3)]
    step = 0
    draw_board(str(len(sequence)), "watch")
    play_sequence()


def fail():
    global state, busy, best
    busy = True
    state = FAIL
    score = max(0, len(sequence) - 1)
    if score > best:
        best = score
    for _ in range(2):
        for i in range(4):
            _set_pad(i, True)
        time.sleep(0.1)
        for i in range(4):
            _set_pad(i, False)
        time.sleep(0.06)
    draw_board("OVER", "b%d" % best)
    state = IDLE
    busy = False


def advance():
    global sequence, step, deadline, state, best
    step += 1
    deadline = time.monotonic() + INPUT_MS
    if step < len(sequence):
        _hub(str(len(sequence)), "%d/%d" % (step, len(sequence)))
        return
    if len(sequence) >= MAX_LEN:
        best = max(best, MAX_LEN)
        draw_board("WIN!", "b%d" % best)
        state = IDLE
        return
    sequence.append(random.randint(0, 3))
    play_sequence()


def on_tap(x, y):
    global busy
    if busy or state == SHOW:
        return
    pad = hit_pad(x, y)
    if state == IDLE:
        if pad >= 0 or (x - CX) * (x - CX) + (y - CY) * (y - CY) <= INNER_R * INNER_R:
            new_game()
        return
    if state != INPUT or pad < 0:
        return
    busy = True
    try:
        flash(pad)
        if pad != sequence[step]:
            fail()
            return
        advance()
    finally:
        if state != FAIL:
            busy = False


draw_board()
print("Simon ready")

while True:
    if state == INPUT and (not busy) and time.monotonic() > deadline:
        fail()
    pt = touch.get_point()
    if pt:
        if not _was_down:
            on_tap(pt[0], pt[1])
        _was_down = True
    else:
        _was_down = False
    time.sleep(0.02)
