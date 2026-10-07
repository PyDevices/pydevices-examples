# hls_display.py -- a display that is live video: whatever an app draws, the
# ESP32-P4 encodes as H.264 and serves as HLS, for a Roku TV (the PyDevices
# Companion channel's video mode), VLC, or any HLS player.
#
#   from hls_display import HlsDisplay
#   display_drv = HlsDisplay(tv="192.168.1.129")    # or tv=None, and open the URL it prints
#
# or let board_config.py beside this file build one, and run any app.
#
# HLS runs about 10 s behind (the player starts at the oldest segment and keeps
# its own buffer), so this is for things you watch rather than drive: a clock,
# a dashboard, a camera, a status board. For an interactive app on a TV, use
# the cast example's CastDisplay (Miracast, about a frame behind) or the
# Companion channel's RokuDisplay.
#
# On an ESP32-P4 the stream is castif.Hls, a task on core 0 that encodes
# (h264enc), segments (tsmux) and serves without the interpreter, so an app
# holding it for a long redraw can't starve the stream. On CPython (python,
# python.exe) ffmpeg encodes and segments, and a thread serves. All this class
# does is hand either one each finished frame at show(). Video only: HLS on a
# Roku plays audio only as AAC. Desktop MicroPython has no H.264 encoder, by
# decision, so there it raises.
import sys
import time

import framebuf
from displaydev.fbdisplay import FBDisplay

try:
    import castif
except ImportError:
    castif = None


def _ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


class _FfmpegHls:
    """castif.Hls's interface on CPython: ffmpeg encodes H.264 and cuts
    one-second segments, a feeder thread gives it the latest frame at a fixed
    rate (so a keyframe, and a segment, lands every second whatever the app
    draws), and a threaded HTTP server serves the playlist and segments."""

    def __init__(self, width, height, fps=20, bitrate=2_000_000, port=8090, path="", segments=4):
        import os
        import shutil
        import tempfile
        import threading

        self.ffmpeg = shutil.which("ffmpeg")
        if self.ffmpeg is None:
            raise RuntimeError("HlsDisplay on a desktop needs ffmpeg on the PATH (https://ffmpeg.org)")
        self.w, self.h, self.fps, self.bitrate = width, height, fps, bitrate
        self.port, self.path, self.segments = port, path.rstrip("/"), segments
        self.dir = tempfile.mkdtemp(prefix="pydevices-hls-")
        self.frame = bytes(width * height * 2)
        self.lock = threading.Lock()
        self.offers = self.frames = self.requests = 0
        self.running = False
        self.proc = self.server = None
        self._os = os

    def start(self):
        import subprocess
        import threading
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        os = self._os
        cmd = [self.ffmpeg, "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb565le",
               "-s", "%dx%d" % (self.w, self.h), "-r", str(self.fps), "-i", "-",
               "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
               "-g", str(self.fps), "-keyint_min", str(self.fps), "-sc_threshold", "0",
               "-b:v", str(self.bitrate), "-maxrate", str(self.bitrate), "-bufsize", str(self.bitrate),
               "-f", "hls", "-hls_time", "1", "-hls_list_size", str(self.segments),
               # segments stay servable a while after they leave the playlist (a
               # Roku fetches late and 404s otherwise)
               "-hls_flags", "delete_segments+independent_segments",
               "-hls_delete_threshold", str(self.segments),
               "-hls_segment_filename", os.path.join(self.dir, "seg%05d.ts"),
               os.path.join(self.dir, "stream.m3u8")]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        self.running = True
        threading.Thread(target=self._feed, daemon=True).start()

        hls = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=hls.dir, **k)

            def translate_path(self, path):
                path = path.split("?", 1)[0]
                if hls.path and path.startswith(hls.path + "/"):
                    path = path[len(hls.path):]
                return super().translate_path(path)

            def end_headers(self):
                self.send_header("Cache-Control", "no-cache")
                super().end_headers()

            def do_GET(self):
                hls.requests += 1
                super().do_GET()

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("", self.port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _feed(self):
        period = 1.0 / self.fps
        nxt = time.monotonic()
        while self.running:
            with self.lock:
                frame = self.frame
            try:
                self.proc.stdin.write(frame)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                break
            self.frames += 1
            nxt += period
            time.sleep(max(0.0, nxt - time.monotonic()))
        self.running = False

    def offer(self, buf):
        frame = bytes(buf)
        with self.lock:
            self.frame = frame
        self.offers += 1

    def stats(self):
        return {"frames": self.frames, "offers": self.offers, "requests": self.requests,
                "overruns": 0, "running": self.running}

    def close(self):
        import shutil

        self.running = False
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.proc is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(5)
            except Exception:
                self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


class HlsDisplay(FBDisplay):
    """An FBDisplay whose frames go out as live HLS.

    Args:
        tv: a Roku's address: it is woken and told to play the stream once
            there is one. None to serve only (open ``url`` in VLC, say).
        width, height: multiples of 16 (1280x720 by default).
        fps: frames encoded per second; a keyframe, and so a segment, about
            every second whatever the app draws.
        bitrate: bits per second.
        port: the HTTP port the playlist and segments are served on.
        segments: how many the playlist lists (4). A player starts at the oldest,
            so each one adds about a second of delay; too few, and a player
            slow to start (VLC, with 3) finds the next one gone and skips it.
        log: where messages go (default: print).
    """

    def __init__(self, tv=None, width=1280, height=720, fps=20, bitrate=2_000_000,
                 port=8090, segments=4, log=print):
        self._buf = bytearray(width * height * 2)
        super().__init__(self._buf, width=width, height=height, quiet=True)
        self._fbuf = framebuf.FrameBuffer(self._buf, width, height, framebuf.RGB565)
        self.tv = tv
        self.log = log
        self.path = "/r%d" % (_ms() & 0xFFFFFF)   # a TV caches by URL: each run its own
        if castif is not None:
            self.hls = castif.Hls(width, height, fps=fps, bitrate=bitrate, port=port, path=self.path,
                                  segments=segments)
        elif sys.implementation.name == "cpython":
            self.hls = _FfmpegHls(width, height, fps=fps, bitrate=bitrate, port=port, path=self.path,
                                  segments=segments)
        else:
            raise RuntimeError("HlsDisplay needs an ESP32-P4 (castif) or CPython with ffmpeg; "
                               "desktop MicroPython has no H.264 encoder")
        self.hls.start()
        self.ip = self._local_ip()
        self.url = "http://%s:%d%s/stream.m3u8" % (self.ip, port, self.path)
        log("HLS at", self.url, "(and http://%s:%d/stream.m3u8)" % (self.ip, port))
        if tv:
            import _thread

            try:
                _thread.stack_size(16 * 1024)
            except Exception:
                pass
            _thread.start_new_thread(self._tell_tv, ())

    def _local_ip(self):
        try:
            import network
        except ImportError:     # a desktop: the address on the route to the TV
            from utils.roku_companion import _routed_ip

            return _routed_ip(self.tv or "8.8.8.8")

        wlan = network.WLAN(network.STA_IF)
        # Wi-Fi power save holds each packet up to a beacon interval: every
        # segment request paid up to 0.7 s just to connect, and VLC skipped
        # seconds at a time. A video server stays awake.
        try:
            wlan.config(pm=wlan.PM_NONE)
        except (AttributeError, ValueError, OSError):
            pass
        return wlan.ifconfig()[0]

    # drawing: framebuf does it in C
    def fill_rect(self, x, y, w, h, c):
        self._fbuf.fill_rect(x, y, w, h, c & 0xFFFF)
        return (x, y, w, h)

    def blit_rect(self, buf, x, y, w, h):
        try:
            src = framebuf.FrameBuffer(buf, w, h, framebuf.RGB565)
        except (TypeError, ValueError):
            return super().blit_rect(buf, x, y, w, h)
        self._fbuf.blit(src, x, y)
        return (x, y, w, h)

    @property
    def needs_refresh(self):
        return True             # appdev calls show() for apps that don't

    def show(self, _timer=None):
        """The app finished a frame: hand it to the stream. The stream's task
        takes a frame only once it has started on the last one, so a fast app
        costs one copy per encoded frame, not one per show()."""
        self.hls.offer(self._buf)

    def stats(self):
        return self.hls.stats()

    def _tell_tv(self):
        """Wake the TV once a few segments exist, and have the Companion
        channel play the stream; launch once more if the channel isn't up a
        few seconds later (a TV just out of standby can drop the first launch
        onto its Home screen)."""
        from utils.roku_companion import RokuCompanion

        time.sleep(4)               # three segments in the playlist
        tv = RokuCompanion(self.tv)
        self.log("TV on:", tv.power_on())
        for _ in range(2):
            self.log("TV plays", self.url)
            tv.video(self.url)
            time.sleep(4)
            if tv._is_active():
                return
        self.log("the Companion channel didn't come up on the TV")

    def close(self):
        self.hls.close()

    def deinit(self):
        self.close()
