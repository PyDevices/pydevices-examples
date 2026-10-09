# deps: audiodsp, pygraphics
# gallery: skip
"""
mp3_from_sd.py -- play an MP3 from the microSD card, with a spectrum analyzer.

Mounts the board's card at /sd, plays the first .mp3 it finds through the
board's audio output, over and over, and draws the music's spectrum on the
display while it plays. It shows one way to put the analyzer in ``spectrum/`` on an app's own
sound: ``analyzer.Spectrum`` is the widget, and ``analyzer.levels_for`` meters
whatever an audiodev output is playing.

It needs a board with a display, a microSD slot (``board_peripherals.sdcard``)
and audio, on a firmware with audiodsp (for ``audiomp3``, the audio pump and
the meter). First played on a Waveshare ESP32-P4-WIFI6-DEV-KIT with a 5" DSI
display: a 44.1 kHz stereo track, the meter at about 50 frames a second.
"""

import os
import sys

_here = __file__.replace("\\", "/").rsplit("/", 1)[0] if "/" in __file__ else "."
if _here + "/spectrum" not in sys.path:
    sys.path.insert(0, _here + "/spectrum")

import appdev  # noqa: E402
import audiomp3  # noqa: E402
import board_config  # noqa: E402
import board_peripherals  # noqa: E402
from analyzer import Spectrum, levels_for  # noqa: E402
from audiodev import AudioFormat  # noqa: E402

MOUNT = "/sd"

try:
    os.listdir(MOUNT)
except OSError:
    os.mount(board_peripherals.sdcard(), MOUNT)
songs = sorted(n for n in os.listdir(MOUNT) if n.lower().endswith(".mp3"))
if not songs:
    raise SystemExit("no .mp3 file on the card")
song = audiomp3.MP3Decoder(open(MOUNT + "/" + songs[0], "rb"))
print("playing", songs[0], "-", song.sample_rate, "Hz,", song.channel_count, "channel(s)")

# Open the output at the song's own format, so nothing is resampled or remixed.
out = board_peripherals.audio_out(AudioFormat(song.sample_rate, song.channel_count, 16))
out.play(song, loop=True)  # back to the start when the song ends

meter = Spectrum(board_config.display_drv, levels_for(out))
# The meter presents just the rows it changed on panels that need presenting,
# so the app's whole-frame refresh is turned off there.
app = appdev.App(board_config, refresh_period=0 if meter.present_rows else None)
out.attach(app)
meter.start(app)
app.run()
