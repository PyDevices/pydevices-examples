# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Portable app-level audio helpers for ``board_peripherals.audio_out``.

Soft-synth mixer + one-shot SFX on top of the PCM ``audio_out`` contract.
Works on CPython, MicroPython, CircuitPython, PyScript, and Jupyter — anything
that exposes a PCMOutput-compatible device (``format``, ``write``, ``close``).

Typical instrument / game loop::

    import board_config
    from board_config import audio_out
    import appdev
    from audio import AudioEngine

    app = appdev.App(board_config)

    eng = AudioEngine(audio_out)
    eng.attach(app)              # pumps mixed PCM on a timer
    eng.note_on("c4", 261.63)    # hold while key is down
    eng.note_on("e4", 329.63)    # chord = multiple active voices
    eng.note_off("c4")
    eng.blip(880, ms=60)         # one-shot game SFX

Wave shapes are registered by name so apps can add custom oscillators without
forking the mixer.
"""

import array
import math
import struct

_TWO_PI = 2.0 * math.pi
_NOTE_BASE = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}


def midi_to_hz(note):
    """Equal-tempered Hz for MIDI note number (A4 = 69 = 440 Hz)."""
    return 440.0 * (2.0 ** ((float(note) - 69.0) / 12.0))


def note_to_midi(name):
    """Parse ``'C4'``, ``'F#3'``, ``'Bb5'`` → MIDI note number."""
    s = name.strip()
    if len(s) < 2:
        raise ValueError("bad note name %r" % (name,))
    letter = s[0].upper()
    if letter not in _NOTE_BASE:
        raise ValueError("bad note name %r" % (name,))
    i = 1
    accidental = 0
    if i < len(s) and s[i] in "#b":
        accidental = 1 if s[i] == "#" else -1
        i += 1
    octave = int(s[i:])
    return 12 * (octave + 1) + _NOTE_BASE[letter] + accidental


def note_to_hz(name):
    return midi_to_hz(note_to_midi(name))


def _wave_sine(phase):
    return math.sin(_TWO_PI * phase)


def _wave_square(phase):
    return 1.0 if phase < 0.5 else -1.0  # noqa: PLR2004


def _wave_triangle(phase):
    if phase < 0.25:  # noqa: PLR2004
        return phase * 4.0
    if phase < 0.75:  # noqa: PLR2004
        return 2.0 - phase * 4.0
    return phase * 4.0 - 4.0


def _wave_saw(phase):
    return 2.0 * phase - 1.0


def _wave_piano(phase):
    # Soft additive tone — enough body for a toy keyboard without samples.
    return (
        0.70 * math.sin(_TWO_PI * phase)
        + 0.22 * math.sin(_TWO_PI * 2.0 * phase)
        + 0.08 * math.sin(_TWO_PI * 3.0 * phase)
    )


_WAVES = {
    "sine": _wave_sine,
    "square": _wave_square,
    "triangle": _wave_triangle,
    "saw": _wave_saw,
    "piano": _wave_piano,
}


def register_wave(name, fn):
    """Register ``fn(phase_0_to_1) -> -1..1`` under *name*."""
    _WAVES[name] = fn


def wave_names():
    return sorted(_WAVES.keys())


class Voice:
    """One mixer voice. Apps normally talk through :class:`AudioEngine`."""

    __slots__ = (
        "amp",
        "attack_left",
        "attack_total",
        "freq",
        "level",
        "phase",
        "release_left",
        "release_total",
        "releasing",
        "remaining",
        "wave",
    )

    def __init__(self, freq, amp, wave, remaining=-1, attack=64, release=96):
        self.freq = float(freq)
        self.amp = float(amp)
        self.phase = 0.0
        self.wave = wave if callable(wave) else _WAVES.get(wave, _wave_sine)
        self.remaining = int(remaining)
        self.attack_total = max(1, int(attack))
        self.attack_left = self.attack_total
        self.release_total = max(1, int(release))
        self.release_left = 0
        self.releasing = False
        self.level = 0.0

    def begin_release(self):
        if self.releasing:
            return
        self.releasing = True
        self.release_left = self.release_total


class Mixer:
    """Mixes active :class:`Voice` instances into mono int16 PCM frames."""

    def __init__(self, rate, *, master=0.55):
        self.rate = int(rate)
        self.master = float(master)
        self._voices = {}
        # Reusable float accumulator, grown (never shrunk) as render() is
        # called with larger *frames* -- avoids allocating a fresh `[0.0] *
        # frames` list every call, which is the exact allocation observed to
        # raise MemoryError under a note_on burst (each note_on kicks an
        # immediate render()) on memory-constrained ports.
        self._acc = array.array("f")
        # Smoothed per-block headroom gain: ramped across each render() call
        # rather than snapped, so voice-count changes (chord press/release)
        # don't produce an instantaneous volume-step click.
        self._scale = float(master)

    @property
    def voice_count(self):
        return len(self._voices)

    def active_ids(self):
        return list(self._voices.keys())

    def note_on(
        self, voice_id, freq, *, amp=0.5, wave="piano", duration_ms=-1, attack=64, release=96
    ):
        remaining = -1
        if duration_ms is not None and int(duration_ms) >= 0:
            remaining = max(1, int(self.rate * int(duration_ms) / 1000))
        self._voices[voice_id] = Voice(
            freq,
            amp,
            wave,
            remaining=remaining,
            attack=attack,
            release=release,
        )

    def note_off(self, voice_id, *, immediate=False):
        voice = self._voices.get(voice_id)
        if voice is None:
            return
        if immediate:
            del self._voices[voice_id]
        else:
            voice.begin_release()

    def note_off_all(self, *, immediate=False):
        if immediate:
            self._voices.clear()
            return
        for voice in self._voices.values():
            voice.begin_release()

    def render(self, frames, buf=None):
        """Fill *frames* of mono int16 little-endian PCM into *buf* (or new)."""
        nbytes = frames * 2
        if buf is None or len(buf) < nbytes:
            buf = bytearray(nbytes)

        if not self._voices:
            for i in range(0, nbytes, 2):
                struct.pack_into("<h", buf, i, 0)
            return memoryview(buf)[:nbytes]

        inv_rate = 1.0 / float(self.rate)
        master = self.master
        dead = []

        # Accumulate float samples then pack — clearer than per-voice packing.
        # Reuse self._acc (growing it only when frames outgrows the current
        # capacity) instead of allocating a fresh list every call.
        acc = self._acc
        if len(acc) < frames:
            acc.extend([0.0] * (frames - len(acc)))
        for i in range(frames):
            acc[i] = 0.0
        for vid, voice in self._voices.items():
            wf = voice.wave
            freq = voice.freq
            amp = voice.amp
            phase = voice.phase
            for i in range(frames):
                if voice.attack_left > 0:
                    voice.attack_left -= 1
                    voice.level = 1.0 - (voice.attack_left / float(voice.attack_total))
                elif voice.releasing:
                    if voice.release_left <= 0:
                        dead.append(vid)
                        break
                    voice.release_left -= 1
                    voice.level = voice.release_left / float(voice.release_total)
                else:
                    voice.level = 1.0

                if voice.remaining == 0:
                    voice.begin_release()
                elif voice.remaining > 0:
                    voice.remaining -= 1

                sample = wf(phase) * amp * voice.level
                acc[i] += sample
                phase += freq * inv_rate
                if phase >= 1.0:
                    phase -= math.floor(phase)
            voice.phase = phase

        for vid in dead:
            self._voices.pop(vid, None)

        n = max(1, len(self._voices) if self._voices else 1)
        # Soft headroom so chords don't clip hard.
        target_scale = master * (1.0 / math.sqrt(float(n)))
        start_scale = self._scale
        step = (target_scale - start_scale) / float(frames) if frames > 1 else 0.0
        scale = start_scale
        for i in range(frames):
            v = int(acc[i] * scale * 32767.0)
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            struct.pack_into("<h", buf, i * 2, v)
            scale += step
        self._scale = target_scale
        return memoryview(buf)[:nbytes]


def _resolve_out(out):
    if out is not None:
        return out
    import board_config

    # Lazy bind: first attribute access constructs PCMOutput.
    return board_config.audio_out


class AudioEngine:
    """App-facing engine: polyphonic notes, SFX, and tick-driven PCM pumping.

    Pass an existing PCMOutput (``board_config.audio_out``) or ``None`` to
    resolve it lazily on first use.
    """

    def __init__(self, out=None, *, chunk_ms=40, master=0.55, wave="piano"):
        self._out = out
        self._opened = False
        self.chunk_ms = int(chunk_ms)
        self.default_wave = wave
        self._mixer = None
        self._master = float(master)
        self._buf = None
        self._frames = 0
        self._sfx_seq = 0
        self._tick_sub = None
        self._pumping = False
        # Time-based look-ahead: keep ~N chunks queued ahead of now so a
        # slow synchronous frame (redraw, GC, event dispatch) doesn't starve
        # the backend's queue before the next tick arrives. Kept minimal —
        # every extra chunk here is audible note_on-to-speaker latency for an
        # interactive instrument, not just anti-underrun slack.
        self._lookahead_chunks = 2
        self._max_catchup_chunks = 5
        self._sched_start_ms = None
        self._played_frames = 0

    @property
    def out(self):
        if self._out is None:
            self._out = _resolve_out(None)
        return self._out

    @property
    def format(self):
        return self.out.format

    @property
    def mixer(self):
        if self._mixer is None:
            fmt = self.format
            if fmt.channels != 1 or fmt.bits != 16:
                raise RuntimeError(
                    "AudioEngine expects mono 16-bit PCM (got channels=%s bits=%s)"
                    % (fmt.channels, fmt.bits)
                )
            self._mixer = Mixer(fmt.rate, master=self._master)
            self._frames = max(1, int(fmt.rate * self.chunk_ms / 1000))
            # Sized for the largest possible catch-up burst, not just one chunk.
            self._buf = bytearray(self._frames * self._max_catchup_chunks * 2)
        return self._mixer

    @property
    def voice_count(self):
        return self.mixer.voice_count if self._mixer is not None else 0

    def open(self):
        if not self._opened:
            self.out.open()
            self._opened = True
            # Touch mixer so format checks happen early.
            _ = self.mixer
        return self

    def note_on(self, voice_id, freq, *, amp=0.5, wave=None, duration_ms=-1):
        """Start/replace a voice. *freq* may be Hz (float/int) or a note name."""
        self.open()
        if isinstance(freq, str):
            freq = note_to_hz(freq)
        self.mixer.note_on(
            voice_id,
            freq,
            amp=amp,
            wave=wave if wave is not None else self.default_wave,
            duration_ms=duration_ms,
        )
        # Kick an immediate chunk so the first gesture unlocks Web Audio and
        # latency stays low on desktop mixers that queue Sounds.
        self.tick()

    def note_off(self, voice_id, *, immediate=False):
        if self._mixer is None:
            return
        self.mixer.note_off(voice_id, immediate=immediate)

    def note_off_all(self, *, immediate=False):
        if self._mixer is None:
            return
        self.mixer.note_off_all(immediate=immediate)

    def blip(self, freq=880, ms=80, *, amp=0.4, wave="square"):
        """One-shot SFX voice (auto-releases after *ms*)."""
        self._sfx_seq += 1
        vid = ("sfx", self._sfx_seq)
        self.note_on(vid, freq, amp=amp, wave=wave, duration_ms=ms)
        return vid

    def beep(self, freq=440, ms=200, *, amp=0.45, wave="sine"):
        """Alias of :meth:`blip` with gentler defaults."""
        return self.blip(freq, ms, amp=amp, wave=wave)

    def play_pcm(self, buf):
        """Write raw PCM matching ``self.format`` (does not go through the mixer)."""
        self.open()
        return self.out.write(buf)

    def tick(self, _=None):
        """Render one chunk and write it when voices are active.

        Safe to call from ``app.on_tick`` or after note changes. Re-entrant
        calls are ignored so a blocking ``write`` cannot nest another pump.
        """
        if self._pumping:
            return
        if self._mixer is None or self.mixer.voice_count == 0:
            # Nothing sounding — next note_on should not inherit a stale
            # look-ahead schedule from a previous (possibly long-idle) note.
            self._sched_start_ms = None
            out = self._out
            if out is not None:
                out.service()
            return
        self._pumping = True
        try:
            self.open()
            from multimer import ticks_diff, ticks_ms

            rate = float(self.mixer.rate)
            max_frames = self._frames * self._max_catchup_chunks
            now = ticks_ms()
            if self._sched_start_ms is None:
                self._sched_start_ms = now
                self._played_frames = 0
            elapsed_ms = ticks_diff(now, self._sched_start_ms)
            lookahead_ms = self._frames * self._lookahead_chunks * 1000.0 / rate
            target_frames = int((elapsed_ms + lookahead_ms) * rate / 1000.0)
            frames_needed = target_frames - self._played_frames
            if frames_needed > max_frames:
                frames_needed = max_frames
                self._played_frames = target_frames - max_frames
            if frames_needed <= 0:
                self.out.service()
                return
            pcm = self.mixer.render(frames_needed, self._buf)
            self.out.write(pcm)
            self.out.service()
            self._played_frames += frames_needed
        finally:
            self._pumping = False

    def attach(self, app, period_ms=None):
        """Subscribe ``tick`` to *app*'s shared timer; returns self."""
        ms = self.chunk_ms if period_ms is None else int(period_ms)
        if hasattr(app, "every"):
            self._tick_sub = app.every(ms, self.tick)
        else:
            async_ = getattr(app, "timer_async", False)
            self._tick_sub = app.on_tick(self.tick, period=ms, async_=async_)
        return self

    def detach(self):
        sub = self._tick_sub
        self._tick_sub = None
        if sub is None:
            return
        if hasattr(sub, "cancel"):
            sub.cancel()
        else:
            deinit = getattr(sub, "deinit", None)
            if deinit is not None:
                try:
                    deinit()
                except Exception:
                    pass

    def close(self):
        self.detach()
        if self._mixer is not None:
            self._mixer.note_off_all(immediate=True)
        if self._opened and self._out is not None:
            try:
                self._out.close()
            except Exception:
                pass
            self._opened = False
