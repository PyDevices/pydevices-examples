# deps: audioinstruments, lvgl, multimer
# gallery: featured, newwindow
"""
drum_machine.py — 16-step drum sequencer with ten classic drum machines.

Four instrument rows (kick, snare, closed hat, open hat — pitches 36/38/42/46,
shared by every machine in ``audioinstruments``) on an LVGL buttonmatrix, a
step-position indicator, transport with BPM and volume controls, and a
dropdown that switches between the ten drum machines while the pattern keeps
playing. The PANEL button opens the generic Tier-0 instrument panel
(``drum_seq.panel``) over the current machine for macro and patch editing.

Where the firmware carries the audio pump, the groove is kept on the **audio
clock**: each step is handed to ``audiodev.pump``'s queue with the frame it
is to sound at, and the pump applies it on its own thread. A screen redraw
or a garbage collection then cannot move a hit. Where it does not, the same
pattern is fired from the wall-clock timer at the bottom of
``_on_step_timer`` and nothing about the example changes.

Designed on a 720×720 touch panel and laid out for 720×480 here, which fits
a browser window; other resolutions lay out proportionally.
Requires the ``audioinstruments`` package (``mip.install("audioinstruments",
index="https://PyDevices.github.io/mip")`` on a board; pip on desktop).
"""

# Desktop resolution override, before board_config is imported: the desktop
# board_config reads these; a board's board_config ignores them (its display
# is a fixed size), so an app can ask for its designed resolution without
# ever fighting real hardware.
from displaydev import env_set

env_set("PYDEVICES_WIDTH", 720)
env_set("PYDEVICES_HEIGHT", 480)
env_set("PYDEVICES_SCALE", 1.0)

import gc

# Wrapping millisecond ticks that exist on every runtime. The tick calls in
# MicroPython's own time module do not exist under CPython, so on the
# pyscript (Pyodide) host the step timer raised on every tick and the
# sequencer could never run there, however well the UI drew.
from multimer import ticks_add, ticks_diff, ticks_ms

import board_config
import appdev

app = appdev.App.current() or appdev.App(board_config)

import display_driver  # noqa: F401  (wires LVGL flush/input/event loop)
import lvgl as lv

import audioinstruments
import board_peripherals

# The audio clock. On a firmware that carries the audio pump, a note can be
# handed to `audiodev` stamped with the frame it is to sound at, and the pump
# applies it on its own thread at the top of that frame's block -- so the
# groove does not move when the screen redraws or the collector runs. On a
# firmware without one, `events()` is None and every line below falls back to
# the wall-clock timer this example has always used.
try:
    from audiodev import pump as audio_pump
except ImportError:
    audio_pump = None

try:
    from audioinstruments.sequencer import Sequencer
except ImportError:
    Sequencer = None

try:
    from drum_seq.panel import Panel
except ImportError:
    Panel = None

MACHINES = (
    "tr808", "tr909", "tr606", "tr707", "cr78",
    "dmx", "linndrum", "drumtraks", "sp1200", "simmons_sdsv",
)
DEFAULT_MACHINE = "tr808"

# Every machine maps these pitches; only the display names differ.
ROW_PITCHES = (36, 38, 42, 46)
N_ROWS = len(ROW_PITCHES)
N_STEPS = 16

# The spike's two-bar 808 groove, folded to one bar: kick, backbeat snare,
# 8th-note closed hats, open hat on the and-of-4 choked by the next downbeat.
DEFAULT_PATTERN = (
    {0, 6, 8, 14},           # kick
    {4, 12},                 # snare
    set(range(0, 16, 2)) - {14},  # closed hat (14 belongs to the open hat)
    {14},                    # open hat
)

BPM_MIN, BPM_MAX, BPM_STEP = 60, 200, 5

# How far in front of the audio the sequencer keeps the queue.
#
# In MILLISECONDS, converted to steps per tempo, because what it has to
# cover is the longest the interpreter can be away and that has nothing to
# do with the tempo. A step scheduled after its frame has gone past is a
# late note again. Measured on this desktop with the matrix repainting and
# a collector storm running: the worst gap between two calls of the 15 ms
# step timer was 100 ms. 300 ms is three times that, and it is 3 steps at
# 120 BPM and 4 at 200.
#
# The other end of the trade is the player. A step is read when it is
# scheduled, so anything inside this window is already committed: toggling
# a cell that close to the playhead would be heard next bar.
# `Sequencer.relay()` takes those back and reads the pattern again, which
# leaves only the step that is sounding right now -- which is why this can
# be set by the stall and not by the editing. Wider still would put more
# hits of one drum in the queue at once, and two hits of one drum in the
# queue retrigger imperfectly (see live-audio-path-sequenced.md).
AHEAD_MS = 300

# One bar of the fullest pattern is 64 hits; two steps of it is 8, and each
# scheduled hit is a press plus the release that chokes the one before it.
QUEUE_CAPACITY = 96

BG = lv.color_hex(0x101418)
FG = lv.color_hex(0xE0E0E0)
ACCENT = lv.color_hex(0xB00020)
STEP_OFF = lv.color_hex(0x2A2F36)
# The clock indicator. Green when the sequencer keeps time off the audio
# clock, amber when it has fallen back to the old step timer on a firmware
# that HAS a pump -- that is a different app and the screen has to say so.
CLOCK_OK = lv.color_hex(0x35C46A)
CLOCK_BAD = lv.color_hex(0xE8A317)


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
            import sys

            printer = getattr(sys, "print_exception", None)
            if printer is not None:
                printer(exc)
            else:
                # CPython and Pyodide: print(exc) gives the message with no
                # location, which is close to useless inside a callback.
                import traceback

                traceback.print_exception(type(exc), exc, exc.__traceback__)

    return wrapper


def _toolbar_button(parent, text, width, cb=None, event=None, checkable=False):
    btn = lv.button(parent)
    btn.set_size(width, lv.pct(100))
    if checkable:
        btn.add_flag(lv.obj.FLAG.CHECKABLE)
    label = lv.label(btn)
    label.set_text(text)
    label.center()
    if cb is not None:
        btn.add_event_cb(_guarded(cb), event, None)
    return btn, label


class _InstrumentAdapter:
    """The Tier-0 panel's adapter contract over an audioinstruments machine."""

    def __init__(self, dm):
        self._dm = dm
        inst = dm.inst
        self.script_name = dm.machine.upper()
        self._patch_keys = sorted(inst.patches.keys())
        self.patches = [inst.patches[k][0] for k in self._patch_keys]
        self.bypass = False
        self.macro_labels = list(inst.macro_labels)
        self.macro_count = len(self.macro_labels)
        self.engine_ready = True
        self.engine_error = 0
        self._cb = None

    @property
    def patch_index(self):
        index = self._dm.inst.patch_index
        return self._patch_keys.index(index) if index in self._patch_keys else 0

    @property
    def macro_values(self):
        inst = self._dm.inst
        return [int(inst.get_macro(i)) for i in range(self.macro_count)]

    def on_external_change(self, cb):
        self._cb = cb

    def set_macro(self, index, value):
        self._dm.inst.set_macro(index, value)

    def set_patch(self, index):
        self._dm.inst.program_change(self._patch_keys[index])

    def set_bypass(self, bypass):
        pass  # a drum machine has no bypass; the panel still draws the switch

    def request_reload(self):
        inst = self._dm.inst
        index = inst.patch_index
        inst.program_change(index if index is not None else 0)


class DrumMachine:
    def __init__(self):
        # The default profile is buffered for throughput; a sequencer firing
        # notes in real time pays that as note-to-sound delay (same reasoning
        # as piano.py).
        self.audio_out = board_peripherals.audio_out(latency="low")
        self.audio_out.attach(app)
        self.audio_out.set_volume(85)
        self.fmt = self.audio_out.format

        self.machine = DEFAULT_MACHINE
        self.inst = None
        self.pattern = [set(s) for s in DEFAULT_PATTERN]
        # The same pattern in the shape a sequencer reads, {step: (pitch, ...)}.
        # Kept beside the four sets rather than replacing them: the sets are
        # what the buttonmatrix is written against, and rebuilding sixteen
        # cells costs nothing.
        self.grid = {}
        self._rebuild_grid()
        # None on a build with no pump, and then nothing below happens.
        self.queue = audio_pump.events(QUEUE_CAPACITY) if audio_pump else None
        self.seq = None
        self.bpm = 120
        self.playing = False
        self.audio_started = False
        self._audio_retry_ms = 0
        self.step = 0
        self.panel = None
        self.panel_scr = None
        self.seq_scr = None
        self._indicator_active = -1

        self._build_ui()
        self._load_machine(DEFAULT_MACHINE, start_audio=True)
        self._sync_matrix_from_pattern()

        # One fast timer, two ways of keeping time behind it.
        #
        # With the pump: the timer tops up a queue of notes that already
        # carry the frame they sound at, so being late costs nothing at all.
        # Without: it fires each step itself against a wall-clock deadline,
        # so lv timer lateness never accumulates and after a UI stall the
        # groove resyncs instead of shifting. A stall longer than one step
        # drops the missed steps rather than machine-gunning them.
        self._next_step_ms = None
        self.timer = lv.timer_create(_guarded(self._on_step_timer), 15, None)

        # Collect little and often: left to itself the heap fills in tens of
        # seconds of audio and pays one long automatic mark-sweep pause;
        # collecting while the garbage is small costs ~1ms.
        self._gc_timer = lv.timer_create(_guarded(self._on_idle_collect), 2000, None)

    # ---------- audio ----------

    def _step_ms(self):
        return 60_000 // self.bpm // 4  # 16th notes

    def _ahead_steps(self):
        """AHEAD_MS as a whole number of steps at the current tempo."""
        step_ms = self._step_ms()
        return max(2, (AHEAD_MS + step_ms - 1) // step_ms)

    def _rebuild_grid(self):
        """Refresh {step: (pitch, ...)} from the four row sets, in place.

        In place because the sequencer holds this dict and reads a cell out
        of it when it schedules that step; handing it a new dict would leave
        it playing the old pattern.
        """
        self.grid.clear()
        for step in range(N_STEPS):
            hits = tuple(ROW_PITCHES[row] for row in range(N_ROWS)
                         if step in self.pattern[row])
            if hits:
                self.grid[step] = hits

    def _arm_sequencer(self, step=0):
        """Put the current kit on the audio clock, from ``step``.

        Called again after every kit change, and this is the reason: the kit
        change stops the player, which shuts the pump down and sets its frame
        clock back to zero. A sequencer still holding frames from before that
        is holding numbers a day in the future, and would play nothing ever
        again -- in silence, with no error anywhere.
        """
        self.seq = None
        if self.queue is None or Sequencer is None or self.inst is None:
            return
        if not self.inst.schedulable:
            return  # acoustickit: a strike is more than a press. Play it live.
        self.seq = Sequencer(
            self.queue, sample_rate=self.fmt.rate, bpm=self.bpm,
            steps=N_STEPS, ahead=self._ahead_steps(), now=audio_pump.now,
        )
        self.seq.track(self.inst, self.grid)
        if self.playing:
            self.seq.start(step=step)

    def _start_audio(self, step=0):
        """Connect the current kit to the speaker; report whether it took.

        A browser will not open audio until the page has had a user gesture --
        the wasm backend raises RuntimeError and the gallery host offers an
        Enable Audio control -- so a build-time connection is not something to
        die on. Nothing is playing yet at that point, so the attempt is simply
        repeated from PLAY and from a kit change, both of which are clicks.
        On a board it succeeds the first time and this costs one try/except.
        """
        if self.inst is None:
            return False
        try:
            self.audio_out.play(self.inst.output)
        except RuntimeError as err:
            if self.audio_started or not self._audio_retry_ms:
                print("drum_machine: audio is not open yet -", err)
            self.audio_started = False
            self._audio_retry_ms = ticks_ms()
            self._refresh_clock()
            return False
        self.audio_started = True
        self._arm_sequencer(step)
        self._refresh_clock()
        return True

    def _refresh_clock(self):
        """Say on the SCREEN which clock the pattern is keeping time on.

        A firmware with a pump and an example that is not using it is the
        failure this exists for: the sequencer falls back to the old step
        timer, the console gets one line, and every number after that is
        about a different app. It was missed exactly that way once.
        """
        label = getattr(self, "clock_label", None)
        if label is None:
            return
        if audio_pump is None:
            # No pump in this firmware. The timer IS the clock here and
            # saying so quietly is the honest answer, not a warning.
            label.set_text("TIMER")
            label.set_style_text_color(STEP_OFF, 0)
            return
        on_pump = bool(getattr(self.audio_out, "pumped", False))
        if on_pump and self.seq is not None:
            label.set_text("CLK AUDIO")
            label.set_style_text_color(CLOCK_OK, 0)
            return
        why = getattr(self.audio_out, "pump_refused", None)
        if why is None and self.seq is None:
            why = "this kit is not schedulable"
        label.set_text("CLK TIMER!")
        label.set_style_text_color(CLOCK_BAD, 0)
        print("drum_machine: keeping time on the OLD step timer -",
              why or "the pump did not take this graph")

    def _playhead(self):
        """The cell the audio is in, or -1 when nothing is playing.

        Derived from the clock rather than counted, so a repaint that is
        forty milliseconds late still lights the step that is sounding.
        """
        if self.seq is None:
            return self.step if self.playing else -1
        pos = self.seq.position
        return pos % N_STEPS if pos >= 0 else -1

    def _load_machine(self, name, start_audio=False):
        # THE STEP TIMER IS PAUSED FOR THE WHOLE OF THIS. Building a kit
        # takes a while -- `audioinstruments.create` plus a pre-warm of every
        # drum -- and LVGL's tick arrives on `micropython.schedule`, between
        # this function's own bytecodes. So `_on_step_timer` ran INSIDE the
        # load, saw `audio_started` False after the stop, and called
        # `_start_audio()` itself; the one at the bottom of this function
        # then asked for an I2S peripheral its own re-entrant copy was
        # already holding and got "Peripheral in use". The groove came off
        # the audio clock on every kit change, and before this sitting put
        # `CLK TIMER!` on the screen it did so in silence.
        timer = getattr(self, "timer", None)
        if timer is not None:
            timer.pause()
        try:
            self._load_machine_locked(name)
        finally:
            if timer is not None:
                timer.resume()

    def _load_machine_locked(self, name):
        # Where the groove is, before the pump's clock is reset under it.
        step = max(self._playhead(), 0)
        if self.inst is not None:
            self.inst.all_notes_off()
            if self.audio_started:
                if self.seq is not None:
                    self.seq.stop()   # take the outgoing kit's bar back
                self.audio_out.stop()
        self.inst = audioinstruments.create(
            name, self.fmt.rate, channel_count=self.fmt.channels
        )
        # Pre-warm before the output is attached: each drum builds its
        # wavetables lazily on first note_on, and paying that inside the
        # low-latency audio window makes a new kit stutter for its first
        # bar or two (dmx, with its 13 voices, was the worst). These hits
        # are inaudible - play() hasn't connected the output yet.
        for pitch in ROW_PITCHES:
            self.inst.note_on(pitch, velocity=1)
        self.inst.all_notes_off()
        self.machine = name
        names = dict(self.inst.note_map)
        for i, pitch in enumerate(ROW_PITCHES):
            self.row_labels[i].set_text(names.get(pitch, str(pitch)))
        self._start_audio(step)

    def _fire_step(self, step):
        """Play a step NOW. The wall-clock path only; the queue schedules."""
        for row, pitch in enumerate(ROW_PITCHES):
            if step in self.pattern[row]:
                self.inst.note_on(pitch, velocity=127)

    # ---------- UI ----------

    def _build_ui(self):
        scr = lv.screen_active()
        self.seq_scr = scr
        scr.set_style_bg_color(BG, 0)

        hres = lv.display_get_default().get_horizontal_resolution()
        vres = lv.display_get_default().get_vertical_resolution()
        pad = max(4, hres // 180)
        top_h = max(56, vres // 10)
        vol_h = max(40, vres // 16)
        ind_h = max(14, vres // 40)
        label_w = max(72, hres // 8)

        # --- transport bar (flex row: nothing can overlap) ---
        bar = lv.obj(scr)
        bar.set_size(hres - 2 * pad, top_h)
        bar.align(lv.ALIGN.TOP_MID, 0, pad)
        bar.set_style_bg_color(BG, 0)
        bar.set_style_border_width(0, 0)
        bar.set_style_pad_all(0, 0)
        bar.set_style_pad_column(pad * 2, 0)
        bar.set_flex_flow(lv.FLEX_FLOW.ROW)
        bar.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        bar.remove_flag(lv.obj.FLAG.SCROLLABLE)

        unit = hres // 9  # ~80px on the 720 panel
        self.play_btn, self.play_label = _toolbar_button(
            bar, "PLAY", unit * 5 // 4, self._on_play, lv.EVENT.VALUE_CHANGED,
            checkable=True,
        )
        self.play_btn.set_style_bg_color(ACCENT, lv.STATE.CHECKED)

        self.dropdown = lv.dropdown(bar)
        self.dropdown.set_options("\n".join(m.upper() for m in MACHINES))
        self.dropdown.set_selected(MACHINES.index(DEFAULT_MACHINE))
        self.dropdown.set_width(unit * 2)
        self.dropdown.add_event_cb(_guarded(self._on_machine), lv.EVENT.VALUE_CHANGED, None)

        _toolbar_button(bar, "CLEAR", unit, self._on_clear, lv.EVENT.CLICKED)

        self.panel_btn, _ = _toolbar_button(
            bar, "PANEL", unit, self._on_panel, lv.EVENT.CLICKED
        )
        if Panel is None:
            self.panel_btn.add_flag(lv.obj.FLAG.HIDDEN)

        spacer = lv.obj(bar)
        spacer.remove_style_all()
        spacer.set_height(1)
        spacer.set_flex_grow(1)

        _toolbar_button(
            bar, "-", unit * 3 // 5,
            lambda e: self._change_bpm(-BPM_STEP), lv.EVENT.CLICKED,
        )
        self.bpm_label = lv.label(bar)
        self.bpm_label.set_text("120 BPM")
        self.bpm_label.set_style_text_color(FG, 0)
        # Which clock this is keeping time on. See `_refresh_clock`.
        self.clock_label = lv.label(bar)
        self.clock_label.set_text("")
        self.clock_label.set_style_text_color(FG, 0)
        _toolbar_button(
            bar, "+", unit * 3 // 5,
            lambda e: self._change_bpm(BPM_STEP), lv.EVENT.CLICKED,
        )

        # --- volume row ---
        vol_row = lv.obj(scr)
        vol_row.set_size(hres - 2 * pad, vol_h)
        vol_row.align(lv.ALIGN.TOP_MID, 0, pad * 2 + top_h)
        vol_row.set_style_bg_color(BG, 0)
        vol_row.set_style_border_width(0, 0)
        vol_row.set_style_pad_all(0, 0)
        vol_row.set_style_pad_column(pad * 3, 0)
        vol_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        vol_row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        vol_row.remove_flag(lv.obj.FLAG.SCROLLABLE)

        vol_label = lv.label(vol_row)
        vol_label.set_text("VOL")
        vol_label.set_style_text_color(FG, 0)
        vol_label.set_width(label_w - pad * 3)

        self.vol_slider = lv.slider(vol_row)
        self.vol_slider.set_range(0, 100)
        self.vol_slider.set_value(85, 0)
        self.vol_slider.set_flex_grow(1)
        self.vol_slider.set_height(max(12, vol_h // 3))
        self.vol_slider.set_style_bg_color(STEP_OFF, lv.PART.MAIN)
        self.vol_slider.set_style_bg_color(ACCENT, lv.PART.INDICATOR)
        self.vol_slider.add_event_cb(_guarded(self._on_volume), lv.EVENT.VALUE_CHANGED, None)

        self.vol_readout = lv.label(vol_row)
        self.vol_readout.set_text("85")
        self.vol_readout.set_style_text_color(FG, 0)
        self.vol_readout.set_width(unit // 2)

        # --- step indicator ---
        grid_x = label_w + pad
        grid_w = hres - grid_x - pad
        self.cells = []
        y = pad * 3 + top_h + vol_h
        cell_w = grid_w // N_STEPS
        for i in range(N_STEPS):
            cell = lv.obj(scr)
            cell.set_size(cell_w - 2, ind_h)
            cell.set_pos(grid_x + i * cell_w, y)
            cell.set_style_bg_color(STEP_OFF, 0)
            cell.set_style_border_width(0, 0)
            cell.set_style_radius(2, 0)
            cell.remove_flag(lv.obj.FLAG.SCROLLABLE)
            self.cells.append(cell)

        # --- row labels + 4x16 step matrix ---
        matrix_y = y + ind_h + pad
        matrix_h = vres - matrix_y - pad

        self.row_labels = []
        for r in range(N_ROWS):
            l = lv.label(scr)
            l.set_text("?")
            l.set_style_text_color(FG, 0)
            l.set_width(label_w)
            l.set_pos(pad, matrix_y + (2 * r + 1) * matrix_h // (2 * N_ROWS) - 8)
            self.row_labels.append(l)

        btnm_map = []
        for r in range(N_ROWS):
            btnm_map.extend(str(s + 1) for s in range(N_STEPS))
            btnm_map.append("\n")
        btnm_map[-1] = ""  # last "\n" -> terminator

        self.btnm = lv.buttonmatrix(scr)
        self.btnm.set_pos(grid_x, matrix_y)
        self.btnm.set_size(grid_w, matrix_h)
        self.btnm.set_map(btnm_map)
        self.btnm.set_style_bg_color(BG, 0)
        self.btnm.set_style_border_width(0, 0)
        self.btnm.set_style_bg_color(ACCENT, lv.PART.ITEMS | lv.STATE.CHECKED)
        # CLICK_TRIG matters: without it, buttonmatrix sends VALUE_CHANGED on
        # *press*, before the CHECKED toggle (which happens on release), so a
        # callback reads the pre-toggle state. With it, the event arrives on
        # release, after the toggle.
        for i in range(N_ROWS * N_STEPS):
            self.btnm.set_button_ctrl(
                i, lv.buttonmatrix.CTRL.CHECKABLE | lv.buttonmatrix.CTRL.CLICK_TRIG
            )
        self.btnm.add_event_cb(
            _guarded(self._on_step_toggled), lv.EVENT.VALUE_CHANGED, None
        )

    def _sync_matrix_from_pattern(self):
        for row in range(N_ROWS):
            for step in range(N_STEPS):
                idx = row * N_STEPS + step
                if step in self.pattern[row]:
                    self.btnm.set_button_ctrl(idx, lv.buttonmatrix.CTRL.CHECKED)
                else:
                    self.btnm.clear_button_ctrl(idx, lv.buttonmatrix.CTRL.CHECKED)

    # ---------- callbacks ----------

    def _on_step_toggled(self, e):
        idx = self.btnm.get_selected_button()
        if idx < 0 or idx >= N_ROWS * N_STEPS:
            return
        row, step = divmod(idx, N_STEPS)
        self.toggle(row, step,
                    self.btnm.has_button_ctrl(idx,
                                              lv.buttonmatrix.CTRL.CHECKED))

    def toggle(self, row, step, on=None):
        """Turn one cell on or off; ``on=None`` flips it.

        A named operation rather than the body of a callback, so the
        sequencer's edit path can be driven from anywhere -- a probe, a MIDI
        controller, a pattern generator -- and not only by a finger.
        """
        if on is None:
            on = step not in self.pattern[row]
        idx = row * N_STEPS + step
        if on:
            self.pattern[row].add(step)
            self.btnm.set_button_ctrl(idx, lv.buttonmatrix.CTRL.CHECKED)
            # Immediate feedback while stopped: audition the hit.
            if not self.playing:
                self.inst.note_on(ROW_PITCHES[row], velocity=127)
        else:
            self.pattern[row].discard(step)
            self.btnm.clear_button_ctrl(idx, lv.buttonmatrix.CTRL.CHECKED)
        self._edited()

    def _edited(self):
        """The pattern changed under a bar that may already be scheduled."""
        self._rebuild_grid()
        if self.seq is not None:
            # Take back every step that has not sounded and read it again,
            # at the frame it already had. Without this an edit inside the
            # look-ahead window is not heard until the next bar, which reads
            # as a button that did not work.
            self.seq.relay()

    def _on_play(self, e):
        self.playing = self.play_btn.has_state(lv.STATE.CHECKED)
        self.play_label.set_text("STOP" if self.playing else "PLAY")
        if self.playing:
            if not self.audio_started:
                self._start_audio()
            self.step = 0
            self._next_step_ms = None
            if self.seq is not None:
                self.seq.start()
        else:
            if self.seq is not None:
                self.seq.stop()      # and take back what has not sounded
            self.inst.all_notes_off()
            self._paint_indicator(-1)

    def _on_machine(self, e):
        name = MACHINES[self.dropdown.get_selected()]
        if name != self.machine:
            self._load_machine(name)

    def _on_clear(self, e):
        for s in self.pattern:
            s.clear()
        self._sync_matrix_from_pattern()
        self._edited()

    def _on_volume(self, e):
        value = self.vol_slider.get_value()
        self.audio_out.set_volume(value)
        self.vol_readout.set_text(str(value))

    def _change_bpm(self, delta):
        self.bpm = min(BPM_MAX, max(BPM_MIN, self.bpm + delta))
        self.bpm_label.set_text("%d BPM" % self.bpm)
        if self.seq is not None:
            # The window is a number of milliseconds, so the number of STEPS
            # in it moves with the tempo. Set it before the bpm, or the
            # re-laid grid is laid with the old one.
            self.seq.ahead = self._ahead_steps()
            # Cancels what has not sounded and re-lays it on the new grid,
            # phase-locked to the next step -- so the tempo changes where the
            # player pressed the button, with no burst and no gap.
            self.seq.bpm = self.bpm

    def _on_step_timer(self, t):
        if self.playing and not self.audio_started:
            # The gallery host unlocks the AudioContext on the page's first
            # gesture (gallery-host.js), which can complete just after the PLAY
            # press that caused it. Retry about once a second rather than make
            # the visitor press PLAY twice.
            if ticks_diff(ticks_ms(), self._audio_retry_ms) > 1000:
                self._start_audio()
        if not self.playing:
            self._next_step_ms = None
            return
        if self.seq is not None:
            if not self.audio_out.pumped:
                # The pump stopped under us and audiodev went back to pulling
                # on this thread. So does the groove, mid-bar, rather than
                # scheduling into a queue nothing applies any more.
                self.seq.stop()
                self.seq = None
                self._next_step_ms = None
                self._refresh_clock()
            else:
                # The queue keeps the time. This tick only tops it up and
                # moves the light, and it may be as late as it likes at both.
                self.seq.tick()
                self.step = max(self._playhead(), 0)
                self._paint_indicator(self._playhead())
                return
        now = ticks_ms()
        if self._next_step_ms is None:
            self._next_step_ms = now
        late = ticks_diff(now, self._next_step_ms)
        if late < 0:
            return
        self._fire_step(self.step)
        self._paint_indicator(self.step)
        self.step = (self.step + 1) % N_STEPS
        step_ms = self._step_ms()
        self._next_step_ms = (
            ticks_add(self._next_step_ms, step_ms)
            if late < step_ms
            else ticks_add(now, step_ms)
        )

    def _on_idle_collect(self, t):
        gc.collect()

    def _paint_indicator(self, active):
        # Restyle only the two cells that change: every style write
        # invalidates its cell, and 16 invalidations per step is render
        # work the audio pump pays for on the board.
        prev = self._indicator_active
        if active == prev:
            return
        if 0 <= prev < N_STEPS:
            self.cells[prev].set_style_bg_color(STEP_OFF, 0)
        if 0 <= active < N_STEPS:
            self.cells[active].set_style_bg_color(ACCENT, 0)
        self._indicator_active = active

    # ---------- instrument panel ----------

    def _on_panel(self, e):
        if Panel is None or self.panel is not None:
            return
        scr = lv.obj(None)
        self.panel = Panel(_InstrumentAdapter(self), screen=scr)
        back = lv.button(scr)
        back.add_flag(lv.obj.FLAG.FLOATING)
        back.set_size(96, 40)
        back.align(lv.ALIGN.BOTTOM_RIGHT, -8, -8)
        back.set_style_bg_color(ACCENT, 0)
        label = lv.label(back)
        label.set_text("BACK")
        label.center()
        back.add_event_cb(_guarded(self._close_panel), lv.EVENT.CLICKED, None)
        self.panel_scr = scr
        lv.screen_load(scr)

    def _close_panel(self, e=None):
        lv.screen_load(self.seq_scr)
        if self.panel_scr is not None:
            self.panel_scr.delete()
        self.panel = None
        self.panel_scr = None


machine = DrumMachine()


def _on_quit(_e=None):
    try:
        machine.timer.pause()
        if machine.seq is not None:
            machine.seq.stop()
        if machine.audio_started:
            machine.audio_out.close()
    except Exception:
        pass


app.on(app.events.QUIT, _on_quit)
app.run()
