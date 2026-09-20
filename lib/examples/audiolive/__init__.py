# deps: audioeffects, audioinstruments
# gallery: skip
"""audiolive - one object that owns the codec, the graph and the audio pump.

The audio pump (``audiopump``) is a C task that pulls your effect graph on
the core the interpreter is *not* on and writes every block straight into
I2S. That is what lets a display redraw, a USB stack and a Python loop all
run while the sound keeps its exact clock. This module is the surface over
it, so an app never touches I2S, never touches the codec registers, and
never has to know what a block is::

    import audiolive

    live = audiolive.LiveAudio()            # codec + I2S from the board config
    live.play(("Overdrive", "TapeDelay"))   # a riff through a two-effect rack
    live.knob(0, 0, 110)                    # effect 0, macro 0, 0-127
    live.input()                            # the microphone becomes the source
    print(live.status())                    # what the pump costs, per block
    live.stop()

Everything above is safe to call while the audio is playing. The reason is
in audioif's C: one recursive mutex that the pump holds for a block pull and
every control path holds around its own final swap. You do not lock
anything; you just call the setter.

Three sources, one surface: ``play()`` (a looped riff), ``instrument()``
(a synthio instrument you press notes on) and ``input()`` (the board's
microphone). All three feed the same chain of effects, so an example can
change its mind about where the sound comes from without rebuilding
anything downstream.

Boards
------
Everything physical is read from the board config, so the same code runs on
any board whose ``board_peripherals`` publishes an ``AUDIO_OUT`` capability
with an ``I2SWire`` on it - the port and pin numbers, published without
opening the peripheral, which is exactly what a consumer that drives I2S
itself is meant to use. Proven on the Waveshare ESP32-P4-WIFI6-Touch-LCD-4B.

On the desktop (the unix port) there is no I2S. The pump still runs, into a
RAM ring you drain yourself, which is enough to develop and debug a graph
before it goes near a board.
"""

import gc
from array import array

import audiocore
import audiomixer
import audioeffects
import audiopump

RATE = 48000
CHANNELS = 2

# One block of audio, in frames. The pump hands the driver a whole block per
# I2S write, so the DMA ring can never be shorter than one block - measured:
# a ring of two 128-frame descriptors plays a 256-frame chain perfectly and
# anything shorter starves. Four descriptors of one block is 21 ms of cushion
# at 48 kHz, which survives a garbage collection with room to spare.
BLOCK = 256
RING_BLOCKS = 4

# The Mixer is double-buffered, so its buffer in bytes is twice one block.
BUFFER_SIZE = BLOCK * CHANNELS * 2 * 2

BLOCKS_FOREVER = 0x7FFFFFFF

# A short riff to hear an effect working on. Six notes of E minor.
NOTES = (164.81, 196.00, 246.94, 329.63, 246.94, 196.00)
NOTE_MS = 400
PEAK = 8200                      # about -12 dBFS

# audioif's pump lock makes every control path safe by itself - the setter
# takes the lock around its own swap, so callers move knobs, press notes and
# retarget the pump with no ceremony at all. Firmware built before the lock
# landed has no such promise, and there the pump has to be parked at a block
# boundary instead. One test, one place, so nothing else in this file has to
# care which firmware it is running on.
LOCKED = hasattr(audiopump, "lock_stats")


def _safely(fn, *args):
    """Run a graph change without the pump reading a half-written graph."""
    if LOCKED:
        return fn(*args)
    if not audiopump.park():
        # A park that times out is not a reason to carry on regardless: an
        # unparked rewire is what panics the board.
        raise RuntimeError("pump would not park; nothing changed")
    try:
        return fn(*args)
    finally:
        audiopump.unpark()


def _pluck(out, at, frames, period, peak, seed):
    """One Karplus-Strong note, written interleaved into `out`.

    A noise burst round a delay line one period long, averaged with its own
    neighbour each lap. The averaging is the string's damping; the squared
    ramp on top is what stops one note ringing into the next.
    """
    line = array("i", bytes(4 * period))
    s = seed | 1
    for i in range(period):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        line[i] = ((s >> 11) & 0xFFFF) - 32768
    p = 0
    for i in range(frames):
        a = line[p]
        q = p + 1
        if q == period:
            q = 0
        v = (a + line[q]) >> 1
        v -= v >> 6
        line[p] = v
        p = q
        r = 16384 - (i * 16384) // frames
        y = (a * ((r * r) >> 14)) >> 14
        y = (y * peak) >> 15
        out[at] = y
        out[at + 1] = y
        at += 2
    return at


def riff(rate=RATE, notes=NOTES, note_ms=NOTE_MS, peak=PEAK):
    """The default material: a plucked phrase, as a loopable RawSample."""
    frames = (rate * note_ms) // 1000
    buf = array("h", bytes(2 * CHANNELS * frames * len(notes)))
    at = 0
    for n, freq in enumerate(notes):
        at = _pluck(buf, at, frames, int(rate / freq), peak, 0x1234 + n * 7919)
    return buf


class LiveAudio:
    """The codec, the graph and the pump, as one object.

    Construct it and the board's speaker is powered and its I2S port is
    open, clocking silence. Nothing is audible until you call ``play()``.

    Optional keywords: ``rate``, ``channels``, ``volume`` (0-100),
    ``block`` (frames per pull) and ``ring_blocks`` (the DMA cushion, in
    blocks). Shorter is lower latency and less room to survive a stall;
    the floor is one block.
    """

    def __init__(self, rate=RATE, channels=CHANNELS, volume=100,
                 block=BLOCK, ring_blocks=RING_BLOCKS):
        if audiopump.running():
            raise RuntimeError("a pump is already running; stop() it first")
        self.rate = rate
        self.channels = channels
        self.block = block
        self.chain = ()
        self.effects = []          # the live effect objects, in chain order
        self.source_name = None
        self._source = None        # what the chain is fed from
        self._tail = None          # what the pump is pointed at
        self._mixer = None
        self._riff = None
        self._instrument = None
        self._input = None
        self._bypassed = False
        self._status = bytearray(audiopump.STATUS_BYTES)
        self._ring = None
        self._dma_at_start = 0

        audioeffects.configure(rate, channels)

        self.on_board = hasattr(audiopump, "i2s_start")
        self.out_wire = None
        self.in_wire = None
        self.cushion = 0
        self.duplex = False
        self._bp = None

        if not self.on_board:
            # Desktop: no I2S and no codec, so the pump produces into a RAM
            # ring you drain yourself. Everything above the ring is the same
            # code that runs on a board.
            self._ring = bytearray(block * channels * 2 * 8)
            return

        # The board describes its own wiring: an I2SWire on the capability,
        # published without opening the peripheral, which is exactly what a
        # consumer that drives I2S itself is meant to read. `audio_power`
        # brings the codec and the amplifier up WITHOUT opening a stream.
        # Never `machine.I2S` here: an armed machine.I2S owns the port and
        # its write() path, and two owners of one peripheral is the failure
        # that sounds like silence.
        import board_peripherals as bp
        self._bp = bp
        self.out_wire = getattr(bp, "AUDIO_OUT").wire
        self.in_wire = getattr(getattr(bp, "AUDIO_IN", None), "wire", None)
        power = getattr(bp, "audio_power", None)
        if power is None:
            raise RuntimeError(
                "this board's board_peripherals has no audio_power role, so "
                "there is no way to power the codec without opening I2S; add "
                "one, or drive the codec directly as probes/listen.py does")
        power(True, volume=volume)

        w = self.out_wire
        # din= opens the RX half of the SAME channel pair, so one clock tree
        # drives capture and playback and the two DMAs cannot drift. The
        # input block is matched to the DMA descriptor on purpose: a read
        # that spans two descriptors costs a block of latency for nothing.
        din = -1
        if self.in_wire is not None and self.in_wire.port == w.port:
            din = self.in_wire.sd
        self.cushion = audiopump.i2s_start(
            w.port, w.sck, w.ws, w.sd, rate,
            bits=16, channels=channels,
            mclk=-1 if w.mck is None else w.mck, mclk_fs=w.mck_fs,
            dma_desc=ring_blocks, dma_frame=block, din=din)
        self.duplex = din >= 0

    # --- where the sound comes from --------------------------------------

    def source(self, what=None):
        """Point the chain at a source: 'riff', 'input', or an instrument."""
        if what is None:
            return self.source_name
        if what == "riff":
            if self._riff is None:
                self._riff = riff(self.rate)
            sample = audiocore.RawSample(self._riff, sample_rate=self.rate,
                                         channel_count=self.channels)
            mixer = audiomixer.Mixer(
                voice_count=1, sample_rate=self.rate,
                channel_count=self.channels, bits_per_sample=16,
                samples_signed=True, buffer_size=BUFFER_SIZE)
            mixer.voice[0].level = 1.0
            mixer.play(sample, voice=0, loop=True)
            self._mixer = mixer
            self._sample = sample
            new = mixer
        elif what == "input":
            if not hasattr(audiopump, "Input"):
                raise RuntimeError("this port has no audio input")
            if not self.duplex:
                raise RuntimeError(
                    "capture is not on the same I2S port as playback on this "
                    "board, so one channel pair cannot carry both")
            # An audiosample whose get_buffer is an I2S read, so the
            # microphone is a source like any other and the read is what
            # paces the pump.
            self._input = audiopump.Input(
                sample_rate=self.rate, channel_count=self.channels,
                frames=self.block)
            new = self._input
        else:
            import audioinstruments
            self._instrument = audioinstruments.create(
                what, self.rate, channel_count=self.channels)
            new = self._instrument.output
        self.source_name = what
        self._source = new
        if self.effects or audiopump.running():
            self._rebuild()
        return what

    def instrument(self, name="karplus"):
        """Play a synthio instrument from audiocomponents through the chain."""
        self.source(name)
        return self._instrument

    def input(self):
        """The board's microphone becomes the source. Wear headphones."""
        return self.source("input")

    @property
    def synth(self):
        """The live instrument, for note_on/note_off; None if there isn't one."""
        return self._instrument

    # --- the chain --------------------------------------------------------

    def play(self, chain=("Overdrive",), source="riff"):
        """Build a chain of effects and start (or re-point) the pump.

        ``chain`` is what audioeffects.Rack takes: effect names, or
        ``(name, options)`` pairs. An empty chain is a wire.
        """
        if isinstance(chain, str):
            chain = (chain,)
        self.chain = tuple(chain)
        if self._source is None:
            self.source(source)
        self._rebuild()
        return self.chain

    def _rebuild(self):
        """Build the new graph, then point the pump at it in one move."""
        old_rack = getattr(self, "_rack", None)
        # Built BEFORE the swap, not during it. Constructing an effect is tens
        # of milliseconds - far longer than the DMA cushion - so it must not
        # happen while the audio is held. The lock covers only the swap, which
        # is a microsecond.
        rack = audioeffects.create("Rack", self._source, self.rate,
                                   chain=self.chain)
        self._rack = rack
        self.effects = list(rack.effects)
        tail = self._source if self._bypassed else rack.output
        self._tail = tail
        if audiopump.running():
            # retarget() swaps the pump's target under the lock. The pump
            # finishes the block it is in and the next one comes from the new
            # graph; nothing is ever pulled half-rewired.
            _safely(audiopump.retarget, tail)
            if old_rack is not None:
                try:
                    old_rack.deinit()      # detached already, so this is safe
                except Exception as exc:
                    print("old rack deinit:", exc)
        else:
            gc.collect()
            self._dma_at_start = self._dma()
            if self.on_board:
                # sink=True: every block the pump pulls goes straight into
                # the I2S DMA, on the pump's own thread, with no Python in
                # the path at all.
                audiopump.spawn(tail, BLOCKS_FOREVER, self._status,
                                sink=True, timeout_ms=500)
            else:
                audiopump.spawn(tail, BLOCKS_FOREVER, self._status,
                                ring=self._ring, timeout_ms=500)
        gc.collect()

    def bypass(self, on=True):
        """Take the whole chain out of circuit, or put it back.

        A retarget rather than a Mix macro, so what you hear is genuinely the
        source with nothing in the way.
        """
        self._bypassed = bool(on)
        tail = self._source if on else self._rack.output
        self._tail = tail
        if audiopump.running():
            _safely(audiopump.retarget, tail)
        return self._bypassed

    # --- knobs ------------------------------------------------------------

    def knob(self, effect, macro, value=None):
        """Move one macro of one effect in the chain, on the 0-127 MIDI scale.

        ``effect`` is its position in the chain (or its NAME); ``macro`` is
        the position in that effect's MACRO_LABELS (or the label). Reading
        takes no value; setting takes 0-127.
        """
        fx = self._effect(effect)
        index = self._macro_index(fx, macro)
        if value is None:
            return fx.get_macro(index)
        _safely(fx.set_macro, index, value)
        return fx.get_macro(index)

    def patch(self, effect, index):
        """Apply a numbered patch to one effect - a MIDI program change."""
        fx = self._effect(effect)
        _safely(fx.program_change, index)
        return fx.patch_index

    def labels(self, effect):
        """The macro names of one effect, in order, for a GUI to read."""
        return type(self._effect(effect)).MACRO_LABELS

    def _effect(self, which):
        if isinstance(which, int):
            return self.effects[which]
        for fx in self.effects:
            if type(fx).NAME == which:
                return fx
        raise KeyError("no %s in this chain" % which)

    def _macro_index(self, fx, macro):
        if isinstance(macro, int):
            return macro
        return list(type(fx).MACRO_LABELS).index(macro)

    # --- what it costs ----------------------------------------------------

    def status(self):
        """What the pump is doing, as a dict a GUI can print every second.

        ``cost_us`` and ``worst_us`` are against ``block_us``: the time one
        block of audio lasts. As long as the worst block is under that, the
        ring never drains. ``starved`` is the real answer to "did I hear a
        hole" - the I2S DMA clocks out silence when the pump is late, so
        bytes the DMA sent that the pump never wrote ARE the silence, in
        bytes.
        """
        import struct
        w = struct.unpack("<%dQ" % audiopump.STATUS_WORDS, self._status)
        blocks = w[0] or 1
        block_us = self.block * 1000000 // self.rate
        dma = self._dma() - self._dma_at_start
        starved = dma - w[15] if dma else 0
        out = {
            "blocks": w[0],
            "cost_us": w[12] // blocks,
            "worst_us": w[20],
            "block_us": block_us,
            "load_pct": (w[12] // blocks) * 100 // block_us,
            "starved": starved if starved > 0 else 0,
            "starved_ms": (starved * 1000 // (self.rate * self.channels * 2)
                           if starved > 0 else 0),
            "timeouts": w[14],
            "error": w[5],
            "fault": w[24],
            "running": audiopump.running(),
        }
        if LOCKED:
            # How long the audio actually stood still inside somebody's swap.
            out["held_us"] = w[27]
        return out

    def _dma(self):
        if hasattr(audiopump, "i2s_dma_bytes"):
            return audiopump.i2s_dma_bytes()
        return 0

    def drain(self, buf):
        """Desktop only: take produced audio out of the RAM ring."""
        return audiopump.drain(buf)

    # --- the door out -----------------------------------------------------

    def stop(self):
        """Silence, and the pump gone with it.

        It also happens by itself on a soft reset - the pump registers a
        finaliser, and a soft reset runs finalisers on everything - so
        Ctrl-D or a fresh `mpftp run` always leaves the board quiet.
        """
        audiopump.shutdown()
        power = getattr(self._bp, "audio_power", None) if self._bp else None
        if power is not None:
            try:
                power(False)
            except Exception:
                pass
        self._tail = None
        self.effects = []
        gc.collect()
