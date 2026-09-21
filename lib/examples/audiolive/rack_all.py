# deps: audioeffects, lvgl
# gallery: skip
"""rack_all.py - a screen, a USB MIDI port and live audio, all at once.

This is the one that answers the question. The microphone goes through a
pedalboard and out of the speaker; the touchscreen is redrawing an animated
meter as fast as it will go; the board is enumerated on your computer as a
MIDI device and you are playing it. Three busy things on one chip.

On screen, in numbers big enough to read from across the room, is what the
audio pump costs and - the one that matters - how many milliseconds of
silence the speaker has had to invent. If the display and USB ever get in
the audio's way, ``STARVED`` is where you see it.

Wear headphones, or the microphone will find the speaker and howl.

Run it on the Waveshare ESP32-P4-WIFI6-Touch-LCD-4B
--------------------------------------------------
::

    mpftp mkdir -d COM4 /lib/audiolive
    mpftp put -d COM4 lib/examples/audiolive/__init__.py /lib/audiolive/__init__.py
    mpftp put -d COM4 lib/examples/audiolive/rack_all.py /lib/audiolive/rack_all.py
    python.exe -m mpremote connect COM4 exec "import audiolive.rack_all" repl

Same costume as rack_midi.py: CDC + MIDI, applied only if it is not already
right, so the serial port re-enumerates at most once.

What you should see and hear
----------------------------
The room comes out of the speaker with overdrive and a tape echo on it -
talk, and you hear yourself, dirty and echoing, about a hundredth of a
second behind. A bar sweeps across the screen the whole time. Play your
MIDI controller and a plucked string joins the room, through the same
pedals. Tap a patch name and the whole sound changes character.

The four numbers along the bottom: ``LOAD`` is the share of each block of
audio the effects use - under 100 is fine. ``WORST`` is the slowest single
block; as long as it stays under the block length printed beside it, the
speaker never runs dry. ``MIDI`` counts the messages that have arrived.
``STARVED`` should be ``0 ms`` and stay there while you drag, play and
talk all at once. If it climbs, something on this chip got in the audio's
way, and the number tells you how much.

Tap SOURCE to swap the microphone for the looped riff, which is the fair
comparison: the same chain, the same load, no acoustic feedback.
"""

import time

from board_config import display_drv  # noqa: F401  (brings the panel up)
from display_driver import app  # noqa: F401  (LVGL flush, input, event loop)
import lvgl as lv

import audiolive
from audiolive import PATCHES

BUF = bytearray(256)
MIDI_POLL_MS = 5          # the MIDI pump rides the display loop
METER_MS = 30             # the animation that keeps the display busy
# Read this as an upper bound, not a rate. On the microphone the pump reads
# 91 % of a block and ONE LVGL pass through `app.poll()` measured 2.1 s, so
# an LVGL timer asking for 30 ms fires once a pass like every other. The
# panel, the effect graph and the audio all live in PSRAM and they are
# competing for it; the bar is the visible part of that bill.
STATUS_MS = 500

BG = lv.color_hex(0x101014)
PANEL = lv.color_hex(0x1E1E26)
FG = lv.color_hex(0xE8E8F0)
ACCENT = lv.color_hex(0xFF8C32)
GOOD = lv.color_hex(0x3FD07F)
BAD = lv.color_hex(0xFF4040)
DIM = lv.color_hex(0x3A3A48)


def _guarded(fn):
    """Never let an exception escape into an LVGL callback."""

    def wrapper(*args):
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            print("rack_all:", exc)

    return wrapper


class AllAtOnce:
    def __init__(self):
        # A deeper ring than the module default, for the same reason
        # rack_gui uses one: a lit 720x720 panel is a megabyte read out of
        # PSRAM per frame and the graph is in PSRAM too, so every block costs
        # more and the worst block costs a lot more. See audiolive's DMA
        # comment for the measurements.
        audiolive.DMA_DESC = audiolive.DMA_DESC_GUI
        self.live = audiolive.LiveAudio(volume=100)
        self.patch = 0
        self.midi_count = 0
        self.synth = None
        self.parser = None
        self.restore = None
        self.phase = 0
        self.mic = True

        # The riff, built here rather than when SOURCE is tapped. Tapping it
        # used to appear to hang the app: the phrase is a long pure-Python
        # loop, and under a lit panel the display timer's soft IRQ leaves
        # the interpreter so little that it does not finish. See
        # LiveAudio.prepare.
        self.live.prepare("riff")

        # mic -> effect -> speaker. Capture and playback are the two halves
        # of ONE I2S channel pair on this board, so they share a clock tree
        # and cannot drift apart.
        self.live.play(PATCHES[0][1], source="input")
        self._build_screen()
        self._start_midi()

        lv.timer_create(_guarded(self._on_meter), METER_MS, None)
        lv.timer_create(_guarded(self._on_status), STATUS_MS, None)
        if self.parser is not None:
            lv.timer_create(_guarded(self._on_midi), MIDI_POLL_MS, None)

    # --- USB ---------------------------------------------------------------

    def _start_midi(self):
        """Wear the CDC+MIDI costume, if this firmware has MIDI at all."""
        try:
            import _usbif
            import usbif
        except ImportError:
            print("no usbif in this firmware; running without MIDI")
            return
        if not (_usbif.dev_functions_built() & _usbif.FN_MIDI):
            print("this firmware has no MIDI device function; no MIDI")
            return
        self._usbif = _usbif
        self.restore = _usbif.dev_functions()
        want = _usbif.FN_CDC | _usbif.FN_MIDI
        if self.restore != want:
            _usbif.dev_functions(want)
            print("costume: cdc+midi -- the serial port re-enumerates once")
        self.parser = usbif.MidiParser()
        self.synth = None

    def _ensure_synth(self):
        """Add the instrument the first time somebody actually plays.

        Not at startup: an instrument nobody presses is a graph nobody
        hears, and it costs a block of CPU anyway. Adding it re-makes the
        source as a two-voice mixer - microphone on one voice, instrument
        on the other - so the room and the string come through the same
        pedals together.
        """
        if self.synth is None:
            self._set_source(True)
            self.synth = self.live.synth
        return self.synth

    def _on_midi(self, _t):
        n = self._usbif.midi_read(BUF)
        if not n:
            return
        self.parser.feed(BUF, n)
        for status, data in self.parser.drain():
            self.midi_count += 1
            kind = status >> 4
            if kind == 0x9 and len(data) == 2 and data[1]:
                self._ensure_synth().note_on(data[0], data[1])
            elif kind == 0x8 or (kind == 0x9 and len(data) == 2):
                if self.synth is not None:
                    self.synth.note_off(data[0])
            elif kind == 0xC and len(data) >= 1:
                self._select(data[0] % len(PATCHES))

    # --- the screen --------------------------------------------------------

    def _build_screen(self):
        scr = lv.screen_active()
        scr.set_style_bg_color(BG, 0)
        hres = display_drv.width
        vres = display_drv.height
        pad = max(6, hres // 60)
        unit = max(44, hres // 9)

        row = lv.obj(scr)
        row.set_size(hres - 2 * pad, unit)
        row.align(lv.ALIGN.TOP_MID, 0, pad)
        self._flat(row)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY, lv.FLEX_ALIGN.CENTER,
                           lv.FLEX_ALIGN.CENTER)
        self.buttons = []
        for i, (name, _chain) in enumerate(PATCHES):
            btn = lv.button(row)
            btn.set_size(lv.pct(100 // (len(PATCHES) + 2)), lv.pct(100))
            btn.set_style_bg_color(ACCENT if i == 0 else PANEL, 0)
            lab = lv.label(btn)
            lab.set_text(name)
            lab.center()
            btn.add_event_cb(_guarded(self._make_patch_cb(i)),
                             lv.EVENT.CLICKED, None)
            self.buttons.append(btn)

        self.source_btn = lv.button(row)
        self.source_btn.set_size(lv.pct(16), lv.pct(100))
        self.source_btn.set_style_bg_color(PANEL, 0)
        self.source_label = lv.label(self.source_btn)
        self.source_label.set_text("MIC")
        self.source_label.center()
        self.source_btn.add_event_cb(_guarded(self._on_source),
                                     lv.EVENT.CLICKED, None)

        # A bar that sweeps across the panel. It has no meaning: it is here
        # to make the display do real work every 30 ms, which is the load
        # the audio has to survive. There is no tap on the pump yet, so this
        # cannot be a level meter - nothing can read what is going out
        # without standing in its path.
        self.meter = lv.bar(scr)
        self.meter.set_size(hres - 2 * pad, vres // 3)
        self.meter.align(lv.ALIGN.CENTER, 0, -unit // 2)
        self.meter.set_range(0, 100)
        self.meter.set_style_bg_color(PANEL, lv.PART.MAIN)
        self.meter.set_style_bg_color(ACCENT, lv.PART.INDICATOR)

        self.big = lv.label(scr)
        self.big.set_style_text_color(FG, 0)
        self.big.align(lv.ALIGN.CENTER, 0, vres // 4)
        self.big.set_text("starting ...")

        self.starved = lv.label(scr)
        self.starved.set_style_text_color(GOOD, 0)
        self.starved.align(lv.ALIGN.BOTTOM_MID, 0, -pad)
        self.starved.set_text("STARVED 0 ms")

    def _flat(self, obj):
        obj.set_style_bg_opa(0, 0)
        obj.set_style_border_width(0, 0)
        obj.set_style_pad_all(0, 0)
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)

    def _make_patch_cb(self, index):
        def cb(_e):
            self._select(index)

        return cb

    def _select(self, index):
        self.patch = index
        for i, btn in enumerate(self.buttons):
            btn.set_style_bg_color(ACCENT if i == index else PANEL, 0)
        self.live.play(PATCHES[index][1])
        print("patch:", PATCHES[index][0],
              [type(f).NAME for f in self.live.effects])

    def _set_source(self, with_synth):
        """Re-make the source: microphone or riff, plus the instrument."""
        first = "input" if self.mic else "riff"
        names = (first, "karplus") if with_synth else (first,)
        self.live.source(names if len(names) > 1 else first)
        self.source_label.set_text("MIC" if self.mic else "RIFF")

    def _on_source(self, _e):
        was = self.mic
        self.mic = not self.mic
        try:
            self._set_source(self.synth is not None)
        except RuntimeError as exc:
            # A board whose capture is on a different I2S port from playback
            # cannot do this; say so rather than failing silently.
            print("source:", exc)
            self.mic = was
            self._set_source(self.synth is not None)

    # --- the numbers -------------------------------------------------------

    def _on_meter(self, _t):
        self.phase = (self.phase + 4) % 200
        self.meter.set_value(self.phase if self.phase <= 100
                             else 200 - self.phase, 0)

    def _on_status(self, _t):
        s = self.live.status()
        self.big.set_text("LOAD %d%%   WORST %d us of %d   MIDI %d"
                          % (s["load_pct"], s["worst_us"], s["block_us"],
                             self.midi_count))
        if s["why"]:
            # The pump stopped on its own. It runs on the other core and has
            # no interpreter to raise at you, so this is how it says so - and
            # tapping any patch calls play(), which starts a fresh one.
            self.starved.set_text("AUDIO STOPPED: %s - tap a patch" % s["why"])
            self.starved.set_style_text_color(BAD, 0)
            return
        ms = s["starved_ms"]
        self.starved.set_text("STARVED %d ms" % ms)
        self.starved.set_style_text_color(GOOD if ms == 0 else BAD, 0)


rack = AllAtOnce()
print("running. starved should stay at 0 ms.")
print("this is mic -> pedals -> speaker: wear headphones.")
time.sleep_ms(1)
