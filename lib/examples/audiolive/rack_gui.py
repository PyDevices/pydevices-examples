# deps: audioeffects, lvgl
# gallery: skip
"""rack_gui.py - an effect rack you play with your fingers.

A riff (or the microphone) runs through a chain of two effects. On screen:
a patch selector, a slider for every macro the selected effect has, a
BYPASS button, a MIC button, and a live readout of what the audio pump
costs per block. The audio never touches the interpreter - it is pulled by
a C task on the other core - so every one of those controls moves while the
sound keeps its exact clock.

That is the whole point of the example: drag a slider hard, watch the
screen redraw, and watch ``starved 0 ms`` stay at zero.

Run it on the Waveshare ESP32-P4-WIFI6-Touch-LCD-4B
--------------------------------------------------
Copy the module and start it without a soft reset, so the REPL stays alive
beside the audio::

    mpftp mkdir -d COM4 /lib/audiolive
    mpftp put -d COM4 lib/examples/audiolive/__init__.py /lib/audiolive/__init__.py
    mpftp put -d COM4 lib/examples/audiolive/rack_gui.py /lib/audiolive/rack_gui.py
    python.exe -m mpremote connect COM4 exec "import audiolive.rack_gui" repl

``exec`` soft-resets on the way in, which is fine - nothing is playing yet.
``repl`` does not: it sends Ctrl-B only, so the pump keeps running and you
land at a prompt with the app still live. Ctrl-] leaves the terminal and
the audio keeps playing.

What you should see and hear
----------------------------
A dark screen with a row of patch names across the top and a stack of
labelled sliders beneath. The speaker plays a six-note plucked phrase,
round and round, with some grit on it. Drag DRIVE to the right and the
phrase gets dirtier and louder in the way a guitar amp does when you turn
it up; drag it back and it cleans up. Tap a different patch name and the
sound changes character on the next note - a little lump in the audio as
the new pedals are switched in, and then it settles. Tap BYPASS and you
hear the bare, clean pluck with nothing on it. Tap MIC and the riff stops
and the room comes through the speaker instead, with the same pedals on it
- put on headphones first or it will howl.

Along the bottom is a line of numbers. ``load`` is how much of each block
of audio the effects actually use; anything under 100 is fine. ``starved``
is the one that matters: it is how many milliseconds of silence the
speaker has had to invent because the effects were late. It should read
``0 ms`` no matter how hard you drag.

The T-Embed S3 follows with two changes: it has no touchscreen, so the
sliders bind to the rotary encoder (``board_config.encoder_read``, which
``appdev`` already maps to mouse-wheel events), and its microphone is on a
different I2S port from its speaker, so ``MIC`` is not available there.
"""

from board_config import display_drv  # noqa: F401  (brings the panel up)
from display_driver import app  # noqa: F401  (LVGL flush, input, event loop)
import lvgl as lv

import audiolive
from audiolive import PATCHES

BG = lv.color_hex(0x101014)
PANEL = lv.color_hex(0x1E1E26)
FG = lv.color_hex(0xE8E8F0)
ACCENT = lv.color_hex(0xFF8C32)
DIM = lv.color_hex(0x3A3A48)

MAX_SLIDERS = 6          # more macros than that and the panel gets unreadable


def _guarded(fn):
    """Never let an exception escape into an LVGL callback.

    The MicroPython binding's callback wrapper leaks its re-entrancy counter
    when a Python callback raises, which silently disables ``task_handler``
    until a hard reset. Print-and-continue is strictly better here.
    """

    def wrapper(*args):
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001
            print("rack_gui:", exc)

    return wrapper


class RackGUI:
    def __init__(self):
        # The pump starts here. Nothing is audible until play().
        self.live = audiolive.LiveAudio(volume=100)
        self.patch = 0
        self.slot = 0                     # which effect in the chain has focus
        self.sliders = []
        self.slider_labels = []
        self._build_screen()
        self.live.play(PATCHES[self.patch][1])
        self._bind_sliders()
        # The readout rides an LVGL timer, so it costs the audio nothing and
        # stops by itself when the screen goes away.
        self.timer = lv.timer_create(_guarded(self._on_tick), 500, None)

    # --- the screen -------------------------------------------------------

    def _build_screen(self):
        scr = lv.screen_active()
        scr.set_style_bg_color(BG, 0)
        scr.set_style_pad_all(0, 0)
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
        self.patch_buttons = []
        for i, (name, _chain) in enumerate(PATCHES):
            btn = lv.button(row)
            btn.set_size(lv.pct(100 // (len(PATCHES) + 2)), lv.pct(100))
            btn.set_style_bg_color(PANEL, 0)
            btn.set_style_bg_color(ACCENT, lv.STATE.CHECKED)
            btn.add_flag(lv.obj.FLAG.CHECKABLE)
            label = lv.label(btn)
            label.set_text(name)
            label.center()
            btn.add_event_cb(_guarded(self._make_patch_cb(i)),
                             lv.EVENT.CLICKED, None)
            self.patch_buttons.append(btn)
        self.patch_buttons[0].add_state(lv.STATE.CHECKED)

        # Which effect in the chain the sliders below belong to. Tapping one
        # rebuilds the sliders; it changes nothing about the audio.
        slot_row = lv.obj(scr)
        slot_row.set_size(hres - 2 * pad, unit)
        slot_row.align(lv.ALIGN.TOP_MID, 0, pad * 2 + unit)
        self._flat(slot_row)
        slot_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        slot_row.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY,
                                lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.slot_row = slot_row
        self.slot_buttons = []

        # The sliders live in their own container so a patch change can empty
        # it and refill it without touching anything else on screen.
        panel = lv.obj(scr)
        panel.set_size(hres - 2 * pad, vres - (unit * 3 + pad * 6))
        panel.align(lv.ALIGN.TOP_MID, 0, pad * 3 + unit * 2)
        self._flat(panel)
        panel.set_style_bg_color(PANEL, 0)
        panel.set_style_pad_all(pad, 0)
        panel.set_style_pad_row(pad, 0)
        panel.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        panel.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY, lv.FLEX_ALIGN.CENTER,
                             lv.FLEX_ALIGN.CENTER)
        self.panel = panel

        foot = lv.obj(scr)
        foot.set_size(hres - 2 * pad, unit)
        foot.align(lv.ALIGN.BOTTOM_MID, 0, -pad)
        self._flat(foot)
        foot.set_flex_flow(lv.FLEX_FLOW.ROW)
        foot.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER,
                            lv.FLEX_ALIGN.CENTER)

        self.bypass_btn = lv.button(foot)
        self.bypass_btn.set_size(unit * 2, lv.pct(100))
        self.bypass_btn.set_style_bg_color(PANEL, 0)
        self.bypass_btn.set_style_bg_color(ACCENT, lv.STATE.CHECKED)
        self.bypass_btn.add_flag(lv.obj.FLAG.CHECKABLE)
        lab = lv.label(self.bypass_btn)
        lab.set_text("BYPASS")
        lab.center()
        self.bypass_btn.add_event_cb(_guarded(self._on_bypass),
                                     lv.EVENT.VALUE_CHANGED, None)

        self.mic_btn = lv.button(foot)
        self.mic_btn.set_size(unit * 3 // 2, lv.pct(100))
        self.mic_btn.set_style_bg_color(PANEL, 0)
        self.mic_btn.set_style_bg_color(ACCENT, lv.STATE.CHECKED)
        self.mic_btn.add_flag(lv.obj.FLAG.CHECKABLE)
        lab = lv.label(self.mic_btn)
        lab.set_text("MIC")
        lab.center()
        self.mic_btn.add_event_cb(_guarded(self._on_mic),
                                  lv.EVENT.VALUE_CHANGED, None)

        self.readout = lv.label(foot)
        self.readout.set_style_text_color(FG, 0)
        self.readout.set_text("starting ...")

    def _flat(self, obj):
        obj.set_style_bg_opa(0, 0)
        obj.set_style_border_width(0, 0)
        obj.set_style_pad_all(0, 0)
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)

    # --- sliders follow whichever effect has focus ------------------------

    def _bind_sliders(self):
        """Throw the old sliders away and make one per macro of this effect."""
        self.slot_row.clean()
        self.slot_buttons = []
        for i, fx in enumerate(self.live.effects):
            btn = lv.button(self.slot_row)
            btn.set_size(lv.pct(40), lv.pct(100))
            btn.set_style_bg_color(ACCENT if i == self.slot else DIM, 0)
            lab = lv.label(btn)
            lab.set_text(type(fx).NAME.upper())
            lab.center()
            btn.add_event_cb(_guarded(self._make_slot_cb(i)),
                             lv.EVENT.CLICKED, None)
            self.slot_buttons.append(btn)

        self.panel.clean()
        self.sliders = []
        self.slider_labels = []
        labels = self.live.labels(self.slot)
        for index, name in enumerate(labels[:MAX_SLIDERS]):
            row = lv.obj(self.panel)
            row.set_size(lv.pct(100), lv.pct(100 // min(len(labels),
                                                        MAX_SLIDERS)) - 2)
            self._flat(row)
            row.set_flex_flow(lv.FLEX_FLOW.ROW)
            row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER,
                               lv.FLEX_ALIGN.CENTER)
            row.set_style_pad_column(12, 0)

            caption = lv.label(row)
            caption.set_text(name)
            caption.set_style_text_color(FG, 0)
            caption.set_width(lv.pct(28))

            slider = lv.slider(row)
            slider.set_flex_grow(1)
            slider.set_range(0, 127)
            slider.set_value(int(self.live.knob(self.slot, index)), 0)
            slider.set_style_bg_color(DIM, lv.PART.MAIN)
            slider.set_style_bg_color(ACCENT, lv.PART.INDICATOR)
            slider.set_style_bg_color(FG, lv.PART.KNOB)
            # The macro moves on every drag event. No park, no queue, no
            # handshake: audioif's control paths take the pump's lock around
            # their own swap, so the pull either sees the old value or the
            # new one and never something in between.
            slider.add_event_cb(_guarded(self._make_knob_cb(index)),
                                lv.EVENT.VALUE_CHANGED, None)

            readout = lv.label(row)
            readout.set_text("%d" % slider.get_value())
            readout.set_style_text_color(DIM, 0)

            self.sliders.append(slider)
            self.slider_labels.append(readout)

    # --- what the controls do ---------------------------------------------

    def _make_knob_cb(self, index):
        def cb(_e):
            value = self.sliders[index].get_value()
            self.live.knob(self.slot, index, value)
            self.slider_labels[index].set_text("%d" % value)

        return cb

    def _make_slot_cb(self, slot):
        def cb(_e):
            self.slot = slot
            self._bind_sliders()

        return cb

    def _make_patch_cb(self, index):
        def cb(_e):
            self.patch = index
            for i, btn in enumerate(self.patch_buttons):
                if i == index:
                    btn.add_state(lv.STATE.CHECKED)
                else:
                    btn.remove_state(lv.STATE.CHECKED)
            # play() builds the new chain first and only then points the pump
            # at it, with retarget(). The build is tens of milliseconds and
            # happens with the audio still running off the old chain; the
            # swap itself is a microsecond. What you hear is one small lump
            # where the new effects reset their buffers, not a gap.
            self.slot = 0
            self.live.play(PATCHES[index][1])
            self._bind_sliders()
            if self.bypass_btn.has_state(lv.STATE.CHECKED):
                self.live.bypass(True)

        return cb

    def _on_bypass(self, _e):
        self.live.bypass(self.bypass_btn.has_state(lv.STATE.CHECKED))

    def _on_mic(self, _e):
        on = self.mic_btn.has_state(lv.STATE.CHECKED)
        try:
            self.live.source("input" if on else "riff")
        except RuntimeError as exc:
            # Boards whose capture is on a different I2S port from playback
            # cannot do this; say so rather than failing silently.
            print("mic:", exc)
            self.mic_btn.remove_state(lv.STATE.CHECKED)

    # --- the pump's own numbers, twice a second ---------------------------

    def _on_tick(self, _t):
        s = self.live.status()
        self.readout.set_text(
            "load %d%%  blk %d/%d us  starved %d ms"
            % (s["load_pct"], s["worst_us"], s["block_us"], s["starved_ms"]))
        # There is no tap on the pump yet, so there is no level meter here:
        # nothing can read the audio going out without being in its path.
        # The cost numbers above are what the status block does publish.


gui = RackGUI()
