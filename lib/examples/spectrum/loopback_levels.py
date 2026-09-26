"""
loopback_levels.py -- band levels from what the computer is playing.

The desktop counterpart of ``pump_levels.PumpLevels``, behind the same
interface as ``fake_music.FakeMusic``: ``LoopbackLevels(n).levels(t)`` returns
``n`` levels in 0..1. It records the default speaker's output through the
operating system's loopback (WASAPI loopback on Windows, the monitor source
on Linux) and analyses it on a background thread with numpy, so the drawing
timer only reads the latest levels.

It needs CPython with ``numpy`` and the ``soundcard`` package
(``pip install soundcard``). MicroPython has neither, so there the meter keeps
its other sources. The dB-to-bar mapping is the one ``pump_levels`` uses, so
the desktop and the P4 look alike for the same music.
"""

import math
import threading
import time

# The same dB-to-bar mapping as pump_levels (which needs _usbif, so it can't
# be imported on a desktop).
FLOOR_DB = -66.0
TOP_DB = -6.0
TILT_DB = 3.0  # per octave
TILT_FROM_HZ = 1000.0
from spectrum_view import HIGH_HZ, LOW_HZ

RATE = 48000
BLOCK = 2048  # samples per analysis: about 43 ms, ~23 Hz resolution
STALE_S = 0.15


def available():
    try:
        import numpy  # noqa: F401
        import soundcard  # noqa: F401
    except ImportError:
        return False
    return True


class LoopbackLevels:
    def __init__(self, bands, low_hz=LOW_HZ, high_hz=HIGH_HZ):
        import numpy as np
        import soundcard as sc

        self.bands = bands
        self._np = np
        self._out = [0.0] * bands
        self._latest = None
        self._fresh = 0.0
        self.peak_db = self.rms_db = -100.0
        span = high_hz / low_hz
        edges = [low_hz * span ** (i / bands) for i in range(bands + 1)]
        freqs = np.fft.rfftfreq(BLOCK, 1.0 / RATE)
        # Each band averages the FFT bins inside it; a band narrower than one
        # bin (the bottom octaves) takes the nearest bin.
        self._bins = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            idx = np.nonzero((freqs >= lo) & (freqs < hi))[0]
            if len(idx) == 0:
                idx = np.array([int(np.argmin(abs(freqs - math.sqrt(lo * hi))))])
            self._bins.append(idx)
        centres = [math.sqrt(lo * hi) for lo, hi in zip(edges[:-1], edges[1:])]
        self._tilt = np.array(
            [TILT_DB * math.log2(c / TILT_FROM_HZ) if c > TILT_FROM_HZ else 0.0 for c in centres]
        )
        self._window = np.hanning(BLOCK)
        # Full-scale sine through this window and FFT reads 0 dB.
        self._ref = self._window.sum() / 2
        speaker = sc.default_speaker()
        self.source = speaker.name
        self._mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        np = self._np
        with self._mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as rec:
            while self._run:
                data = rec.record(numframes=BLOCK)
                mono = data.mean(axis=1) if data.ndim > 1 else data
                if len(mono) < BLOCK:
                    continue
                mono = mono[-BLOCK:]
                mag = np.abs(np.fft.rfft(mono * self._window)) / self._ref
                power = mag * mag
                band = np.array([power[i].mean() for i in self._bins])
                db = 10.0 * np.log10(band + 1e-12) + self._tilt
                lvl = np.clip((db - FLOOR_DB) / (TOP_DB - FLOOR_DB), 0.0, 1.0)
                peak = float(np.max(np.abs(mono)))
                rms = float(np.sqrt(np.mean(mono * mono)))
                self._latest = lvl.tolist()
                self.peak_db = 20 * math.log10(peak + 1e-9)
                self.rms_db = 20 * math.log10(rms + 1e-9)
                self._fresh = time.monotonic()

    def levels(self, t=None):
        latest = self._latest
        if latest is not None and time.monotonic() - self._fresh < STALE_S:
            self._out[:] = latest
        else:
            self._out[:] = [0.0] * self.bands
            self.peak_db = self.rms_db = -100.0
        return self._out

    def close(self):
        self._run = False
