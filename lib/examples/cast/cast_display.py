# cast_display.py -- a display that is a TV or a laptop across the room.
#
# CastDisplay is an FBDisplay over a framebuffer in RAM. Whatever an app draws
# goes out over Wi-Fi Display (Miracast over infrastructure) to a Roku TV or a
# Windows laptop's Wireless Display app, so a P4 with no screen of its own can
# run any pydevices app. On a laptop, its mouse and keyboard come back over
# UIBC as touches and keys.
#
#   from cast_display import CastDisplay
#   display_drv = CastDisplay("192.168.1.143", 720, 720, kind="windows")
#
# or let ../miracast/board_config.py build one, and run any app unchanged.
#
# On an ESP32-P4 the cast is castif's C task on core 0 (the firmware needs
# castif and h264enc). On CPython (python, python.exe) it is pycast.py: ffmpeg
# encodes, Python muxes castif's own TS and sends it. Either way the Wi-Fi
# Display session runs on a thread and rejoins by itself if the sink goes
# away, and drawing costs what drawing into RAM costs. Desktop MicroPython has
# no H.264 encoder, by decision, so there it raises.
import sys
import time

import framebuf
from displaydev.fbdisplay import FBDisplay

from micecast import Session
from uibcinput import UibcInput

try:
    import castif  # noqa: F401  (the P4's cast task)
    import castfast
    pycast = None
except ImportError:
    castfast = None
    if sys.implementation.name != "cpython":
        raise RuntimeError("CastDisplay needs an ESP32-P4 (castif) or CPython with ffmpeg; "
                           "desktop MicroPython has no H.264 encoder")
    import pycast


class CastDisplay(FBDisplay):
    """An FBDisplay whose glass is a Roku TV or a Windows Wireless Display window.

    Args:
        sink: the TV's or the laptop's IP address.
        width, height: the picture, multiples of 16 (720x720 by default).
        kind: "windows" (Wireless Display app) or "roku" (Screen mirroring on).
        canvas: (w, h) of the stream, at least the picture, which is centred
            on black (default: the picture's own size).
        fps, bitrate: the stream's.
        name: what the sink lists the cast as.
        log: where session messages go (default: nowhere).
    """

    def __init__(self, sink, width=720, height=720, kind="windows", canvas=None,
                 fps=30, bitrate=3_000_000, name="PyDevices P4", log=None):
        if kind not in ("windows", "roku"):
            raise ValueError("kind is 'windows' or 'roku'")
        self._buf = bytearray(width * height * 2)
        super().__init__(self._buf, width=width, height=height, quiet=True)
        # framebuf fills and blits in C; FBDisplay over a plain bytearray would
        # do it a row at a time in Python (a full 720x720 fill took ~1 s)
        self._fbuf = framebuf.FrameBuffer(self._buf, width, height, framebuf.RGB565)
        self.sink = sink
        self.kind = kind
        self.name = name
        self.log = log or (lambda *a: None)
        if castfast is not None:
            self.cast = castfast.make_caster(width, height, canvas=canvas or (width, height),
                                             fps=fps, bitrate=bitrate)
        else:
            self.cast = pycast.FfmpegCaster(width, height, canvas=canvas, fps=fps, bitrate=bitrate)
        self.uibc = UibcInput(width, height)
        self.sessions = 0
        self._session = None
        self._idr_before = 0        # IDR requests in the sessions before this one
        self._stop = False
        self._running = False
        self._start()

    @property
    def needs_refresh(self):
        # appdev drives show(); here that is what tells castif a frame changed
        return True

    def show(self, _timer=None):
        """Send the next frame: castif streams the buffer itself, so this only
        marks it changed (its own change check samples, and could miss a
        small redraw)."""
        self.cast.mark_dirty()

    def fill_rect(self, x, y, w, h, c):
        self._fbuf.fill_rect(x, y, w, h, c & 0xFFFF)
        return (x, y, w, h)

    def blit_rect(self, buf, x, y, w, h):
        try:
            src = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)
        except (TypeError, ValueError):       # a read-only buffer: FBDisplay's copy
            return super().blit_rect(buf, x, y, w, h)
        self._fbuf.blit(src, x, y)
        return (x, y, w, h)

    def stats(self):
        """How the cast is going: frames encoded and sent, frames a second
        (measured by castif, or by pycast on a desktop), sessions joined, and
        the keyframes the sink asked for: a sink asks when it lost part of the
        stream, so it counts the glitches the screen showed."""
        st = self.cast.stats()
        s = self._session
        idr = self._idr_before + (s.idr_requests if s is not None else 0)
        return {"frames": st.get("frames", 0), "fps": st.get("fps", 0) / 1000.0,
                "sent": st.get("sent", 0), "sessions": self.sessions, "idr_requests": idr}

    # touch_read / keypad_read for a board_config: the laptop's mouse (left
    # button held) and keys
    def touch_read(self):
        return self.uibc.read_points()

    def keypad_read(self):
        return self.uibc.read_keys()

    def _start(self):
        import _thread

        # the default thread stack is small for the session's socket work on a
        # board; on CPython 32 KB would be far too little, for every thread after
        if sys.implementation.name != "cpython":
            try:
                _thread.stack_size(32 * 1024)
            except Exception:
                pass
        self._running = True
        _thread.start_new_thread(self._run, ())

    def _run(self):
        try:
            while not self._stop:
                if self.kind == "roku":
                    try:
                        from roku_cast import RokuScreen

                        RokuScreen(self.sink, name=self.name, log=self.log).on()
                    except Exception as e:
                        self.log("roku power-on:", repr(e))
                s = Session(self.sink, name=self.name, log=self.log, on_input=self.uibc.feed)
                s.session_request = 0 if self.kind == "roku" else None
                s.hidc_caps = "Keyboard/USB, Mouse/USB"
                self.sessions += 1
                self._session = s

                def make(dst_ip, dst_port, server_port):
                    if castfast is None:
                        return pycast.FfmpegStreamer(self.cast, self._buf, dst_ip, dst_port,
                                                     server_port, 24 * 3600, self.log)
                    return castfast.CastifStreamer(self.cast, self._buf, dst_ip, dst_port,
                                                   server_port, 24 * 3600, self.log)

                try:
                    result = s.run(make, seconds=24 * 3600, idle_after_done=2, stop=lambda: self._stop)
                    self.log("cast session ended:", result)
                except Exception as e:
                    self.log("cast session:", repr(e))
                self._idr_before += s.idr_requests
                self._session = None
                # the sink went away (closed, asleep, out of range): try again
                for _ in range(30):
                    if self._stop:
                        break
                    time.sleep(0.1)
        finally:
            self._running = False

    def close(self):
        """End the cast and give the encoder back."""
        self._stop = True
        for _ in range(60):
            if not self._running:
                break
            time.sleep(0.1)
        self.cast.close()

    def deinit(self):
        self.close()
