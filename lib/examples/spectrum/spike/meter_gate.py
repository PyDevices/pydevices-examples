"""Audio meter spike gate, board half. Mode set by the host before upload.

MODE 'off'  : sound card pump only (soundcard.py's configuration).
MODE 'c'    : plus the C meter analysing, nothing drawn.
MODE 'draw' : plus the spectrum drawing on the panel at frame rate.

Every 10 s: packets/s against 8000, pump% against the wire rate, the meter's
CPU cost and worst analysis time, and the drawing's fps. Logged to /gate.txt.
"""

import sys
import time

import _usbif
import board_peripherals as bp
import usbif.auto

MODE = "draw"
VOLUME = 20
WINDOWS = 8
TRACK = 0
CAPTURE_AT = 0
WIRE = 48000

_LOG = "/gate.txt"
try:
    import os

    os.remove(_LOG)
except OSError:
    pass


def log(*a):
    line = " ".join(str(x) for x in a)
    with open(_LOG, "a") as f:
        f.write(line + "\n")
    print(line)


dev = usbif.auto.device()
w = bp.AUDIO_OUT.wire
bp.audio_power(True, volume=VOLUME)
dev.functions("cdc", "uac")
kw = dict(rate=WIRE, bits=bp.AUDIO_OUT.default.bits, channels=bp.AUDIO_OUT.default.channels)
if w.mck is not None and w.mck >= 0:
    kw["mclk"] = w.mck
    kw["mclk_multiple"] = w.mck_fs
dev.uac_pump_stop()
_usbif.uac_pump_meter(0)
dev.uac_pump_start(w.sck, w.ws, w.sd, **kw)

spectrum = None
if MODE == "c":
    _usbif.uac_pump_meter(44, 20, 20000)
elif MODE == "draw":
    sys.path.insert(0, "/spectrum")
    import spectrum  # noqa: F811 -- starts drawing

    if TRACK:
        spectrum.music.track_start()
log("MEASURE start mode=%s volume=%d" % (MODE, VOLUME))

prev = None
k = 0
while k < WINDOWS:
    time.sleep_ms(10000)
    s = dev.uac_pump_stats()
    c = _usbif.uac_pump_clock()
    mt = _usbif.uac_pump_meter()
    host, wire, _ = dev.uac_pump_rate()
    cur = (s[1], c[0], c[4], s[3], mt[2], mt[3], mt[4], mt[6], c[2])
    if prev:
        k += 1
        dt = (cur[2] - prev[2]) / 1e6
        pump = (cur[0] - prev[0]) / dt
        pk = (cur[1] - prev[1]) / dt
        el = (cur[7] - prev[7]) or 1
        feed = 100 * (cur[5] - prev[5]) / el
        fft = 100 * (cur[6] - prev[6]) / el
        an = (cur[4] - prev[4]) / dt
        fps = spectrum.last_report if spectrum else ""
        dma = (cur[8] - prev[8]) / dt / 2
        log("MEASURE host=%d wire=%d pkts/s=%.1f pump%%=%.3f timeouts=%d "
            "dma_rate=%.1f meter: %.1f/s feed=%.2f%% fft=%.2f%% worst=%dus | %s"
            % (host, wire, pk, 100 * pump / (2 * wire) if wire else 0,
               cur[3] - prev[3], dma, an, feed, fft, mt[5], fps))
        if CAPTURE_AT and k == CAPTURE_AT and spectrum:
            spectrum.capture("/spectrum.raw")
            log("CAPTURED /spectrum.raw %dx%d" % (spectrum.view.width, spectrum.view.height))
    prev = cur

if spectrum and TRACK:
    tr = spectrum.music.track
    n = tr[3] or 1
    from spectrum_view import band_centres

    for i, hz in enumerate(band_centres(spectrum.view.bands)):
        log("BAND %2d %7.1f Hz max=%6.1f mean=%6.1f min=%6.1f dB" % (
            i, hz, tr[0][i] / 2 - 100, tr[2][i] / n / 2 - 100, tr[1][i] / 2 - 100))
    log("BANDS analyses=%d" % tr[3])
log("MEASURE done")
if spectrum:
    spectrum.timer.cancel() if hasattr(spectrum.timer, "cancel") else None
dev.uac_pump_stop()
