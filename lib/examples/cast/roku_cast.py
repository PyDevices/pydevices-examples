# roku_cast.py -- a Roku TV as a wireless display you can also control.
#
# Two halves, for a PyDevices smart-home app:
#   * Control, over ECP (the examples roku_engine): power, keys, launching
#     apps, reading what is on screen. Works from any host with a socket,
#     the P4 included.
#   * Cast, over Miracast-over-Infrastructure (micecast + the castif C task):
#     mirror a framebuffer to the TV, with sound. Needs the ESP32-P4 firmware
#     that carries castif.
#
# The Roku needs the MICE Session Request first, and micecast now answers the
# sink's own OPTIONS before asking for its capabilities (an early GET_PARAMETER
# earns a 455 from Roku OS, though Windows tolerates it).
import sys, time, gc

# roku_engine lives in the roku_remote example beside this one. Its package
# __init__ starts the remote app, so its directory goes on the path instead,
# unless roku_engine is importable already.
try:
    import roku_engine
except ImportError:
    _f = __file__.replace("\\", "/")
    _parent = _f.rsplit("/", 2)[0] if _f.count("/") >= 2 else ".."
    sys.path.append(_parent + "/roku_remote")
    try:
        import roku_engine
    except ImportError:
        roku_engine = None        # casting still works; TV control does not

from micecast import Session  # noqa: E402


class RokuScreen:
    def __init__(self, host, name="PyDevices", log=print):
        self.host = host
        self.name = name
        self.log = log
        self.eng = None
        if roku_engine is not None:
            self.eng = roku_engine.RokuEngine()
            self.eng.set_host(host)
            self.eng.connect()

    # --- control (ECP) ---
    def is_on(self):
        return self.eng.power_is_on() if self.eng else None

    def on(self):
        if self.eng and not self.eng.power_is_on():
            self.log("roku: powering on")
            self.eng.press("PowerOn")
            time.sleep(2)
        return self.is_on()

    def press(self, key):
        return self.eng.press(key) if self.eng else None

    def launch(self, app_id, query=""):
        return self.eng.launch(app_id, query) if self.eng else None

    def now_playing(self):
        return self.eng.query_active_app() if self.eng else None

    def off(self):
        return self.press("PowerOff")

    def volume_up(self, n=1):
        r = None
        for _ in range(n):
            r = self.press("VolumeUp")
        return r

    def volume_down(self, n=1):
        r = None
        for _ in range(n):
            r = self.press("VolumeDown")
        return r

    def mute(self):
        return self.press("VolumeMute")

    def set_input(self, name):
        # Roku inputs launch like apps: "hdmi1".."hdmi4", "dtv", "av1".
        if not name.startswith("tvinput."):
            name = "tvinput." + name
        return self.launch(name)

    # --- cast (Miracast over Infrastructure) ---
    def cast(self, fb, scene=None, seconds=60, fps=30, bitrate=3_000_000, audio=None, stop=None,
             size=(720, 720), skip_ms=None):
        """Mirror `fb` to the TV until `seconds` elapse or `stop()` returns True.
        Blocks until the cast ends. The castif C task on core 0 streams;
        `audio` is a castfast feed (PumpFeed, TapFeed) or a callable returning
        10 ms blocks of 48 kHz stereo s16 little-endian PCM (the speaker's
        format)."""
        return self._cast_castif(fb, scene, seconds, fps, bitrate, audio, stop, size, skip_ms)

    def _cast_castif(self, fb, scene, seconds, fps, bitrate, audio, stop, size, skip_ms=None):
        import castfast
        w, h = size
        want_audio = audio is not None
        c = getattr(self, "_caster", None)
        # one encoder per board (esp_h264 is a singleton): keep it across casts,
        # rebuild only when the audio ring is wanted and it has none
        if c is None or getattr(self, "_caster_audio", False) != want_audio:
            if c is not None:
                c.close()
            c = self._caster = castfast.make_caster(w, h, fps=fps, bitrate=bitrate, audio=want_audio)
            self._caster_audio = want_audio
        if skip_ms is not None:
            c.set_skip(skip_ms)          # 0: every frame, for a UI whose small changes the sampled hash misses
        feed = None
        if want_audio:
            # a feed (PumpFeed, TapFeed: anything with pump()) is used as is; a
            # bare block source gets a PumpFeed around it
            feed = audio if hasattr(audio, "pump") else castfast.PumpFeed(audio, log=self.log)

        def make(dst_ip, dst_port, server_port):
            return castfast.CastifStreamer(c, fb, dst_ip, dst_port, server_port, seconds, self.log,
                                           scene=scene, audio=feed)
        gc.collect()
        s = Session(self.host, name=self.name, log=self.log)
        s.session_request = 0
        self._session = s
        try:
            return s.run(make, seconds=seconds, idle_after_done=2, stop=stop)
        finally:
            if feed is not None and feed is not audio:
                feed.close()

    # --- non-blocking cast, for a long-running app: start it, stop it later ---
    def start_cast(self, fb, scene=None, seconds=3600, fps=30, bitrate=3_000_000, audio=None, skip_ms=None):
        """Cast in a background thread. Returns False if one is already running."""
        if getattr(self, "_casting", False):
            return False
        import _thread
        self._stop = False
        self._casting = True
        # the default thread stack is small: a session that opens the pump's
        # driver from here hit "maximum recursion depth exceeded" (2026-09-27)
        try:
            _thread.stack_size(32 * 1024)
        except Exception:
            pass

        def run():
            try:
                self.cast(fb, scene=scene, seconds=seconds, fps=fps,
                          bitrate=bitrate, audio=audio, stop=lambda: self._stop, skip_ms=skip_ms)
            except Exception as e:
                self.log("cast thread:", repr(e))
            finally:
                self._casting = False

        _thread.start_new_thread(run, ())
        return True

    def stop_cast(self):
        """Ask a background cast to stop; returns once it has, or after ~5 s."""
        self._stop = True
        for _ in range(50):
            if not getattr(self, "_casting", False):
                return True
            time.sleep_ms(100)
        return not self._casting

    def is_casting(self):
        return getattr(self, "_casting", False)
