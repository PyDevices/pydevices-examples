"""
Roku remote as input: every button the TV lets a channel see, drawn on the TV.

The TV shows a grid of tiles and a list of the remote's buttons. Arrows move
the cursor, OK paints the tile under it, and every press ticks its button off
the list, so you can see what your remote really delivers. Back clears the
grid. Home leaves the channel; Ctrl-C here ends the app.

Presses come through ``RokuDisplay.get_events()`` and appdev's ``HostEvents``
adapter, the same path an ``App(host_read=display.get_events)`` takes.

Usage::

    python roku_companion_remote.py 192.0.2.10

The PyDevices Companion channel must be sideloaded on the TV
(tools/roku_companion_app).
"""

import sys
import time

from utils.roku_companion import RokuCompanion, RokuDisplay, roku_host

from appdev.devices import HostEvents
import events
import keys
from pygraphics import RGB565, FrameBuffer

WIDTH = 480
HEIGHT = 270
COLS, ROWS = 8, 4
TILE = 28
GRID_X, GRID_Y = 16, 40

BG = 0x18C3
TILE_OFF = 0x39E7
CURSOR = 0xFFE0
PAINT = (0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F)
WHITE = 0xFFFF
DIM = 0x8410

# The buttons a channel can see, as (label, key code); see _REMOTE_KEYS in
# utils.roku_companion for how each is mapped.
BUTTONS = (
    ("Up", keys.K_UP),
    ("Down", keys.K_DOWN),
    ("Left", keys.K_LEFT),
    ("Right", keys.K_RIGHT),
    ("OK", keys.K_RETURN),
    ("Back", keys.K_AC_BACK),
    ("* Options", keys.K_MENU),
    ("Play/Pause", keys.K_AUDIOPLAY),
    ("Rewind", keys.K_AUDIOPREV),
    ("Fast fwd", keys.K_AUDIONEXT),
    ("Replay", keys.K_AC_REFRESH),
)
MOVES = {keys.K_UP: (0, -1), keys.K_DOWN: (0, 1), keys.K_LEFT: (-1, 0), keys.K_RIGHT: (1, 0)}


class RemoteTest:
    def __init__(self, disp):
        self.disp = disp
        self.fb = FrameBuffer(disp.framebuffers()[0], WIDTH, HEIGHT, RGB565)
        self.tiles = [[None] * COLS for _ in range(ROWS)]
        self.cx = self.cy = 0
        self.seen = set()
        self.unknown = []
        self.log = []
        self.presses = 0

    def handle(self, ev):
        down = ev.type == events.KEYDOWN
        self.log.append("%s %s" % (ev.name, "down" if down else "up"))
        self.log = self.log[-5:]
        if not down:
            return
        self.presses += 1
        if ev.key:
            self.seen.add(ev.key)
        elif ev.name not in self.unknown:
            self.unknown.append(ev.name)
        if ev.key in MOVES:
            dx, dy = MOVES[ev.key]
            self.cx = (self.cx + dx) % COLS
            self.cy = (self.cy + dy) % ROWS
        elif ev.key == keys.K_RETURN:
            colour = self.tiles[self.cy][self.cx]
            nxt = 0 if colour is None else (PAINT.index(colour) + 1) % (len(PAINT) + 1)
            self.tiles[self.cy][self.cx] = PAINT[nxt] if nxt < len(PAINT) else None
        elif ev.key == keys.K_AC_BACK:
            self.tiles = [[None] * COLS for _ in range(ROWS)]

    def draw(self):
        fb = self.fb
        fb.fill(BG)
        fb.text("Roku remote test - press every button", 16, 14, WHITE)
        for row in range(ROWS):
            for col in range(COLS):
                x, y = GRID_X + col * (TILE + 4), GRID_Y + row * (TILE + 4)
                if (col, row) == (self.cx, self.cy):
                    fb.fill_rect(x - 3, y - 3, TILE + 6, TILE + 6, CURSOR)
                fb.fill_rect(x, y, TILE, TILE, self.tiles[row][col] or TILE_OFF)
        fb.text("OK paints, Back clears", GRID_X, GRID_Y + ROWS * (TILE + 4) + 6, DIM)
        y = GRID_Y + ROWS * (TILE + 4) + 26
        fb.text("presses: %d" % self.presses, GRID_X, y, WHITE)
        for i, line in enumerate(self.log):
            fb.text(line, GRID_X, y + 14 + i * 11, DIM if i < len(self.log) - 1 else WHITE)
        bx = 290
        fb.text("Seen:", bx, 40, WHITE)
        for i, (label, code) in enumerate(BUTTONS):
            hit = code in self.seen
            fb.text(("[x] " if hit else "[ ] ") + label, bx, 56 + i * 13, WHITE if hit else DIM)
        for i, name in enumerate(self.unknown[:3]):
            fb.text("[?] " + name, bx, 56 + (len(BUTTONS) + i) * 13, CURSOR)
        self.disp.show()


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else roku_host()
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    disp = RokuDisplay(RokuCompanion(host), width=WIDTH, height=HEIGHT)
    remote = HostEvents(disp.get_events, disp)
    test = RemoteTest(disp)
    test.draw()
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            evs = remote.poll()
            for ev in evs:
                test.handle(ev)
            if evs:
                test.draw()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        disp.close()
    print("Buttons seen:", sorted(keys.keyname(k) for k in test.seen), "unknown:", test.unknown)


if __name__ == "__main__":
    main()
