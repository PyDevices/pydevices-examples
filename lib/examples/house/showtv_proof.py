# gallery: skip
# A proof of the house appliance's SHOW-TV path with nobody at the panel: the
# house app, unchanged, with board_config.touch_read wrapped so that at each
# planned time the NEXT touch read reports one press in the middle of the
# SHOW-TV button (the painter's own code path decides what that press does),
# and the TV session's log printed instead of silenced. Watch the TV's active
# app from a PC while it runs:
#   curl http://<roku>:8060/query/active-app      (RokuCast while casting)
#
#   import house.showtv_proof
import time
import _thread
import board_config
import house  # noqa: F401  paths
import house_panel as hp

T0 = time.ticks_ms()
PLAN = [25, 85, 100, 150, 165, 225]      # seconds after start: three start/stop cycles
bx, by, bw, bh = hp.CAST_BTN
PT = (bx + bw // 2, by + bh // 2)
armed = [False]
real = board_config.touch_read


def touch_read():
    if armed[0]:
        armed[0] = False
        print("[%6d] PRESS SHOW-TV at %s" % (time.ticks_diff(time.ticks_ms(), T0), PT))
        return [PT]
    return real()


board_config.touch_read = touch_read

# the house app hands RokuScreen a silent log; for the proof, print it
import roku_cast  # noqa: E402
_init = roku_cast.RokuScreen.__init__


def _loud(self, host, name="PyDevices", log=None):
    _init(self, host, name=name, log=lambda *a: print("[%6d] tv:" % time.ticks_diff(time.ticks_ms(), T0), *a))


roku_cast.RokuScreen.__init__ = _loud


def presser():
    for s in PLAN:
        while time.ticks_diff(time.ticks_ms(), T0) < s * 1000:
            time.sleep_ms(200)
        armed[0] = True


_thread.stack_size(16 * 1024)
_thread.start_new_thread(presser, ())
import house_app  # noqa: E402  binds the wrapped touch_read
house_app.run(port=80)
