"""
fake_music.py -- band levels that move like a band playing, with no audio.

A stand-in for the real source (band levels published from C where the audio
passes). ``FakeMusic(n).levels(t)`` returns ``n`` levels in 0..1 for time ``t``
seconds, over log-spaced bands from 20 Hz to 20 kHz, mapped from -54..0 dB.

What it plays, at 120 BPM in an 8-second loop (four bars):

* a kick on every beat, a thump around 55 Hz that dies in a tenth of a second;
* a snare on beats 2 and 4, a broad crack centred near 1.5 kHz with some body;
* closed hats on the eighths and an open hat before each bar, fizz above 5 kHz
  with a different sparkle on every hit;
* a bass line and a three-note pad following the chords (Am, F, C, G);
* a lead line hopping round a pentatonic scale, with vibrato;
* a pink-ish tilt over the lot, falling about 3 dB an octave above 150 Hz.

Bar two ends in a dead stop (3.5 s to 4.25 s) so the bars and the peak caps
can be seen falling, then a breakdown of pad, lead and hats until 5.5 s, when
the drums and bass come back in.

Deterministic: every loop replays the same numbers from a seeded xorshift, so
a capture is repeatable and loops cleanly.
"""

import math

from spectrum_view import band_centres

BEAT = 0.5  # seconds, 120 BPM
LOOP = 8.0
FLOOR_DB = -54.0

# Chord per bar: bass root, pad notes (Hz).
CHORDS = (
    (55.00, (220.0, 261.6, 329.6)),  # Am
    (43.65, (174.6, 220.0, 261.6)),  # F
    (65.41, (196.0, 261.6, 329.6)),  # C
    (49.00, (196.0, 246.9, 293.7)),  # G
)
PENTA = (440.0, 523.3, 587.3, 659.3, 784.0, 880.0, 1046.5, 1174.7)


class XorShift:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF or 1

    def next(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s

    def uniform(self):
        return self.next() / 4294967296.0


def _gauss(x):
    return math.exp(-x * x)


class FakeMusic:
    def __init__(self, bands, seed=2026):
        self.n = bands
        self.seed = seed
        fc = band_centres(bands)
        self.oct = [math.log(f / 20.0) / math.log(2) for f in fc]  # octaves above 20 Hz
        self.bw_oct = math.log(1000) / math.log(2) / bands
        # Width of a partial's smear across bands, in octaves.
        self.sigma = max(0.16, self.bw_oct * 0.6)
        self.tilt = [10 ** (-0.3 * max(0.0, math.log(f / 150.0) / math.log(2))) for f in fc]
        # Fixed spectral shapes (linear power per band) of the noisy sounds.
        self.snare_w = [
            0.5 * _gauss((o - self._o(1500)) / 1.6) + 0.35 * _gauss((o - self._o(200)) / 0.4)
            for o in self.oct
        ]
        self.hat_w = [
            (1 / (1 + math.exp(-(o - self._o(6000)) * 3.0))) * _gauss((o - self._o(11000)) / 1.4)
            for o in self.oct
        ]
        self.room_w = [
            _gauss((o - self._o(400)) / 3.0) for o in self.oct
        ]  # reverb wash under everything
        self.kick_click_w = [_gauss((o - self._o(3500)) / 0.8) for o in self.oct]
        self._p = [0.0] * bands
        self._rng = XorShift(seed)
        self._loop = -1
        self._sparkle = [1.0] * bands
        self._hat_n = -1

    @staticmethod
    def _o(hz):
        return math.log(hz / 20.0) / math.log(2)

    def _partial(self, hz, power):
        """Add a pitched partial, smeared over the bands within reach of it."""
        if hz <= 20 or hz >= 20000 or power <= 0:
            return
        o = self._o(hz)
        sig = self.sigma
        centre = o / self.bw_oct - 0.5
        reach = int(2.5 * sig / self.bw_oct) + 1
        lo = max(0, int(centre) - reach)
        hi = min(self.n, int(centre) + reach + 2)
        p, oc = self._p, self.oct
        for i in range(lo, hi):
            d = (oc[i] - o) / sig
            p[i] += power * math.exp(-d * d)

    def levels(self, t):
        n = self.n
        p = self._p
        for i in range(n):
            p[i] = 0.0
        loop = int(t // LOOP)
        tl = t - loop * LOOP
        if loop != self._loop:
            self._loop = loop
            self._rng = XorShift(self.seed)
            self._hat_n = -1
        rng = self._rng

        stop = 3.5 <= tl < 4.25
        breakdown = 4.25 <= tl < 5.5
        drums = not stop and not breakdown
        bar = int(tl // (4 * BEAT)) % 4
        beat_t = tl % BEAT
        beat_i = int(tl // BEAT) % 4
        root, pad = CHORDS[bar]
        out = [FLOOR_DB] * n
        if stop:
            return [0.0] * n

        # Room wash: quiet, keeps the floor alive while the band plays.
        room = 0.000006 + 0.000006 * rng.uniform()
        for i in range(n):
            p[i] += room * self.room_w[i]

        if drums:
            k = math.exp(-beat_t / 0.09)
            kick_hz = 50 + 70 * math.exp(-beat_t / 0.02)
            self._partial(kick_hz, 1.0 * k)
            self._partial(kick_hz * 2, 0.25 * k)
            click = 0.02 * math.exp(-beat_t / 0.01)
            for i in range(n):
                p[i] += click * self.kick_click_w[i]
            if beat_i in (1, 3):
                s = 0.18 * math.exp(-beat_t / 0.11)
                for i in range(n):
                    p[i] += s * self.snare_w[i]
            # Bass: eighth notes pumping on the chord root, octave on the offbeat.
            e_t = tl % (BEAT / 2)
            off = int(tl // (BEAT / 2)) & 1
            b = 0.35 * (0.25 + 0.75 * math.exp(-e_t / 0.18))
            f = root * (2 if off else 1)
            for h in range(1, 5):
                self._partial(f * h, b / (h * h))

        # Hats: closed on the eighths, open on the last offbeat of each bar.
        e_n = int(tl // (BEAT / 2))
        e_t = tl % (BEAT / 2)
        if e_n != self._hat_n:
            self._hat_n = e_n
            for i in range(n):
                self._sparkle[i] = 0.35 + 1.3 * rng.uniform()
        open_hat = (e_n % 8) == 7
        acc = 1.0 if (e_n & 1) else 0.55
        hat = 0.5 * acc * math.exp(-e_t / (0.2 if open_hat else 0.035))
        sp = self._sparkle
        for i in range(n):
            p[i] += hat * self.hat_w[i] * sp[i]

        # Pad: swells in on each bar.
        bar_t = tl % (4 * BEAT)
        swell = 0.02 * (1 - math.exp(-bar_t / 0.4)) * (1.4 if breakdown else 1.0)
        for note in pad:
            for h in range(1, 4):
                self._partial(note * h, swell / (h * h))

        # Lead: a new pentatonic note every sixteenth-ish, with vibrato.
        step = int(tl / 0.375)
        note = PENTA[(step * 5 + bar * 3 + (step >> 2)) % len(PENTA)]
        n_t = tl - step * 0.375
        vib = 1 + 0.012 * math.sin(2 * math.pi * 5.5 * tl)
        lead = 0.05 * (0.35 + 0.65 * math.exp(-n_t / 0.25))
        for h in range(1, 6):
            self._partial(note * vib * h, lead / h)

        # To 0..1 over -60..0 dB, with the tilt applied.
        tilt = self.tilt
        for i in range(n):
            v = p[i] * tilt[i]
            if v > 1e-6:
                out[i] = 10 * math.log10(v)
        return [(d - FLOOR_DB) / -FLOOR_DB for d in out]
