"""Fleet page: every board mpftp can reach, on one web page on your PC.

    python fleet.py                    # then open http://localhost:8700
    python fleet.py --host 192.168.1.137 --ble

It finds boards three ways and never interrupts one to do it:

- **Serial**: ``mpftp ports`` lists what's plugged in. Listing ports doesn't
  talk to the boards. Reading a board's details over serial does interrupt
  its program (every mpftp serial connect does), so that happens only when
  you click Probe, and the page says so on the button.
- **Wi-Fi**: boards mpftp remembers (``mpftp wifi boards``) plus any
  ``--host``. Every 15 s the page asks each one for ``/api/status``, which a
  board running the sensor hub serves without stopping anything. A board
  without it shows as reachable or not; its details come from a WebREPL
  probe, on demand, like serial.
- **Bluetooth** (``--ble``): a passive scan every 60 s lists boards
  advertising bledev's services (the REPL or file transfer, or the hub),
  with their signal strength. Scanning doesn't connect to anything.

It's read-only until you tick "Allow changes". Then each board gets an
"Update /lib" button that installs one released package with ``mpftp mip``,
one click and one confirmation at a time.

Only the standard library; mpftp does the talking. Point ``--mpftp`` (or
``MPFTP``) at the launcher if ``mpftp`` isn't on PATH.
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WIFI_POLL_S = 15
BLE_POLL_S = 60
INDEXES = {
    "PyDevices": "https://pydevices.github.io/mip",
    "micropython-lib": "https://micropython.org/pi/v2",
}
# Services a board running bledev advertises: Nordic UART (bledev.repl),
# file transfer (bledev.filetransfer), and the sensor hub's own.
BLE_SERVICES = {
    "6e400001-b5a3-f393-e0a9-e50e24dcca9e": "repl",
    "0000febb-0000-1000-8000-00805f9b34fb": "files",
    "7d9a0001-5a5e-4c2b-9f0e-8b3c1d2e4f60": "sensor hub",
}
# USB vendors that are boards rather than phones or modems.
BOARD_VIDS = {0x303A, 0x1A86, 0x10C4, 0x0403, 0x239A, 0x2E8A, 0x0483, 0x16C0, 0x2886, 0x1915}

# Runs on the board for a probe. One JSON line, marked so it can be found in
# whatever else the board prints.
PROBE = r"""
import sys, os, gc, time, json
d = {'impl': sys.implementation.name, 'version': '.'.join(str(v) for v in sys.implementation.version[:3])}
try:
    u = os.uname(); d['machine'] = u.machine; d['firmware'] = u.version
except Exception: pass
try: d['uptime_s'] = time.ticks_ms() // 1000
except Exception:
    try: d['uptime_s'] = int(time.monotonic())
    except Exception: pass
try:
    gc.collect(); d['mem_free'] = gc.mem_free()
except Exception: pass
try:
    import network
    w = network.WLAN(network.STA_IF)
    if w.isconnected(): d['ip'] = w.ifconfig()[0]; d['rssi'] = w.status('rssi')
except Exception: pass
try: d['lib'] = sorted(os.listdir('/lib'))
except Exception: pass
print('@@FLEET@@' + json.dumps(d))
"""

BLE_SCAN = r"""
import asyncio, json
from bleak import BleakScanner
async def main():
    seen = await BleakScanner.discover(timeout=6.0, return_adv=True)
    out = []
    for dev, adv in seen.values():
        out.append({"address": dev.address, "name": adv.local_name or dev.name,
                    "rssi": adv.rssi, "services": [s.lower() for s in adv.service_uuids]})
    print(json.dumps(out))
asyncio.run(main())
"""


def is_wsl():
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


class Fleet:
    def __init__(self, mpftp, hosts=(), ble=False, skip=()):
        self.mpftp = mpftp
        self.skip = set(skip)
        self.extra_hosts = list(hosts)
        self.ble = ble
        self.boards = {}  # id -> dict
        self.jobs = []  # newest last
        self.lock = threading.Lock()
        self.busy = set()  # board ids with an mpftp job running
        self.ble_note = "off" if not ble else "waiting for the first scan"

    # -- mpftp

    def run(self, *args, timeout=180):
        cmd = self.mpftp + list(args)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr

    def job(self, board_id, title, fn):
        """Run ``fn`` in the background as one visible job; one job per board at a time."""
        with self.lock:
            if board_id in self.busy:
                return None
            self.busy.add(board_id)
            j = {"id": len(self.jobs) + 1, "board": board_id, "title": title, "state": "running",
                 "started": time.time(), "log": ""}
            self.jobs.append(j)
            del self.jobs[:-30]

        def go():
            try:
                ok, log = fn()
                j["state"] = "done" if ok else "failed"
                j["log"] = log
            except Exception as e:
                j["state"] = "failed"
                j["log"] = repr(e)
            finally:
                j["ended"] = time.time()
                with self.lock:
                    self.busy.discard(board_id)

        threading.Thread(target=go, daemon=True).start()
        return j

    # -- discovery (none of this talks to a board's REPL)

    def board(self, uid, **fields):
        b = self.boards.get(uid)
        if b is None:
            b = self.boards[uid] = {"id": uid, "routes": {}, "info": {}, "info_from": None,
                                    "info_at": None, "name": None}
        for k, v in fields.items():
            if v is not None:
                b[k] = v
        return b

    def scan_serial(self):
        rc, out, err = self.run("ports", timeout=60)
        if rc:
            raise RuntimeError("mpftp ports failed: " + (err or out)[-300:])
        seen = set()
        for p in json.loads(out):
            if p.get("vid") not in BOARD_VIDS or p["device"] in self.skip:
                continue
            serial = (p.get("serial_number") or p["device"]).lower().replace(":", "")
            uid = serial[:12]
            b = self.board(uid)
            b["routes"]["serial"] = {"address": p["device"], "detail": p.get("description") or "",
                                     "reachable": True}
            seen.add(uid)
        for uid, b in self.boards.items():
            if "serial" in b["routes"] and uid not in seen:
                b["routes"]["serial"]["reachable"] = False

    def scan_wifi_known(self):
        rc, out, err = self.run("wifi", "boards", timeout=60)
        hosts = {}
        for line in out.splitlines():
            m = re.match(r"(\S+)\s+ws://([\w.\-]+)\S*\s+([0-9a-f]{6,})", line.strip())
            if m:
                hosts[m.group(2)] = (m.group(3)[:12], m.group(1), "(password saved" in line)
        for h in self.extra_hosts:
            hosts.setdefault(h, (None, None, False))
        for host, (uid, name, pw) in hosts.items():
            if host in self.skip:
                continue
            b = self.board(uid or "wifi-" + host, name=name)
            r = b["routes"].setdefault("wifi", {"address": host})
            if r["address"] != host:  # a board remembered at an old address; keep the newest
                continue
            r["password"] = pw

    def poll_wifi(self):
        for b in list(self.boards.values()):
            r = b["routes"].get("wifi")
            if not r:
                continue
            host = r["address"]
            try:
                with urllib.request.urlopen(f"http://{host}/api/status", timeout=4) as resp:
                    s = json.loads(resp.read())
                r["reachable"] = True
                r["detail"] = "sensor hub status"
                b["name"] = b["name"] or s.get("hub")
                b["info"] = s
                b["info_from"] = "Wi-Fi, hub status (no interruption)"
                b["info_at"] = time.time()
            except Exception as e:
                refused = isinstance(getattr(e, "reason", e), ConnectionRefusedError)
                r["reachable"] = refused or _tcp_open(host, 80)
                r["detail"] = "on the network, no status service" if r["reachable"] else "not answering"
        self.merge_ble()

    def merge_ble(self):
        """Fold a Bluetooth-only entry into the board it turned out to be (same hub name)."""
        for uid in [u for u in self.boards if u.startswith("ble-")]:
            name = uid[4:]
            same = [b for b in self.boards.values()
                    if not b["id"].startswith("ble-") and name in (b["name"], b["info"].get("hub"))]
            if same:
                same[0]["routes"]["ble"] = self.boards.pop(uid)["routes"]["ble"]

    def scan_ble(self):
        if is_wsl():
            cmd = ["python.exe", "-c", BLE_SCAN]
        else:
            cmd = [sys.executable, "-c", BLE_SCAN]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if p.returncode:
            self.ble_note = "scan failed: " + (p.stderr.strip().splitlines() or ["?"])[-1][:200]
            return
        found = 0
        now = time.time()
        for d in json.loads(p.stdout):
            kinds = [BLE_SERVICES[s] for s in d["services"] if s in BLE_SERVICES]
            if not kinds or not d["name"]:
                continue
            found += 1
            same = [x for x in self.boards.values()
                    if d["name"] in (x["name"], x["info"].get("hub")) and not x["id"].startswith("ble-")]
            b = same[0] if same else self.board("ble-" + d["name"], name=d["name"])
            b["routes"]["ble"] = {"address": d["name"], "detail": ", ".join(kinds),
                                  "rssi": d["rssi"], "reachable": True, "seen": now}
        for b in self.boards.values():
            r = b["routes"].get("ble")
            if r and now - r.get("seen", 0) > 3 * BLE_POLL_S:
                r["reachable"] = False
        self.merge_ble()
        self.ble_note = f"{found} bledev board(s) in the last scan"

    def pollers(self):
        def wifi_loop():
            while True:
                try:
                    self.poll_wifi()
                except Exception as e:
                    print("fleet: wifi poll", repr(e))
                time.sleep(WIFI_POLL_S)

        def ble_loop():
            while True:
                try:
                    self.scan_ble()
                except Exception as e:
                    self.ble_note = "scan failed: " + repr(e)
                time.sleep(BLE_POLL_S)

        threading.Thread(target=wifi_loop, daemon=True).start()
        if self.ble:
            threading.Thread(target=ble_loop, daemon=True).start()

    def rescan(self):
        """Ports and remembered boards: cheap, and nothing is interrupted."""
        errors = []
        for fn in (self.scan_serial, self.scan_wifi_known):
            try:
                fn()
            except Exception as e:
                errors.append(str(e))
        return errors

    # -- on-demand actions (these do interrupt the board's program)

    def device(self, b, route):
        r = b["routes"][route]
        return {"serial": r["address"], "wifi": "ws://" + r["address"], "ble": "ble://" + r["address"]}[route]

    def probe(self, uid, route, restart):
        b = self.boards[uid]
        dev = self.device(b, route)

        def go():
            rc, out, err = self.run("exec", "-d", dev, PROBE, timeout=90)
            try:
                text = json.loads(out).get("output", "")
            except ValueError:
                text = out
            m = re.search(r"@@FLEET@@(\{.*\})", text)
            log = f"$ mpftp exec -d {dev} <probe>\n" + (text or out + err)[-1500:]
            if m:
                b["info"] = json.loads(m.group(1))
                b["info_from"] = {"serial": "serial probe", "wifi": "WebREPL probe", "ble": "Bluetooth probe"}[route]
                b["info_at"] = time.time()
            if restart and m:
                rc2, out2, err2 = self.run("soft-reboot", "-d", dev, timeout=60)
                log += f"\n$ mpftp soft-reboot -d {dev}  (runs main.py again)\n" + (out2 + err2)[-500:]
            return bool(m), log

        return self.job(uid, f"Probe over {route}", go)

    def update_lib(self, uid, route, package, index, restart=True):
        b = self.boards[uid]
        dev = self.device(b, route)
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+(@[A-Za-z0-9_.\-]+)?", package or ""):
            raise ValueError("not a package name: %r" % package)
        index_url = INDEXES.get(index, index)

        def go():
            rc, out, err = self.run("mip", "-d", dev, package, "--index", index_url, timeout=600)
            log = f"$ mpftp mip -d {dev} {package} --index {index_url}\n" + (out + err)[-3000:]
            if restart:
                rc2, out2, err2 = self.run("soft-reboot", "-d", dev, timeout=60)
                log += f"\n$ mpftp soft-reboot -d {dev}  (runs main.py again)\n" + (out2 + err2)[-500:]
            return rc == 0, log

        return self.job(uid, f"Install {package} into /lib over {route}", go)

    def state(self):
        return {"boards": sorted(list(self.boards.values()), key=lambda b: (b["name"] or "~", b["id"])),
                "jobs": self.jobs[::-1], "busy": sorted(self.busy), "ble": self.ble_note,
                "now": time.time(), "indexes": INDEXES}


def _tcp_open(host, port):
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False


def make_handler(fleet, allow_changes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "fleet.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                s = fleet.state()
                s["allow_changes"] = allow_changes
                self._send(200, s)
            elif self.path == "/api/packages":
                self._send(200, packages())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
                if self.path == "/api/rescan":
                    return self._send(200, {"errors": fleet.rescan()})
                uid, route = req.get("id"), req.get("route")
                if uid not in fleet.boards or route not in fleet.boards[uid]["routes"]:
                    return self._send(400, {"error": "no such board or route"})
                if self.path == "/api/probe":
                    j = fleet.probe(uid, route, bool(req.get("restart", True)))
                elif self.path == "/api/update":
                    if not allow_changes:
                        return self._send(403, {"error": "the page was started read-only (--read-only)"})
                    j = fleet.update_lib(uid, route, req.get("package"), req.get("index", "PyDevices"),
                                         bool(req.get("restart", True)))
                else:
                    return self._send(404, {"error": "not found"})
                if j is None:
                    return self._send(409, {"error": "that board is busy with another job"})
                self._send(200, j)
            except Exception as e:
                self._send(400, {"error": str(e)})

    return Handler


_packages = {}


def packages():
    """Package names in each index, fetched once (for the Update box's suggestions)."""
    if not _packages:
        for name, url in INDEXES.items():
            try:
                with urllib.request.urlopen(url + "/index.json", timeout=10) as r:
                    _packages[name] = sorted(p["name"] for p in json.loads(r.read())["packages"])
            except Exception:
                _packages[name] = []
    return _packages


def main(argv=None):
    ap = argparse.ArgumentParser(description="A web page listing every board mpftp can reach.")
    ap.add_argument("--port", type=int, default=8700)
    ap.add_argument("--bind", default="127.0.0.1", help="address to serve on (default: this PC only)")
    ap.add_argument("--host", action="append", default=[], help="a Wi-Fi board to poll (repeatable)")
    ap.add_argument("--ble", action="store_true", help="scan for bledev boards every minute")
    ap.add_argument("--skip", action="append", default=[],
                    help="a port or host to leave alone entirely, e.g. one another program is using")
    ap.add_argument("--read-only", action="store_true", help="never offer Update /lib")
    ap.add_argument("--mpftp", default=os.environ.get("MPFTP") or shutil.which("mpftp") or "mpftp")
    a = ap.parse_args(argv)

    fleet = Fleet([a.mpftp], a.host, a.ble, a.skip)
    print("fleet: scanning ports and remembered Wi-Fi boards ...")
    for e in fleet.rescan():
        print("fleet:", e)
    fleet.pollers()
    srv = ThreadingHTTPServer((a.bind, a.port), make_handler(fleet, not a.read_only))
    print(f"fleet: http://localhost:{a.port}/")
    srv.serve_forever()


if __name__ == "__main__":
    main()
