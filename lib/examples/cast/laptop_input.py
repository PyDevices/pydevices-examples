# The laptop drives the P4 over the cast: mouse and keyboard reports come back
# over UIBC, become touch and key events through the board's own touch_read and
# keypad_read and appdev's ordinary Touch and Keypad adapters, and the scene
# draws what it sees: a cursor, a dot per click, the last keys typed. The panel
# and the cast show the same thing. The stream is the castif C task (core 0);
# Python only polls the adapters and draws, stepped from the session loop.
#
#   import cast.laptop_input
#
# Set SINK to the laptop's address and open its Wireless Display app first
# (Windows: Settings > System > Projecting to this PC).
import gc
import framebuf
import board_config
from board_config import fb, display_drv
import events
from appdev.devices import Touch, Keypad
from micecast import Session
from castfast import CastifStreamer, make_caster
from uibcinput import UibcInput

from _common import log, wifi_up

SINK = "192.168.1.143"    # the laptop's IP address
SECONDS = 75

wifi_up()

W, H = display_drv.width, display_drv.height
uibc = UibcInput(W, H).install(board_config)      # an app cannot tell laptop from panel
touch = Touch(board_config.touch_read, display=display_drv)   # the adapters an appdev App would build
keypad = Keypad(board_config.keypad_read)
dots = []
typed = []


def on_down(event, *a):
    x, y = event.pos[0], event.pos[1]
    dots.append((x, y))
    log("click at", x, y, "(button %d)" % event.button)


def on_key(event, *a):
    typed.append(event.key)
    log("key", event.key, repr(chr(event.key)) if 32 <= event.key < 127 else event.name)

BG = 0x0841
display_drv.fill(BG)
for i in range(0, W, 90):
    display_drv.fill_rect(i, 0, 1, H, 0x2945)
    display_drv.fill_rect(0, i, W, 1, 0x2945)


def rect(x, y, w, h, color):
    """fill_rect clipped to the panel, then only those rows to the glass.

    This DSI panel shows the framebuffer only on a refresh, and a whole-frame
    refresh (a 1 MB cache write-back) flashes the glass white; syncing the few
    rows that changed does not."""
    x0 = max(x, 0); y0 = max(y, 0)
    x1 = min(x + w, W); y1 = min(y + h, H)
    if x1 > x0 and y1 > y0:
        display_drv.fill_rect(x0, y0, x1 - x0, y1 - y0, color)
        display_drv.flush_rect(x0, y0, x1 - x0, y1 - y0)


def big_text(s, x, y, scale, color):
    tmp = framebuf.FrameBuffer(bytearray(8 * 8 * 2 * len(s)), 8 * len(s), 8, framebuf.RGB565)
    tmp.fill(0)
    tmp.text(s, 0, 0, 0xFFFF)
    for j in range(8):
        for i in range(8 * len(s)):
            if tmp.pixel(i, j):
                display_drv.fill_rect(x + i * scale, y + j * scale, scale, scale, color)


big_text("laptop drives P4", 40, 30, 4, 0xFFE0)
display_drv.show()      # the DSI panel samples the buffer only on refresh: nothing reaches the glass without this


class Scene:
    def __init__(self, cast=None):
        self.last = None
        self.n = 0
        self.shown_keys = 0
        self.shown_dots = 0
        self.cast = cast

    def step(self):
        for ev in touch.poll():          # devices to events, as an App would
            if ev.type == events.MOUSEBUTTONDOWN:
                on_down(ev)
        for ev in keypad.poll():
            if ev.type == events.KEYDOWN:
                on_key(ev)
        x, y = uibc.cx, uibc.cy
        changed = self.last != (x, y) or len(dots) != self.shown_dots or len(typed) != self.shown_keys
        if self.last and self.last != (x, y):
            lx, ly = self.last
            rect(lx - 12, ly - 1, 25, 3, BG)
            rect(lx - 1, ly - 12, 3, 25, BG)
        if len(dots) != self.shown_dots:
            self.shown_dots = len(dots)
            for dx, dy in dots[-64:]:
                rect(dx - 6, dy - 6, 12, 12, 0xF800)
        if self.last != (x, y):
            rect(x - 12, y - 1, 25, 3, 0x07FF)
            rect(x - 1, y - 12, 3, 25, 0x07FF)
            self.last = (x, y)
        if len(typed) != self.shown_keys:
            self.shown_keys = len(typed)
            rect(40, H - 90, W - 80, 60, BG)
            text = "".join(chr(k) if 32 <= k < 127 else "#" for k in typed[-16:])
            big_text(text or "-", 40, H - 80, 5, 0x07E0)
            display_drv.flush_rect(40, H - 90, W - 80, 60)
        if changed and self.cast:
            self.cast.mark_dirty()       # beat the sampled hash: a 3-pixel cursor is easy to miss
        self.n += 1


cast = make_caster(W, H, fps=30, bitrate=3_000_000)


def make(dst_ip, dst_port, server_port):
    return CastifStreamer(cast, fb, dst_ip, dst_port, server_port, SECONDS, log, scene=Scene(cast))


gc.collect()
s = Session(SINK, log=log, on_input=uibc.feed)
s.hidc_caps = "Keyboard/USB, Mouse/USB, MultiTouch/USB, Gesture/USB, RemoteControl/USB"
try:
    result = s.run(make, seconds=SECONDS + 15, idle_after_done=2)
    log("result:", result, "reports", uibc.reports, "moves", uibc.moved, "clicks", len(dots), "keys", len(typed), "cursor", uibc.cx, uibc.cy)
except Exception as e:
    log("EXC", repr(e))
finally:
    cast.close()
