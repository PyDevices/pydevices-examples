# deps: lvgl
# gallery: featured
"""
drum_machine.py — 16-step drum sequencer with ten classic drum machines.

Four instrument rows (kick, snare, closed hat, open hat — pitches 36/38/42/46,
shared by every machine in ``audioinstruments``) on an LVGL buttonmatrix, a
step-position indicator, transport with BPM control, and a dropdown that
switches between the ten drum machines while the pattern keeps playing.

Sized for a 720×720 touch panel; other resolutions lay out proportionally.
Requires the ``audioinstruments`` package (``mip.install("audioinstruments",
index="https://PyDevices.github.io/mip")`` on a board; pip on desktop).
"""

import board_config
import appdev

app = appdev.App.current() or appdev.App(board_config)

import display_driver  # noqa: F401  (wires LVGL flush/input/event loop)
import lvgl as lv

import audioinstruments
import board_peripherals

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

BG = lv.color_hex(0x101418)
FG = lv.color_hex(0xE0E0E0)
ACCENT = lv.color_hex(0xB00020)
STEP_OFF = lv.color_hex(0x2A2F36)


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

            sys.print_exception(exc) if hasattr(sys, "print_exception") else print(exc)

    return wrapper


class DrumMachine:
    def __init__(self):
        self.audio_out = board_peripherals.audio_out()
        self.audio_out.attach(app)
        self.audio_out.set_volume(100)
        self.fmt = self.audio_out.format

        self.machine = DEFAULT_MACHINE
        self.inst = None
        self.pattern = [set(s) for s in DEFAULT_PATTERN]
        self.bpm = 120
        self.playing = False
        self.step = 0

        self._build_ui()
        self._load_machine(DEFAULT_MACHINE, start_audio=True)
        self._sync_matrix_from_pattern()

        self.timer = lv.timer_create(_guarded(self._on_step_timer), self._step_ms(), None)
        self.timer.pause()

    # ---------- audio ----------

    def _step_ms(self):
        return 60_000 // self.bpm // 4  # 16th notes

    def _load_machine(self, name, start_audio=False):
        was_playing = self.playing
        if self.inst is not None:
            self.inst.all_notes_off()
            self.audio_out.stop()
        self.inst = audioinstruments.create(
            name, self.fmt.rate, channel_count=self.fmt.channels
        )
        self.machine = name
        names = dict(self.inst.note_map)
        for i, pitch in enumerate(ROW_PITCHES):
            self.row_labels[i].set_text(names.get(pitch, str(pitch)))
        self.audio_out.play(self.inst.output)
        if not (was_playing or start_audio):
            # play() is what opens the transport; keep it open but silent.
            pass

    def _fire_step(self, step):
        for row, pitch in enumerate(ROW_PITCHES):
            if step in self.pattern[row]:
                self.inst.note_on(pitch, velocity=127)

    # ---------- UI ----------

    def _build_ui(self):
        scr = lv.screen_active()
        scr.set_style_bg_color(BG, 0)

        hres = lv.display_get_default().get_horizontal_resolution()
        vres = lv.display_get_default().get_vertical_resolution()
        pad = max(4, hres // 180)
        top_h = max(56, vres // 9)
        ind_h = max(14, vres // 40)
        label_w = max(72, hres // 8)

        # --- transport bar ---
        bar = lv.obj(scr)
        bar.set_size(hres - 2 * pad, top_h)
        bar.align(lv.ALIGN.TOP_MID, 0, pad)
        bar.set_style_bg_color(BG, 0)
        bar.set_style_border_width(0, 0)
        bar.set_style_pad_all(pad, 0)
        bar.remove_flag(lv.obj.FLAG.SCROLLABLE)

        self.play_btn = lv.button(bar)
        self.play_btn.add_flag(lv.obj.FLAG.CHECKABLE)
        self.play_btn.set_size(top_h * 2, lv.pct(100))
        self.play_btn.align(lv.ALIGN.LEFT_MID, 0, 0)
        self.play_btn.set_style_bg_color(ACCENT, lv.STATE.CHECKED)
        self.play_label = lv.label(self.play_btn)
        self.play_label.set_text("PLAY")
        self.play_label.center()
        self.play_btn.add_event_cb(
            _guarded(self._on_play), lv.EVENT.VALUE_CHANGED, None
        )

        self.dropdown = lv.dropdown(bar)
        self.dropdown.set_options("\n".join(m.upper() for m in MACHINES))
        self.dropdown.set_selected(MACHINES.index(DEFAULT_MACHINE))
        self.dropdown.set_width(hres // 4)
        self.dropdown.align(lv.ALIGN.LEFT_MID, top_h * 2 + pad * 2, 0)
        self.dropdown.add_event_cb(
            _guarded(self._on_machine), lv.EVENT.VALUE_CHANGED, None
        )

        clear_btn = lv.button(bar)
        clear_btn.set_size(top_h * 3 // 2, lv.pct(100))
        clear_btn.align(lv.ALIGN.LEFT_MID, top_h * 2 + hres // 4 + pad * 4, 0)
        lbl = lv.label(clear_btn)
        lbl.set_text("CLEAR")
        lbl.center()
        clear_btn.add_event_cb(_guarded(self._on_clear), lv.EVENT.CLICKED, None)

        # BPM cluster, right-aligned: [-] 120 [+]
        bpm_plus = lv.button(bar)
        bpm_plus.set_size(top_h, lv.pct(100))
        bpm_plus.align(lv.ALIGN.RIGHT_MID, 0, 0)
        lbl = lv.label(bpm_plus)
        lbl.set_text("+")
        lbl.center()
        bpm_plus.add_event_cb(
            _guarded(lambda e: self._change_bpm(BPM_STEP)), lv.EVENT.CLICKED, None
        )

        self.bpm_label = lv.label(bar)
        self.bpm_label.set_text("120 BPM")
        self.bpm_label.set_style_text_color(FG, 0)
        self.bpm_label.align(lv.ALIGN.RIGHT_MID, -(top_h + pad * 2), 0)

        bpm_minus = lv.button(bar)
        bpm_minus.set_size(top_h, lv.pct(100))
        bpm_minus.align(lv.ALIGN.RIGHT_MID, -(top_h + pad * 4 + hres // 9), 0)
        lbl = lv.label(bpm_minus)
        lbl.set_text("-")
        lbl.center()
        bpm_minus.add_event_cb(
            _guarded(lambda e: self._change_bpm(-BPM_STEP)), lv.EVENT.CLICKED, None
        )

        # --- step indicator ---
        grid_x = label_w + pad
        grid_w = hres - grid_x - pad
        self.cells = []
        y = pad * 2 + top_h
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
        for i in range(N_ROWS * N_STEPS):
            self.btnm.set_button_ctrl(i, lv.buttonmatrix.CTRL.CHECKABLE)
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
        if self.btnm.has_button_ctrl(idx, lv.buttonmatrix.CTRL.CHECKED):
            self.pattern[row].add(step)
            # Immediate feedback while stopped: audition the hit.
            if not self.playing:
                self.inst.note_on(ROW_PITCHES[row], velocity=127)
        else:
            self.pattern[row].discard(step)

    def _on_play(self, e):
        self.playing = self.play_btn.has_state(lv.STATE.CHECKED)
        self.play_label.set_text("STOP" if self.playing else "PLAY")
        if self.playing:
            self.step = 0
            self.timer.set_period(self._step_ms())
            self.timer.reset()
            self.timer.resume()
        else:
            self.timer.pause()
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

    def _change_bpm(self, delta):
        self.bpm = min(BPM_MAX, max(BPM_MIN, self.bpm + delta))
        self.bpm_label.set_text("%d BPM" % self.bpm)
        self.timer.set_period(self._step_ms())

    def _on_step_timer(self, t):
        self._fire_step(self.step)
        self._paint_indicator(self.step)
        self.step = (self.step + 1) % N_STEPS

    def _paint_indicator(self, active):
        for i, cell in enumerate(self.cells):
            cell.set_style_bg_color(ACCENT if i == active else STEP_OFF, 0)


machine = DrumMachine()


def _on_quit(_e=None):
    try:
        machine.timer.pause()
        machine.audio_out.close()
    except Exception:
        pass


app.on(app.events.QUIT, _on_quit)
app.run()
