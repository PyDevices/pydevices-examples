# castfast.py -- cast with the castif C task.
#
# Same MICE + RTSP session as micecast, but on PLAY the streaming loop is the
# castif FreeRTOS task on core 0 instead of a Python pump: the Python side only
# answers RTSP keepalives, forwards keyframe requests, steps an optional scene
# and keeps the sound moving. Sound: a PumpFeed keeps the audio
# pump's stream topped up from a block source and hands the cast the same
# 10 ms blocks; the task muxes them as LPCM on the video's clock.
#
#   import castfast
#   castfast.cast(fb, "192.168.1.129", 720, 720, seconds=60)   # to a Roku, silent
#   castfast.cast(fb, "192.168.1.129", 720, 720, audio=feed)   # feed = castfast.PumpFeed(source)
#
# The sink is chosen the same way as roku_cast: session_request=0 for the Roku,
# None for Windows.
import micropython
import time

from micecast import Session
import castif


BLOCK_BYTES = 1920          # 10 ms of 48 kHz stereo s16


def pump_stream(fmt=None, volume=85, capacity=32, log=print):
    """A pump stream wired to the board's speaker, at the given listening level.

    ``pump.attach_stream(fmt)`` on its own attaches to a pump with NO hardware
    driver: it pulls the stream into nothing, at any speed (measured
    2026-09-27 on the P4: silent, a 320 ms ring drained in 1.7 ms). The driver
    is the board's I2S transport, found the way audiodev's AudioOut finds it.
    """
    from audiodev import pump, AudioFormat
    from boarddev import pcm_out
    fmt = fmt or AudioFormat(48000, 2, 16)
    transport = pcm_out(fmt)
    while transport is not None and getattr(transport, "wire", None) is None:
        transport = getattr(transport, "_inner", None)
    if transport is None:
        raise RuntimeError("this board publishes no I2S transport for the pump")
    try:
        transport.volume = volume
    except Exception:
        pass
    driver = pump.BusioDriver(transport.wire, fmt, power=getattr(transport, "audio_power", None),
                              volume=volume, transport=transport)
    stream = pump.attach_stream(fmt, driver=driver, frames=256, capacity=capacity)
    log("pump stream on the speaker at %d %% (%d bytes free)" % (volume, stream.space()))
    return stream


class PumpFeed:
    """The one producer for both listeners: the P4's speaker (the pump) and the cast.

    ``source()`` returns the next 10 ms block: 1920 bytes of 48 kHz stereo
    16-bit little-endian PCM, the pump's own format; the cast byte-swaps to
    LPCM on the wire. Production is paced by the wall clock, one block per
    10 ms plus a small lead, because the pump's stream ring never pushes back
    on this board (measured 2026-09-27: a 320 ms ring drained in 1.7 ms, and
    a feeder paced on ``space()`` ran at 1.5x real time). A stall longer than
    the lead is skipped, not caught up: what was not produced in time is
    silence at the sink, never a burst.
    """

    def __init__(self, source, stream=None, lead=8, log=print):
        self.source = source
        self.stream = stream
        self.cast = None
        self.lead = lead            # blocks kept ahead of the clock (80 ms)
        self.t0 = None
        self.n = 0                  # blocks produced since t0
        self.fed = 0
        self.full = 0
        self.skipped = 0            # blocks a stall cost
        self.log = log
        if stream is None:
            try:
                self.stream = pump_stream(log=log)
            except Exception as e:
                log("pumpfeed: no pump stream (%r); the cast gets the audio, the speaker does not" % (e,))
                self.stream = None

    def pump(self, limit=12):
        now = time.ticks_ms()
        if self.t0 is None:
            self.t0 = now
        want = time.ticks_diff(now, self.t0) // 10 + self.lead
        due = want - self.n
        if due > self.lead + limit:          # a stall: skip the lost time
            self.skipped += due - self.lead
            self.n = want - self.lead
            due = self.lead
        n = 0
        s = self.stream
        c = self.cast
        while n < due and n < limit:
            b = self.source()
            if s is not None and s.space() >= BLOCK_BYTES:
                s.write(b)
            if c is not None:
                if c.feed_audio(b):
                    self.fed += 1
                else:
                    self.full += 1
            self.n += 1
            n += 1
        return n

    def close(self):
        if self.stream is not None:
            try:
                self.stream.deinit()
            except Exception:
                pass
            self.stream = None


# Rate/channel conversion for TapFeed, in viper: 10 ms of 24 kHz mono is
# 240 samples, too many for a bytecode loop on every poll. ptr16 reads come
# back unsigned, so each sample is sign-extended before the midpoint.
@micropython.viper
def _up_mono24(src: ptr16, n: int, dst: ptr16, prev: int) -> int:
    p = prev
    for i in range(n):
        s = int(src[i])
        if s > 32767:
            s -= 65536
        m = (p + s) >> 1
        j = i * 4
        dst[j] = m
        dst[j + 1] = m
        dst[j + 2] = s
        dst[j + 3] = s
        p = s
    return p


@micropython.viper
def _up_stereo24(src: ptr16, frames: int, dst: ptr16, prev: int) -> int:
    # prev packs the last frame: left in the low 16 bits, right above
    pl = (prev << 16) >> 16
    pr = prev >> 16
    for i in range(frames):
        l = int(src[2 * i])
        r = int(src[2 * i + 1])
        if l > 32767:
            l -= 65536
        if r > 32767:
            r -= 65536
        j = i * 4
        dst[j] = (pl + l) >> 1
        dst[j + 1] = (pr + r) >> 1
        dst[j + 2] = l
        dst[j + 3] = r
        pl = l
        pr = r
    return (pl & 0xFFFF) | (pr << 16)


@micropython.viper
def _spread_mono(src: ptr16, n: int, dst: ptr16):
    for i in range(n):
        s = src[i]
        dst[2 * i] = s
        dst[2 * i + 1] = s


class TapFeed:
    """The cast's audio from the pump's OUTPUT: whatever the P4 plays, the
    cast gets, an app's pulled graph included (the drum machine).

    ``audiopump.Tap`` is a lossy window of the last bytes the pump produced;
    reading it as a stream means asking for exactly the bytes written since
    the last read (``stats()[0]`` is the write counter), so nothing repeats.
    The tap is sized for the session loop's 50 ms cadence with room to spare.
    The pump's own clock paces production, so no lead and no time pacing
    here; each block is stamped when read (at most one poll late).

    The cast carries 48 kHz stereo (the only LPCM a sink takes), and the
    pump runs at whatever the app opened: the drum machine's low-latency
    output on the P4 is 24 kHz MONO. Pass the pump's ``rate`` and
    ``channels``; mono is spread to both sides and 24 kHz is doubled with a
    midpoint between samples. ``in_bytes`` counts what the tap produced, so
    a wrong format shows in the log as a byte rate that is not rate*ch*2.
    """

    def __init__(self, frames=16384, rate=48000, channels=2, log=print):
        from audiodev import pump
        if rate not in (24000, 48000) or channels not in (1, 2):
            raise ValueError("TapFeed takes 24 or 48 kHz, mono or stereo")
        self.rate, self.channels = rate, channels
        self.frame = 2 * channels
        self.grow = (48000 // rate) * (2 // channels)   # output bytes per input byte
        mod = pump.module()
        self.tap = mod.Tap(frames=frames, channel_count=channels)
        mod.tap(self.tap)
        self.cap = self.tap.stats()[4]
        self.cursor = self.tap.stats()[0]
        self.buf = bytearray(self.cap)
        self.mv = memoryview(self.buf)
        self.out = bytearray(self.cap * self.grow) if self.grow > 1 else None
        self.prev = 0                     # last input sample, for the midpoint
        self.carry = bytearray()          # a partial block between polls
        self.cast = None
        self.fed = 0
        self.full = 0
        self.in_bytes = 0
        self.lapped = 0                   # times the pump overwrote unread audio
        self.c_path = False
        self.log = log
        log("tapfeed: pump tap of %d bytes, %d Hz x%d in, 48000 Hz x2 out" % (self.cap, rate, channels))

    def _convert(self, got):
        if self.grow == 1:
            return self.mv[:got]
        n = got // 2                       # input samples
        if self.rate == 24000 and self.channels == 1:
            self.prev = _up_mono24(self.buf, n, self.out, self.prev)
        elif self.rate == 24000:
            self.prev = _up_stereo24(self.buf, n // 2, self.out, self.prev)
        else:
            _spread_mono(self.buf, n, self.out)
        return memoryview(self.out)[:got * self.grow]

    def pump(self, limit=64):
        c = self.cast
        if self.c_path:
            return 0                      # the cast task reads the tap itself
        if c is not None and hasattr(c, "set_tap"):
            # castif reads the tap in C: no interpreter in the audio path
            c.set_tap(self.tap, self.rate, self.channels)
            self.c_path = True
            self.log("tapfeed: castif reads the tap in C")
            return 0
        w = self.tap.stats()[0]
        new = (w - self.cursor) & 0xFFFFFFFF
        if new == 0:
            return 0
        if new > self.cap:
            self.lapped += 1
            new = self.cap
        new -= new % self.frame
        got = self.tap.readinto(self.mv[:new])
        self.cursor = w
        if not got:
            return 0
        self.in_bytes += got
        conv = self._convert(got)
        data = self.carry + conv if self.carry else conv
        n = 0
        pos = 0
        c = self.cast
        while pos + BLOCK_BYTES <= len(data) and n < limit:
            if c is not None:
                if c.feed_audio(data[pos:pos + BLOCK_BYTES]):
                    self.fed += 1
                else:
                    self.full += 1
            pos += BLOCK_BYTES
            n += 1
        self.carry = bytearray(data[pos:])
        return n

    def close(self):
        try:
            from audiodev import pump
            pump.module().tap(None)
        except Exception:
            pass


class CastifStreamer:
    """Adapts the castif task to the micecast streamer interface (pump/done/
    force_idr/close) so micecast.Session drives it unchanged."""

    def __init__(self, cast, fb, dst_ip, dst_port, server_port, seconds, log, scene=None, audio=None):
        self.cast = cast
        self.log = log
        self.seconds = seconds
        self.scene = scene          # stepped from pump(): input polling and drawing stay in Python
        self.audio = audio          # a PumpFeed, or None for a silent cast
        if audio is not None:
            audio.cast = cast
        self.t0 = time.ticks_ms()
        self.done = False
        self.idle_poll = True   # the C task streams; the Session loop can block, not spin
        cast.start(fb, dst_ip, dst_port, server_port)
        log("castif task -> %s:%d from :%d" % (dst_ip, dst_port, server_port))

    def pump(self, budget_us):
        # the C task does the streaming; here we step the scene (if any), enforce
        # the duration and surface a stats line every few seconds
        if self.audio is not None:
            self.audio.pump()
        if self.scene:
            self.scene.step()
        now = time.ticks_ms()
        if now - getattr(self, "_beat", 0) > 3000:
            self._beat = now
            s = self.cast.stats()
            line = "castif: %d frames, %.1f fps, %d sent, %d stalls, enc %d us, ppa %d us, mux %d us, %d B/f" % (
                s["frames"], s["fps"] / 1000.0, s["sent"], s["stalls"],
                s["enc_us"], s["ppa_us"], s["mux_us"], s["length"])
            if self.audio is not None and "audio_fed" in s:
                line += " | audio fed %d muxed %d level %d underruns %d drift %d ms ins %d drop %d ringfull %d" % (
                    s["audio_fed"], s["audio_muxed"], s["audio_level"], s["audio_underruns"],
                    s["audio_drift_ms"], s["audio_inserted"], s["audio_dropped"], self.audio.full)
                if hasattr(self.audio, "skipped"):
                    line += " skipped %d" % self.audio.skipped
                if hasattr(self.audio, "lapped"):
                    line += " lapped %d" % self.audio.lapped
            self.log(line)
        if self.seconds and time.ticks_diff(now, self.t0) > self.seconds * 1000:
            self.done = True

    def force_idr(self):
        self.cast.force_idr()

    def close(self):
        s = self.cast.stats()
        self.cast.stop()
        self.log("castif stopped: %d frames, %.1f fps, %d sent, %d stalls" % (
            s["frames"], s["fps"] / 1000.0, s["sent"], s["stalls"]))


def make_caster(w, h, canvas=(1280, 720), fps=30, bitrate=3_000_000, audio=False):
    """A reusable castif.Cast (the encoder + PPA are set up once); audio=True adds the LPCM ring."""
    if audio:
        return castif.Cast(w, h, canvas_w=canvas[0], canvas_h=canvas[1], fps=fps, bitrate=bitrate, audio=True)
    return castif.Cast(w, h, canvas_w=canvas[0], canvas_h=canvas[1], fps=fps, bitrate=bitrate)


def cast(fb, sink_ip, w, h, canvas=(1280, 720), fps=30, bitrate=3_000_000,
         seconds=60, session_request=0, name="PyDevices P4", log=print, cast_obj=None,
         scene=None, audio=None):
    c = cast_obj or make_caster(w, h, canvas=canvas, fps=fps, bitrate=bitrate, audio=audio is not None)

    def make(dst_ip, dst_port, server_port):
        return CastifStreamer(c, fb, dst_ip, dst_port, server_port, seconds, log, scene=scene, audio=audio)

    s = Session(sink_ip, name=name, log=log)
    s.session_request = session_request
    try:
        return s.run(make, seconds=seconds, idle_after_done=2)
    finally:
        if cast_obj is None:
            c.close()
