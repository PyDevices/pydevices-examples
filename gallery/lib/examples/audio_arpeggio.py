# deps: audiodsp
"""
A C-major arpeggio: two octaves up and back down, twice, then a held chord.

synthio plays the notes, audiodsp's Biquad low-pass shapes them, and the
board's own audio output plays the result: an I2S amplifier on a board, the
sound card on a desktop, Web Audio in a browser. It first played on a QT Py
ESP32 Pico with an Audio BFF, from a CircuitPython-compatible build with
audiodsp compiled in.
"""

import board_config
import appdev

app = appdev.App(board_config)
import board_peripherals
import synthio
import audiobiquad
from array import array
from math import pi, sin

audio_out = board_peripherals.audio_out()
RATE = audio_out.format.rate
CHANNELS = audio_out.format.channels

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
audio_out.attach(app)
audio_out.play(lowpass)

UP = [60, 64, 67, 72, 76, 79, 84]  # C4 E4 G4 C5 E5 G5 C6
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
    elif i == len(SEQUENCE):
        synth.press([note(m, 0.5) for m in (60, 64, 67, 72)])
    elif i == len(SEQUENCE) + CHORD_STEPS:
        synth.release_all()
    elif i > len(SEQUENCE) + CHORD_STEPS + 3:
        timer.deinit()
        audio_out.stop()
        print("arpeggio done")


app.every(STEP_MS, step)
app.run()
