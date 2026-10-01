import sys

sys.path.insert(0, "/home/brad/gh/pydevices/pydevices-examples/lib")
sys.path.insert(0, "/home/brad/gh/pydevices/pydevices/lib")
sys.path.insert(0, "/home/brad/gh/pydevices/pygraphics/lib")

from displaydev.fbdisplay import FBDisplay
from utils.roku_companion import RokuCompanion, RokuDisplayWrapper, RokuAudioSink

WIDTH = 480
HEIGHT = 270
buf = bytearray(WIDTH * HEIGHT * 2)
base_display = FBDisplay(buf, width=WIDTH, height=HEIGHT)

# Connect to the Roku TV
tv = RokuCompanion("192.168.1.129")

# Wrap the base display with the Roku companion display
display_drv = RokuDisplayWrapper(base_display, tv, port=8090)

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

