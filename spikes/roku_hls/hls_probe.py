"""Spike: does the Roku play our H.264 as HLS, and with how much delay?

Runs ffmpeg live (a test pattern with its timestamp burned in), serves the HLS
it writes, puts the PyDevices Companion channel in video mode, and logs:

- every request the TV makes (playlist, segments) against when each segment
  was written,
- the channel's player reports (state, position, errors),
- developer screenshots of the TV every few seconds, each with the PC time it
  was taken, so the burned-in timestamp can be read against it.

Usage (CPython on the PC; the channel must be sideloaded)::

    ROKU_DEV_PASSWORD=... python hls_probe.py ROKU_IP --seg 1 --audio aac --seconds 60

Results land in a new directory under --out.
"""

import argparse
import http.server
import json
import os
import socket
import subprocess

# Must match the module the examples use.
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from utils.roku_companion import RokuCompanion, get_local_ip  # noqa: E402

PORT = 8090  # the port the TV can already reach (8095 never arrived)


def ffmpeg_cmd(out_dir, seg, audio, profile, list_size, rate=1.0):
    # The stream's own time, and the PC's clock for checking by eye.
    vf = (
        "drawtext=text='%{pts\\:hms}':fontsize=110:fontcolor=white:box=1:"
        "boxcolor=black@0.75:boxborderw=12:x=60:y=60,"
        "drawtext=text='PC %{localtime\\:%H\\\\\\:%M\\\\\\:%S}':fontsize=110:fontcolor=yellow:box=1:"
        "boxcolor=black@0.75:boxborderw=12:x=60:y=220"
    )
    # -readrate paces by this machine's monotonic clock; under WSL that runs
    # ~5% fast, so --rate slows it to real time (see the spike's notes).
    pace = ["-readrate", "%.4f" % rate]
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        *pace,
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=1280x720:rate=30",
    ]
    if audio != "none":
        cmd += [*pace, "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    cmd += [
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-profile:v",
        profile,
        "-pix_fmt",
        "yuv420p",
        "-g",
        "30",
        "-keyint_min",
        "30",
        "-sc_threshold",
        "0",
    ]
    if audio == "aac":
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    elif audio == "lpcm":
        cmd += ["-c:a", "pcm_bluray"]
    cmd += [
        "-f",
        "hls",
        "-hls_time",
        str(seg),
        "-hls_list_size",
        str(list_size),
        "-hls_flags",
        "delete_segments+independent_segments+program_date_time",
        "-hls_segment_filename",
        os.path.join(out_dir, "seg%05d.ts"),
        os.path.join(out_dir, "stream.m3u8"),
    ]
    return cmd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roku")
    ap.add_argument("--seg", type=float, default=1)
    ap.add_argument("--audio", choices=("aac", "lpcm", "none"), default="aac")
    ap.add_argument("--profile", default="baseline")
    ap.add_argument("--list", type=int, default=6, help="segments in the playlist")
    ap.add_argument(
        "--rate",
        type=float,
        default=1.0,
        help="ffmpeg read rate against this machine's clock (0.952 on WSL, 2026-10-06)",
    )
    ap.add_argument(
        "--start",
        type=float,
        default=None,
        help="add #EXT-X-START:TIME-OFFSET=<this> (negative: from the live edge)",
    )
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument(
        "--shots", type=float, default=10, help="seconds between screenshots, 0 for none"
    )
    ap.add_argument("--out", default=tempfile.gettempdir())
    a = ap.parse_args()

    run = tempfile.mkdtemp(prefix="hls_probe_", dir=a.out)
    prefix = "/%s/" % os.path.basename(run)  # one URL per run: no stale players
    hls = os.path.join(run, "hls")
    os.mkdir(hls)
    log = []
    lock = threading.Lock()

    def note(kind, **kw):
        with lock:
            log.append(dict(t=time.time(), kind=kind, **kw))

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw):
            super().__init__(*args, directory=hls, **kw)

        def log_message(self, *args):
            pass

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path.startswith(prefix):
                path = path[len(prefix) - 1 :]
                self.path = path + ("?" + query if query else "")  # what the file server reads
            elif path != "/video":
                note("stale", path=path)  # a previous run's player
                self.send_error(404)
                return
            if path == "/video":
                fields = dict(urllib.parse.parse_qsl(query))
                note("report", **fields)
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            name = path.lstrip("/")
            full = os.path.join(hls, name)
            written = os.path.getmtime(full) if os.path.exists(full) else None
            note("fetch", path=name, written=written)
            if name.endswith(".m3u8") and written:
                note("pdt", segments=program_date_times(full))
            if name.endswith(".m3u8") and a.start is not None and written:
                with open(full, "rb") as f:
                    body = f.read().replace(
                        b"#EXTM3U\n", b"#EXTM3U\n#EXT-X-START:TIME-OFFSET=%g\n" % a.start, 1
                    )
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    server = http.server.ThreadingHTTPServer(("", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    ff = subprocess.Popen(ffmpeg_cmd(hls, a.seg, a.audio, a.profile, a.list, a.rate))
    note("ffmpeg_start")
    playlist = os.path.join(hls, "stream.m3u8")
    while not os.path.exists(playlist):
        time.sleep(0.05)
    time.sleep(a.seg * 2)  # a couple of segments before the TV asks

    url = "http://%s:%d%sstream.m3u8" % (get_local_ip(a.roku), PORT, prefix)
    tv = RokuCompanion(a.roku)
    tv._launch({"mode": "video", "url": url})
    note("launch", url=url)

    password = os.environ.get("ROKU_DEV_PASSWORD")
    shots = []
    end = time.time() + a.seconds
    next_shot = time.time() + 8
    while time.time() < end:
        if password and a.shots and time.time() >= next_shot:
            next_shot += a.shots
            shots.append(screenshot(a.roku, password, run, len(shots)))
        time.sleep(0.1)

    tv.close_channel()  # the next run starts from a fresh player
    ff.terminate()
    ff.wait()
    server.shutdown()
    # Segments' PROGRAM-DATE-TIME map media to wall time for the report.
    with open(os.path.join(run, "log.json"), "w") as f:
        json.dump({"args": vars(a), "log": log, "shots": shots}, f, indent=1)
    print(run)


def program_date_times(playlist):
    """{segment name: wall time its first frame was made}, from EXT-X-PROGRAM-DATE-TIME."""
    from datetime import datetime

    out, when = {}, None
    with open(playlist) as f:
        lines = f.read().splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            when = datetime.strptime(line.split(":", 1)[1], "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
        elif line and not line.startswith("#") and when is not None:
            out[line] = when
            when = None
    return out


def screenshot(roku, password, run, n):
    """Ask the TV's developer page for a screenshot; return (requested, saved path)."""
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, "http://%s/" % roku, "rokudev", password)
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))
    boundary = "----hlsprobe"
    body = (
        '--%s\r\nContent-Disposition: form-data; name="mysubmit"\r\n\r\nScreenshot\r\n'
        '--%s\r\nContent-Disposition: form-data; name="archive"; filename=""\r\n'
        "Content-Type: application/octet-stream\r\n\r\n\r\n--%s--\r\n"
        % (boundary, boundary, boundary)
    ).encode()
    requested = time.time()
    try:
        req = urllib.request.Request(
            "http://%s/plugin_inspect" % roku,
            data=body,
            headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary},
        )
        page = opener.open(req, timeout=10).read().decode("utf-8", "replace")
        done = time.time()
        img = None
        for ext in ("jpg", "png"):
            if "dev.%s" % ext in page:
                img = opener.open("http://%s/pkgs/dev.%s?t=%d" % (roku, ext, n), timeout=10).read()
                path = os.path.join(run, "shot%02d.%s" % (n, ext))
                with open(path, "wb") as f:
                    f.write(img)
                return {"requested": requested, "answered": done, "path": path}
        return {"requested": requested, "answered": done, "path": None, "page": page[-400:]}
    except (OSError, socket.timeout) as e:
        return {"requested": requested, "error": str(e)}


if __name__ == "__main__":
    main()
