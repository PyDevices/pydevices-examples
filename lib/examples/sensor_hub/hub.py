"""The sensor hub: nodes publish readings, browsers watch them live.

One asyncio program serves four doors, all feeding the same table:

- ``UDP :5005``: one reading per datagram (fire and forget, the cheapest).
- ``POST /api/publish`` on the web port: the same text over HTTP.
- Bluetooth: a small GATT service with one writable characteristic
  (``blefeed.py``), for a node or a phone that has no Wi-Fi.
- ``GET /ws``: the WebSocket feed the dashboard (``GET /``) listens to.

A reading is either JSON or one line of text, whichever is easier to send::

    {"node": "pc", "readings": {"load1": 0.42, "mem": 61.5}}
    pc load1=0.42 mem=61.5

``GET /api/readings`` is the whole table as JSON and ``GET /api/status`` says
how the hub itself is doing (firmware, uptime, RSSI, free memory, ``/lib``).
Reading either one never interrupts anything, which is why the fleet page
polls ``/api/status`` instead of opening a REPL.

It runs on MicroPython (the T-Embed today, the P4 later) and on CPython or
the unix port for testing::

    import sensor_hub.hub
    sensor_hub.hub.run()            # port 80, UDP 5005, Bluetooth if there is a radio
"""

import asyncio
import gc
import json
import os
import socket
import sys
import time

from . import wsfeed

try:
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
except AttributeError:  # CPython
    _T0 = time.monotonic()

    def ticks_ms():
        return int((time.monotonic() - _T0) * 1000)

    def ticks_diff(a, b):
        return a - b


HISTORY = 40  # values kept per series, so a new dashboard has a sparkline at once
MAX_NODES = 16
MAX_SERIES = 12  # per node
HERE = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."


def _num(text):
    try:
        v = float(text)
    except ValueError:
        return None
    return int(v) if v == int(v) and "." not in text else v


def parse(data):
    """``(node, {name: number})`` from a JSON or text reading, or raise ValueError."""
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode()
    data = data.strip()
    if data.startswith("{"):
        obj = json.loads(data)
        node = str(obj["node"])
        readings = {}
        for k, v in obj["readings"].items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                readings[str(k)] = v
    else:
        parts = data.split()
        if not parts:
            raise ValueError("empty reading")
        node = parts[0]
        readings = {}
        for p in parts[1:]:
            k, _, v = p.partition("=")
            n = _num(v)
            if k and n is not None:
                readings[k] = n
    if not node or len(node) > 24 or not readings:
        raise ValueError("a reading needs a node name and at least one number")
    return node, readings


class Hub:
    def __init__(self, name="sensor-hub", plant=None):
        self.name = name
        self.nodes = {}  # node -> {"via", "seen", "series": {name: [values]}}
        self.feed = wsfeed.Feed()
        self.counts = {"udp": 0, "http": 0, "ble": 0, "rejected": 0}
        self.started = ticks_ms()
        # Test hook: plant="drop_feed" accepts readings but never forwards them
        # to browsers, so a checker that should notice a dead feed can be seen
        # to fail. Nothing else reads it.
        self.plant = plant
        self.ble_state = "off"

    # -- the table

    def ingest(self, data, via):
        try:
            node, readings = parse(data)
        except Exception:
            self.counts["rejected"] += 1
            return False
        entry = self.nodes.get(node)
        if entry is None:
            if len(self.nodes) >= MAX_NODES:
                self.counts["rejected"] += 1
                return False
            entry = self.nodes[node] = {"series": {}}
        entry["via"] = via
        entry["seen"] = ticks_ms()
        series = entry["series"]
        for k, v in readings.items():
            hist = series.get(k)
            if hist is None:
                if len(series) >= MAX_SERIES:
                    continue
                hist = series[k] = []
            hist.append(v)
            if len(hist) > HISTORY:
                hist.pop(0)
        self.counts[via] = self.counts.get(via, 0) + 1
        if self.plant != "drop_feed":
            self.feed.send(json.dumps({"type": "reading", "node": node, "via": via, "readings": readings}))
        return True

    def snapshot(self):
        now = ticks_ms()
        nodes = {}
        for node, e in self.nodes.items():
            nodes[node] = {"via": e["via"], "age_ms": ticks_diff(now, e["seen"]), "series": e["series"]}
        return {"type": "snapshot", "hub": self.name, "nodes": nodes}

    def status(self):
        s = {
            "hub": self.name,
            "impl": sys.implementation.name,
            "version": ".".join(str(v) for v in sys.implementation.version[:3]),
            "platform": sys.platform,
            "uptime_s": ticks_ms() // 1000,  # the board's, since boot (MicroPython)
            "hub_uptime_s": ticks_diff(ticks_ms(), self.started) // 1000,
            "nodes": len(self.nodes),
            "clients": len(self.feed),
            "counts": self.counts,
            "ble": self.ble_state,
        }
        try:
            u = os.uname()
            s["machine"] = u.machine
            s["firmware"] = u.version
        except Exception:
            pass
        try:
            gc.collect()
            s["mem_free"] = gc.mem_free()
            s["mem_alloc"] = gc.mem_alloc()
        except Exception:
            pass
        try:
            import network

            w = network.WLAN(network.STA_IF)
            if w.isconnected():
                s["ip"] = w.ifconfig()[0]
                s["rssi"] = w.status("rssi")
        except Exception:
            pass
        try:
            s["lib"] = sorted(os.listdir("/lib"))
        except Exception:
            pass
        return s

    # -- doors

    async def udp(self, port=5005):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(socket.getaddrinfo("0.0.0.0", port)[0][-1])
        sock.setblocking(False)
        while True:
            try:
                data, _ = sock.recvfrom(512)
            except OSError:
                await asyncio.sleep(0.03)
                continue
            self.ingest(data, "udp")

    async def http(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            method, path, _ = line.decode().split(" ", 2)
            headers = {}
            while True:
                h = await reader.readline()
                if h in (b"\r\n", b"\n", b""):
                    break
                k, _, v = h.decode().partition(":")
                headers[k.strip().lower()] = v.strip()
            path = path.split("?", 1)[0]
            if path == "/ws":
                await self.feed.serve(reader, writer, headers, hello=json.dumps(self.snapshot()))
            elif method == "POST" and path == "/api/publish":
                n = int(headers.get("content-length", "0"))
                body = await reader.readexactly(n) if 0 < n <= 1024 else b""
                ok = self.ingest(body, "http")
                await _reply(writer, 200 if ok else 400, b'{"ok":true}' if ok else b'{"ok":false}')
            elif path == "/api/readings":
                await _reply(writer, 200, json.dumps(self.snapshot()).encode())
            elif path == "/api/status":
                await _reply(writer, 200, json.dumps(self.status()).encode())
            elif path in ("/", "/index.html"):
                await _send_file(writer, HERE + "/dashboard.html", "text/html; charset=utf-8")
            else:
                await _reply(writer, 404, b'{"error":"not found"}')
        except Exception as e:
            print("hub: http", repr(e))
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            gc.collect()


async def _reply(writer, code, body, ctype="application/json"):
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found"}.get(code, "OK")
    writer.write(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\n"
        "Access-Control-Allow-Origin: *\r\nCache-Control: no-store\r\n"
        "Connection: close\r\n\r\n".format(code, reason, ctype, len(body)).encode()
    )
    writer.write(body)
    await writer.drain()


async def _send_file(writer, path, ctype):
    size = os.stat(path)[6]
    writer.write(
        "HTTP/1.1 200 OK\r\nContent-Type: {}\r\nContent-Length: {}\r\n"
        "Cache-Control: no-store\r\nConnection: close\r\n\r\n".format(ctype, size).encode()
    )
    buf = bytearray(1024)
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buf)
            if not n:
                break
            writer.write(buf[:n])
            await writer.drain()


async def main(port=80, udp_port=5005, ble=True, name="sensor-hub", plant=None):
    hub = Hub(name, plant=plant)
    server = await asyncio.start_server(hub.http, "0.0.0.0", port)
    tasks = [asyncio.create_task(hub.udp(udp_port))]
    if ble:
        try:
            from . import blefeed

            tasks.append(asyncio.create_task(blefeed.serve(hub, name=name)))
        except ImportError as e:
            hub.ble_state = "unavailable: {}".format(e)
    print("hub: http :{}  udp :{}  ble {}".format(port, udp_port, "on" if len(tasks) > 1 else "off"))
    try:
        await asyncio.gather(*tasks)
    finally:
        server.close()
    return hub


def run(**kwargs):
    """Start the hub and serve forever. Keyword arguments go to :func:`main`."""
    asyncio.run(main(**kwargs))
