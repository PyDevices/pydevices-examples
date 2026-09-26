"""End-to-end check of a running sensor hub, from a PC (CPython, stdlib only).

It opens the dashboard's WebSocket feed, publishes a fresh random value over
UDP and another over HTTP, and passes only if both come back on the feed,
unchanged, within the timeout. It also checks that the dashboard page and
``/api/status`` are served. Exit status 0 means it all worked.

    python check_hub.py 192.168.1.137
    python check_hub.py 127.0.0.1 --port 8080 --udp-port 5005
    python check_hub.py 192.168.1.137 --expect-node phone --timeout 60   # wait for a BLE node too

Run it against a hub started with ``plant="drop_feed"`` to see it fail: that
hub takes readings but never forwards them to browsers.
"""

import argparse
import base64
import json
import os
import random
import socket
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish import send  # noqa: E402


def ws_open(host, port):
    s = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(
        (
            f"GET /ws HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = s.recv(1)
        if not chunk:
            raise OSError("hub closed the connection during the handshake")
        head += chunk
    if b" 101 " not in head.split(b"\r\n")[0]:
        raise OSError("no WebSocket upgrade: " + head.split(b"\r\n")[0].decode())
    return s


def _exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise OSError("feed closed")
        buf += chunk
    return buf


def ws_read(s):
    b0, b1 = _exact(s, 2)
    n = b1 & 0x7F
    if n == 126:
        n = int.from_bytes(_exact(s, 2), "big")
    elif n == 127:
        n = int.from_bytes(_exact(s, 8), "big")
    return b0 & 0x0F, _exact(s, n)


def main(argv=None):
    ap = argparse.ArgumentParser(description="End-to-end check of a running sensor hub.")
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--udp-port", type=int, default=5005)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--expect-node", action="append", default=[], help="also wait for a reading from this node")
    a = ap.parse_args(argv)

    base = f"http://{a.host}:{a.port}"
    page = urllib.request.urlopen(base + "/", timeout=10).read()
    assert b"<title>Sensor hub</title>" in page, "the dashboard page is not being served"
    status = json.loads(urllib.request.urlopen(base + "/api/status", timeout=10).read())
    print("status:", json.dumps({k: status.get(k) for k in ("hub", "impl", "version", "uptime_s", "rssi", "mem_free", "ble")}))

    ws = ws_open(a.host, a.port)
    op, hello = ws_read(ws)
    snap = json.loads(hello)
    assert snap.get("type") == "snapshot", f"first message was not a snapshot: {snap}"

    tag = random.randint(100000, 999999)
    want = {("check-udp", "nonce"): tag, ("check-http", "nonce"): tag + 1}
    for n in a.expect_node:
        want[(n, None)] = None
    t0 = time.monotonic()
    send(a.host, "check-udp", {"nonce": tag}, "udp", a.udp_port)
    send(a.host, "check-http", {"nonce": tag + 1}, "http", a.port)

    seen = {}
    ws.settimeout(0.5)
    while len(seen) < len(want) and time.monotonic() - t0 < a.timeout:
        try:
            op, data = ws_read(ws)
        except socket.timeout:
            continue
        if op != 1:
            continue
        msg = json.loads(data)
        if msg.get("type") != "reading":
            continue
        for (node, key), value in want.items():
            if msg["node"] != node or (node, key) in seen:
                continue
            if key is None or msg["readings"].get(key) == value:
                seen[(node, key)] = (round((time.monotonic() - t0) * 1000), msg["via"], msg["readings"])
    ws.close()

    ok = len(seen) == len(want)
    for k in want:
        if k in seen:
            ms, via, r = seen[k]
            print(f"PASS {k[0]:<11} via {via:<4} {ms:>5} ms  {r}")
        else:
            print(f"FAIL {k[0]:<11} never arrived on the feed within {a.timeout:g} s")
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
