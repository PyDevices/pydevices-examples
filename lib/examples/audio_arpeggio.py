# deps: audiodsp
"""
A C-major arpeggio: two octaves up and back down, twice, then a held chord.

synthio plays the notes, audiodsp's Biquad low-pass shapes them, and the
board's own audio output plays the result: an I2S amplifier on a board, the
sound card on a desktop, Web Audio in a browser. The screen shows a bar for each
note of the arpeggio, lit while it sounds. On a board with no display (no
board_config.py, only board_peripherals.py) it just plays, on MicroPython
or CircuitPython: a headless QT Py ESP32 Pico with an Audio BFF plays it. It first played on a QT Py
ESP32 Pico with an Audio BFF, from a CircuitPython-compatible build with
audiodsp compiled in.
"""

from array import array
from math import pi, sin

import appdev
import audiobiquad
import synthio

try:
    import board_config
except ImportError:  # a headless board: board_peripherals.py only
    board_config = None
app = appdev.App(board_config)
import board_peripherals  # noqa: E402  after the App, as the other examples do

audio_out = board_peripherals.audio_out()
# pydevices' AudioOut reports its format; CircuitPython's own I2SOut doesn't,
# and takes whatever rate it's given.
_format = getattr(audio_out, "format", None)
RATE = _format.rate if _format else 22050
CHANNELS = _format.channels if _format else 1

PEAK = 16000  # about -6 dBFS
SINE = array("h", [int(PEAK * sin(2 * pi * i / 256)) for i in range(256)])

synth = synthio.Synthesizer(
    sample_rate=RATE,
    channel_count=CHANNELS,
    envelope=synthio.Envelope(
        attack_time=0.01, decay_time=0.25, sustain_level=0.5, release_time=0.25
    ),
)
lowpass = audiobiquad.Biquad(
    mode=audiobiquad.LOW_PASS, frequency=3000.0, sample_rate=RATE, channel_count=CHANNELS
)
lowpass.play(synth)
if hasattr(audio_out, "attach"):  # CircuitPython's I2SOut runs on its own
    audio_out.attach(app)
audio_out.play(lowpass)

UP = [60, 64, 67, 72, 76, 79, 84]  # C4 E4 G4 C5 E5 G5 C6

display_drv = getattr(board_config, "display_drv", None)
if display_drv is not None:
    from displaydev import color565

    BACKGROUND = color565(16, 20, 40)
    DIM = color565(50, 60, 100)
    LIT = [
        color565(255, 90, 60),
        color565(255, 170, 40),
        color565(250, 230, 60),
        color565(90, 220, 110),
        color565(60, 200, 230),
        color565(90, 120, 255),
        color565(200, 100, 250),
    ]


def draw(lit):
    """A bar per arpeggio note, taller for higher notes; the sounding ones lit."""
    if display_drv is None:
        return
    w, h = display_drv.width, display_drv.height
    display_drv.fill(BACKGROUND)
    column = w // len(UP)
    for i, midi in enumerate(UP):
        bar = h * (i + 2) // (len(UP) + 2)
        color = LIT[i] if midi in lit else DIM
        display_drv.fill_rect(i * column + column // 6, h - bar, column * 2 // 3, bar, color)
    display_drv.show()


draw(())
SEQUENCE = (UP + UP[-2:0:-1]) * 2
STEP_MS = 160
CHORD_STEPS = 10  # the chord rings for 10 steps, then everything stops

state = {"step": 0, "note": None}


def note(midi, amplitude=1.0):
    return synthio.Note(frequency=synthio.midi_to_hz(midi), waveform=SINE, amplitude=amplitude)


def step(timer):
    if state["note"] is not None:
        synth.release(state["note"])
        state["note"] = None
    i = state["step"]
    state["step"] += 1
    if i < len(SEQUENCE):
        state["note"] = note(SEQUENCE[i])
        synth.press(state["note"])
        draw((SEQUENCE[i],))
    elif i == len(SEQUENCE):
        synth.press([note(m, 0.5) for m in (60, 64, 67, 72)])
        draw((60, 64, 67, 72))
    elif i == len(SEQUENCE) + CHORD_STEPS:
        synth.release_all()
        draw(())
    elif i > len(SEQUENCE) + CHORD_STEPS + 3:
        timer.deinit()
        audio_out.stop()
        print("arpeggio done")


app.every(STEP_MS, step)
app.run()
