"""Timing analysis of a captured cast: the stream's clocks against the wall clock.

``python3 ts_timing.py CAPTURE.bin`` reads what rtp_capture.py wrote and reports,
per second of wall clock: video frames, audio blocks, PCR-vs-arrival drift and
jitter, audio PTS continuity (gaps and overlaps), the audio track's rate against
the wall clock, and the offset between the audio and video timelines. This is
the Phase 2 instrument: a sink resamples (pitch and tempo wobble) when the
audio timeline runs faster or slower than the clock the PCR carries, and it
starves (stutter) when arrival lags the PCR by more than its buffer.
"""
import struct, sys

PID_VIDEO, PID_AUDIO, PID_PMT = 0x100, 0x101, 0x1000


def read_capture(path):
    with open(path, "rb") as f:
        data = f.read()
    pos = 0
    while pos + 10 <= len(data):
        t_ns, n = struct.unpack_from("<QH", data, pos)
        pos += 10
        yield t_ns, data[pos:pos + n]
        pos += n


def pts_of(b, off):
    return ((b[off] & 0x0E) << 29) | (b[off + 1] << 22) | ((b[off + 2] & 0xFE) << 14) | (b[off + 3] << 7) | (b[off + 4] >> 1)


def analyse(path):
    first_ns = None
    wall = 0.0
    seq_prev = None
    seq_gaps = 0          # datagrams missing (forward jumps)
    seq_reorder = 0       # datagrams that arrived after a later one
    pkts = 0
    pcr_samples = []      # (wall_s, pcr_s)
    video_pts = []        # (wall_s, pts_s)
    audio_pts = []        # (wall_s, pts_s, bytes)
    cc = {}
    cc_errors = 0
    pes_buf = {}          # pid -> [bytearray, wall_s]
    for t_ns, dg in read_capture(path):
        if first_ns is None:
            first_ns = t_ns
        wall = (t_ns - first_ns) / 1e9
        if len(dg) < 12 or (dg[0] >> 6) != 2:
            continue
        seq = (dg[2] << 8) | dg[3]
        if seq_prev is not None:
            d = (seq - seq_prev) & 0xFFFF
            if d == 0 or d > 32768:
                seq_reorder += 1          # late or duplicate: do not move the expectation
                continue
            if d != 1:
                seq_gaps += d - 1
        seq_prev = seq
        pkts += 1
        body = dg[12:]
        for i in range(0, len(body) - 187, 188):
            p = body[i:i + 188]
            if p[0] != 0x47:
                continue
            pid = ((p[1] & 0x1F) << 8) | p[2]
            pusi = p[1] & 0x40
            afc = (p[3] >> 4) & 3
            c = p[3] & 15
            if afc & 1:
                if pid in cc and ((cc[pid] + 1) & 15) != c:
                    cc_errors += 1
                cc[pid] = c
            off = 4
            if afc & 2:
                alen = p[4]
                if alen and (p[5] & 0x10) and pid == PID_VIDEO:
                    base = (p[6] << 25) | (p[7] << 17) | (p[8] << 9) | (p[9] << 1) | (p[10] >> 7)
                    pcr_samples.append((wall, base / 90000.0))
                off = 5 + alen
            if not (afc & 1):
                continue
            payload = p[off:]
            if pid in (PID_VIDEO, PID_AUDIO):
                if pusi:
                    prev = pes_buf.pop(pid, None)
                    if prev:
                        finish(pid, prev, video_pts, audio_pts)
                    pes_buf[pid] = [bytearray(payload), wall]
                elif pid in pes_buf:
                    pes_buf[pid][0] += payload
    for pid, prev in pes_buf.items():
        finish(pid, prev, video_pts, audio_pts)
    return dict(pkts=pkts, seq_gaps=seq_gaps, seq_reorder=seq_reorder, cc_errors=cc_errors, pcr=pcr_samples,
                video=video_pts, audio=audio_pts, wall_end=wall)


def slope(pairs):
    """Least-squares slope of y against x over (x, y) pairs: a rate that jitter
    at the two ends cannot fake, unlike last-minus-first."""
    n = len(pairs)
    if n < 3:
        return 0.0
    mx = sum(x for x, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    return sxy / sxx if sxx else 0.0


def finish(pid, entry, video_pts, audio_pts):
    b, wall = entry
    if len(b) < 14 or b[0:3] != b"\x00\x00\x01":
        return
    if not (b[7] & 0x80):
        return
    pts = pts_of(b, 9) / 90000.0
    if pid == PID_VIDEO:
        video_pts.append((wall, pts))
    else:
        hlen = 9 + b[8]
        audio_pts.append((wall, pts, len(b) - hlen - 4))   # minus the 4-byte LPCM header


def report(r):
    if not r["pkts"]:
        print("empty capture: no RTP datagrams arrived")
        return
    print("RTP datagrams %d, lost %d, reordered %d, TS continuity errors %d" % (r["pkts"], r["seq_gaps"], r["seq_reorder"], r["cc_errors"]))
    v, a, pcr = r["video"], r["audio"], r["pcr"]
    print("video frames %d, audio blocks %d, capture %.1f s" % (len(v), len(a), r["wall_end"]))
    if not a or not v:
        return
    # audio continuity: each block is 10 ms; gaps/overlaps in PTS
    gaps = overl = 0
    worst_gap = 0.0
    for (w0, p0, n0), (w1, p1, n1) in zip(a, a[1:]):
        d = p1 - p0 - n0 / 192000.0
        if d > 0.0005:
            gaps += 1; worst_gap = max(worst_gap, d)
        elif d < -0.0005:
            overl += 1
    print("audio PTS: %d gaps (worst %.0f ms), %d overlaps" % (gaps, worst_gap * 1000, overl))
    # audio rate against the wall clock: bytes per wall second, in windows
    t0 = a[0][0]; span = a[-1][0] - t0
    if span > 5:
        total = sum(n for _, _, n in a)
        print("audio bytes/wall-s %.0f (192000 is real time): %.4f x" % (total / span, total / span / 192000.0))
        # the audio clock against the PC's clock: a regression over every block
        k = slope([(w, p) for w, p, _ in a])
        print("audio PTS rate vs wall clock (regression): %.6f  (%+.0f ppm; jitter at the ends cannot fake this)" % (k, (k - 1) * 1e6))
    # PCR vs arrival
    if len(pcr) > 10:
        offs = [w - p for w, p in pcr]
        base = min(offs)                      # the earliest-arriving sample: the least delayed path
        kp = slope(pcr)                       # PCR advance per wall second
        jit = max(offs) - min(offs)
        print("PCR: %d samples, PCR rate vs wall clock %.6f (%+.0f ppm), arrival delay spread %.0f ms" % (len(pcr), kp, (kp - 1) * 1e6, jit * 1000))
        # worst late arrival vs a 400 ms presentation lead (the sink's buffer)
        late = [o - base for o in offs]
        print("  worst late arrival %+.0f ms (a sink with a 400 ms lead starves past +400)" % (max(late) * 1000))
    # A/V: audio PTS vs video PTS at the same wall second
    print("per-second: wall  video  audio  a-v offset(ms)  pcr lag(ms)")
    for sec in range(int(r["wall_end"]) + 1):
        vs = [p for w, p in v if sec <= w < sec + 1]
        as_ = [p for w, p, _ in a if sec <= w < sec + 1]
        ps = [w - p for w, p in pcr if sec <= w < sec + 1]
        if vs and as_:
            print("  %3d  %5d  %5d  %+8.0f  %+8.0f" % (sec, len(vs), len(as_), (as_[-1] - vs[-1]) * 1000,
                  ((ps[-1] - (pcr[0][0] - pcr[0][1])) * 1000) if ps else 0))
        elif vs or as_:
            print("  %3d  %5d  %5d" % (sec, len(vs), len(as_)))


if __name__ == "__main__":
    report(analyse(sys.argv[1]))
