# deps: audioeffects, audioinstruments, pygraphics
# manifests: audiolive
"""A guitar pedalboard playing in a browser tab, on the same pump a board uses.

``audiolive`` is a library, not a program: it owns the codec, the effect graph
and the audio pump, and an app drives it. This is the app -- the smallest one
that makes a sound you can hear on a page. A looped riff runs through a pair
of pedals, the patch changes every few seconds (or when you click), and the
screen shows what the pump costs per block of audio.

**What is different in a browser is who runs the pump.** On a board the pump
is a C task on the core the interpreter is not on, and it writes every block
straight into I2S; nothing in Python is in the audio path at all. WebAssembly
has no second thread, so ``audiopump.spawn()`` adopts the graph and then sits
still: the loop only advances when somebody calls ``audiopump.service()``,
which pulls blocks into a RAM ring on the interpreter's own thread and returns
when the ring is full. This example is that somebody. A timer ticks, the tick
services the pump, drains the ring and hands the bytes to Web Audio -- and the
audio that comes out is byte-identical to the board's, because everything
above the ring is the same code.

That is also why the tick has to keep the browser ahead of itself: everything
serviced in one tick has to last until the next one. ``QUEUED`` on screen is
how much audio the browser is holding; as long as it never reaches zero you
hear no gap, and the tick stops filling once it is far enough ahead.

Click (or press a key) to start the sound -- browsers do not let a page make
noise until you have touched it -- and click again to jump to the next patch.

Runs unchanged on a board, where ``on_board`` is true, the pump writes to I2S
itself and this file only draws.
"""

import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    # So a clone can run this file by path: `audiolive` is the package beside
    # it. In the browser the host has already installed that package into
    # lib/, which comes first on sys.path, so this changes nothing there.
    sys.path.insert(0, _EXAMPLES)

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)

import pygraphics

import audiolive
from audiolive import PATCHES

# How often the pump is serviced. Everything one tick produces has to last
# until the next, so this and LOOKAHEAD_MS are one decision: a 20 ms tick
# needs more than 20 ms of audio queued at all times, and the margin is what
# absorbs a slow frame. 20/240 leaves an order of magnitude of room and still
# only costs a quarter of a second of latency, which nobody can hear in a
# demo that nobody is playing.
AUDIO_MS = 20
LOOKAHEAD_MS = 240

# The screen is redrawn four times a second. It is a status panel, not an
# animation, and a browser tab redrawing a 320x480 canvas at 60 Hz would be
# spending on paint what the audio wants for its own tick.
DRAW_MS = 250

# How long each patch plays before the next one. Long enough to hear what the
# pedals are doing, short enough that a visitor who stays ten seconds hears
# the sound change once.
PATCH_MS = 8000

# One drain, in bytes. The ring audiolive gives the pump on this path is eight
# blocks (8192 bytes at 256 frames stereo), so half of it per drain keeps the
# loop cheap without ever asking for more than there is.
DRAIN_BYTES = 4096

BYTES_PER_MS = audiolive.RATE * audiolive.CHANNELS * 2 // 1000
QUEUE_TARGET = LOOKAHEAD_MS * BYTES_PER_MS

WIDTH = display_drv.width
HEIGHT = display_drv.height


# A display whose bus cannot be told to stop byteswapping wants its colors
# already swapped, so the swap is decided once, here, and every constant below
# is built through it.
if display_drv.requires_byteswap:
    _swap = display_drv.disable_auto_byteswap(True)
else:
    _swap = False


def color565(r, g, b):
    c = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((c & 0xFF) << 8) | (c >> 8) if _swap else c


BG = color565(16, 18, 24)
FG = color565(236, 238, 245)
DIM = color565(120, 128, 150)
ACCENT = color565(255, 176, 64)
METER = color565(80, 220, 140)
METER_BG = color565(38, 42, 54)

# `available()` and `why()` exist for exactly this: a runtime without the pump
# built in cannot play any of this, and an example that dies on its
# constructor tells a reader nothing. The Pyodide half of the gallery is that
# runtime, and so is a firmware built without the audiodsp usermod.
_no_sound = None if audiolive.available() else audiolive.why()

live = None
if _no_sound is None:
    live = audiolive.LiveAudio(volume=audiolive.VOLUME)
    # Synthesised before anything is on screen: `riff` is 115 200 Python loop
    # iterations, and paying for it while a timer is already ticking is how an
    # example ends up looking wedged on its first frame.
    live.prepare("riff")

# The pump's engine, through audiodev's accessor rather than a bare import:
# `module()` is the supported way to ask for it, and `threaded()` is the
# question that decides whether this file has to service it at all.
from audiodev import pump as pumpdev  # noqa: E402 - after the heavy build

_pump = pumpdev.module()
# Two separate questions, and conflating them is a silent bug. Off a board the
# pump fills a RAM ring and SOMEBODY has to drain it into a sink -- that is
# true on a desktop as much as in a browser. Whether that somebody also has to
# *run* the pump is the second question, and only WebAssembly answers yes.
_drains = live is not None and not live.on_board
_services = _drains and not pumpdev.threaded()

_sink = None
_sink_open = False
if _drains:
    from audiodev import auto as audioauto  # noqa: E402

    try:
        _sink = audioauto.pcm_out()
    except Exception as exc:  # a desktop with no audio backend installed
        _no_sound = str(exc)
        _drains = _services = False

_WHERE = (
    audiolive.why()
    if _no_sound is not None
    else ("on the board, straight into I2S" if live.on_board
          else ("in the browser, serviced by a timer" if _services
                else "into a ring you drain"))
)

_buf = bytearray(DRAIN_BYTES)
_patch = 0
_peak = 0
_queued = 0
_started = False


def _chain():
    return PATCHES[_patch][1]


def _name():
    return PATCHES[_patch][0]


def _labels():
    return " -> ".join(str(fx[0]) for fx in _chain())


def _sink_ready():
    """True once the sink will take bytes. Cheap after the first call.

    In a browser this is the gesture gate: a page may not make a sound until
    somebody has touched it, and ``open()`` raises until they have. On a board
    there is no sink here at all -- the pump owns the I2S port itself.
    """
    global _sink_open
    if _no_sound is not None:
        return False
    if _sink is None:
        return True
    if _sink_open:
        return True
    try:
        _sink.open()
    except Exception:
        # Not an error: no gesture has reached the page yet, so Web Audio is
        # still muted. The screen says so and the next tick asks again.
        return False
    _sink_open = True
    return True


def _start():
    global _started
    if _started:
        return
    live.play(_chain(), source="riff")
    _started = True


def _next_patch(_e=None):
    global _patch
    _patch = (_patch + 1) % len(PATCHES)
    if _started:
        # A retarget under the pump's own lock: the block being pulled
        # finishes on the old chain and the next one comes from the new.
        live.play(_chain(), source="riff")


def _level(buf, count):
    """Peak of the drained block, 0-128, from the high byte of each sample.

    Every other byte of signed little-endian 16-bit audio IS the sample
    divided by 256, which is all the resolution a 200-pixel meter has. Read
    every 16th frame: a full scan of 4096 bytes eight times a second is
    real interpreter time spent on a decoration.
    """
    peak = 0
    for i in range(1, count, 64):
        value = buf[i]
        if value > 127:
            value = 256 - value
        if value > peak:
            peak = value
    return peak


def _audio_tick(_=None):
    """Service the pump, drain the ring, hand the bytes to the browser."""
    global _peak, _queued
    if not _sink_ready():
        return
    _start()
    if not _drains:
        return
    _queued = _sink.queued_size()
    # Fill until the sink is far enough ahead, then stop: producing past that
    # would run the graph faster than it is heard and grow an unbounded queue
    # of latency.
    while _queued < QUEUE_TARGET:
        if _services:
            _pump.service()
        count = live.drain(_buf)
        if not count:
            break
        _sink.write(memoryview(_buf)[:count])
        _queued += count
        peak = _level(_buf, count)
        if peak > _peak:
            _peak = peak


# The 8-pixel font is 8 pixels wide too, so a line of text is as many
# characters as the canvas has eighths. Everything below lays itself out from
# that rather than from a number somebody measured once at 320x480.
COLS = (WIDTH - 20) // 8
ROW = 14


def _wrap(text, cols):
    """The sentence, broken on spaces into lines that fit. Two lines at most.

    A status panel that runs off the side of the canvas is worse than one that
    says less: the browser gallery is 320 pixels wide, and `audiolive.why()`
    is a whole sentence.
    """
    words = text.split(" ")
    lines = []
    line = ""
    for word in words:
        candidate = word if not line else line + " " + word
        if len(candidate) > cols and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def _draw_tick(_=None):
    global _peak
    pygraphics.fill(display_drv, BG)
    scale = 2 if WIDTH < 400 else 3
    pad = 10
    pygraphics.text(display_drv, "audiolive", pad, pad, DIM, scale=scale)
    y = pad + 10 * scale
    for line in _wrap(_WHERE, COLS):
        pygraphics.text(display_drv, line, pad, y, DIM, scale=1)
        y += ROW

    y += 6
    pygraphics.text(display_drv, _name(), pad, y, ACCENT, scale=scale + 2)
    y += 10 * (scale + 2)
    pygraphics.text(display_drv, _labels()[:COLS], pad, y, FG, scale=1)
    y += ROW + 8

    # The meter: peak of the last blocks drained, as a bar, full scale at the
    # top of the 16-bit range. It decays on its own so a pump that has stopped
    # reads as silence rather than as the last loud thing that happened.
    bar_w = WIDTH - 2 * pad
    pygraphics.fill_rect(display_drv, pad, y, bar_w, 16, METER_BG)
    filled = min(bar_w, (_peak * bar_w) // 128)
    if filled:
        pygraphics.fill_rect(display_drv, pad, y, filled, 16, METER)
    _peak = (_peak * 2) // 3
    y += 16 + 12

    if not _started:
        if _no_sound is not None:
            pygraphics.text(display_drv, "NO SOUND HERE", pad, y, ACCENT, scale=2)
            y += 22
            for line in _wrap(_no_sound, COLS):
                pygraphics.text(display_drv, line, pad, y, DIM, scale=1)
                y += ROW
            return
        pygraphics.text(display_drv, "CLICK OR PRESS", pad, y, ACCENT, scale=2)
        y += 20
        pygraphics.text(display_drv, "A KEY", pad, y, ACCENT, scale=2)
        y += 26
        for line in _wrap("a page is not allowed to make a sound until you "
                          "have touched it", COLS):
            pygraphics.text(display_drv, line, pad, y, DIM, scale=1)
            y += ROW
        return

    status = live.status()
    rows = [
        ("LOAD", "%d %% of each block" % status["load_pct"]),
        ("BLOCKS", "%d pulled" % status["blocks"]),
        ("STARVED", "%d ms" % status["starved_ms"]),
    ]
    if _drains:
        rows.append(("QUEUED", "%d ms in the sink" % (_queued // BYTES_PER_MS)))
    for label, value in rows:
        pygraphics.text(display_drv, label, pad, y, DIM, scale=1)
        pygraphics.text(display_drv, value, pad + 8 * 9, y, FG, scale=1)
        y += ROW

    y += 10
    for line in _wrap(audiolive.why(), COLS):
        pygraphics.text(display_drv, line, pad, y, DIM, scale=1)
        y += ROW
    why = status["why"]
    if why:
        y += 6
        for line in _wrap(why, COLS):
            pygraphics.text(display_drv, line, pad, y, ACCENT, scale=1)
            y += ROW

    # The whole pedalboard, so a visitor can see what is coming as well as
    # what is playing. Five rows of text is cheaper than one more effect.
    y += 12
    for index, (name, chain) in enumerate(PATCHES):
        color = ACCENT if index == _patch else DIM
        row = "%-7s %s" % (name, " -> ".join(str(fx[0]) for fx in chain))
        pygraphics.text(display_drv, row[:COLS], pad, y, color, scale=1)
        y += ROW

    pygraphics.text(
        display_drv, "click or a key: next patch", pad, HEIGHT - pad - 8, DIM, scale=1
    )


def _on_quit(_e=None):
    if live is not None:
        live.stop()
    if _sink is not None and _sink_open:
        _sink.close()
    display_drv.quit()


app.on(app.events.MOUSEBUTTONDOWN, _next_patch)
app.on(app.events.FINGERDOWN, _next_patch)
app.on(app.events.KEYDOWN, _next_patch)
app.on(app.events.QUIT, _on_quit)

_draw_tick()
app.every(_audio_tick, period=AUDIO_MS, async_=app.timer_async)
app.every(_draw_tick, period=DRAW_MS, async_=app.timer_async)
app.every(_next_patch, period=PATCH_MS, async_=app.timer_async)
