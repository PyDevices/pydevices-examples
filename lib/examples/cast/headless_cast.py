# headless_cast.py -- a P4 with no screen of its own casts a picture it draws
# in memory: a clock, its uptime and a moving bar, to a Roku TV or a Windows
# laptop's Wireless Display app.
#
#   import cast.headless_cast
#
# Nothing here touches a display or board_config: the "screen" is a bytearray
# the P4 draws into with framebuf, and castif encodes it on the P4's hardware
# H.264 encoder (the firmware needs castif and h264enc, as in any `all` build).
# Only the ESP32-P4 has that encoder, so this is a P4 example.
#
# Set SINK to the TV's or the laptop's address and KIND to match. A Roku needs
# Screen mirroring on; a laptop needs its Wireless Display app open (Windows:
# Settings > System > Projecting to this PC).
import time

import framebuf

import castfast
from _common import log, wifi_up

SINK = "192.168.1.129"    # your Roku's or laptop's IP address
KIND = "roku"             # "roku" or "windows"
SECONDS = 60
W, H = 1280, 720          # the whole TV picture; any multiple of 16 works

BG = 0x0006               # RGB565: dark navy
FG = 0xFFFF
ACCENT = 0xFFE0


class Picture:
    """A 1280x720 RGB565 framebuffer in RAM, and what is drawn on it."""

    def __init__(self, cast):
        self.cast = cast
        self.buf = bytearray(W * H * 2)
        self.fb = framebuf.FrameBuffer(self.buf, W, H, framebuf.RGB565)
        self.glyph = framebuf.FrameBuffer(bytearray(8 * 8 * 2), 8, 8, framebuf.RGB565)
        self.t0 = time.ticks_ms()
        self.second = -1
        self.bar = 0
        self.last_bar = self.t0
        self.fb.fill(BG)
        self.big_text("PyDevices P4", 64, 60, 8, ACCENT)
        self.big_text("no screen attached", 64, 150, 4, FG)

    def big_text(self, s, x, y, scale, color):
        """framebuf's 8x8 font, each pixel drawn as a scale x scale block."""
        for ch in s:
            self.glyph.fill(0)
            self.glyph.text(ch, 0, 0, 1)
            for gy in range(8):
                for gx in range(8):
                    if self.glyph.pixel(gx, gy):
                        self.fb.fill_rect(x + gx * scale, y + gy * scale, scale, scale, color)
            x += 8 * scale

    def step(self):
        """Called from the cast's session loop: redraw what changed, then tell castif."""
        now = time.ticks_ms()
        changed = False
        up = time.ticks_diff(now, self.t0) // 1000
        if up != self.second:
            self.second = up
            t = time.localtime()
            self.fb.fill_rect(64, 260, W - 128, 260, BG)
            self.big_text("%02d:%02d:%02d" % (t[3], t[4], t[5]), 64, 270, 16, FG)
            self.big_text("up %d s" % up, 64, 430, 6, FG)
            changed = True
        if time.ticks_diff(now, self.last_bar) >= 40:     # the bar moves at 25 steps a second
            self.last_bar = now
            x = 64 + (self.bar * 16) % (W - 128 - 160)
            self.bar += 1
            self.fb.fill_rect(64, 600, W - 128, 40, BG)
            self.fb.fill_rect(x, 600, 160, 40, ACCENT)
            changed = True
        if changed:
            self.cast.mark_dirty()   # castif's change check samples; this is certain


wifi_up()                                    # also sets the clock over NTP
cast = castfast.make_caster(W, H, canvas=(W, H))
picture = Picture(cast)
if KIND == "roku":
    from roku_cast import RokuScreen
    log("TV on:", RokuScreen(SINK, name="PyDevices P4", log=log).on())
log("casting %d s to %s" % (SECONDS, SINK))
result = castfast.cast(picture.buf, SINK, W, H, canvas=(W, H), seconds=SECONDS,
                       session_request=0 if KIND == "roku" else None,
                       log=log, scene=picture, cast_obj=cast)
log("result:", result)
cast.close()
