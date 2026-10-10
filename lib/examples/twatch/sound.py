"""Sound: a beep from the speaker, the microphone's level, and vibration
patterns. The speaker and microphone are opened when first used and closed
when you leave the app."""

import math

import board_config as board
import lvgl as lv

from . import services as sv
from . import ui

# DRV2605 library effects (TI's numbering): name, sequence. A number above 128
# is a pause of (n - 128) x 10 ms.
BUZZ_PATTERNS = (("Tap", (1,)), ("Double", (10,)), ("Buzz", (47,)), ("Alarm", (52, 128 + 20, 52, 128 + 20, 52)))


def main(scope):
    scr = ui.screen(scope, "Sound")
    state = {"out": None, "mic": None, "buf": None, "on": False}
    r = ui.row(scr)

    def beep():
        if state["out"] is None:
            from audiodev import AudioFormat

            state["out"] = scope.adopt(board.pcm_out(AudioFormat(16000, 1, 16)))
        n = 16000 * 150 // 1000
        buf = bytearray(2 * n)
        for i in range(n):
            v = int(12000 * math.sin(2 * math.pi * 1000 * i / 16000))
            buf[2 * i] = v & 0xFF
            buf[2 * i + 1] = (v >> 8) & 0xFF
        state["out"].write(buf)

    if sv.has_speaker:
        ui.button(r, "Beep", beep)
    mic_bar = lbl_mic = btn_lbl = None
    if sv.has_mic:

        def toggle_mic():
            state["on"] = not state["on"]
            if state["on"] and state["mic"] is None:
                state["mic"] = scope.adopt(board.pcm_in())
                state["buf"] = bytearray(1024)
            btn_lbl.set_text("Mic off" if state["on"] else "Mic on")

        btn = ui.button(r, "Mic on", toggle_mic)
        btn_lbl = btn.get_child(0)
        mic_bar = lv.bar(scr)
        mic_bar.set_width(lv.pct(90))
        mic_bar.set_range(0, 50)  # -50 to 0 dBFS
        lbl_mic = ui.label(scr, "", sv.small, sv.MUTED)
    if not sv.has_speaker and not sv.has_mic:
        ui.missing(scr, "no speaker or microphone role")
    if sv.haptic is not None:
        r = ui.row(scr)
        for name, seq in BUZZ_PATTERNS:
            ui.button(r, name, (lambda s: lambda: sv.buzz(*s))(seq), width=sv.W // 2 - 16)
    else:
        ui.missing(scr, "no vibration motor")

    def update():
        mic = state["mic"]
        if not (state["on"] and mic is not None):
            return
        buf = state["buf"]
        n = mic.readinto(buf)
        acc = 0
        count = n // 2
        for i in range(0, n, 2):
            v = buf[i] | (buf[i + 1] << 8)
            if v & 0x8000:
                v -= 0x10000
            acc += v * v
        rms = math.sqrt(acc / count) if count else 0
        db = 20 * math.log10(rms / 32768) if rms > 0 else -90
        mic_bar.set_value(int(max(0, 50 + db)), 0)
        lbl_mic.set_text("%.0f dBFS" % db)

    sv.use(scope, update)
