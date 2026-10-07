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
# The stream is castif.Hls, a task on the P4's core 0 that encodes (h264enc),
# segments (tsmux) and serves without the interpreter, so an app holding it
# for a long redraw can't starve the stream. All this class does is hand it
# each finished frame at show(). Video only: HLS on a Roku plays audio only as
# AAC. Needs firmware with castif, h264enc and tsmux (an `all` build of an
# ESP32-P4).
import time

import framebuf
from displaydev.fbdisplay import FBDisplay

import castif


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
        self.path = "/r%d" % (time.ticks_ms() & 0xFFFFFF)   # a TV caches by URL: each run its own
        self.hls = castif.Hls(width, height, fps=fps, bitrate=bitrate, port=port, path=self.path,
                              segments=segments)
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

    @staticmethod
    def _local_ip():
        import network

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
