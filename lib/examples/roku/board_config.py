"""Run a PyDevices example on a Roku TV, with the TV's remote as its keyboard.

Put this folder first on the path and run the example, e.g. testris.py.
"""

from utils.roku_companion import RokuAudioSink, RokuCompanion, RokuDisplay, roku_host

WIDTH = 480
HEIGHT = 270

# Connect to the Roku TV
tv = RokuCompanion(roku_host())

display_drv = RokuDisplay(tv, width=WIDTH, height=HEIGHT, port=8090)

# appdev.App(board_config) reads input from here: the remote's buttons.
get_events = display_drv.get_events

# Other stubs that PyDevices examples sometimes expect from board_config
has_touch = False
touch_drv = None
audio_drv = None
is_rotated = False

# Monkeypatch desktop audio to stream to Roku TV
import audiodev.auto
def roku_pcm_out(format=None, **kwargs):
    return RokuAudioSink(tv, format=format)
audiodev.auto.pcm_out = roku_pcm_out

