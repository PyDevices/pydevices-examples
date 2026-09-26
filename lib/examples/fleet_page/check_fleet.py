"""Check a running fleet page against a board that runs the sensor hub.

It passes when:

1. the page lists the board by both serial and Wi-Fi, with its details
   taken from the hub's status (firmware, uptime, RSSI, free memory, /lib);
2. over ``--wait`` seconds the page keeps refreshing those details; and
3. the hub was never interrupted meanwhile: its own uptime grew by the whole
   wait. A page that polled the board over serial (or WebREPL) would stop
   the hub, and this is where it would show.

    python check_fleet.py --board 192.168.1.137
    python check_fleet.py --board 192.168.1.137 --plant-probe   # must FAIL

``--plant-probe`` asks the page for a serial probe halfway through the wait,
which stops the hub and restarts it; the check has to catch that.
"""

import argparse
import json
import sys
import time
import urllib.request


def get(url, data=None):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 method="GET" if data is None else "POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default="http://localhost:8700")
    ap.add_argument("--board", required=True, help="the hub board's IP")
    ap.add_argument("--wait", type=float, default=50)
    ap.add_argument("--plant-probe", action="store_true")
    a = ap.parse_args(argv)
    fails = []

    state = get(a.page + "/api/state")
    board = next((b for b in state["boards"] if b["routes"].get("wifi", {}).get("address") == a.board), None)
    if not board:
        print("FAIL the page does not list", a.board)
        return 1
    routes = sorted(board["routes"])
    print("routes:", ", ".join(f"{k} {board['routes'][k]['address']}" for k in routes))
    if "serial" not in routes:
        fails.append("no serial route for the board")
    info = board["info"]
    for k in ("impl", "version", "uptime_s", "rssi", "mem_free", "lib"):
        if info.get(k) in (None, []):
            fails.append(f"no {k} in the details")
    print("details from:", board["info_from"])
    first_at = board["info_at"] or 0

    hub0 = get(f"http://{a.board}/api/status")["hub_uptime_s"]
    t0 = time.time()
    planted = False
    while time.time() - t0 < a.wait:
        time.sleep(5)
        if a.plant_probe and not planted and time.time() - t0 > a.wait / 2:
            get(a.page + "/api/probe", {"id": board["id"], "route": "serial", "restart": True})
            planted = True
            print("planted: asked the page for a serial probe")
    elapsed = time.time() - t0
    try:
        hub1 = get(f"http://{a.board}/api/status")["hub_uptime_s"]
    except Exception as e:
        hub1 = None
        fails.append(f"hub not answering after the wait: {e}")
    board = next(b for b in get(a.page + "/api/state")["boards"] if b["id"] == board["id"])

    if hub1 is not None:
        grew = hub1 - hub0
        print(f"hub uptime grew {grew} s over {elapsed:.0f} s")
        if grew < elapsed - 3:
            fails.append(f"the hub restarted during the wait (uptime {hub0} -> {hub1} s)")
    if not board["info_at"] or board["info_at"] <= first_at:
        fails.append("the page did not refresh the board's details during the wait")
    else:
        print(f"page refreshed the details {time.time() - board['info_at']:.0f} s ago")

    for f in fails:
        print("FAIL", f)
    print("OK" if not fails else "FAILED")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
