# deps: pygraphics
# gallery: skip
"""
spectrum.py -- an audio spectrum analyzer.

Log-spaced bars from 20 Hz to 20 kHz in a cool gradient, with peak-hold caps,
a reflection under the baseline, and frequency labels at their true log
positions. Drawn with ``pygraphics``: the static art once, then each bar as
its own packed column, so a frame copies and sends only the rows that moved.

The layout comes from the display's size, so the same file runs on a desktop
window, the ESP32-P4 panel (800x480) and the T-Embed (320x170). On desktop it
opens at 800x480 unless ``PYDEVICES_WIDTH``/``PYDEVICES_HEIGHT`` say otherwise.
Set ``SPECTRUM_STYLE=segmented`` for LED-style bars.

The levels come from the sound card's C pump when the firmware has one
(``pump_levels.PumpLevels``: run this beside usbif's ``soundcard.py``), from
what the computer is playing on a CPython desktop with numpy and
``soundcard`` installed (``loopback_levels.LoopbackLevels``), and from
``fake_music.FakeMusic`` otherwise. ``SPECTRUM_SOURCE=fake|pump|loopback``
forces one. Either only has to hand ``SpectrumView.update`` one 0..1 level per band.

``capture(path)`` writes the frame on screen to a file as raw RGB565, for a
screenshot of a real panel.
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
from spectrum_view import SpectrumView, band_count_for  # noqa: E402
from pygraphics import RGB565, FrameBuffer  # noqa: E402

try:
    from time import ticks_us
except ImportError:  # CPython

    def ticks_us():
        return ticks_ms() * 1000


FRAME_MS = 16
REPORT_S = 5

# A panel that needs presenting (the P4's DSI panel samples its framebuffer
# only when told to) gets just the changed rows presented after each frame,
# rather than appdev's whole-frame refresh every 33 ms, which costs 22 ms a
# time on the P4 and keeps PSRAM busy for two thirds of every second.
_present_rows = bool(getattr(display_drv, "needs_refresh", False)) and hasattr(
    getattr(display_drv, "_raw_buffer", None), "refresh_rect"
)
app = None
view = None
music = None
_send = None
_y = 0  # the meter's top row on the panel
timer = None

def _source():
    """The sound card's C pump on a board, what the computer is playing on a
    desktop (``loopback_levels``), else the fake. ``SPECTRUM_SOURCE`` forces
    one: ``fake``, ``pump`` or ``loopback``."""
    want = env_get("SPECTRUM_SOURCE")
    if want != "fake":
        if want in (None, "pump"):
            try:
                import pump_levels

                if pump_levels.available():
                    return pump_levels.PumpLevels(view.bands)
            except ImportError:
                pass
        if want in (None, "loopback"):
            try:
                import loopback_levels

                if loopback_levels.available():
                    return loopback_levels.LoopbackLevels(view.bands)
            except Exception as error:  # no loopback device, no audio stack
                print("spectrum: no loopback source (%r)" % (error,))
    return FakeMusic(view.bands)


def _panel_blit():
    """How a run of bar rows reaches the panel.

    Where the driver shares a packed framebuffer that has to be presented
    (the P4's DSI panel), rows are copied straight into it with no cache sync,
    and the frame's dirty band is synced and presented once, after the bars.
    The panel's own ``blit`` syncs the cache for every call, and a cache sync
    runs with interrupts off: forty-odd of them a frame kept the USB
    interrupt waiting long enough to lose sound-card packets. Otherwise, the
    driver's ``blit_rect``."""
    if _present_rows and getattr(display_drv, "share_framebuffer", False):
        buf, _, n, stride = display_drv.framebuffers()
        w, h = display_drv.width, display_drv.height
        if n == w * h * 2 and stride == w * 2:
            return FrameBuffer(buf, w, h, RGB565).blit_rect
    return display_drv.blit_rect


_dirty = [0, 0]  # rows touched this frame, top and bottom


def blit(buf, x, y, w, h):
    y += _y
    _send(buf, x, y, w, h)
    d = _dirty
    if y < d[0]:
        d[0] = y
    if y + h > d[1]:
        d[1] = y + h


last_report = ""
_t0 = 0
_last = 0
_stats = [0, 0, 0, 0, 0]  # frames, data us, draw us, blit us, report start


def _tick(_=None):
    global _last, last_report
    now = ticks_ms()
    dt = ticks_diff(now, _last) / 1000
    _last = now
    a = ticks_us()
    levels = music.levels(ticks_diff(now, _t0) / 1000)
    b = ticks_us()
    view.update(levels, min(dt, 0.1))
    c = ticks_us()
    _dirty[0], _dirty[1] = _y + view.height, 0
    view.render_columns(blit)
    if _present_rows and _dirty[1] > _dirty[0]:
        display_drv.flush_rect(0, _dirty[0], view.width, _dirty[1] - _dirty[0])
    d = ticks_us()
    s = _stats
    s[0] += 1
    s[1] += b - a
    s[2] += c - b
    s[3] += d - c
    span = ticks_diff(now, s[4])
    if span >= REPORT_S * 1000:
        n = s[0]
        last_report = "{:.1f} fps; per frame: data {:.2f} ms, update {:.2f} ms, draw+send {:.2f} ms".format(
            n * 1000 / span, s[1] / n / 1000, s[2] / n / 1000, s[3] / n / 1000
        )
        print(last_report)
        s[0] = s[1] = s[2] = s[3] = 0
        s[4] = now



def capture(path):
    """Write the meter's rows on screen to ``path`` as raw little-endian
    RGB565: from the panel's own framebuffer when the driver shares it, else a
    rebuild."""
    frame = None
    fbs = getattr(display_drv, "framebuffers", None)
    if fbs is not None and getattr(display_drv, "share_framebuffer", False):
        buf, _, n, stride = fbs()
        if stride == view.width * 2 and n >= (_y + view.height) * stride:
            frame = memoryview(buf)[_y * stride : (_y + view.height) * stride]
    with open(path, "wb") as f:
        f.write(frame if frame is not None else view.compose())
    return view.width, view.height


def start(bands=None, height=None, y=None, style=None):
    """Start the meter. Every argument is optional:

    - ``bands``: how many bars (x resolution). Default: half of what
      ``band_count_for`` gives for the panel's width.
    - ``height``: the meter's height in rows (y resolution). Default: half
      the panel.
    - ``y``: the meter's top row. Default: the meter sits at the bottom of
      the panel.
    - ``style``: ``"smooth"`` or ``"segmented"``; default ``SPECTRUM_STYLE``
      or smooth.

    Halving both was Brad's trade for frame rate under loud music
    (2026-09-26): 18-19 fps full size, 35-45 at half by half on the P4.
    """
    global app, view, music, _send, _y, timer, _t0, _last, _stats
    W, H = display_drv.width, display_drv.height
    if height is None:
        height = H // 2
    if bands is None:
        bands = band_count_for(W) // 2
    _y = H - height if y is None else y
    app = appdev.App(board_config, refresh_period=0 if _present_rows else None)
    view = SpectrumView(W, height, bands=bands, style=style or env_get("SPECTRUM_STYLE") or "smooth")
    music = _source()
    _send = _panel_blit()
    fill = getattr(display_drv, "fill_rect", None)
    if fill is not None and height < H:
        fill(0, 0, W, H, 0)  # clear whatever the panel showed before
    display_drv.blit_rect(view.strip(0, view.height), 0, _y, view.width, view.height)
    if _present_rows:
        display_drv.show()
    view._build_bar_columns()  # a second on the P4; not on the first frame
    _t0 = ticks_ms()
    _last = _t0
    _stats = [0, 0, 0, 0, _t0]
    timer = app.every(_tick, period=FRAME_MS, async_=app.timer_async)
    return view


if __name__ == "__main__":
    start()
