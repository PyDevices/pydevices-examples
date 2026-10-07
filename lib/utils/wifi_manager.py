# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
wifi_manager.py - join a known Wi-Fi network, or ask for a new one on the screen.

Call it once near the top of ``main.py``, before the app touches the network::

    import wifi_manager
    ip = wifi_manager.connect()

``connect()`` scans and joins the strongest network it already knows.  It
knows the network in ``secrets.py`` (``WIFI_SSID`` / ``WIFI_PASSWORD``), the
one in CircuitPython's ``settings.toml`` (``CIRCUITPY_WIFI_SSID`` /
``CIRCUITPY_WIFI_PASSWORD``), and every network it has joined before.  Every
network that works is remembered, so once a board has joined, ``secrets.py``
can be deleted.

When none of those is in range, the board starts its own access point and
says how to reach it, on the display from ``board_config.display_drv`` when
there is one and always on the REPL:

1. Join ``PyDevices-1A2B`` (the last four hex digits of the board's MAC) with
   the password shown.  A phone camera can join from the QR code.
2. The phone opens the setup page by itself.  If it doesn't, browse to
   http://192.168.4.1.
3. Pick your network, type its password, press Join.

The board remembers the network and carries on.  While it waits it rescans
every minute, so a board that booted before the router came back joins on its
own.  To move to a new network on purpose, call ``wifi_manager.run()``.

``networks()`` lists the remembered SSIDs, ``forget(ssid)`` drops one and
``forget()`` drops them all.  A network that is still in ``secrets.py`` comes
back the next time it is joined.

Hidden networks: type the name into "Other" on the setup page.  The board then
tries it at every boot even though scans can't see it.

Install
-------
MicroPython::

    import mip
    mip.install("github:PyDevices/pydevices-examples/lib/utils/wifi_manager.py")

CircuitPython: copy this file to ``/lib``.

The screen
----------
With LVGL compiled in (``lvgl`` and ``display_driver``), the page is drawn in
LVGL with an ``lv.qrcode``.  Otherwise it is drawn with ``pygraphics`` straight
onto ``display_drv``, text scaled to the panel, and the QR code comes from
``adafruit_miniqr`` when that is installed (optional)::

    mip.install("github:adafruit/Adafruit_CircuitPython_miniQR/adafruit_miniqr.py")
    circup install adafruit_miniqr          # CircuitPython

With neither, the REPL is the only screen.

Where remembered networks live
------------------------------
CircuitPython keeps them in ``microcontroller.nvm``, which code can write even
while USB has CIRCUITPY mounted.  The record starts at ``NVM_OFFSET`` behind a
magic header; move ``NVM_OFFSET`` if your app keeps its own data in nvm.

MicroPython on ESP32 keeps them in ``esp32.NVS`` namespace ``"wifi_manager"``.
That survives a filesystem wipe, but not ``esptool erase_flash``.  Other
MicroPython ports use ``/wifi_networks.json``.

Passwords are stored in plain text, as they are in ``secrets.py``.
"""

import json
import sys
import time

_CP = sys.implementation.name == "circuitpython"

# Name prefix for the setup access point; the MAC's last four hex digits follow.
AP_PREFIX = "PyDevices"
# CircuitPython: where the record starts in microcontroller.nvm.
NVM_OFFSET = 0
# MicroPython ports without esp32.NVS.
CACHE_FILE = "/wifi_networks.json"
# Seconds to wait for one network to associate and hand out an address.
JOIN_TIMEOUT_S = 20
# Seconds between scans for a known network while setup mode waits.
RESCAN_S = 60

_MAX_NETWORKS = 16
_MAGIC = b"WSU1"
_NVS_NAMESPACE = "wifi_manager"
_NVS_KEY = "nets"
_NVS_MAX = 4000
# No 0/O, 1/l/i: the password is read off a screen and typed on a phone.
_PW_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
_MINIQR_INSTALL = (
    "circup install adafruit_miniqr"
    if _CP
    else 'mip.install("github:adafruit/Adafruit_CircuitPython_miniQR/adafruit_miniqr.py")'
)

try:
    from multimer import sleep_ms as _sleep_ms  # keeps LVGL and app timers running
except ImportError:
    if hasattr(time, "sleep_ms"):
        _sleep_ms = time.sleep_ms
    else:

        def _sleep_ms(ms):
            time.sleep(ms / 1000)


if hasattr(time, "ticks_ms"):
    _ticks_ms = time.ticks_ms
    _ticks_diff = time.ticks_diff
else:

    def _ticks_ms():
        return time.monotonic_ns() // 1000000

    def _ticks_diff(a, b):
        return a - b


# --------------------------------------------------------------- public calls


def connect(*, setup=True, hostname=None, display_drv=None, timeout=JOIN_TIMEOUT_S):
    """Join a known network, or run setup mode when none is in range.

    Args:
        setup (bool): Start setup mode when no known network is in range.
            ``False`` returns ``None`` instead.
        hostname (str): Set before joining, so DHCP and mDNS see it.
        display_drv: Display for setup mode.  Default:
            ``board_config.display_drv`` when there is one.
        timeout (int): Seconds to wait for each network.

    Returns:
        str | None: The IPv4 address, or ``None`` when no network was joined.
    """
    if setup and display_drv is None:
        # Display first, then radio: on an S3 the panel needs a contiguous
        # block of internal RAM that a running radio no longer leaves.
        display_drv = _board_display()
    radio = _radio()
    if hostname:
        _set_hostname(radio, hostname)
    ip = radio.ip()
    if ip:
        print("wifi_manager: already connected,", ip)
        return ip
    ip = _join_known(radio, timeout)
    if ip or not setup:
        if not ip:
            print("wifi_manager: no known network in range")
        return ip
    return _Setup(radio, display_drv, timeout).run()


def run(*, hostname=None, display_drv=None, timeout=JOIN_TIMEOUT_S):
    """Start setup mode now, even when a known network is in range.

    Returns:
        str: The IPv4 address of the network joined.
    """
    if display_drv is None:
        display_drv = _board_display()
    radio = _radio()
    if hostname:
        _set_hostname(radio, hostname)
    return _Setup(radio, display_drv, timeout).run()


def networks():
    """The SSIDs of the remembered networks."""
    return [n["ssid"] for n in _load()]


def forget(ssid=None):
    """Forget one remembered network, or all of them when ``ssid`` is None."""
    nets = [] if ssid is None else [n for n in _load() if n["ssid"] != ssid]
    return _save(nets)


# ------------------------------------------------------------ known networks


def _from_settings():
    """Networks from secrets.py and CircuitPython's settings.toml."""
    found = []
    try:
        import secrets as s
    except ImportError:
        s = None
    except Exception as exc:
        print("wifi_manager: secrets.py failed to import:", exc)
        s = None
    if s is not None:
        ssid = getattr(s, "WIFI_SSID", None) or getattr(s, "ssid", None)
        password = getattr(s, "WIFI_PASSWORD", None) or getattr(s, "password", None)
        if ssid:
            found.append({"ssid": ssid, "password": password or ""})
    if _CP:
        import os

        ssid = os.getenv("CIRCUITPY_WIFI_SSID")
        if ssid:
            found.append({"ssid": ssid, "password": os.getenv("CIRCUITPY_WIFI_PASSWORD") or ""})
    return found


def _known():
    """Every network we may join.  secrets.py wins over a remembered password."""
    nets = []
    seen = set()
    for n in _from_settings() + _load():
        if n["ssid"] not in seen:
            seen.add(n["ssid"])
            nets.append(n)
    return nets


def _remember(ssid, password, hidden=False):
    """Save a network that worked.  Writes flash only when something changed."""
    nets = _load()
    for n in nets:
        if n["ssid"] == ssid:
            if n.get("password") == password and bool(n.get("hidden")) == hidden:
                return True
            nets.remove(n)
            break
    entry = {"ssid": ssid, "password": password}
    if hidden:
        entry["hidden"] = True
    nets.insert(0, entry)
    return _save(nets)


def _load():
    try:
        raw = _store_read()
    except Exception as exc:
        print("wifi_manager: can't read saved networks:", exc)
        return []
    if not raw:
        return []
    try:
        nets = json.loads(raw.decode())
    except (ValueError, UnicodeError):
        print("wifi_manager: saved networks are unreadable; starting fresh")
        return []
    if not isinstance(nets, list):
        return []
    return [n for n in nets if isinstance(n, dict) and n.get("ssid")]


def _save(nets):
    nets = nets[:_MAX_NETWORKS]
    limit = _store_limit()
    while True:
        data = json.dumps(nets).encode()
        if len(data) <= limit or not nets:
            break
        nets.pop()  # drop the oldest until it fits
    try:
        _store_write(data)
        return True
    except Exception as exc:
        print("wifi_manager: can't save networks:", exc)
        return False


def _store_kind():
    if _CP:
        try:
            import microcontroller

            if microcontroller.nvm is not None:
                return "nvm"
        except (ImportError, AttributeError):
            pass
        return "file"
    try:
        import esp32

        if hasattr(esp32, "NVS"):
            return "nvs"
    except ImportError:
        pass
    return "file"


def _store_limit():
    kind = _store_kind()
    if kind == "nvm":
        import microcontroller

        return len(microcontroller.nvm) - NVM_OFFSET - len(_MAGIC) - 2
    if kind == "nvs":
        return _NVS_MAX
    return 16384


def _store_read():
    kind = _store_kind()
    if kind == "nvm":
        import microcontroller

        nvm = microcontroller.nvm
        start = NVM_OFFSET + len(_MAGIC)
        if bytes(nvm[NVM_OFFSET:start]) != _MAGIC:
            return None
        n = nvm[start] | (nvm[start + 1] << 8)
        return bytes(nvm[start + 2 : start + 2 + n])
    if kind == "nvs":
        import esp32

        buf = bytearray(_NVS_MAX)
        try:
            n = esp32.NVS(_NVS_NAMESPACE).get_blob(_NVS_KEY, buf)
        except OSError:  # ESP_ERR_NVS_NOT_FOUND: nothing saved yet
            return None
        return bytes(buf[:n])
    try:
        with open(CACHE_FILE, "rb") as f:
            return f.read()
    except OSError:
        return None


def _store_write(data):
    kind = _store_kind()
    if kind == "nvm":
        import microcontroller

        nvm = microcontroller.nvm
        record = _MAGIC + bytes((len(data) & 0xFF, len(data) >> 8)) + data
        if NVM_OFFSET + len(record) > len(nvm):
            raise ValueError("nvm too small")
        nvm[NVM_OFFSET : NVM_OFFSET + len(record)] = record
    elif kind == "nvs":
        import esp32

        nvs = esp32.NVS(_NVS_NAMESPACE)
        nvs.set_blob(_NVS_KEY, data)
        nvs.commit()
    else:
        with open(CACHE_FILE, "wb") as f:
            f.write(data)


# --------------------------------------------------------------------- radio


def _radio():
    return _CPRadio() if _CP else _MPRadio()


def _set_hostname(radio, name):
    try:
        radio.set_hostname(name)
    except Exception as exc:
        print("wifi_manager: can't set hostname:", exc)


def _join_known(radio, timeout):
    known = _known()
    if not known:
        print("wifi_manager: no networks known yet")
        return None
    try:
        seen = radio.scan()
    except Exception as exc:
        print("wifi_manager: scan failed:", exc)
        seen = None
    if seen is None:
        order = known
    else:
        order = [n for n in known if n["ssid"] in seen]
        order.sort(key=lambda n: -seen[n["ssid"]])
        order += [n for n in known if n.get("hidden") and n["ssid"] not in seen]
    for n in order:
        ip = _try_join(radio, n["ssid"], n.get("password", ""), timeout, seen)
        if ip:
            # A network from secrets.py lands in the cache here, which is what
            # lets secrets.py be deleted afterwards.
            _remember(n["ssid"], n.get("password", ""), bool(n.get("hidden")))
            return ip
    return None


def _try_join(radio, ssid, password, timeout, seen=None):
    rssi = seen.get(ssid) if seen else None
    print("wifi_manager: joining", ssid, "(%d dBm)" % rssi if rssi is not None else "")
    err = radio.join(ssid, password, timeout)
    if err is None:
        ip = radio.ip()
        print("wifi_manager: connected to", ssid, "as", ip)
        return ip
    print("wifi_manager:", ssid, "-", err)
    return None


class _MPRadio:
    """MicroPython ``network.WLAN``: one STA and one AP interface."""

    def __init__(self):
        import network

        self._net = network
        self.sta = network.WLAN(network.STA_IF)
        self.sta.active(True)
        self.ap = network.WLAN(network.AP_IF)

    def ip(self):
        try:
            if not self.sta.isconnected():
                return None
            ip = self.sta.ifconfig()[0]
        except Exception:
            return None
        return ip if ip and ip != "0.0.0.0" else None

    def set_hostname(self, name):
        self._net.hostname(name)

    def mac(self):
        return bytes(self.sta.config("mac"))

    def scan(self):
        """``{ssid: best rssi}`` for every network in range."""
        best = {}
        for rec in self.sta.scan():
            try:
                ssid = rec[0].decode()
            except UnicodeError:
                continue
            if ssid and (ssid not in best or rec[3] > best[ssid]):
                best[ssid] = rec[3]
        return best

    def join(self, ssid, password, timeout):
        """None on success, else a short reason."""
        net = self._net
        # esp32 reports these while it retries, so they only end the wait
        # after a grace period.  15 and 204 are handshake timeouts, which is
        # how most WPA2 routers turn away a wrong password.
        wrong = (getattr(net, "STAT_WRONG_PASSWORD", 202), 15, 204)
        no_ap = getattr(net, "STAT_NO_AP_FOUND", 201)
        try:
            self.sta.disconnect()
        except OSError:
            pass
        # `reconnects` stays at its default of 0, which in this port is retry
        # forever. -1 means give up after the first drop (network_wlan.c).
        self.sta.connect(ssid, password)
        t0 = _ticks_ms()
        reason = "timed out after %ds" % timeout
        while _ticks_diff(_ticks_ms(), t0) < timeout * 1000:
            if self.ip():
                return None
            if _ticks_diff(_ticks_ms(), t0) > 6000:
                st = self.sta.status()
                if st in wrong:
                    reason = "wrong password"
                    break
                if st == no_ap:
                    reason = "network not found"
                    break
            _sleep_ms(200)
        try:
            self.sta.disconnect()
        except OSError:
            pass
        return reason

    def start_ap(self, ssid, password):
        self.ap.active(True)
        net = self._net
        auth = getattr(net, "AUTH_WPA2_PSK", None)
        if auth is None:
            auth = getattr(net.WLAN, "SEC_WPA2", 3)
        self.ap.config(essid=ssid, password=password, authmode=auth)
        return self.ap.ifconfig()[0]

    def stop_ap(self):
        self.ap.active(False)

    def sockets(self):
        import socket

        return socket


class _CPRadio:
    """CircuitPython ``wifi.radio``."""

    def __init__(self):
        import socketpool
        import wifi

        self.r = wifi.radio
        self.r.enabled = True
        self._socketpool = socketpool
        self._pool = None

    def ip(self):
        a = self.r.ipv4_address
        return str(a) if a else None

    def set_hostname(self, name):
        self.r.hostname = name

    def mac(self):
        return bytes(self.r.mac_address)

    def scan(self):
        best = {}
        try:
            for n in self.r.start_scanning_networks():
                if n.ssid and (n.ssid not in best or n.rssi > best[n.ssid]):
                    best[n.ssid] = n.rssi
        finally:
            self.r.stop_scanning_networks()
        return best

    def join(self, ssid, password, timeout):
        try:
            self.r.connect(ssid, password, timeout=timeout)
        except Exception as exc:  # ConnectionError carries the reason
            return str(exc) or type(exc).__name__
        return None if self.ip() else "no address"

    def start_ap(self, ssid, password):
        self.r.start_ap(ssid, password)
        a = self.r.ipv4_address_ap
        return str(a) if a else "192.168.4.1"

    def stop_ap(self):
        self.r.stop_ap()

    def sockets(self):
        if self._pool is None:
            self._pool = self._socketpool.SocketPool(self.r)
        return self._pool


# ---------------------------------------------------------------- setup mode


class _Setup:
    """The access point, the captive DNS, the setup page, and the screen."""

    def __init__(self, radio, display_drv, timeout):
        self.radio = radio
        self.display_drv = display_drv
        self.timeout = timeout
        self.seen = {}
        self.message = ""
        self.pending = None
        self.dns = None
        self.http = None
        self.port = 80

    def run(self):
        radio = self.radio
        try:
            self.seen = radio.scan()  # before the AP is up: a cleaner scan
        except Exception as exc:
            print("wifi_manager: scan failed:", exc)
        mac = radio.mac()
        ap_name = "%s-%02X%02X" % (AP_PREFIX, mac[-2], mac[-1])
        ap_pass = "".join(_PW_CHARS[b % len(_PW_CHARS)] for b in _random_bytes(8))
        ap_ip = radio.start_ap(ap_name, ap_pass)
        self._open_sockets(ap_ip)
        url = "http://" + ap_ip + ("" if self.port == 80 else ":%d" % self.port)
        ui = _make_ui(self.display_drv)
        try:
            ui.show(ap_name, ap_pass, url)
            last_scan = _ticks_ms()
            while True:
                self._serve_dns(ap_ip)
                self._serve_http()
                if self.pending:
                    ssid, password, hidden = self.pending
                    self.pending = None
                    ui.status("Joining %s..." % ssid)
                    ip = _try_join(radio, ssid, password, self.timeout, self.seen)
                    if ip:
                        _remember(ssid, password, hidden)
                        ui.status("Connected to %s  %s" % (ssid, ip), ok=True)
                        _sleep_ms(2000)
                        return ip
                    self.message = "Couldn't join %s. Check the password and try again." % ssid
                    ui.status(self.message, error=True)
                    last_scan = _ticks_ms()
                elif _ticks_diff(_ticks_ms(), last_scan) > RESCAN_S * 1000:
                    ui.status("Looking for a known network...")
                    ip = _join_known(radio, self.timeout)
                    if ip:
                        ui.status("Connected  %s" % ip, ok=True)
                        _sleep_ms(2000)
                        return ip
                    try:
                        self.seen = radio.scan() or self.seen
                    except Exception:
                        pass
                    ui.status(self.message or "Waiting for setup", error=bool(self.message))
                    last_scan = _ticks_ms()
                _sleep_ms(20)
        finally:
            self._close_sockets()
            try:
                radio.stop_ap()
            except Exception:
                pass
            ui.close()

    # -- sockets

    def _open_sockets(self, ap_ip):
        pool = self.radio.sockets()
        self.dns = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        self.dns.bind(("0.0.0.0", 53))
        self.dns.setblocking(False)
        for port in (80, 8080):  # CircuitPython's web workflow may hold 80
            s = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
            try:
                s.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
            except Exception:
                pass
            try:
                s.bind(("0.0.0.0", port))
                s.listen(2)
            except OSError:
                s.close()
                continue
            s.setblocking(False)
            self.http, self.port = s, port
            break
        if self.http is None:
            raise OSError("wifi_manager: no free port for the setup page")

    def _close_sockets(self):
        for s in (self.dns, self.http):
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
        self.dns = self.http = None

    def _serve_dns(self, ap_ip):
        """Answer every name with the board, so phones open the setup page."""
        try:
            query, addr = _recvfrom(self.dns, 512)
        except OSError:
            return
        reply = _dns_reply(query, bytes(int(p) for p in ap_ip.split(".")))
        if reply:
            try:
                self.dns.sendto(reply, addr)
            except OSError:
                pass

    def _serve_http(self):
        try:
            conn, _ = self.http.accept()
        except OSError:
            return
        try:
            conn.settimeout(3)
            req = _read_request(conn)
            if req is not None:
                _sendall(conn, self._respond(*req))
        except Exception as exc:
            print("wifi_manager: page error:", exc)
        finally:
            conn.close()

    # -- the page

    def _respond(self, method, path, body):
        if method == "POST":
            form = _form(body)
            if path.startswith("/join"):
                ssid = form.get("other", "").strip() or form.get("ssid", "")
                if ssid:
                    password = form.get("password", "")
                    self.pending = (ssid, password, ssid not in self.seen)
                    return _http(_page_trying(ssid))
                self.message = "Pick a network first."
            elif path.startswith("/forget"):
                ssid = form.get("ssid", "")
                if ssid:
                    forget(ssid)
                    self.message = "Forgot %s." % ssid
            elif path.startswith("/scan"):
                try:
                    self.seen = self.radio.scan() or self.seen
                except Exception as exc:
                    self.message = "Scan failed: %s" % exc
            return _http("", status="303 See Other", extra="Location: /\r\n")
        # Everything else, the phones' captive-portal probes included, gets the
        # page: a 200 that isn't what the probe expects is what opens the sheet.
        return _http(_page_form(self.seen, networks(), self.message))


def _random_bytes(n):
    try:
        import os

        return os.urandom(n)
    except (ImportError, AttributeError, NotImplementedError):
        import random

        return bytes(random.getrandbits(8) for _ in range(n))


def _recvfrom(sock, n):
    if hasattr(sock, "recvfrom"):
        return sock.recvfrom(n)
    buf = bytearray(n)
    k, addr = sock.recvfrom_into(buf)  # CircuitPython has only the _into forms
    return bytes(buf[:k]), addr


def _recv(sock, n):
    if hasattr(sock, "recv"):
        return sock.recv(n)
    buf = bytearray(n)
    k = sock.recv_into(buf, n)
    return bytes(buf[:k])


def _sendall(sock, data):
    if hasattr(sock, "sendall"):
        sock.sendall(data)
        return
    view = memoryview(data)
    while view:
        view = view[sock.send(view) :]


def _dns_reply(query, ip):
    if len(query) < 12:
        return None
    i = 12
    while i < len(query) and query[i]:
        i += query[i] + 1
    i += 5  # the name's zero byte, QTYPE, QCLASS
    if i > len(query):
        return None
    is_a = query[i - 4] == 0 and query[i - 3] == 1
    head = (
        query[:2]
        + b"\x81\x80\x00\x01"
        + (b"\x00\x01" if is_a else b"\x00\x00")
        + b"\x00\x00\x00\x00"
    )
    out = head + query[12:i]
    if is_a:
        out += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04" + ip
    return out


def _read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data and len(data) < 4096:
        chunk = _recv(conn, 1024)
        if not chunk:
            break
        data += chunk
    if b"\r\n\r\n" not in data:
        return None
    head, body = data.split(b"\r\n\r\n", 1)
    lines = head.decode().split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) < 2:
        return None
    length = 0
    for line in lines[1:]:
        if line.lower().startswith("content-length:"):
            try:
                length = min(int(line.split(":", 1)[1].strip()), 2048)
            except ValueError:
                pass
    while len(body) < length:
        chunk = _recv(conn, length - len(body))
        if not chunk:
            break
        body += chunk
    return parts[0], parts[1], body.decode()


def _unquote(s):
    s = s.replace("+", " ")
    pieces = s.split("%")
    out = bytearray(pieces[0].encode())
    for p in pieces[1:]:
        try:
            out.append(int(p[:2], 16))
            out.extend(p[2:].encode())
        except ValueError:
            out.extend(("%" + p).encode())
    return bytes(out).decode()


def _form(body):
    form = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            form[_unquote(k)] = _unquote(v)
    return form


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _http(html, status="200 OK", extra=""):
    body = html.encode()
    head = (
        "HTTP/1.1 %s\r\nContent-Type: text/html; charset=utf-8\r\n"
        "Content-Length: %d\r\nCache-Control: no-store\r\n%sConnection: close\r\n\r\n"
        % (status, len(body), extra)
    )
    return head.encode() + body


_STYLE = (
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<style>body{font-family:sans-serif;max-width:28em;margin:1em auto;padding:0 1em}"
    "label{display:block;padding:.5em 0;border-bottom:1px solid #ddd}"
    "small{color:#888}input[type=text],input[type=password]{width:100%;font-size:1.1em;"
    "padding:.4em;box-sizing:border-box}button{font-size:1.1em;padding:.5em 1.2em;margin:.6em 0}"
    ".msg{color:#b00}.saved form{display:inline}</style>"
)


def _page_form(seen, saved, message):
    rows = []
    for ssid in sorted(seen, key=lambda s: -seen[s]):
        e = _esc(ssid)
        rows.append(
            '<label><input type=radio name=ssid value="%s"> %s <small>%d dBm%s</small></label>'
            % (e, e, seen[ssid], ", saved" if ssid in saved else "")
        )
    if not rows:
        rows.append("<p>No networks found. Press Rescan, or type the name below.</p>")
    forget_rows = "".join(
        '<li>%s <form method=post action=/forget><input type=hidden name=ssid value="%s">'
        "<button>Forget</button></form></li>" % (_esc(s), _esc(s))
        for s in saved
    )
    return (
        "<!doctype html><html><head><title>Wi-Fi setup</title>%s</head><body>"
        "<h2>Wi-Fi setup</h2>%s"
        "<form method=post action=/join>%s"
        "<label>Other (hidden network)<input type=text name=other autocapitalize=none></label>"
        "<label>Password<input type=password name=password id=pw autocapitalize=none></label>"
        "<label><input type=checkbox onclick=\"pw.type=this.checked?'text':'password'\"> Show password</label>"
        "<button>Join</button></form>"
        "<form method=post action=/scan><button>Rescan</button></form>"
        "%s</body></html>"
        % (
            _STYLE,
            "<p class=msg>%s</p>" % _esc(message) if message else "",
            "".join(rows),
            "<div class=saved><h3>Saved networks</h3><ul>%s</ul></div>" % forget_rows
            if saved
            else "",
        )
    )


def _page_trying(ssid):
    return (
        "<!doctype html><html><head><title>Joining</title>%s</head><body>"
        "<h2>Joining %s</h2>"
        "<p>Watch the board's screen. If it works, the board's own network goes away "
        "and your phone goes back to its usual Wi-Fi.</p>"
        "<p>If it doesn't, the board's network comes back. Reopen this page to see why "
        "and try again.</p></body></html>" % (_STYLE, _esc(ssid))
    )


# -------------------------------------------------------------------- screens


def _board_display():
    try:
        import board_config
    except ImportError:
        return None
    except Exception as exc:
        print("wifi_manager: board_config failed:", exc)
        return None
    return getattr(board_config, "display_drv", None)


def _make_ui(display_drv):
    """LVGL when it is compiled in, else pygraphics on display_drv, else the REPL."""
    try:
        return _LvUI()
    except ImportError:
        pass
    except Exception as exc:
        print("wifi_manager: LVGL screen unavailable:", exc)
    if display_drv is not None:
        try:
            return _GfxUI(display_drv)
        except ImportError:
            pass
        except Exception as exc:
            print("wifi_manager: screen unavailable:", exc)
    return _ReplUI()


def _wifi_qr(ap_name, ap_pass):
    return "WIFI:T:WPA;S:%s;P:%s;;" % (ap_name, ap_pass)


class _ReplUI:
    qr_hint = False  # True when a QR code would show if adafruit_miniqr were installed

    def show(self, ap_name, ap_pass, url):
        print()
        print("wifi_manager: no known network in range. To set one up:")
        print("  1. Join Wi-Fi  %s  password  %s" % (ap_name, ap_pass))
        print("  2. Open %s if the setup page doesn't open by itself" % url)
        print("  3. Pick your network and type its password")
        if self.qr_hint:
            print("  For a QR code on the screen, install adafruit_miniqr:")
            print("    " + _MINIQR_INSTALL)
        print()

    def status(self, text, ok=False, error=False):
        print("wifi_manager:", text)

    def close(self):
        pass


def _encode(rgb, depth):
    r, g, b = rgb
    if depth == 16:
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    if depth >= 24:
        return (r << 16) | (g << 8) | b
    if depth == 8:
        return (r & 0xE0) | ((g & 0xE0) >> 3) | (b >> 6)
    lum = (r * 77 + g * 151 + b * 28) >> 8
    if depth == 4:
        return lum >> 4
    if depth == 2:
        return lum >> 6
    return 1 if lum > 0x7F else 0


def _wrap(text, cols):
    """Greedy word wrap; words longer than a line are split."""
    cols = max(1, cols)
    out = []
    line = ""
    for word in text.split(" "):
        while len(word) > cols:
            if line:
                out.append(line)
                line = ""
            out.append(word[:cols])
            word = word[cols:]
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= cols:
            line += " " + word
        else:
            out.append(line)
            line = word
    out.append(line)
    return out


class _GfxUI(_ReplUI):
    """pygraphics text, scaled to the panel, drawn straight onto display_drv."""

    _COLS = 22  # characters a line should hold before the scale steps down

    def __init__(self, display_drv):
        import pygraphics

        self.pg = pygraphics
        self.d = display_drv
        self.W = display_drv.width
        self.H = display_drv.height
        depth = getattr(display_drv, "color_depth", None) or 16
        self.fmt = {
            1: pygraphics.MONO_HMSB,
            2: pygraphics.GS2_HMSB,
            4: pygraphics.GS4_HMSB,
            8: pygraphics.GS8,
            16: pygraphics.RGB565,
            24: pygraphics.RGB888,
        }[depth]
        self.depth = depth
        self.bg = _encode((0, 0, 0), depth)
        self.fg = _encode((255, 255, 255), depth)
        self.accent = _encode((85, 255, 255), depth)
        self.muted = _encode((170, 170, 170), depth)
        self.good = _encode((85, 255, 85), depth)
        self.bad = _encode((255, 85, 85), depth)
        try:
            import adafruit_miniqr

            self.miniqr = adafruit_miniqr
        except ImportError:
            self.miniqr = None
            self.qr_hint = True
        self._strip = None
        self._strip_key = None

    def show(self, ap_name, ap_pass, url):
        super().show(ap_name, ap_pass, url)
        W, H = self.W, self.H
        pad = max(4, min(W, H) // 40)
        matrix = self._qr_matrix(_wifi_qr(ap_name, ap_pass))
        if matrix is not None:
            if W >= H:
                side = min(H - 2 * pad, W * 45 // 100)
                qr_box = (pad, (H - side) // 2, side)
                tx, ty, tw, th = side + 2 * pad, pad, W - side - 3 * pad, H - 2 * pad
            else:
                side = min(W - 2 * pad, H * 45 // 100)
                qr_box = ((W - side) // 2, H - side - pad, side)
                tx, ty, tw, th = pad, pad, W - 2 * pad, H - side - 3 * pad
        else:
            qr_box = None
            tx, ty, tw, th = pad, pad, W - 2 * pad, H - 2 * pad

        lines = [
            ("Wi-Fi setup", self.accent),
            ("", 0),
            ("1. Join Wi-Fi", self.fg),
            ("   " + ap_name, self.accent),
            ("   password " + ap_pass, self.accent),
            ("2. Open " + url, self.fg),
            ("3. Pick your network", self.fg),
        ]
        hint = "For a QR code: " + _MINIQR_INSTALL if self.qr_hint else ""
        # Rows: the lines, a blank, two of status, and the hint at half scale.
        rows = len(lines) + 3 + (2 if hint else 0)
        scale = max(1, min(tw // (8 * self._COLS), th // (18 * rows)))
        cols = tw // (8 * scale)

        self.d.fill_rect(0, 0, W, H, self.bg)
        y = ty
        lh = 18 * scale
        for text, color in lines:
            for part in _wrap(text, cols) if text else [""]:
                if part:
                    self._text(tx, y, tw, part, color, scale)
                y += lh
        y += lh // 2
        self._status_box = (tx, y, tw, 2 * lh, scale, cols)
        y += 2 * lh
        if hint:
            hs = max(1, scale // 2)
            for part in _wrap(hint, tw // (8 * hs)):
                if y + 16 * hs > H:
                    break
                self._text(tx, y, tw, part, self.muted, hs)
                y += 18 * hs
        if qr_box is not None:
            self._draw_qr(matrix, *qr_box)
        self._present()

    def status(self, text, ok=False, error=False):
        super().status(text, ok, error)
        x, y, w, h, scale, cols = self._status_box
        self.d.fill_rect(x, y, w, h, self.bg)
        color = self.good if ok else self.bad if error else self.muted
        for i, part in enumerate(_wrap(text, cols)[:2]):
            self._text(x, y + i * 18 * scale, w, part, color, scale)
        self._present()

    def close(self):
        self.d.fill_rect(0, 0, self.W, self.H, self.bg)
        self._present()
        self._strip = None

    def _present(self):
        show = getattr(self.d, "show", None)
        if show is not None:
            try:
                show()
            except Exception:
                pass

    def _text(self, x, y, w, text, color, scale):
        """One opaque line: composed in a strip, sent in one blit."""
        h = 16 * scale
        key = (w, h)
        try:
            if self._strip_key != key:
                self._strip = None
                buf = bytearray((w * self.depth + 7) // 8 * h)
                self._strip = (buf, self.pg.FrameBuffer(buf, w, h, self.fmt))
                self._strip_key = key
            buf, fb = self._strip
            fb.fill(self.bg)
            fb.text16(text, 0, 0, color, scale)
            self.d.blit_rect(buf, x, y, w, h)
        except MemoryError:
            # Not enough RAM for a strip: draw glyph pixels straight on the panel.
            self._strip = self._strip_key = None
            self.d.fill_rect(x, y, w, h, self.bg)
            self.pg.text16(self.d, text, x, y, color, scale)

    def _qr_matrix(self, payload):
        if self.miniqr is None:
            return None
        try:
            qr = self.miniqr.QRCode(error_correct=self.miniqr.L)
            qr.add_data(payload.encode())
            qr.make()
            return qr.matrix
        except Exception as exc:
            print("wifi_manager: QR code failed:", exc)
            return None

    def _draw_qr(self, matrix, x, y, side):
        border = 2
        n = matrix.width
        module = side // (n + 2 * border)
        if module < 1:
            return
        full = module * (n + 2 * border)
        x += (side - full) // 2
        y += (side - full) // 2
        light = _encode((255, 255, 255), self.depth)
        dark = _encode((0, 0, 0), self.depth)
        self.d.fill_rect(x, y, full, full, light)
        ox = x + border * module
        oy = y + border * module
        for row in range(n):
            col = 0
            while col < n:
                if matrix[col, row]:
                    start = col
                    while col < n and matrix[col, row]:
                        col += 1
                    self.d.fill_rect(
                        ox + start * module,
                        oy + row * module,
                        (col - start) * module,
                        module,
                        dark,
                    )
                else:
                    col += 1


class _LvUI(_ReplUI):
    """The same page in LVGL, with lv.qrcode."""

    def __init__(self):
        import display_driver  # noqa: F401  wires LVGL to board_config's display
        import lvgl as lv

        self.lv = lv
        self.prev = lv.screen_active()
        self.W = self.prev.get_width()
        self.H = self.prev.get_height()
        self.scr = None
        self.status_lbl = None

    def _font(self, target):
        for size in (48, 40, 36, 32, 28, 24, 22, 20, 18, 16, 14, 12):
            if size <= target:
                font = getattr(self.lv, "font_montserrat_%d" % size, None)
                if font is not None:
                    return font
        return None

    def _label(self, parent, text, color, font, width):
        lv = self.lv
        lbl = lv.label(parent)
        lbl.set_width(width)
        lm = getattr(lv.label, "LONG_MODE", None)
        mode = getattr(lm, "WRAP", None) if lm is not None else None
        if mode is not None:
            lbl.set_long_mode(mode)
        lbl.set_style_text_color(lv.color_hex(color), 0)
        if font is not None:
            lbl.set_style_text_font(font, 0)
        lbl.set_text(text)
        return lbl

    def show(self, ap_name, ap_pass, url):
        super().show(ap_name, ap_pass, url)
        lv = self.lv
        W, H = self.W, self.H
        pad = max(4, min(W, H) // 40)
        scr = lv.obj()
        scr.set_style_bg_color(lv.color_hex(0x000000), 0)
        flag = getattr(getattr(lv.obj, "FLAG", None), "SCROLLABLE", None)
        if flag is not None and hasattr(scr, "remove_flag"):
            scr.remove_flag(flag)
        has_qr = getattr(lv, "qrcode", None) is not None
        if has_qr and W >= H:
            side = min(H - 2 * pad, W * 45 // 100)
            qx, qy = pad, (H - side) // 2
            tx, ty, tw, th = side + 2 * pad, pad, W - side - 3 * pad, H - 2 * pad
        elif has_qr:
            side = min(W - 2 * pad, H * 45 // 100)
            qx, qy = (W - side) // 2, H - side - pad
            tx, ty, tw, th = pad, pad, W - 2 * pad, H - side - 3 * pad
        else:
            tx, ty, tw, th = pad, pad, W - 2 * pad, H - 2 * pad
        # Ten text rows should fit the column; montserrat line height ~1.2x size.
        font = self._font(min(th // 12, tw // 14))
        text = "1. Join Wi-Fi\n    %s\n    password  %s\n2. Open %s\n3. Pick your network" % (
            ap_name,
            ap_pass,
            url,
        )
        title = self._label(scr, "Wi-Fi setup", 0x55FFFF, font, tw)
        title.set_pos(tx, ty)
        body = self._label(scr, text, 0xFFFFFF, font, tw)
        body.align_to(title, lv.ALIGN.OUT_BOTTOM_LEFT, 0, pad)
        self.status_lbl = self._label(scr, "", 0xAAAAAA, font, tw)
        self.status_lbl.align_to(body, lv.ALIGN.OUT_BOTTOM_LEFT, 0, 2 * pad)
        if has_qr:
            try:
                border = max(2, side // 16)
                qr = lv.qrcode(scr)
                qr.set_size(side - 2 * border)
                qr.set_dark_color(lv.color_hex(0x000000))
                qr.set_light_color(lv.color_hex(0xFFFFFF))
                qr.set_style_border_color(lv.color_hex(0xFFFFFF), 0)
                qr.set_style_border_width(border, 0)
                data = _wifi_qr(ap_name, ap_pass).encode()
                qr.update(data, len(data))
                qr.set_pos(qx, qy)
            except Exception as exc:
                print("wifi_manager: lv.qrcode failed:", exc)
        lv.screen_load(scr)
        self.scr = scr
        self._refresh()

    def status(self, text, ok=False, error=False):
        super().status(text, ok, error)
        if self.status_lbl is None:
            return
        color = 0x55FF55 if ok else 0xFF5555 if error else 0xAAAAAA
        self.status_lbl.set_style_text_color(self.lv.color_hex(color), 0)
        self.status_lbl.set_text(text)
        self._refresh()

    def close(self):
        if self.scr is not None:
            self.lv.screen_load(self.prev)
            self.scr.delete()
            self.scr = self.status_lbl = None

    def _refresh(self):
        # Paint now: a CircuitPython join blocks in C and no timer runs meanwhile.
        try:
            self.lv.refr_now(None)
        except Exception:
            pass
        _sleep_ms(10)
