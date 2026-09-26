"""
pump_levels.py -- band levels from the sound card's C pump.

The real source behind the same interface as ``fake_music.FakeMusic``:
``PumpLevels(n).levels(t)`` returns ``n`` levels in 0..1. The work happens in
C, in usbif's UAC pump task, where the audio from the PC already passes. This
file only asks for the bands once and reads the latest levels each frame.

It needs a firmware whose ``_usbif`` has ``uac_pump_levels`` (usbif branch
``spike/audio-meter``) and something else running the sound card's pump,
such as ``soundcard.py``. With no audio flowing the levels stop advancing, and
after ``STALE_MS`` this returns zeros so the bars fall.

The mapping from dB to bar height is here, not in C, because it's a matter of
taste: ``FLOOR_DB`` is an empty bar, ``TOP_DB`` a full one, and ``TILT_DB``
lifts the top octaves a little per octave above ``TILT_FROM_HZ``, since music
has far less energy up there than a bar chart would like.
"""

from time import ticks_diff, ticks_ms

import _usbif

from spectrum_view import HIGH_HZ, LOW_HZ, band_centres

FLOOR_DB = -66.0
TOP_DB = -6.0
TILT_DB = 3.0  # per octave
TILT_FROM_HZ = 1000.0
STALE_MS = 150


def available():
    return hasattr(_usbif, "uac_pump_levels")


class PumpLevels:
    def __init__(self, bands, low_hz=LOW_HZ, high_hz=HIGH_HZ):
        self.bands = bands
        _usbif.uac_pump_meter(bands, low_hz, high_hz)
        self._buf = bytearray(bands)
        self._out = [0.0] * bands
        self._seq = -1
        self._fresh = ticks_ms()
        self.peak_db = -100.0
        self.rms_db = -100.0
        self.track = None  # set to track_start() to record per-band extremes
        # Per band: offset (tilt) in half-dB units, folded into one scale.
        import math

        span = 2.0 * (TOP_DB - FLOOR_DB)
        self._scale = 1.0 / span
        self._offset = []
        for hz in band_centres(bands):
            tilt = TILT_DB * math.log(hz / TILT_FROM_HZ) / math.log(2) if hz > TILT_FROM_HZ else 0
            # level = (byte + 2*tilt - 2*(FLOOR_DB + 100)) / span
            self._offset.append(2.0 * tilt - 2.0 * (FLOOR_DB + 100.0))

    def raw(self):
        """(seq, levels bytes, peak, rms) straight from C."""
        return _usbif.uac_pump_levels(self._buf)

    def levels(self, t=None):
        seq, buf, pk, rms = _usbif.uac_pump_levels(self._buf)
        out = self._out
        now = ticks_ms()
        if seq != self._seq:
            self._seq = seq
            self._fresh = now
            sc, off = self._scale, self._offset
            for i in range(self.bands):
                out[i] = (buf[i] + off[i]) * sc
            tr = self.track
            if tr and buf[0] | buf[self.bands // 2] | buf[-1]:
                hi, lo, tot = tr[0], tr[1], tr[2]
                for i in range(self.bands):
                    b = buf[i]
                    if b > hi[i]:
                        hi[i] = b
                    if b < lo[i]:
                        lo[i] = b
                    tot[i] += b
                tr[3] += 1
            self.peak_db = pk / 2 - 100
            self.rms_db = rms / 2 - 100
        elif ticks_diff(now, self._fresh) > STALE_MS:
            for i in range(self.bands):
                out[i] = 0.0
            self.peak_db = self.rms_db = -100.0
        return out

    def track_start(self):
        """Record each band's loudest, quietest and summed raw level (half-dB
        bytes) over every fresh analysis from now on, while audio flows."""
        n = self.bands
        self.track = [bytearray(n), bytearray(b"\xff" * n), [0] * n, 0]
        return self.track

    def close(self):
        _usbif.uac_pump_meter(0)
