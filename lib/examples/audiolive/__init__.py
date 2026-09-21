# deps: audioeffects, audioinstruments, pygraphics
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
try:
    # The pump's platform driver: the I2S channel, the microphone `Input` and
    # the round-trip probe. A separate module from `audiopump` because a
    # separate repo builds it -- the engine is portable and ships with
    # audioif everywhere, this half exists only where there is hardware. On a
    # build without it these examples have nothing to play through, and they
    # say so rather than failing on the import line.
    import _audioif
except ImportError:
    _audioif = None

RATE = 48000
CHANNELS = 2

# One block of audio, in frames: what the pump pulls from the graph at a time.
BLOCK = 256

# The DMA ring, in descriptors of so many frames. This is the LATENCY, and it
# is a different number from the block above - conflating the two was a bug
# here, because a 256-frame descriptor makes the smallest ring 21 ms when the
# same cushion in 128-frame pieces is 10.7 ms. The floor is one block: the
# pump hands the driver a whole block per write, so a ring shorter than one
# block cannot be full when the write returns. 4 x 128 is the smallest ring
# every class in the palette survives (ShimmerHall pulls 512 frames), and it
# ran ten minutes of garbage collection with zero starved bytes.
#
# Module-level so a board or a harness can lower them before constructing:
# 2 x 128 is one block, 5.3 ms, the lowest this board plays.
#
# A SCREEN COSTS YOU RING. Measured on the P4 with the CRUNCH board playing,
# 25 seconds each, as a fraction of the 5333 us a 256-frame block lasts:
#
#     no display at all                         41 %    0 ms starved
#     the panel lit and LVGL doing nothing      52 %    2 ms
#     sliders being dragged                     63 %   16 ms
#     whole-screen repaints forced on top       66 %   69 ms
#
# Two things to take from that. The first is that just LIGHTING the panel
# costs the pump eleven points before a finger touches it: a 720x720 16-bit
# framebuffer is a megabyte being read out of PSRAM for every frame the
# display clocks, and the graph lives in PSRAM too. That is a bandwidth tax
# on every block - a MEAN cost, not a tail one - so no amount of moving the
# flush to another core or raising the pump's priority reaches it. The second
# is what does reach it: ring. The worst block under a finger is 7.5-8.6 ms
# against a mean of 3.5, and the ring is what absorbs the difference.
#
# So an app with a screen sets a deeper ring, and rack_gui.py does exactly
# that. The same 190-second run with pedalboard changes, three thousand
# slider moves and forced repaints:
#
#     4 x 128   (10.7 ms)   silence all the way through
#     6 x 128   (16 ms)     381 ms of silence, all of it at patch changes
#     12 x 128  (32 ms)     seven of nine readings exactly 0 ms
DMA_DESC = 4
DMA_FRAME = 128

#: What an app with a lit screen should use on a board like the P4. 32 ms of
#: latency, which is inaudible for a pedalboard and far too much for playing
#: an instrument - so it is a constant an app opts into, not the default.
DMA_DESC_GUI = 12

#: Codec volume, 0-100, for every example here. Module-level for the same
#: reason DMA_DESC is: a board file or a harness sets `audiolive.VOLUME = 50`
#: once and every example follows, without editing three files. On the P4 the
#: speaker and the microphone are two inches apart, so anything running
#: `source="input"` in a room wants this down.
VOLUME = 100

# The Mixer is double-buffered, so its buffer in bytes is twice one block.
BUFFER_SIZE = BLOCK * CHANNELS * 2 * 2

BLOCKS_FOREVER = 0x7FFFFFFF

# Four pedalboards, shared by every example here so there is one list to
# read and one to edit. Each is a chain the way audioeffects.Rack takes one:
# a name, or a (name, options) pair. Two effects rather than five on
# purpose - LiveAudio.status() tells you what a third one costs before you
# commit to it.
# Measured on the P4 at 48 kHz stereo as a fraction of one block of audio,
# whole chain, ring at DMA_DESC_GUI: CRUNCH 41 %, DIRT 57 %, FUZZ 52 %,
# CLEAN 41 %, LO-FI 16 %. Anything over 100 % cannot play and the speaker
# fills the gap with silence, so `LiveAudio.status()` is how you find out
# what a third pedal would cost before you commit to it.
#
# Read `load_pct` against the block the chain actually returns, not the one
# you asked for: a class chooses its own length, `SlapbackDelay` hands back
# 512 frames where `Overdrive` hands back 256, and a percentage against the
# wrong denominator reads exactly double. That mistake has cost this spike
# three separate evenings.
PATCHES = (
    ("CRUNCH", (("Overdrive", {}), ("TapeDelay", {"mix": 0.22}))),
    ("DIRT", (("Distortion", {}), ("SlapbackDelay", {}))),
    ("FUZZ", (("Fuzz", {}), ("TapeDelay", {"mix": 0.22}))),
    ("CLEAN", (("Compressor", {}), ("Reverb", {"mix": 0.30}))),
    ("LO-FI", (("Bitcrusher", {}), ("AnalogDelay", {}))),
)

# The same five names for a board with about half the P4's arithmetic, and
# every chain here was measured on one. The T-Embed S3 runs the same code
# 1.6-2.3x slower, so a pedalboard there is one dear pedal or two cheap ones
# -- not any two the P4 will carry.
#
# Two classes are out of the list entirely. Measured on the T-Embed with the
# pump playing and nothing else running, against each class's OWN block
# (`docs/spikes/live-audio-path-s3.md` in the workspace anchor):
#
#     ShimmerHall   10.14 ms of its own 10.67 ms block -- 92 %, and it
#                   starves 21 ms in 8 seconds with nothing beside it
#     Reverb         5.54 ms of a 10.67 ms block -- 52 % with nothing after
#                   it, so a delay behind it does not fit
#
# And the P4's own pairs are too dear here even without those two:
# Overdrive -> TapeDelay reads 82 %, Fuzz -> TapeDelay 92 %, Bitcrusher ->
# AnalogDelay 73 % -- and an app with a screen and a knob on it adds 15-20
# points more, which is a hole in the audio rather than a slow app. What the
# list below costs, same conditions, 256-frame blocks, ring 4 x 128:
#
#     CRUNCH  Overdrive                  67 %
#     DIRT    Distortion                 70 %
#     FUZZ    Fuzz                       73 %
#     CLEAN   Compressor -> CabinetSim   66 %
#     LO-FI   Bitcrusher -> TapeDelay    64 %
LIGHT_PATCHES = (
    ("CRUNCH", (("Overdrive", {}),)),
    ("DIRT", (("Distortion", {}),)),
    ("FUZZ", (("Fuzz", {}),)),
    ("CLEAN", (("Compressor", {}), ("CabinetSim", {}))),
    ("LO-FI", (("Bitcrusher", {}), ("TapeDelay", {"mix": 0.22}))),
)

# What the pump publishes when it stops on its own, as sentences. Word 5 of
# the status block is the pump's own reason for breaking out of its loop;
# word 24 is the code audioif's funnel left behind on the way.
PUMP_ERRORS = {
    1: "a node in the graph returned no buffer",
    2: "a node in the graph returned a null buffer",
    3: "the source ran out",
    4: "the graph's memory was re-used under it",
    5: "a node in the graph faulted",
}
PUMP_FAULTS = {
    1: "something in the chain is not an audio node",
    2: "something in the chain was released while it was playing",
    3: "a file-backed source cannot be pulled by the pump",
    4: "a read that would have raised inside the pull",
}

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


def _play_voice(mixer, sample, voice, loop):
    """`mixer.play()` as a positional call, so `_safely` can wrap it."""
    mixer.play(sample, voice=voice, loop=loop)


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
    ``block`` (frames per pull), and ``dma_desc`` / ``dma_frame`` - the DMA
    ring, which is the latency. Shorter is lower latency and less room to
    survive a stall; the floor is one block of the graph you are playing.
    """

    def __init__(self, rate=RATE, channels=CHANNELS, volume=100,
                 block=BLOCK, dma_desc=None, dma_frame=None, level=1.0):
        # Read from the module rather than baked into the signature, so a
        # board file or a harness can set audiolive.DMA_DESC once and every
        # example here follows.
        dma_desc = DMA_DESC if dma_desc is None else dma_desc
        dma_frame = DMA_FRAME if dma_frame is None else dma_frame
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
        self._voices = 0
        self._built = {}           # name -> (audiosample, loop), cached
        self._insts = {}           # name -> the instrument object itself
        self._riff = None
        self._instrument = None
        self._input = None
        self._bypassed = False
        self._status = bytearray(audiopump.STATUS_BYTES)
        self._ring = None
        self._dma_at_start = 0
        #: The most silence the speaker has ever had to invent since play(),
        #: in bytes. See `status()` for why this is a high-water mark and not
        #: the instantaneous gap.
        self._starved_peak = 0
        self._retired = None
        self._rack = None
        # True from the moment a pump exists until we tear it down. The pump
        # can stop by itself - a fault takes it out of its loop - and then
        # `audiopump.running()` is False while the task is still registered,
        # so `spawn()` refuses with "a pump is already spawned". That pair is
        # the whole of the crash a GUI used to die with; `_recover()` below is
        # the answer to it.
        self._spawned = False
        self.volume = volume
        # What every source voice is opened at, 0.0-1.0. On a board with a
        # codec this is a trim and `volume` is the loudness; on a board whose
        # amplifier has no registers -- the T-Embed's MAX98357A has no I2C at
        # all -- it is the ONLY volume there is, because the loudness then
        # lives entirely in the samples.
        self.level = level

        audioeffects.configure(rate, channels)

        self.on_board = hasattr(_audioif, "i2s_start")
        self.out_wire = None
        self.in_wire = None
        self.cushion = 0
        self.duplex = False
        self._bp = None
        self._power = None

        if not self.on_board:
            # Desktop: no I2S and no codec, so the pump produces into a RAM
            # ring you drain yourself. Everything above the ring is the same
            # code that runs on a board.
            self._ring = bytearray(block * channels * 2 * 8)
            return
        self.dma_desc = dma_desc
        self.dma_frame = dma_frame

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
        # A board with a codec publishes `audio_power` so the codec and the
        # amplifier can be brought up WITHOUT opening a stream. A board with
        # no codec has nothing to switch: the T-Embed's MAX98357A is an
        # amplifier with no I2C, no register set and no volume, and its
        # `board_peripherals` raises the LilyGO rail (GPIO46) at import. So
        # importing that module is the whole of "power on" there, `volume`
        # has no hardware meaning, and `level` is the loudness.
        self._power = getattr(bp, "audio_power", None)
        self._open_codec()

    def _open_codec(self):
        """Power the codec and open the I2S port. Also the recovery path.

        `audiopump.shutdown()` closes the I2S channel as well as ending the
        task, so anything that means to spawn again has to come back through
        here first.
        """
        if self._power is not None:
            self._power(True, volume=self.volume)
        w = self.out_wire
        # din= opens the RX half of the SAME channel pair, so one clock tree
        # drives capture and playback and the two DMAs cannot drift. The
        # input block is matched to the DMA descriptor on purpose: a read
        # that spans two descriptors costs a block of latency for nothing.
        din = -1
        if self.in_wire is not None and self.in_wire.port == w.port:
            din = self.in_wire.sd
        self.cushion = _audioif.i2s_start(
            w.port, w.sck, w.ws, w.sd, self.rate,
            bits=16, channels=self.channels,
            mclk=-1 if w.mck is None else w.mck, mclk_fs=w.mck_fs,
            dma_desc=self.dma_desc, dma_frame=self.dma_frame, din=din)
        self.duplex = din >= 0

    # --- where the sound comes from --------------------------------------

    def prepare(self, *names):
        """Build now, while nothing is on screen, what `source()` will want.

        Call this before you draw anything. `source("riff")` synthesises
        2.4 seconds of Karplus-Strong in pure Python -- 115 200 loop
        iterations, about 1.4 s on an idle P4. Under `rack_all` as it was
        first written the same loop did not finish in 300 s, with 30 MB of
        heap free: it was not memory and not the pump's lock, it was the
        example's own animated meter. LVGL's tick is a soft callback that
        runs between your bytecodes, so a repaint that costs more than the
        tick period starves the interpreter of its own thread. See
        `rack_all.METER_MS` for the numbers and the rule.

        Even with a cheap meter this is worth calling. Building a source
        while a screen is up costs whatever share of the thread the screen
        is taking, and it is nicer to spend 1.4 s before the app is drawn
        than in the middle of a tap.

        Everything here is cached, so the `source()` that follows is a
        Mixer, a Rack and a `retarget()` -- about 135 ms.
        """
        for name in names:
            # `input` is left out: it is an I2S channel, not a computation,
            # and it is cheap on demand. Everything else -- the riff's
            # 115 200-iteration loop, an instrument's wavetables -- is built
            # here and kept by `_make`'s cache.
            if name != "input":
                self._make(name)
        return self

    def _build(self, name):
        """One source, as an audiosample, plus whether it wants looping."""
        if name == "riff":
            if self._riff is None:
                self._riff = riff(self.rate)
            return audiocore.RawSample(self._riff, sample_rate=self.rate,
                                       channel_count=self.channels), True
        if name == "input":
            if not hasattr(_audioif, "Input"):
                raise RuntimeError("this port has no audio input")
            if not self.duplex:
                raise RuntimeError(
                    "capture is not on the same I2S port as playback on this "
                    "board, so one channel pair cannot carry both")
            # An audiosample whose get_buffer is an I2S read, so the
            # microphone is a source like any other and the read is what
            # paces the pump.
            self._input = _audioif.Input(
                sample_rate=self.rate, channel_count=self.channels,
                frames=self.block)
            return self._input, False
        import audioinstruments
        inst = audioinstruments.create(name, self.rate,
                                       channel_count=self.channels)
        self._insts[name] = inst
        return inst.output, False

    def _make(self, name):
        """One source, built the first time and kept after that.

        An app that toggles between two sources should not pay to
        synthesise the riff, re-open the microphone or rebuild an
        instrument's wavetables every time somebody taps the button. The
        cache is cleared by `recover()` and `stop()`, because an `Input`
        belongs to an I2S channel that `shutdown()` closes.
        """
        made = self._built.get(name)
        if made is None:
            made = self._built[name] = self._build(name)
        inst = self._insts.get(name)
        if inst is not None:
            self._instrument = inst
        return made

    def source(self, what=None):
        """Point the chain at a source, or at several summed together.

        ``what`` is ``'riff'``, ``'input'``, an instrument name from
        ``audioinstruments``, or a tuple of those. A tuple puts one voice of
        an ``audiomixer.Mixer`` behind each, so the microphone and an
        instrument play through the same pedals at once.
        """
        if what is None:
            return self.source_name
        names = (what,) if isinstance(what, str) else tuple(what)
        mixer = self._mixer
        if mixer is not None and len(names) == self._voices:
            # Same shape as the Mixer already feeding the chain, so re-point
            # its voices where they stand. Nothing downstream changes: the
            # Rack is still fed by this Mixer and the pump is still pointed
            # at the Rack, so there is no graph to rebuild and no retarget.
            # `Mixer.play()` is a control path like any other and the pump
            # lock covers its swap.
            #
            # This is the difference between an app that feels instant and
            # one that does not. Measured on the P4 inside `rack_all`, with
            # the panel lit, the USB costume on and the pump playing:
            # rebuilding cost 206-352 ms a tap and re-pointing costs ~10.
            for voice, name in enumerate(names):
                sample, loop = self._make(name)
                _safely(_play_voice, mixer, sample, voice, loop)
            self.source_name = what
            return what
        mixer = audiomixer.Mixer(
            voice_count=len(names), sample_rate=self.rate,
            channel_count=self.channels, bits_per_sample=16,
            samples_signed=True, buffer_size=BUFFER_SIZE)
        for voice, name in enumerate(names):
            sample, loop = self._make(name)
            # Headroom: the Mixer sums, it does not limit, so two voices at
            # full level clip as soon as both are loud. `level` rides on top
            # of that, and on a board with no codec volume it IS the volume.
            mixer.voice[voice].level = self.level / len(names)
            mixer.play(sample, voice=voice, loop=loop)
        self._mixer = mixer
        self._voices = len(names)
        self.source_name = what
        self._source = mixer
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
        # A pump that stopped on its own is cleared away here, before
        # anything is built, so that "play it again" is the whole of the
        # recovery a user has to know about.
        self.recover()
        if self._source is None:
            self.source(source)
        self._rebuild()
        return self.chain

    def died(self):
        """The reason the audio stopped by itself, or None if it is fine.

        The pump breaks out of its loop rather than raising - it has no
        interpreter thread to raise on - so this is how a stop reaches you.
        """
        if not self._spawned or audiopump.running():
            return None
        import struct
        return self._why(struct.unpack("<%dQ" % audiopump.STATUS_WORDS,
                                       self._status))

    def _why(self, w):
        if not self._spawned or audiopump.running():
            return None
        why = PUMP_FAULTS.get(w[24]) or PUMP_ERRORS.get(w[5])
        return why or "the pump stopped (error %d, fault %d)" % (w[5], w[24])

    def recover(self):
        """Clear a stopped pump away so the next play() can start a new one.

        Nothing else in the example has to know that a pump which has
        faulted still holds its task and its I2S channel: it is not
        `running()`, and `spawn()` refuses it all the same. Returns the
        reason it stopped, or None if it was healthy.
        """
        why = self.died()
        if why is None:
            return None
        print("audiolive: the audio stopped -", why, "- restarting")
        audiopump.shutdown()
        self._spawned = False
        self._tail = None
        self._retired = None
        self._rack = None
        self.effects = []
        # shutdown() closed the I2S channel with the task, and an `Input`
        # built on the old channel is stale with it -- so the whole source
        # cache goes, and with it the Mixer that fed the chain. `self._riff`
        # survives, which is the expensive part (a 115 200-iteration loop).
        self._built = {}
        self._insts = {}
        self._mixer = None
        self._voices = 0
        if self.on_board:
            self._input = None
            if self.source_name == "input":
                self._source = None
                self.source_name = None
            self._open_codec()
        for i in range(len(self._status)):
            self._status[i] = 0
        gc.collect()
        return why

    def _rebuild(self):
        """Build the new graph, then point the pump at it in one move."""
        # Last swap's chain, released now that many blocks have gone by on
        # the new one. Releasing it *immediately* after the retarget is what
        # a first reading of the lock says you may do -- retarget swaps the
        # pump's tail under the lock, so the old chain is detached the
        # instant it returns -- and on the P4, under a live GUI, it stopped
        # the audio at the first patch change with fault=deinited. Stepped
        # through by hand with a few hundred milliseconds between the two it
        # never fails, so it is a race and not a rule. One generation of lag
        # costs one spare chain of memory and closes it.
        retired = getattr(self, "_retired", None)
        if retired is not None:
            try:
                retired.deinit()
            except Exception as exc:
                print("retired rack deinit:", exc)
            self._retired = None
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
            # Not deinited here; retired until the next swap. See above.
            self._retired = old_rack
        else:
            gc.collect()
            self._dma_at_start = self._dma()
            self._starved_peak = 0
            if self.on_board:
                # sink=True: every block the pump pulls goes straight into
                # the I2S DMA, on the pump's own thread, with no Python in
                # the path at all.
                audiopump.spawn(tail, BLOCKS_FOREVER, self._status,
                                sink=True, timeout_ms=500)
            else:
                audiopump.spawn(tail, BLOCKS_FOREVER, self._status,
                                ring=self._ring, timeout_ms=500)
            self._spawned = True
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
        # A block of audio lasts as long as the frames in it, and a class
        # chooses how many frames it hands back: `Fuzz` and `Saturation`
        # return 512 where `Overdrive` returns 256. So the denominator is
        # counted from the bytes that actually came out, not from the block
        # size this object asked for - dividing by the configured 256
        # reported Fuzz at 553 % of a block when it is 274 %, and every
        # 512-frame class was overstated by exactly two.
        #
        # Wall time cannot be used for this while the pump is live: the pump
        # publishes its wall clock once, when its loop ends. And a pump that
        # is behind has a wall period equal to its own pull, which would read
        # 100 % however far behind it is.
        frames = (w[1] // blocks) // (self.channels * 2) or self.block
        block_us = frames * 1000000 // self.rate
        dma = self._dma() - self._dma_at_start
        # `dma - written` is how far behind the pump is RIGHT NOW, and the
        # screen was presenting it as silence already heard. It is not: it
        # shrinks again when the pump catches up, so the panel read 88, 82,
        # 2, 2 ms -- a decreasing sequence, which no cumulative count can
        # produce, and a strict checker called that a failure.
        #
        # What a listener wants is total silence since play(), which never
        # goes down. The gap can only rise when the DMA clocks out a byte the
        # pump never wrote, and a byte of silence once heard stays heard, so
        # the total is the gap's HIGH-WATER MARK. Recovery stops it growing;
        # it does not give any back.
        gap = dma - w[15] if dma else 0
        if gap > self._starved_peak:
            self._starved_peak = gap
        starved = self._starved_peak
        out = {
            "blocks": w[0],
            "cost_us": w[12] // blocks,
            "worst_us": w[20],
            "block_us": block_us,
            "load_pct": (w[12] // blocks) * 100 // block_us,
            "starved": starved if starved > 0 else 0,
            "starved_ms": (starved * 1000 // (self.rate * self.channels * 2)
                           if starved > 0 else 0),
            # How far behind the pump is at this instant, which is what
            # `starved` used to be. Useful while tuning a ring; not silence.
            "starved_now": gap if gap > 0 else 0,
            "timeouts": w[14],
            "error": w[5],
            "fault": w[24],
            "running": audiopump.running(),
            # None while the audio is playing; a sentence once it has
            # stopped by itself. A GUI shows this instead of dying.
            "why": self._why(w),
        }
        if LOCKED:
            # How long the audio actually stood still inside somebody's swap.
            out["held_us"] = w[27]
        return out

    def _dma(self):
        if hasattr(_audioif, "i2s_dma_bytes"):
            return _audioif.i2s_dma_bytes()
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
        self._spawned = False
        power = getattr(self._bp, "audio_power", None) if self._bp else None
        if power is not None:
            try:
                power(False)
            except Exception:
                pass
        self._tail = None
        self._rack = None
        self._retired = None
        self._input = None
        self._built = {}
        self._insts = {}
        self._mixer = None
        self._voices = 0
        self.effects = []
        gc.collect()
