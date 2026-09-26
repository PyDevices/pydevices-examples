"""
capture.py -- render the analyzer headless, for screenshots and timing.

Runs on MicroPython (or CPython) with no display. Renders ``frames`` frames at
a fixed ``fps`` of fake-music time, prints what each part of a frame costs,
and, given an output path, appends every frame from ``start`` on to it as raw
RGB565 (little-endian, width x height per frame)::

    micropython capture.py WIDTH HEIGHT FRAMES FPS [STYLE] [OUT.raw] [START]

``make_captures.py`` drives this and turns the raw frames into PNGs and a GIF.
"""

import sys

try:
    from time import ticks_diff, ticks_us
except ImportError:
    from time import perf_counter

    def ticks_us():
        return int(perf_counter() * 1e6)

    def ticks_diff(a, b):
        return a - b


_here = __file__.replace("\\", "/").rsplit("/", 1)[0] if "/" in __file__ else "."
if _here not in sys.path:
    sys.path.insert(0, _here)

from fake_music import FakeMusic  # noqa: E402
from spectrum_view import SpectrumView  # noqa: E402

args = sys.argv[1:]
width, height, frames, fps = int(args[0]), int(args[1]), int(args[2]), int(args[3])
style = args[4] if len(args) > 4 else "smooth"
out = args[5] if len(args) > 5 else None
start = int(args[6]) if len(args) > 6 else 0

t0 = ticks_us()
view = SpectrumView(width, height, style=style)
setup_us = ticks_diff(ticks_us(), t0)
music = FakeMusic(view.bands)
dt = 1 / fps
f = open(out, "wb") if out else None
src_us = draw_us = rows = 0
worst = 0
for k in range(frames):
    t = k * dt
    a = ticks_us()
    levels = music.levels(t)
    b = ticks_us()
    view.update(levels, dt)
    y, h = view.render()
    c = ticks_us()
    src_us += ticks_diff(b, a)
    draw_us += ticks_diff(c, b)
    worst = max(worst, ticks_diff(c, b))
    rows += h
    if f and k >= start:
        f.write(view.fb.buffer if hasattr(view.fb, "buffer") else view._buf)
if f:
    f.close()
print(
    "{}x{} {} bands, style {}: setup {:.1f} ms; per frame: fake data {:.2f} ms, "
    "draw {:.2f} ms (worst {:.2f}), dirty rows {:.0f} of {}".format(
        width,
        height,
        view.bands,
        style,
        setup_us / 1000,
        src_us / frames / 1000,
        draw_us / frames / 1000,
        worst / 1000,
        rows / frames,
        height,
    )
)
