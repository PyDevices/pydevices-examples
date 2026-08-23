# gallery: featured
# deps: pygraphics
# utils: audio
"""Two-octave landscape piano (480x320) with polyphonic touch and chords.

Uses ``utils.audio.AudioEngine``. Touch or click keys to play; hold for
sustain; multiple keys (and the computer keyboard) sound together. Rotates a
portrait panel 90 degrees into landscape.
"""

from audio import AudioEngine, midi_to_hz
import board_config
import board_config
import appdev

app = appdev.App(board_config)
import board_peripherals

import keys
from pygraphics import Draw

display_drv = board_config.display_drv
# Built here rather than taken from board_config so it can ask for the
# interactive profile: the default is buffered for throughput, which a synth
# writing at realtime pays as note-to-sound delay.
audio_out = board_peripherals.audio_out(latency="low")

# Landscape keyboard target.
if display_drv.width < display_drv.height:
    display_drv.rotation = (display_drv.rotation + 90) % 360

WIDTH = display_drv.width
HEIGHT = display_drv.height

# C4 (MIDI 60) through C6 (MIDI 84) — two octaves + top C.
MIDI_LO = 60
MIDI_HI = 84

NOTE_NAMES = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

# Computer keyboard: whites on Z row, blacks on Q row (plus A-row for upper whites).
_KEY_TO_MIDI = {
    # White C4..B4
    keys.K_z: 60,
    keys.K_x: 62,
    keys.K_c: 64,
    keys.K_v: 65,
    keys.K_b: 67,
    keys.K_n: 69,
    keys.K_m: 71,
    # White C5..C6
    keys.K_COMMA: 72,
    keys.K_PERIOD: 74,
    keys.K_SLASH: 76,
    keys.K_a: 77,
    keys.K_s: 79,
    keys.K_d: 81,
    keys.K_f: 83,
    keys.K_g: 84,
    # Black C#4..A#4
    keys.K_q: 61,
    keys.K_w: 63,
    keys.K_e: 66,
    keys.K_r: 68,
    keys.K_t: 70,
    # Black C#5..A#5
    keys.K_y: 73,
    keys.K_u: 75,
    keys.K_i: 78,
    keys.K_o: 80,
    keys.K_p: 82,
}


def _c565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


COL_BG = _c565(0x1A, 0x12, 0x0E)
COL_CASE = _c565(0x3B, 0x24, 0x18)
COL_CASE_EDGE = _c565(0x5C, 0x3A, 0x28)
COL_GOLD = _c565(0xD4, 0xA0, 0x4A)
COL_GOLD_DIM = _c565(0x8A, 0x68, 0x30)
COL_IVORY = _c565(0xF4, 0xEF, 0xE4)
COL_IVORY_EDGE = _c565(0xC8, 0xC0, 0xB0)
COL_IVORY_PRESS = _c565(0xFF, 0xD0, 0x90)
COL_EBONY = _c565(0x18, 0x18, 0x1C)
COL_EBONY_EDGE = _c565(0x40, 0x40, 0x48)
COL_EBONY_PRESS = _c565(0x5A, 0x4A, 0x28)
COL_TEXT = _c565(0xF0, 0xE6, 0xD2)
COL_TEXT_DIM = _c565(0xA0, 0x90, 0x78)
COL_LED = _c565(0xE8, 0xC0, 0x50)


def _is_black(midi):
    return (midi % 12) in (1, 3, 6, 8, 10)


def _note_label(midi):
    return "%s%d" % (NOTE_NAMES[midi % 12], (midi // 12) - 1)


class Piano:
    def __init__(self):
        self.draw = Draw(display_drv)
        self.eng = AudioEngine(audio_out, chunk_ms=40, master=0.5, wave="piano")
        self.eng.attach(app)

        self.header_h = max(36, HEIGHT // 8)
        self.pad = max(4, min(WIDTH, HEIGHT) // 64)
        self.kb_y = self.header_h + self.pad // 2
        self.kb_h = HEIGHT - self.kb_y - self.pad

        self.white_midis = [m for m in range(MIDI_LO, MIDI_HI + 1) if not _is_black(m)]
        self.n_white = len(self.white_midis)
        self.white_w = WIDTH // self.n_white
        self.kb_w = self.white_w * self.n_white
        self.kb_x = (WIDTH - self.kb_w) // 2

        self.black_w = max(8, int(self.white_w * 0.58))
        self.black_h = int(self.kb_h * 0.62)

        self._white_geom = {}
        self._black_geom = {}
        self._build_geometry()

        # source_id -> midi
        self._sources = {}
        # midi -> refcount
        self._held = {}
        self._audio_ready = False
        # Android focus + mediaPlayback FGS + OpenSL take a few seconds on
        # first open. Warm here (before event handlers) and gate notes so
        # early taps do not queue up and play late when the stream catches up.
        self._status = "Starting audio…"
        self._draw_all()
        try:
            self.eng.open()
            self._audio_ready = True
            self._status = "Tap keys  |  Z-/  Q-P"
        except Exception as exc:
            self._audio_ready = False
            self._status = "Audio not available"
            print("piano: audio open failed: %r" % (exc,), flush=True)
        self._draw_all()

    def _build_geometry(self):
        y = self.kb_y
        h = self.kb_h
        for i, midi in enumerate(self.white_midis):
            x = self.kb_x + i * self.white_w
            self._white_geom[midi] = (x, y, self.white_w, h)

        for midi in range(MIDI_LO, MIDI_HI + 1):
            if not _is_black(midi):
                continue
            left = midi - 1
            while left >= MIDI_LO and _is_black(left):
                left -= 1
            if left not in self._white_geom:
                continue
            lx, _, lw, _ = self._white_geom[left]
            cx = lx + lw - self.black_w // 2
            self._black_geom[midi] = (cx, y, self.black_w, self.black_h)

    def _hit_test(self, x, y):
        for midi, (kx, ky, kw, kh) in self._black_geom.items():
            if kx <= x < kx + kw and ky <= y < ky + kh:
                return midi
        for midi, (kx, ky, kw, kh) in self._white_geom.items():
            if kx <= x < kx + kw and ky <= y < ky + kh:
                return midi
        return None

    def _press(self, source, midi):
        if midi is None:
            return
        if not self._audio_ready:
            if self._status != "Audio not available":
                self._status = "Starting audio…"
                self._draw_header()
                display_drv.show()
            return
        prev = self._sources.get(source)
        if prev == midi:
            return
        if prev is not None:
            self._release_source(source, redraw=False)
        self._sources[source] = midi
        self._held[midi] = self._held.get(midi, 0) + 1
        if self._held[midi] == 1:
            self.eng.note_on(midi, midi_to_hz(midi), amp=0.55, wave="piano")
        self._status = self._chord_status()
        self._draw_all()

    def _release_source(self, source, redraw=True):
        midi = self._sources.pop(source, None)
        if midi is None:
            return
        count = self._held.get(midi, 0) - 1
        if count <= 0:
            self._held.pop(midi, None)
            self.eng.note_off(midi)
        else:
            self._held[midi] = count
        self._status = self._chord_status()
        if redraw:
            self._draw_all()

    def _chord_status(self):
        if not self._held:
            return "Tap keys  |  Z-/  Q-P"
        return "  ".join(_note_label(m) for m in sorted(self._held.keys()))

    def _draw_key_white(self, midi, pressed):
        x, y, w, h = self._white_geom[midi]
        fill = COL_IVORY_PRESS if pressed else COL_IVORY
        self.draw.fill_rect(x + 1, y + 1, w - 2, h - 2, fill)
        self.draw.rect(x, y, w, h, COL_IVORY_EDGE)
        self.draw.hline(x + 2, y + h - 3, w - 4, COL_IVORY_EDGE)
        label = NOTE_NAMES[midi % 12]
        if len(label) == 1:
            self.draw.text(
                label,
                x + (w - 8) // 2,
                y + h - 18,
                COL_CASE if pressed else COL_TEXT_DIM,
            )

    def _draw_key_black(self, midi, pressed):
        x, y, w, h = self._black_geom[midi]
        fill = COL_EBONY_PRESS if pressed else COL_EBONY
        self.draw.fill_rect(x, y, w, h, fill)
        self.draw.rect(x, y, w, h, COL_GOLD_DIM if pressed else COL_EBONY_EDGE)
        self.draw.hline(x + 2, y + 2, w - 4, COL_EBONY_EDGE)

    def _draw_header(self):
        self.draw.fill_rect(0, 0, WIDTH, self.header_h, COL_CASE)
        self.draw.hline(0, self.header_h - 1, WIDTH, COL_GOLD)
        self.draw.text16("PyPiano", self.pad + 4, (self.header_h - 16) // 2, COL_TEXT)
        status = self._status
        max_chars = max(8, (WIDTH - 120) // 8)
        if len(status) > max_chars:
            status = status[: max_chars - 1] + "."
        sw = len(status) * 8
        self.draw.text(status, WIDTH - self.pad - sw - 4, (self.header_h - 8) // 2, COL_GOLD)

    def _draw_case(self):
        self.draw.fill_rect(0, self.header_h, WIDTH, HEIGHT - self.header_h, COL_BG)
        fx = self.kb_x - 3
        fy = self.kb_y - 3
        fw = self.kb_w + 6
        fh = self.kb_h + 6
        self.draw.round_rect(fx, fy, fw, fh, 4, COL_CASE, True)
        self.draw.round_rect(fx, fy, fw, fh, 4, COL_CASE_EDGE, False)
        self.draw.hline(fx + 4, fy + 2, fw - 8, COL_GOLD_DIM)

    def _draw_all(self):
        self._draw_header()
        self._draw_case()
        for midi in self.white_midis:
            self._draw_key_white(midi, midi in self._held)
        for midi in self._black_geom:
            self._draw_key_black(midi, midi in self._held)
        led = COL_LED if self._held else COL_GOLD_DIM
        self.draw.fill_rect(WIDTH - self.pad - 10, 8, 8, 8, led)
        display_drv.show()

    def on_pointer_down(self, source, pos):
        self._press(source, self._hit_test(pos[0], pos[1]))

    def on_pointer_move(self, source, pos):
        if source not in self._sources:
            return
        midi = self._hit_test(pos[0], pos[1])
        if midi is None:
            self._release_source(source)
        else:
            self._press(source, midi)

    def on_pointer_up(self, source, _pos=None):
        self._release_source(source)

    def on_key(self, key, pressed):
        midi = _KEY_TO_MIDI.get(key)
        if midi is None or midi < MIDI_LO or midi > MIDI_HI:
            return
        source = ("key", key)
        if pressed:
            self._press(source, midi)
        else:
            self._release_source(source)


piano = Piano()


def _on_mouse_button(e):
    if app.quit_requested:
        return
    # Finger path synthesizes mouse for the primary contact; ignore those so
    # multi-touch chords are not double-pressed.
    if getattr(e, "touch", False):
        return
    if e.button != 1:
        return
    if e.type == app.events.MOUSEBUTTONDOWN:
        piano.on_pointer_down("mouse", e.pos)
    else:
        piano.on_pointer_up("mouse", e.pos)


def _on_mouse_motion(e):
    if app.quit_requested:
        return
    if getattr(e, "touch", False):
        return
    if not e.buttons or not e.buttons[0]:
        return
    piano.on_pointer_move("mouse", e.pos)


def _on_finger(e):
    if app.quit_requested:
        return
    source = ("finger", e.finger_id)
    if e.type == app.events.FINGERDOWN:
        piano.on_pointer_down(source, e.pos)
    elif e.type == app.events.FINGERMOTION:
        piano.on_pointer_move(source, e.pos)
    else:
        piano.on_pointer_up(source, e.pos)


def _on_key(e):
    if app.quit_requested:
        return
    piano.on_key(e.key, e.type == app.events.KEYDOWN)


def _on_quit(_e=None):
    piano.eng.close()
    display_drv.quit()


app.on([app.events.MOUSEBUTTONDOWN, app.events.MOUSEBUTTONUP], _on_mouse_button)
app.on(app.events.MOUSEMOTION, _on_mouse_motion)
app.on(
    [app.events.FINGERDOWN, app.events.FINGERUP, app.events.FINGERMOTION],
    _on_finger,
)
app.on([app.events.KEYDOWN, app.events.KEYUP], _on_key)
app.on(app.events.QUIT, _on_quit)