"""Run a PyDevices app on a TV or a laptop's Wireless Display window, from a P4
with no screen of its own.

Put this folder first on the path and run the app (testris, a dashboard, any
appdev App): its display is CastDisplay (../cast/cast_display.py), and on a
laptop its touch and keys are the laptop's mouse and keyboard.

Set SINK and KIND first. A Windows laptop needs its Wireless Display app open
(Settings > System > Projecting to this PC); a Roku TV needs Screen mirroring
on. The firmware needs castif and h264enc, so this is the ESP32-P4.
"""

import sys

_here = __file__.replace("\\", "/")
_here = _here.rsplit("/", 1)[0] if "/" in _here else "."
_cast = _here.rsplit("/", 1)[0] + "/cast" if "/" in _here else "../cast"
if _cast not in sys.path:
    sys.path.append(_cast)

from _common import wifi_up  # noqa: E402
from cast_display import CastDisplay  # noqa: E402

SINK = "192.168.1.143"    # the laptop's (or the Roku's) IP address
KIND = "windows"          # "windows" or "roku"
WIDTH = 720
HEIGHT = 720

wifi_up()
display_drv = CastDisplay(SINK, WIDTH, HEIGHT, kind=KIND)

# what appdev.App and the examples read from a board_config
fb = display_drv._buf
touch_read = display_drv.touch_read
keypad_read = display_drv.keypad_read
has_touch = True
touch_drv = None
audio_drv = None
is_rotated = False
