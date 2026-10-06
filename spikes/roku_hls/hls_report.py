"""Summarise one hls_probe run: player states, segment fetch lag, and the
media-to-wall mapping for reading the burned-in timestamps in its screenshots.

    python hls_report.py RUN_DIR
"""

import json
import re
import statistics
import sys

run = sys.argv[1]
with open(run + "/log.json") as f:
    d = json.load(f)
seg = d["args"]["seg"]
log = d["log"]
t0 = next(e["t"] for e in log if e["kind"] == "launch")

print("states:")
for e in log:
    if e["kind"] == "report" and "pos" not in e and e["t"] >= t0 - 0.5:
        extra = {k: v for k, v in e.items() if k not in ("t", "kind")}
        print("  %6.2f s  %s" % (e["t"] - t0, extra))

fetches = [e for e in log if e["kind"] == "fetch"]
segs = [e for e in fetches if e["path"].endswith(".ts") and e["written"]]
lists = [e for e in fetches if e["path"].endswith(".m3u8")]
print("playlist fetches: %d, segment fetches: %d" % (len(lists), len(segs)))
if lists:
    print("  first playlist fetch %.2f s after launch" % (lists[0]["t"] - t0))
if segs:
    lag = [e["t"] - e["written"] for e in segs]
    print(
        "  segment fetched after written: median %.2f s, max %.2f s"
        % (statistics.median(lag), max(lag))
    )
    print("  first segment fetched: %s at %.2f s" % (segs[0]["path"], segs[0]["t"] - t0))

# The playlist's PROGRAM-DATE-TIME gives each segment's start in wall time:
# wall(pts) = offset + pts.
starts = {}
for e in log:
    if e["kind"] == "pdt":
        starts.update(e["segments"])
offsets = [w - int(re.search(r"(\d+)", name).group(1)) * seg for name, w in starts.items()]
stale = sum(1 for e in log if e["kind"] == "stale")
if stale:
    print("requests from a previous run's player: %d (refused)" % stale)
if offsets:
    off = statistics.median(offsets)
    print("wall(pts) = %.3f + pts  (spread %.2f s)" % (off, max(offsets) - min(offsets)))
    for s in d["shots"]:
        if s.get("path"):
            print(
                "  %s taken at pts-equivalent %.2f s  (read the burned-in time; delay = this - shown)"
                % (s["path"].rsplit("/", 1)[-1], s["requested"] - off)
            )

pos = [e for e in log if e["kind"] == "report" and "pos" in e and e["t"] >= t0]
if pos:
    print("first positions: %s" % [round(float(e["pos"]), 1) for e in pos[:4]])
if pos and offsets:
    late = [(e["t"] - off) - float(e["pos"]) for e in pos[len(pos) // 2 :]]
    print(
        "position reports: %d; (arrival as pts) - position: median %.2f s"
        % (len(pos), statistics.median(late))
    )
