"""Run a PyDevices app as live video on a Roku TV (or in VLC), from an
ESP32-P4 with no screen of its own.

Put this folder first on the path and run the app: its display is HlsDisplay
(hls_display.py beside this), which encodes what the app draws as H.264 and
serves it as HLS, and tells the TV's PyDevices Companion channel to play it.
Set TV to your Roku's address, or to None and open the printed URL in VLC
(Media > Open Network Stream).

HLS runs 7-10 s behind, so this suits apps you watch, not ones you drive:
there is no input here. For an interactive app, use ../miracast/board_config.py.
"""

import sys

_here = __file__.replace("\\", "/")
_here = _here.rsplit("/", 1)[0] if "/" in _here else "."
if _here not in sys.path:
    sys.path.append(_here)

import wifi  # noqa: E402

from hls_display import HlsDisplay  # noqa: E402

TV = "192.168.1.129"      # your Roku's IP address, or None
WIDTH = 1280
HEIGHT = 720

wifi.connect_from_secrets()
display_drv = HlsDisplay(TV, WIDTH, HEIGHT)

# what appdev.App and the examples read from a board_config
fb = display_drv._buf
has_touch = False
touch_drv = None
audio_drv = None
is_rotated = False
