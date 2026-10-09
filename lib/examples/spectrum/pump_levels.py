"""
pump_levels.py -- band levels from audiodsp's audiometer, fed in C.

The real sources behind the same interface as ``fake_music.FakeMusic``:
``PumpLevels(n).levels(t)`` returns ``n`` levels in 0..1. Python never sees a
sample. ``PumpLevels`` meters usbif's sound card: its pump feeds the meter on
its own core, where the audio from the PC already passes. ``TapLevels`` meters
any audiopump stream, the drum machine's for one, through the pump's tap; the
tap is read in C each time the levels are.

It needs a firmware with audiodsp's ``audiometer``. ``PumpLevels`` also needs
something running the sound card's pump, such as ``soundcard.py``. With no
audio flowing the levels stop advancing, and after ``STALE_MS`` this returns
zeros so the bars fall.

The mapping from dB to bar height is here, not in C, because it's a matter of
taste: ``FLOOR_DB`` is an empty bar, ``TOP_DB`` a full one, and ``TILT_DB``
lifts the top octaves a little per octave above ``TILT_FROM_HZ``, since music
has far less energy up there than a bar chart would like.
"""

from time import ticks_diff, ticks_ms

import audiometer

from spectrum_view import HIGH_HZ, LOW_HZ, band_centres

FLOOR_DB = -66.0
TOP_DB = -6.0
TILT_DB = 3.0  # per octave
TILT_FROM_HZ = 1000.0
STALE_MS = 150


def available():
    """True on a board where usbif's sound card can feed the meter.

    A desktop MicroPython build carries ``_usbif`` too, with no sound card
    behind it, so importing it isn't enough: the audio pump also has to own a
    real I2S peripheral. Without that the meter would wait on a sound card
    that never plays, and the bars would never move.
    """
    try:
        import _usbif  # noqa: F401

        from audiodev import pump
    except ImportError:
        return False
    return pump.on_board()


class PumpLevels:
    """The sound card's meter. ``source`` and ``rate`` are for TapLevels."""

    def __init__(self, bands, low_hz=LOW_HZ, high_hz=HIGH_HZ, source=audiometer.UAC, rate=None):
        self.bands = bands
        self.meter = audiometer.Meter(bands, low_hz=low_hz, high_hz=high_hz)
        if rate is None:
            self.meter.attach(source)
        else:
            self.meter.attach(source, rate)
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
        return self.meter.levels(self._buf)

    def levels(self, t=None):
        seq, buf, pk, rms = self.meter.levels(self._buf)
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
        self.meter.deinit()


class TapLevels(PumpLevels):
    """Any audiopump stream, through the pump's tap: ``TapLevels(n, rate)``.

    Attaches a tap of its own unless one is given. The pump has one tap at a
    time, and each reader keeps its own place in it, so a tap someone else
    attached (castfast's audio feed, say) can be shared.
    """

    def __init__(self, bands, rate=48000, low_hz=LOW_HZ, high_hz=HIGH_HZ, tap=None, channels=2):
        if tap is None:
            from audiodev import pump

            mod = pump.module()
            tap = mod.Tap(frames=4096, channel_count=channels)
            mod.tap(tap)
        self.tap = tap
        super().__init__(bands, low_hz, high_hz, source=tap, rate=rate)
