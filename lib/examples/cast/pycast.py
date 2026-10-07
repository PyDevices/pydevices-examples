# pycast.py -- castif's cast on CPython: ffmpeg encodes the H.264, Python muxes
# the MPEG-TS and sends the RTP, for micecast's session. So CastDisplay (and any
# app on ../miracast/board_config.py) runs from python and python.exe, to a Roku
# or Windows' Wireless Display, with no ESP32-P4.
#
# The bytes on the wire are castif's: TsMux is tsmux_core.c line for line (the
# PAT and PMT, the access-unit delimiter in the PES header, the PCR 400 ms
# ahead of the PTS in each frame's first packet), and the RTP is castif's, 7 TS
# packets to a datagram, payload type 33, from the server port the session
# advertised. That matters: Windows' receiver checks the stream strictly, and
# castif's is a stream it is known to accept.
#
# Silent, as CastDisplay is: the PMT lists the video only.
import shutil
import socket
import subprocess
import threading
import time

PID_PMT = 0x1000
PID_VIDEO = 0x100
PCR_LEAD = 36000            # 400 ms in 90 kHz ticks


def _crc32_mpeg(data):
    c = 0xFFFFFFFF
    for b in data:
        c ^= b << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if c & 0x80000000 else (c << 1) & 0xFFFFFFFF
    return c


def _section(table_id, ident, body):
    length = 5 + len(body) + 4
    sec = bytes([table_id, 0xB0 | ((length >> 8) & 0x0F), length & 0xFF, ident >> 8, ident & 0xFF, 0xC1, 0, 0]) + body
    return sec + _crc32_mpeg(sec).to_bytes(4, "big")


def _pts_field(pts):
    return bytes([0x21 | ((pts >> 29) & 0x0E), (pts >> 22) & 0xFF, 0x01 | ((pts >> 14) & 0xFE),
                  (pts >> 7) & 0xFF, 0x01 | ((pts << 1) & 0xFE)])


class TsMux:
    """tsmux_core.c, video only: each call returns the 188-byte packets."""

    def __init__(self):
        self.cc = {0: 0, PID_PMT: 0, PID_VIDEO: 0}
        pat = _section(0x00, 1, bytes([0, 1, 0xE0 | (PID_PMT >> 8), PID_PMT & 0xFF]))
        pmt = _section(0x02, 1, bytes([0xE0 | (PID_VIDEO >> 8), PID_VIDEO & 0xFF, 0xF0, 0x00,
                                       0x1B, 0xE0 | (PID_VIDEO >> 8), PID_VIDEO & 0xFF, 0xF0, 0x00]))
        self.pat_body = (b"\x00" + pat).ljust(184, b"\xff")
        self.pmt_body = (b"\x00" + pmt).ljust(184, b"\xff")

    def _head(self, pid, pusi, afc):
        cc = self.cc[pid]
        self.cc[pid] = (cc + 1) & 15
        return bytes([0x47, (0x40 if pusi else 0) | (pid >> 8), pid & 0xFF, (afc << 4) | cc])

    def tables(self):
        return [self._head(0, True, 1) + self.pat_body, self._head(PID_PMT, True, 1) + self.pmt_body]

    def video(self, au, pts, key):
        pts &= 0xFFFFFFFF
        pes = bytes([0, 0, 1, 0xE0, 0, 0, 0x80, 0x80, 5]) + _pts_field(pts) + bytes([0, 0, 0, 1, 9, 0xF0]) + au
        pcr = (pts - PCR_LEAD) & 0xFFFFFFFF
        pcr_af = bytes([0x50 if key else 0x10, (pcr >> 25) & 0xFF, (pcr >> 17) & 0xFF,
                        (pcr >> 9) & 0xFF, (pcr >> 1) & 0xFF, ((pcr & 1) << 7) | 0x7E, 0])
        out = []
        pos, total, first = 0, len(pes), True
        while pos < total:
            remaining = total - pos
            if first:
                room = 176
                if remaining < room:
                    pad = room - remaining
                    pkt = self._head(PID_VIDEO, True, 3) + bytes([7 + pad]) + pcr_af + b"\xff" * pad
                    room = remaining
                else:
                    pkt = self._head(PID_VIDEO, True, 3) + bytes([7]) + pcr_af
            else:
                room = 184
                if remaining < room:
                    pad = room - remaining
                    af = bytes([pad - 1]) + ((b"\x00" + b"\xff" * (pad - 2)) if pad >= 2 else b"")
                    pkt = self._head(PID_VIDEO, False, 3) + af
                    room = remaining
                else:
                    pkt = self._head(PID_VIDEO, False, 1)
            pkt += pes[pos:pos + room]
            pos += room
            out.append(pkt)
            first = False
        return out


def _ffmpeg():
    ff = shutil.which("ffmpeg")
    if ff is None:
        raise RuntimeError("CastDisplay on a desktop needs ffmpeg on the PATH (https://ffmpeg.org)")
    return ff


class FfmpegCaster:
    """castif.Cast's part of the interface CastDisplay uses: the picture's
    size, the stream's, and its counters."""

    def __init__(self, width, height, canvas=None, fps=30, bitrate=3_000_000):
        self.ffmpeg = _ffmpeg()
        self.w, self.h = width, height
        self.cw, self.ch = canvas or (width, height)
        self.fps, self.bitrate = fps, bitrate
        self.frames = self.sent = self.stalls = 0
        self._t0 = time.monotonic()

    def mark_dirty(self):
        pass                # every tick is encoded; there is no skip to defeat

    def stats(self):
        el = time.monotonic() - self._t0
        return {"frames": self.frames, "fps": int(1000 * self.frames / el) if el else 0,
                "sent": self.sent, "stalls": self.stalls}

    def close(self):
        pass


class FfmpegStreamer:
    """micecast's streamer interface (pump, done, idle_poll, force_idr, close)
    over ffmpeg: a feeder thread hands it the framebuffer at the frame rate, a
    reader thread muxes each access unit it returns and sends it."""

    def __init__(self, caster, fb, dst_ip, dst_port, server_port, seconds, log):
        self.c, self.fb, self.log = caster, fb, log
        self.seconds = seconds
        self.done = False
        self.idle_poll = True
        self.mux = TsMux()
        self.dst = (dst_ip, dst_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", server_port))
        self.seq = 0
        self.pts = []               # capture times, one per frame given to ffmpeg
        self.lock = threading.Lock()
        c = caster
        vf = []
        if (c.cw, c.ch) != (c.w, c.h):
            vf = ["-vf", "pad=%d:%d:%d:%d:black" % (c.cw, c.ch, ((c.cw - c.w) // 2) & ~1, ((c.ch - c.h) // 2) & ~1)]
        cmd = [c.ffmpeg, "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb565le",
               "-s", "%dx%d" % (c.w, c.h), "-r", str(c.fps), "-i", "-"] + vf + [
               "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
               "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-bf", "0",
               "-g", str(c.fps), "-keyint_min", str(c.fps), "-sc_threshold", "0",
               "-b:v", str(c.bitrate), "-maxrate", str(c.bitrate), "-bufsize", str(c.bitrate // 2),
               "-x264-params", "aud=1:repeat-headers=1", "-f", "h264", "-"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.t0 = time.monotonic()
        self.running = True
        threading.Thread(target=self._feed, daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()
        log("ffmpeg cast -> %s:%d from :%d" % (dst_ip, dst_port, server_port))

    def _pts(self):
        return 90000 + int((time.monotonic() - self.t0) * 90000)

    def _feed(self):
        period = 1.0 / self.c.fps
        nxt = time.monotonic()
        while self.running:
            frame = bytes(self.fb)
            with self.lock:
                self.pts.append(self._pts())
            try:
                self.proc.stdin.write(frame)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                break
            nxt += period
            time.sleep(max(0.0, nxt - time.monotonic()))

    def _send(self, packets):
        for i in range(0, len(packets), 7):
            ts90 = (self._last_pts - PCR_LEAD) & 0xFFFFFFFF
            hdr = bytes([0x80, 33, (self.seq >> 8) & 0xFF, self.seq & 0xFF]) + ts90.to_bytes(4, "big") + b"P4CA"
            try:
                self.sock.sendto(hdr + b"".join(packets[i:i + 7]), self.dst)
                self.c.sent += 1
            except OSError:
                self.c.stalls += 1
            self.seq = (self.seq + 1) & 0xFFFF

    def _au(self, au):
        """One access unit from ffmpeg, starting with its delimiter."""
        # tsmux's PES header carries the delimiter: drop ffmpeg's
        if au.startswith(b"\x00\x00\x00\x01\x09"):
            au = au[6:]
        elif au.startswith(b"\x00\x00\x01\x09"):
            au = au[5:]
        key = False
        i = au.find(b"\x00\x00\x01")
        while i >= 0 and i + 3 < len(au):
            if au[i + 3] & 0x1F == 5:
                key = True
                break
            i = au.find(b"\x00\x00\x01", i + 3)
        with self.lock:
            pts = self.pts.pop(0) if self.pts else self._pts()
        self._last_pts = pts
        packets = (self.mux.tables() if key else []) + self.mux.video(au, pts, key)
        self._send(packets)
        self.c.frames += 1

    def _read(self):
        buf = b""
        marker = b"\x00\x00\x00\x01\x09"
        while self.running:
            d = self.proc.stdout.read1(65536) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(4096)
            if not d:
                break
            buf += d
            # each delimiter after the first starts the next access unit
            while True:
                j = buf.find(marker, 1)
                if j < 0:
                    break
                self._au(buf[:j])
                buf = buf[j:]

    def pump(self, budget_us):
        now = time.monotonic()
        if now - getattr(self, "_beat", 0) > 3:
            self._beat = now
            s = self.c.stats()
            self.log("pycast: %d frames, %.1f fps, %d sent, %d stalls" % (s["frames"], s["fps"] / 1000, s["sent"], s["stalls"]))
        if now - self.t0 > self.seconds:
            self.done = True

    def force_idr(self):
        pass                # a keyframe comes every second regardless

    def close(self):
        self.running = False
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(3)
        except Exception:
            self.proc.kill()
        self.sock.close()
