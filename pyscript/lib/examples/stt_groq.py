# gallery: skip
"""Groq Whisper push-to-talk transcription.

Desktop: hold Left Ctrl while speaking, then release it.
Microcontrollers: hold the active-low BOOT button, then release it.
"""

import sys
import time

from secrets import GROQ_API_KEY

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not set in the environment")

import board_config as bc
import board_config
import appdev

app = appdev.App(board_config)
from stt import GroqSTT, STTClient


_client = STTClient(GroqSTT(GROQ_API_KEY), chunk_size=4096)
_recording = False


def _transcribe(pressed):
    global _recording
    try:
        print("Listening...")
        recording = _client.record(bc.audio_in, while_pressed=pressed, max_ms=30000)
        if not recording.pcm:
            print("No audio captured")
            return
        print("Transcribing %d PCM bytes..." % len(recording.pcm))
        result = _client.transcribe(recording, language="en")
        print("Transcript:", result.text)
    except Exception as exc:
        print("stt_groq:", exc)
    finally:
        _recording = False


def _desktop():
    import _thread
    import keys

    held = [False]

    def on_key(event):
        global _recording
        if event.key != keys.K_LCTRL:
            return
        held[0] = event.type == app.events.KEYDOWN
        if held[0] and not _recording:
            _recording = True
            _thread.start_new_thread(_transcribe, (lambda: held[0],))

    app.on([app.events.KEYDOWN, app.events.KEYUP], on_key)
    print("stt_groq: hold Left Ctrl to talk; release to transcribe")


def _microcontroller():
    global _recording
    import keys

    pressed = lambda: keys.K_LCTRL in bc.keypad.read()
    print("stt_groq: hold BOOT to talk; release to transcribe")
    while True:
        if pressed() and not _recording:
            _recording = True
            _transcribe(pressed)
        try:
            app.poll()
        except AttributeError:
            pass
        if hasattr(time, "sleep_ms"):
            time.sleep_ms(10)
        else:
            time.sleep(0.01)


if sys.implementation.name in ("micropython", "circuitpython") and sys.platform not in (
    "linux",
    "darwin",
    "win32",
    "unix",
    "webassembly",
    "emscripten",
):
    _microcontroller()
else:
    _desktop()