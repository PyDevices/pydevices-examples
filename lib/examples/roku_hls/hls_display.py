# hls_display.py -- a display that is live video: whatever an app draws, the
# ESP32-P4 encodes as H.264 and serves as HLS, for a Roku TV (the PyDevices
# Companion channel's video mode), VLC, or any HLS player.
#
#   from hls_display import HlsDisplay
#   display_drv = HlsDisplay(tv="192.168.1.129")    # or tv=None, and open the URL it prints
#
# or let board_config.py beside this file build one, and run any app.
#
# HLS runs 7-10 s behind (the player starts at the oldest segment and keeps
# its own buffer), so this is for things you watch rather than drive: a clock,
# a dashboard, a camera, a status board. For an interactive app on a TV, use
# the cast example's CastDisplay (Miracast, about a frame behind) or the
# Companion channel's RokuDisplay.
#
# A background thread encodes the framebuffer at a steady rate whatever the
# app is doing (h264enc lets go of the interpreter while the hardware works),
# cuts 1-second segments (tsmux.Segmenter, the last 3 kept) and serves them.
# Video only: HLS on a Roku plays audio only as AAC. Needs firmware with
# h264enc and tsmux (an `all` build of an ESP32-P4).
import socket
import time

import framebuf
from displaydev.fbdisplay import FBDisplay

import h264enc
import tsmux


class HlsDisplay(FBDisplay):
    """An FBDisplay whose frames go out as live HLS.

    Args:
        tv: a Roku's address: it is told to play the stream once there is one.
            None to serve only (open ``url`` in VLC, say).
        width, height: multiples of 16 (1280x720 by default).
        fps: frames encoded per second; a keyframe, and so a segment, each second.
        bitrate: bits per second.
        port: the HTTP port the playlist and segments are served on.
        log: where messages go (default: print).
    """

    def __init__(self, tv=None, width=1280, height=720, fps=20, bitrate=2_000_000,
                 port=8090, log=print):
        self._buf = bytearray(width * height * 2)
        # What the encoder reads: a copy taken at show(), when the app has
        # finished a frame. Encoding the live buffer caught LVGL mid-redraw (the
        # dial cleared to black, not yet painted) as black boxes on the TV.
        self._shown = bytearray(width * height * 2)
        self._pending = False
        super().__init__(self._buf, width=width, height=height, quiet=True)
        self._fbuf = framebuf.FrameBuffer(self._buf, width, height, framebuf.RGB565)
        self.tv = tv
        self.fps = fps
        self.log = log
        self.port = port
        # keyframes by the clock, not by count (see _run): the GOP is the longest allowed
        self.enc = h264enc.Encoder(width, height, fps, 255, bitrate)
        self.seg = tsmux.Segmenter(3, 900)
        # Segments stay servable a while after they leave the playlist: a
        # player starts at the oldest one listed, and by the time it asks the
        # segmenter has moved on (a Roku stopped on a 404 without this).
        self._kept = {}
        self._began = {}        # segment number -> wall-clock ms it began (for /stats)
        self.first_fetch = {}   # client address -> the first segment it fetched
        self.path = "/r%d" % (time.ticks_ms() & 0xFFFFFF)   # a TV caches by URL: each run its own
        self.ip = self._local_ip()
        self.url = "http://%s:%d%s/stream.m3u8" % (self.ip, port, self.path)
        self.frames = 0
        self.requests = 0
        self.player = None                  # the Companion channel's last report
        self._stop = False
        self._running = False
        self._ls = socket.socket()
        self._ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._ls.bind(("0.0.0.0", port))
        self._ls.listen(4)
        self._ls.setblocking(False)
        self._clients = []
        log("HLS at", self.url)
        self._start()

    @staticmethod
    def _local_ip():
        import network

        return network.WLAN(network.STA_IF).ifconfig()[0]

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
        """The app finished a frame: the encoder takes it next time round.

        Only a flag: the copy happens on the encoder's thread, at most once a
        frame. It can't land mid-redraw there either -- the copy holds the
        interpreter, and LVGL holds it for the whole of a redraw."""
        self._pending = True

    # the encoder and the server, on their own thread
    def _start(self):
        import _thread

        try:
            _thread.stack_size(32 * 1024)
        except Exception:
            pass
        self._running = True
        _thread.start_new_thread(self._run, ())

    def _run(self):
        try:
            t0 = time.ticks_ms()
            next_ms = t0
            frame_ms = 1000 // self.fps
            told = False
            last_key = t0
            while not self._stop:
                now = time.ticks_ms()
                if time.ticks_diff(now, next_ms) >= 0:
                    next_ms += frame_ms
                    if time.ticks_diff(now, next_ms) > 1000:
                        next_ms = now               # fell far behind: don't chase it
                    # a keyframe every 0.9 s of wall clock, so a segment is about
                    # a second whatever frame rate a busy app leaves the encoder
                    if time.ticks_diff(now, last_key) >= 900:
                        self.enc.force_idr()
                        last_key = now
                    if self._pending:
                        self._pending = False
                        self._shown[:] = self._buf
                    au = self.enc.encode(self._shown)
                    if self.seg.add(au, 90000 + time.ticks_diff(now, t0) * 90, self.enc.keyframe):
                        last = self.seg.first + self.seg.count - 1
                        self._kept[last] = self.seg.segment(last)
                        self._kept.pop(last - 8, None)
                        self._began[last + 1] = self._wall_ms()      # this frame starts the next
                        self._began.pop(last - 300, None)    # five minutes of start times
                    elif not self._began:
                        self._began[0] = self._wall_ms()
                    self.frames += 1
                    if not told and self.seg.count >= 2:
                        told = True
                        if self.tv:
                            from utils.roku_companion import RokuCompanion

                            # on its own thread: waking a TV takes seconds, and the
                            # encoder must not stop (one long segment would hold
                            # the playlist's target duration up for good)
                            import _thread

                            _thread.start_new_thread(self._tell_tv, ())
                self._poll()
                time.sleep_ms(1)
        except Exception as e:
            self.log("HLS thread:", repr(e))
        finally:
            self._running = False

    def _tell_tv(self):
        """Wake the TV and have the Companion channel play the stream; launch
        once more if the channel isn't up a few seconds later (a TV just out of
        standby can drop the first launch onto its Home screen)."""
        from utils.roku_companion import RokuCompanion

        tv = RokuCompanion(self.tv)
        self.log("TV on:", tv.power_on())
        for attempt in range(2):
            self.log("TV plays", self.url)
            tv.video(self.url)
            time.sleep(4)
            if tv._is_active():
                return
        self.log("the Companion channel didn't come up on the TV")

    @staticmethod
    def _wall_ms():
        try:
            return time.time_ns() // 1_000_000
        except AttributeError:
            return int(time.time() * 1000)

    def _poll(self):
        try:
            c, addr = self._ls.accept()
            c.setblocking(False)
            self._clients.append([c, b"", None, addr[0] if isinstance(addr, tuple) else str(addr)])
        except OSError:
            pass
        for cl in list(self._clients):
            try:
                if cl[2] is None:
                    data = cl[0].recv(1024)
                    if data == b"":
                        raise OSError("closed")
                    cl[1] += data
                    if b"\r\n\r\n" in cl[1]:
                        cl[2] = memoryview(self._respond(cl[1], cl[3]))
                # as much as the socket takes now: a segment has to go out faster
                # than real time, and the encoder can leave long gaps between polls
                while cl[2] is not None and len(cl[2]):
                    n = cl[0].send(cl[2][:32768])
                    if not n:
                        break
                    cl[2] = cl[2][n:]
                if cl[2] is not None and not len(cl[2]):
                    raise OSError("done")
            except OSError as e:
                if e.args and e.args[0] == 11:      # EAGAIN: next time round
                    continue
                cl[0].close()
                self._clients.remove(cl)

    def _respond(self, req, client=None):
        line = req.split(b"\r\n", 1)[0].decode()
        path = line.split(" ")[1] if " " in line else "/"
        self.requests += 1
        body, ctype, status = b"", "text/plain", "404 Not Found"
        if path.startswith("/video"):
            # the Companion channel reports the player: state=..., pos=...
            self.player = path.split("?", 1)[1] if "?" in path else None
            status = "200 OK"
        elif path in (self.path + "/stream.m3u8", "/stream.m3u8"):
            # the run's own path for a TV (it caches by URL); the plain one for VLC
            body, ctype, status = self.seg.playlist().encode(), "application/vnd.apple.mpegurl", "200 OK"
        elif path == "/stats":
            # how the stream is doing, and what a delay measurement needs: when
            # each segment began (wall clock, ms) and what each client fetched first
            body = ('{"now": %d, "frames": %d, "requests": %d, "player": "%s", "began": {%s}, "first_fetch": {%s}}' % (
                self._wall_ms(), self.frames, self.requests, self.player or "",
                ", ".join('"%d": %d' % kv for kv in sorted(self._began.items())),
                ", ".join('"%s": %d' % kv for kv in self.first_fetch.items()))).encode()
            ctype, status = "application/json", "200 OK"
        elif "/seg" in path and path.endswith(".ts"):
            try:
                n = int(path[path.rindex("/seg") + 4:-3])
                s = self._kept.get(n)
            except ValueError:
                s = None
            if s is not None and client is not None and client not in self.first_fetch:
                self.first_fetch[client] = n
            if s is not None:
                body, ctype, status = s, "video/mp2t", "200 OK"
        head = ("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                "Cache-Control: no-cache\r\nConnection: close\r\n\r\n") % (status, ctype, len(body))
        return head.encode() + body

    def close(self):
        self._stop = True
        for _ in range(50):
            if not self._running:
                break
            time.sleep_ms(100)
        self.enc.close()
        self._ls.close()

    def deinit(self):
        self.close()
