# deps: audioeffects, pygraphics
# gallery: skip
"""rack_knob.py - an effect rack you turn with a knob.

The touch pedalboard (``rack_gui.py``) for a board with one encoder and no
touchscreen. A riff runs through a chain of two effects; the panel lists the
patch and every macro the chain has; turning the knob moves the highlighted
row and pressing it moves the highlight on. The audio never touches the
interpreter - a C task pulls it on the other core and writes it straight into
I2S - so the screen can redraw and the knob can spin while the sound keeps
its exact clock.

Run it on the LilyGO T-Embed S3
------------------------------
Copy the module and start it without a soft reset, so the REPL stays alive
beside the audio::

    mpftp mkdir -d COM12 /lib/audiolive
    mpftp put -d COM12 lib/examples/audiolive/__init__.py /lib/audiolive/__init__.py
    mpftp put -d COM12 lib/examples/audiolive/rack_knob.py /lib/audiolive/rack_knob.py
    python.exe -m mpremote connect COM12 exec "import audiolive.rack_knob" repl

``exec`` soft-resets on the way in, which is fine - nothing is playing yet.
``repl`` does not: it sends Ctrl-B only, so the pump keeps running and you
land at a prompt with the app still live. Ctrl-] leaves the terminal and the
audio keeps playing.

What you should see and hear
----------------------------
A six-note plucked phrase, round and round, with some grit on it. On the
panel: the patch name at the top, then one row per macro, then a line of
numbers. One row is orange - that is the one the knob moves.

    turn the knob    moves the highlighted row. On PATCH that steps through
                     the pedalboards and the sound changes character on the
                     next note; on a macro row it moves that macro 0-127 and
                     you hear it immediately.
    press the knob   moves the highlight down one row, wrapping at the end.

So the knob is the value and the button is the cursor, which is the one
idiom a single encoder can carry without inventing modifiers. It is the
``appdev`` encoder mapping the other examples here use - ``encoder_read``
becomes mouse-wheel events and ``encoder_button_read`` becomes button 2,
exactly as in ``appdev_encoder_test.py``.

The bottom line is the one that matters. ``load`` is how much of each block
of audio the effects use; anything under 100 is fine. ``starved`` is how many
milliseconds of silence the speaker has had to invent because the effects
were late. Spin the knob and it stays at ``0 ms``; that is what the ring
below was chosen for, and the measurements are beside it.

Two honest caveats. The ring is 64 ms deep, so a macro you move is heard up
to 64 ms later - a knob still feels immediate at that, and anything
shallower leaks silence on this board. And **changing pedalboard does cost
you a hole**: building the new Rack takes 395-1036 ms on the interpreter
thread and drops up to 176 ms of audio. No ring depth reaches that, so the
``0 ms`` above is a promise about the macro rows and not about PATCH.

Two things this board does not do
---------------------------------
**No MIC button.** Its microphones are on I2S port 0 and its amplifier is on
port 1, so one channel pair cannot carry both; ``rack_gui``'s MIC button has
nothing to bind to here.

**No ShimmerHall, and no Reverb - and only one dear pedal at a time.** Both
fit on this board only if nothing else plays: measured with the pump running
and nothing else on it, ``ShimmerHall`` uses 92 % of its own block and
starves anyway, and ``Reverb`` 52 %, which leaves no room for the delay
behind it. The P4's own pairs are too dear here as well - ``Overdrive ->
TapeDelay`` reads 82 % and ``Fuzz -> TapeDelay`` 92 %, and this app's screen
and knob add 15-20 points on top, which is a hole in the audio rather than a
slow app. So the list here is ``audiolive.LIGHT_PATCHES``: one dear pedal or
two cheap ones, 64-73 % measured, with the numbers beside it in that file.
On the P4, use ``rack_gui.py`` and the full ``PATCHES``.

**The volume is in the samples.** The MAX98357A is an amplifier with no I2C,
no registers and no volume control, so ``LiveAudio(level=...)`` scales the
source instead. 0.5 is half of what the material was written at; raise it to
1.0 if it is too quiet for you.
"""

import time

from board_config import display_drv
import board_config
import appdev
from pygraphics import FrameBuffer, RGB565

import audiolive
from audiolive import LIGHT_PATCHES as PATCHES

app = appdev.App(board_config)

# 565 colours, as the panel wants them.
BG = 0x0000
PANEL = 0x2124
FG = 0xFFFF
DIM = 0x8410
ACCENT = 0xFC41            # orange: the row the knob moves

ROW_H = 24
PAD = 3
STEP = 4                   # macro units per encoder detent
LEVEL = 0.5                # see the docstring: this board's only volume

# 12 x 256 descriptors = 12 288 bytes = 64 ms. It is the smallest ring that
# starves nothing UNDER THE KNOB, and it is not enough to make a long run
# read zero - be clear about which claim you are reading.
#
# Twenty seconds a row, the panel lit, a detent every 30 ms and a press every
# 2 s, one fresh LiveAudio per row because ``starved_ms`` is a high-water mark
# nothing in a boot can lower (``probes/s3_rack.py`` ``ringsweep()``):
#
#     4 x 128   10.7 ms   starved 426 ms
#     8 x 128   21.3 ms   starved  85 ms
#    12 x 128   32.0 ms   starved  93 ms
#    16 x 128   42.7 ms   starved  18 ms
#    12 x 256   64.0 ms   starved   0 ms      <- this
#    16 x 256   85.3 ms   starved   0 ms
#
# What decides it is not the pump's average but its worst block: one pull of
# ``Overdrive`` costs 89-90 % of the 5333 us a block lasts and the worst is
# 8.4-8.7 ms, so a ring of 128-frame pieces cannot hold one late block
# however many pieces it has. That is why 16 x 128 (42.7 ms) still leaks
# where 12 x 256 (64 ms) does not, and why the note that used to be here -
# "nothing deeper bought anything" - was wrong: it was measured at 128-frame
# descriptors only.
#
# **What is left is the pedalboard change, and no ring cures it.** Thirty
# seconds of continuous turning on a macro row adds 0 ms, five times out of
# five. A CHANGE adds 0-176 ms, and costs 395-1036 ms on the interpreter
# thread building the new Rack - so a 190 s run that keeps changing patch
# reads 3749 ms starved at this same ring. Change pedalboards while you are
# playing and you will hear it; turn a macro and you will not.
# See ``docs/spikes/live-audio-path-s3.md``.
#
# The P4 runs ``rack_gui`` at 12 x 128, because a lit 720x720 panel reads a
# megabyte of PSRAM per frame and an SPI ST7789 reads none.
# A harness or a board file can choose the ring before this module is
# imported; everything else gets the number this board was measured at.
audiolive.DMA_DESC = getattr(audiolive, "RACK_DMA_DESC", 12)
audiolive.DMA_FRAME = getattr(audiolive, "RACK_DMA_FRAME", 256)


class RackKnob:
    def __init__(self):
        self.w = display_drv.width
        self.h = display_drv.height
        self.live = audiolive.LiveAudio(level=LEVEL)
        # Build the 2.4 s of Karplus-Strong now, before anything is drawn:
        # it is 115 200 iterations of pure Python and it wants the machine to
        # itself. Everything after this is a Mixer and a Rack.
        self.live.prepare("riff")
        self.patch = 0
        self.sel = 0                    # 0 is the PATCH row
        self.rows = []                  # (effect index, macro index) or None
        self.strip = bytearray(self.w * ROW_H * 2)
        self.fb = FrameBuffer(self.strip, self.w, ROW_H, RGB565)
        display_drv.fill_rect(0, 0, self.w, self.h, BG)
        self.live.play(PATCHES[self.patch][1])
        self._bind()
        app.on(app.events.MOUSEWHEEL, self._on_wheel)
        app.on(app.events.MOUSEBUTTONDOWN, self._on_button)
        # The numbers ride a timer, so they cost the audio nothing and stop
        # by themselves when the app does.
        app.every(500, self._on_tick)

    # --- what is on screen ------------------------------------------------

    def _bind(self):
        """One row per macro of the live chain, plus PATCH at the top."""
        self.rows = [None]
        for index, fx in enumerate(self.live.effects):
            for macro in range(len(self.live.labels(index))):
                self.rows.append((index, macro))
        # As many as fit above the numbers line.
        fits = (self.h - ROW_H) // ROW_H
        if len(self.rows) > fits:
            self.rows = self.rows[:fits]
        if self.sel >= len(self.rows):
            self.sel = 0
        self._draw_all()

    def _label(self, row):
        if row is None:
            return "PATCH", PATCHES[self.patch][0], self.patch * 127 // \
                max(len(PATCHES) - 1, 1)
        index, macro = row
        fx = self.live.effects[index]
        value = int(self.live.knob(index, macro))
        return (type(fx).NAME[:7].upper(),
                "%s %d" % (self.live.labels(index)[macro][:6], value), value)

    def _draw_row(self, n):
        """One strip, drawn off screen and blitted in one go.

        One blit a row rather than a pixel at a time, and only the row that
        changed: what costs this pump is the NUMBER of blits, not their size
        (a bar at 237 blits/s costs it 27 points of a block, whole-screen
        repaints at 31/s cost 12).
        """
        row = self.rows[n]
        name, text, value = self._label(row)
        on = n == self.sel
        self.fb.fill(PANEL if on else BG)
        self.fb.text(name, PAD, 2, ACCENT if on else DIM)
        self.fb.text(text, PAD, 12, FG)
        # The value as a bar under the text, so a glance is enough.
        width = max(0, min(self.w - 2 * PAD, (self.w - 2 * PAD) * value // 127))
        self.fb.fill_rect(PAD, ROW_H - 5, width, 3, ACCENT if on else DIM)
        display_drv.blit_rect(self.strip, 0, n * ROW_H, self.w, ROW_H)

    def _draw_all(self):
        for n in range(len(self.rows)):
            self._draw_row(n)

    # --- the knob and the button ------------------------------------------

    def turn(self, steps):
        """The encoder moved `steps` detents. Also the harness's door in."""
        if not steps:
            return
        if self.rows[self.sel] is None:
            self.patch = (self.patch + steps) % len(PATCHES)
            self.live.play(PATCHES[self.patch][1])
            self._bind()
            return
        index, macro = self.rows[self.sel]
        value = int(self.live.knob(index, macro)) + steps * STEP
        value = 0 if value < 0 else (127 if value > 127 else value)
        self.live.knob(index, macro, value)
        self._draw_row(self.sel)

    def press(self):
        """The encoder was pushed: move the highlight on."""
        was = self.sel
        self.sel = (self.sel + 1) % len(self.rows)
        self._draw_row(was)
        self._draw_row(self.sel)

    def _on_wheel(self, e):
        # appdev hands an encoder's motion over as a wheel event; which axis
        # it lands on is the device's business, so take whichever moved.
        try:
            self.turn(int(e.y) or int(e.x))
        except Exception as exc:                             # noqa: BLE001
            print("rack_knob:", exc)

    def _on_button(self, e):
        # Button 2 is what appdev gives an encoder's push. Anything else on
        # this board is somebody else's button.
        try:
            if e.button == 2:
                self.press()
        except Exception as exc:                             # noqa: BLE001
            print("rack_knob:", exc)

    # --- the pump's own numbers -------------------------------------------

    def _on_tick(self, _t=None):
        try:
            s = self.live.status()
        except Exception as exc:                             # noqa: BLE001
            print("rack_knob:", exc)
            return
        self.fb.fill(BG)
        if s["why"]:
            # The pump stopped on its own. It has no interpreter thread to
            # raise on, so this line is how it tells you; turning the knob on
            # the PATCH row starts a fresh one.
            self.fb.text("stopped: press+turn", PAD, 2, ACCENT)
            self.fb.text(s["why"][:20], PAD, 12, ACCENT)
        else:
            self.fb.text("load %d%% blk %d/%dus"
                         % (s["load_pct"], s["worst_us"], s["block_us"]),
                         PAD, 2, FG)
            self.fb.text("starved %d ms  err %d"
                         % (s["starved_ms"], s["error"]), PAD, 12, DIM)
        display_drv.blit_rect(self.strip, 0, self.h - ROW_H, self.w, ROW_H)


gui = RackKnob()
app.run()
