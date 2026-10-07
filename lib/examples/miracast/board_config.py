"""Run a PyDevices app on a TV or a laptop's Wireless Display window, from a P4
with no screen of its own.

Put this folder first on the path and run the app (testris, a dashboard, any
appdev App): its display is CastDisplay (../cast/cast_display.py), and on a
laptop its touch and keys are the laptop's mouse and keyboard.

Set SINK and KIND first. A Windows laptop needs its Wireless Display app open
(Settings > System > Projecting to this PC); a Roku TV needs Screen mirroring
on. On a board the firmware needs castif and h264enc (the ESP32-P4); on a
desktop, CPython with ffmpeg.
"""

import sys

_here = __file__.replace("\\", "/")
_here = _here.rsplit("/", 1)[0] if "/" in _here else "."
_cast = _here.rsplit("/", 1)[0] + "/cast" if "/" in _here else "../cast"
if _cast not in sys.path:
    sys.path.append(_cast)

from cast_display import CastDisplay  # noqa: E402

from utils import cast_target  # noqa: E402

# the laptop's (or the Roku's) address; "roku:ADDRESS" for a Roku
SINK = cast_target.get("192.168.1.143")
KIND = "windows"          # "windows" or "roku"
if SINK.startswith("roku:") or SINK.startswith("windows:"):
    KIND, SINK = SINK.split(":", 1)
WIDTH = 720
HEIGHT = 720

if sys.implementation.name != "cpython":     # a board joins Wi-Fi; a desktop is on the LAN
    from _common import wifi_up

    wifi_up()
# the session's progress on the console: joining, the sink's answers, frame rates
display_drv = CastDisplay(SINK, WIDTH, HEIGHT, kind=KIND, log=print)

# what appdev.App and the examples read from a board_config
fb = display_drv._buf
touch_read = display_drv.touch_read
keypad_read = display_drv.keypad_read
has_touch = True
touch_drv = None
audio_drv = None
is_rotated = False
