# deps: pygraphics
# gallery: skip
"""
spectrum.py -- an audio spectrum analyzer, fed fake music for now.

Log-spaced bars from 20 Hz to 20 kHz in a cool gradient, with peak-hold caps,
a reflection under the baseline, and frequency labels at their true log
positions. Drawn with ``pygraphics`` into an off-screen framebuffer; each frame
only the rows the bars could have touched are copied and sent to the panel.

The layout comes from the display's size, so the same file runs on a desktop
window, the ESP32-P4 panel (800x480) and the T-Embed (320x170). On desktop it
opens at 800x480 unless ``PYDEVICES_WIDTH``/``PYDEVICES_HEIGHT`` say otherwise.
Set ``SPECTRUM_STYLE=segmented`` for LED-style bars.

The levels come from ``fake_music.FakeMusic``; a real source only has to hand
``SpectrumView.update`` one 0..1 level per band.
"""

import sys

from displaydev import env_get, env_set

# A desktop board_config reads these; a real board's display ignores them.
if env_get("PYDEVICES_WIDTH") is None:
    env_set("PYDEVICES_WIDTH", 800)
    env_set("PYDEVICES_HEIGHT", 480)
if env_get("PYDEVICES_SCALE") is None:
    env_set("PYDEVICES_SCALE", 1.0)

_here = __file__.replace("\\", "/").rsplit("/", 1)[0] if "/" in __file__ else "."
if _here not in sys.path:
    sys.path.insert(0, _here)

import board_config  # noqa: E402
import appdev  # noqa: E402
from board_config import display_drv  # noqa: E402
from multimer import ticks_diff, ticks_ms  # noqa: E402

from fake_music import FakeMusic  # noqa: E402
from spectrum_view import SpectrumView  # noqa: E402

try:
    from time import ticks_us
except ImportError:  # CPython

    def ticks_us():
        return ticks_ms() * 1000


FRAME_MS = 16
REPORT_S = 5

app = appdev.App(board_config)
view = SpectrumView(
    display_drv.width, display_drv.height, style=env_get("SPECTRUM_STYLE") or "smooth"
)
music = FakeMusic(view.bands)
display_drv.blit_rect(view.strip(0, view.height), 0, 0, view.width, view.height)

_t0 = ticks_ms()
_last = _t0
_stats = [0, 0, 0, 0, _t0]  # frames, data us, draw us, blit us, report start


def _tick(_=None):
    global _last
    now = ticks_ms()
    dt = ticks_diff(now, _last) / 1000
    _last = now
    a = ticks_us()
    levels = music.levels(ticks_diff(now, _t0) / 1000)
    b = ticks_us()
    view.update(levels, min(dt, 0.1))
    y, h = view.render()
    c = ticks_us()
    display_drv.blit_rect(view.strip(y, h), 0, y, view.width, h)
    d = ticks_us()
    s = _stats
    s[0] += 1
    s[1] += b - a
    s[2] += c - b
    s[3] += d - c
    span = ticks_diff(now, s[4])
    if span >= REPORT_S * 1000:
        n = s[0]
        print(
            "{} fps; per frame: data {:.2f} ms, draw {:.2f} ms, blit {:.2f} ms".format(
                round(n * 1000 / span), s[1] / n / 1000, s[2] / n / 1000, s[3] / n / 1000
            )
        )
        s[0] = s[1] = s[2] = s[3] = 0
        s[4] = now


app.every(_tick, period=FRAME_MS, async_=app.timer_async)
