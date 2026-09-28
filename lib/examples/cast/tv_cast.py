# tv_cast.py -- cast the P4's panel, with sound, to a Roku TV, and control
# the TV over ECP. One producer plays a melody on the P4's speaker (at the
# panel's listening level, 85 %) and on the TV, on the cast's clock, while a
# square moves across the panel.
#
#   import cast.tv_cast
#
# Set TV to your Roku's address and turn on its Screen Mirroring.
import time
from _common import log, wifi_up
from board_config import fb, display_drv
from roku_cast import RokuScreen
from melody import Melody
import castfast

TV = "192.168.1.129"      # your Roku's IP address
SECONDS = 60

wifi_up()
display_drv.fill(0x0006)
display_drv.fill_rect(0, 0, 720, 90, 0xF81F)
display_drv.fill_rect(160, 240, 400, 240, 0x07E0)
display_drv.show()


class Scene:
    """Moves a square every 40 ms, syncing only the rows it changed."""

    def __init__(self):
        self.n = 0
        self.t = time.ticks_ms()

    def step(self):
        now = time.ticks_ms()
        if time.ticks_diff(now, self.t) < 40:
            return
        self.t = now
        self.n += 1
        x = 20 + (self.n * 8) % 600
        display_drv.fill_rect(0, 110, 720, 80, 0x0006)
        display_drv.fill_rect(x, 110, 80, 80, 0xFFE0)
        display_drv.flush_rect(0, 110, 720, 80)


feed = castfast.PumpFeed(Melody(), log=log)
tv = RokuScreen(TV, name="PyDevices P4", log=log)
log("TV on:", tv.on())
log("casting %d s" % SECONDS)
try:
    result = castfast.cast(fb, TV, 720, 720, seconds=SECONDS, session_request=0, log=log,
                           scene=Scene(), audio=feed)
    log("result:", result, "blocks fed", feed.fed)
finally:
    feed.close()
