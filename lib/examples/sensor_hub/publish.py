"""Publish readings to a sensor hub over Wi-Fi, by UDP or HTTP.

From a PC (CPython) it sends the machine's own numbers, once a second::

    python publish.py 192.168.1.137                 # UDP, node "pc"
    python publish.py 192.168.1.137 --via http --node desk --every 2

From your own code, on a PC or a board::

    from sensor_hub.publish import send
    send("192.168.1.137", "greenhouse", {"temp": 21.4, "rh": 55})

Only the standard library (``socket``), so it runs on MicroPython too.
"""

import json
import math
import socket
import sys
import time

UDP_PORT = 5005


def send(hub, node, readings, via="udp", port=None):
    """Send one reading. ``via`` is ``"udp"`` (no reply) or ``"http"`` (raises on refusal)."""
    body = json.dumps({"node": node, "readings": readings}).encode()
    if via == "udp":
        addr = socket.getaddrinfo(hub, port or UDP_PORT)[0][-1]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.sendto(body, addr)
        finally:
            s.close()
        return True
    addr = socket.getaddrinfo(hub, port or 80)[0][-1]
    s = socket.socket()
    try:
        s.settimeout(5)
        s.connect(addr)
        s.send(
            "POST /api/publish HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\n"
            "Content-Length: {}\r\nConnection: close\r\n\r\n".format(hub, len(body)).encode() + body
        )
        status = s.recv(64).split(b" ", 2)[1]
    finally:
        s.close()
    if status != b"200":
        raise OSError("hub refused the reading: HTTP " + status.decode())
    return True


def pc_readings(t):
    """What a PC has to say: load average and memory in use (Linux), plus a slow wave."""
    r = {"wave": round(50 + 40 * math.sin(t / 20), 1)}
    try:
        with open("/proc/loadavg") as f:
            r["load1"] = float(f.read().split()[0])
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.split()[0])
        r["mem_pct"] = round(100 * (1 - mem["MemAvailable"] / mem["MemTotal"]), 1)
    except (OSError, KeyError, ValueError):
        pass
    return r


def main(argv):
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hub", help="the hub's address, e.g. 192.168.1.137")
    ap.add_argument("--via", choices=("udp", "http"), default="udp")
    ap.add_argument("--node", default="pc")
    ap.add_argument("--every", type=float, default=1.0, help="seconds between readings")
    ap.add_argument("--port", type=int, default=None, help="the hub's UDP or HTTP port, if not 5005 or 80")
    ap.add_argument("--count", type=int, default=0, help="stop after this many (0: forever)")
    a = ap.parse_args(argv)
    t0 = time.time()
    n = 0
    while not a.count or n < a.count:
        r = pc_readings(time.time() - t0)
        send(a.hub, a.node, r, a.via, a.port)
        n += 1
        print(n, a.via, r, flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    main(sys.argv[1:])
