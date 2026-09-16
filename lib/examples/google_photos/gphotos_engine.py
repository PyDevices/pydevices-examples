# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
`gphotos_engine`
====================================================

Google Photos Picker API client — no display, event, or UI imports.

Since March 31, 2025 the Google Photos Library API only returns media that
the calling app uploaded itself, so the only self-serve way for a device to
show photos from a user's own library is the **Picker API**: the app creates
a *picker session*, the user opens the session's ``pickerUri`` (shown here as
a QR code) in Google Photos on their phone, picks photos, and the app then
lists the picked items and fetches sized thumbnails.

What this module does, with plain HTTPS (``urllib`` on CPython, ``requests``
on MicroPython, ``adafruit_requests`` on CircuitPython, raw ``socket`` + TLS
as the last resort):

* Mint access tokens from a stored **refresh token** (Google's TV
  "device code" login refuses the Picker scope, and Google will not register
  a LAN IP as an OAuth redirect, so the one-time browser login runs on a PC
  via ``tools/gphotos_auth.py`` and its output JSON is copied to the device).
* Create / poll / delete picker sessions, list picked media items, and
  download ``baseUrl`` thumbnails (which need the bearer token and expire
  after 60 minutes — this module re-lists to refresh them).
* Persist the session and the picked list in a small prefs file so a reboot
  lands on the list without re-picking, and keep a bounded thumbnail cache
  on flash so images are downloaded once.

Files (desktop ``~/…``, MCU ``/…``; override with ``GPHOTOS_TOKENS``,
``GPHOTOS_PREFS``, ``GPHOTOS_CACHE``):

* ``.gphotos_tokens.json`` — ``client_id``, ``client_secret``,
  ``refresh_token`` (written by ``tools/gphotos_auth.py``; read-only here).
* ``.gphotos_prefs`` — JSON: current session, picked items (without their
  short-lived URLs), ``slideshow_s``.
* ``.gphotos_cache/`` — ``<hash>_<w>x<h>[c].jpg|png`` thumbnails.

Usage::

    from gphotos_engine import GPhotosEngine

    eng = GPhotosEngine()
    eng.restore()                        # prefs: session + items
    if not eng.items:
        s = eng.create_session()         # show s["pickerUri"] as a QR code
        while not eng.poll_session():
            time.sleep(eng.poll_interval_s())
        eng.list_items()
    path = eng.thumbnail_path(eng.items[0], 96, 96, crop=True)

Blocking network calls only; the LVGL front end queues them on its main-tick
pump (no ``_thread``). Errors never raise out of the public methods: they
return ``None`` / ``False`` / ``""`` and set :attr:`GPhotosEngine.last_error`.
"""

import sys

try:
    import json
except ImportError:  # pragma: no cover
    json = None

try:
    import os
except ImportError:  # pragma: no cover
    os = None

try:
    import time
except ImportError:  # pragma: no cover
    time = None

try:
    import socket
except ImportError:  # pragma: no cover — e.g. CircuitPython unix, PyScript
    socket = None

TOKEN_URL = "https://oauth2.googleapis.com/token"
PICKER_BASE = "https://photospicker.googleapis.com/v1"
SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"

TOKENS_HOME_NAME = ".gphotos_tokens.json"
TOKENS_MCU_NAME = "/gphotos_tokens.json"
PREFS_HOME_NAME = ".gphotos_prefs"
PREFS_MCU_NAME = "/gphotos_prefs"
CACHE_HOME_NAME = ".gphotos_cache"
CACHE_MCU_NAME = "/gphotos_cache"

# Picker base URLs stay valid for 60 minutes; re-list a little early.
URL_TTL_S = 50 * 60
# Refresh the access token this long before Google says it expires.
TOKEN_MARGIN_S = 60
PAGE_SIZE = 25
DEFAULT_MAX_ITEMS = 100
DEFAULT_CACHE_MAX = 48
DEFAULT_SLIDESHOW_S = 5
DOWNLOAD_CHUNK = 2048

# Set by the launcher so ``gphotos_lvgl`` does not auto-run on import.
_LAUNCHER_OWNS_RUN = False


class GPhotosError(Exception):
    """Transport-level failure (no HTTP status available)."""


# ----------------------------------------------------------------------
# Small portable helpers (no os.path / pathlib — MicroPython-safe)
# ----------------------------------------------------------------------


def _env_get(name):
    """Portable getenv (CPython / MicroPython / CircuitPython)."""
    if os is None:
        return None
    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            val = environ.get(name)
            if val:
                return val
        except Exception:
            pass
    getenv = getattr(os, "getenv", None)
    if getenv is not None:
        try:
            return getenv(name)
        except Exception:
            return None
    return None


def _path_join(base, name):
    """Join directory + filename without requiring ``os.path``."""
    if not base:
        return name
    if base.endswith("/") or base.endswith("\\"):
        return base + name
    if sys.platform == "win32" and len(base) >= 2 and base[1] == ":":
        return base + "\\" + name
    return base + "/" + name


def _user_home_dir():
    """Best-effort user home on desktop hosts; empty on typical MCU images."""
    for key in ("HOME", "USERPROFILE"):
        val = _env_get(key)
        if val:
            return val
    try:
        expanduser = getattr(getattr(os, "path", None), "expanduser", None)
        if expanduser is not None:
            home = expanduser("~")
            if home and home != "~":
                return home
    except Exception:
        pass
    return ""


def _default_path(env_name, home_name, mcu_name):
    override = _env_get(env_name)
    if override:
        return override
    home = _user_home_dir()
    if home and home not in (".", "/"):
        return _path_join(home, home_name)
    return mcu_name


def tokens_path():
    """Desktop ``~/.gphotos_tokens.json``; MCU ``/gphotos_tokens.json``."""
    return _default_path("GPHOTOS_TOKENS", TOKENS_HOME_NAME, TOKENS_MCU_NAME)


def prefs_path():
    """Desktop ``~/.gphotos_prefs``; MCU ``/gphotos_prefs``."""
    return _default_path("GPHOTOS_PREFS", PREFS_HOME_NAME, PREFS_MCU_NAME)


def cache_dir():
    """Desktop ``~/.gphotos_cache``; MCU ``/gphotos_cache``."""
    return _default_path("GPHOTOS_CACHE", CACHE_HOME_NAME, CACHE_MCU_NAME)


def _exists(path):
    if os is None or not path:
        return False
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _ensure_dir(path):
    if os is None or not path:
        return False
    if _exists(path):
        return True
    try:
        os.mkdir(path)
        return True
    except OSError:
        return False


def _remove(path):
    if os is None or not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _read_text(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""


def _write_text(path, text):
    try:
        with open(path, "w") as f:
            f.write(text)
        return True
    except OSError:
        return False


def _mono_ms():
    """Monotonic milliseconds; compare only via :func:`_elapsed_ms`."""
    if time is None:
        return 0
    f = getattr(time, "ticks_ms", None)
    if f is not None:
        return f()
    f = getattr(time, "monotonic", None)
    if f is not None:
        return int(f() * 1000)
    return int(time.time() * 1000)


def _elapsed_ms(since):
    now = _mono_ms()
    f = getattr(time, "ticks_diff", None) if time is not None else None
    if f is not None:
        return f(now, since)
    return now - since


_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def quote(value):
    """RFC 3986 percent-encoding (everything but unreserved characters)."""
    out = []
    for ch in str(value):
        if ch in _SAFE:
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append("%%%02X" % b)
    return "".join(out)


def form_encode(fields):
    """``application/x-www-form-urlencoded`` body from ``[(key, value), …]``."""
    return "&".join(quote(k) + "=" + quote(v) for k, v in fields)


def json_loads(raw):
    """Parse bytes/str JSON → dict (``{}`` on any failure)."""
    if json is None or not raw:
        return {}
    try:
        if isinstance(raw, (bytes, bytearray, memoryview)):
            raw = bytes(raw).decode("utf-8")
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def parse_duration_s(text, default=5.0):
    """Protobuf JSON duration (``"5s"``, ``"1.5s"``) → seconds."""
    if text is None:
        return default
    try:
        t = str(text).strip()
        if t.endswith("s"):
            t = t[:-1]
        return float(t)
    except (ValueError, TypeError):
        return default


def date_label(create_time):
    """``2024-05-03T14:22:11Z`` → ``2024-05-03``."""
    return (create_time or "")[:10]


def time_label(create_time):
    """``2024-05-03T14:22:11Z`` → ``14:22`` (UTC as reported by Google)."""
    t = create_time or ""
    return t[11:16] if len(t) >= 16 and t[10] == "T" else ""


def item_hash(item_id):
    """Short stable name for cache files (FNV-1a 32-bit of the media item id)."""
    h = 2166136261
    for b in str(item_id).encode("utf-8"):
        h ^= b
        h = (h * 16777619) & 0xFFFFFFFF
    return "%08x" % h


def thumb_url(base_url, w, h, crop=False):
    """Sized image URL from a Picker ``baseUrl`` (``-c`` crops to exactly w×h)."""
    if not base_url:
        return ""
    return "%s=w%d-h%d%s" % (base_url, int(w), int(h), "-c" if crop else "")


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def normalize_item(raw):
    """Flatten one Picker ``PickedMediaItem`` into the dict the UI consumes."""
    if not isinstance(raw, dict):
        return {}
    mf = raw.get("mediaFile") or {}
    meta = mf.get("mediaFileMetadata") or {}
    return {
        "id": raw.get("id") or "",
        "filename": mf.get("filename") or "",
        "createTime": raw.get("createTime") or "",
        "type": raw.get("type") or "",
        "mime": mf.get("mimeType") or "",
        "width": _to_int(meta.get("width")),
        "height": _to_int(meta.get("height")),
        "baseUrl": mf.get("baseUrl") or "",
    }


def sniff_ext(head):
    """``.jpg`` / ``.png`` / ``""`` from the first bytes of an image file."""
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return ""


# ----------------------------------------------------------------------
# HTTP transport (urllib → requests / adafruit_requests → raw socket + TLS)
# ----------------------------------------------------------------------

_requests_backend = None


def _find_requests():
    """MicroPython ``requests`` module or a CircuitPython ``adafruit_requests`` session."""
    global _requests_backend
    if _requests_backend is not None:
        return _requests_backend or None
    try:
        import requests as mod

        if hasattr(mod, "request"):
            _requests_backend = mod
            return mod
    except ImportError:
        pass
    try:
        import ssl
        import wifi
        import socketpool
        import adafruit_requests

        pool = socketpool.SocketPool(wifi.radio)
        _requests_backend = adafruit_requests.Session(pool, ssl.create_default_context())
        return _requests_backend
    except ImportError:
        pass
    _requests_backend = False
    return None


def _wrap_tls(sock, host):
    """Client TLS for the raw-socket fallback (no CA verification — the
    MicroPython ``requests`` default, and most boards have no CA bundle)."""
    try:
        import tls as _tls

        ctx = _tls.SSLContext(_tls.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = _tls.CERT_NONE
        return ctx.wrap_socket(sock, server_hostname=host)
    except ImportError:
        pass
    import ssl

    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            ctx.check_hostname = False
        except AttributeError:
            pass
        ctx.verify_mode = ssl.CERT_NONE
        return ctx.wrap_socket(sock, server_hostname=host)
    except (AttributeError, TypeError):
        return ssl.wrap_socket(sock, server_hostname=host)


class _SockIO:
    """Tiny buffered stream over CPython / MicroPython sockets (plain or TLS)."""

    def __init__(self, sock):
        self.s = sock
        self._buf = b""

    def send(self, data):
        s = self.s
        if hasattr(s, "sendall"):
            s.sendall(data)
            return
        mv = memoryview(data)
        off = 0
        while off < len(mv):
            n = s.write(mv[off:]) if hasattr(s, "write") else s.send(mv[off:])
            if n is None:
                n = len(mv) - off
            off += n

    def _recv(self, n):
        s = self.s
        if hasattr(s, "recv"):
            return s.recv(n)
        return s.read(n)

    def readline(self):
        while b"\n" not in self._buf:
            chunk = self._recv(512)
            if not chunk:
                line, self._buf = self._buf, b""
                return line
            self._buf += chunk
        i = self._buf.index(b"\n") + 1
        line, self._buf = self._buf[:i], self._buf[i:]
        return line

    def read(self, n):
        if self._buf:
            out, self._buf = self._buf[:n], self._buf[n:]
            return out
        return self._recv(n) or b""


def _socket_request(method, url, headers, body, timeout, sink=None):
    """HTTP/1.0 over ``socket`` (+TLS). Returns ``(status, body_bytes | n)``."""
    if socket is None:
        raise GPhotosError("no socket module")
    parts = url.split("/", 3)
    proto = parts[0]
    host = parts[2] if len(parts) > 2 else ""
    path = "/" + (parts[3] if len(parts) > 3 else "")
    https = proto == "https:"
    port = 443 if https else 80
    if ":" in host:
        host, p = host.rsplit(":", 1)
        port = int(p)
    ai = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
    s = socket.socket(ai[0], socket.SOCK_STREAM, ai[2])
    try:
        s.settimeout(timeout)
    except (AttributeError, OSError):
        pass
    s.connect(ai[-1])
    if https:
        s = _wrap_tls(s, host)
    io = _SockIO(s)
    try:
        lines = ["%s %s HTTP/1.0" % (method, path), "Host: " + host, "Connection: close"]
        hdrs = dict(headers or {})
        if body is not None and "Content-Length" not in hdrs:
            hdrs["Content-Length"] = str(len(body))
        for k in hdrs:
            lines.append("%s: %s" % (k, hdrs[k]))
        io.send(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
        if body:
            io.send(body)
        status_line = io.readline().split(None, 2)
        if len(status_line) < 2:
            raise GPhotosError("bad status line")
        status = int(status_line[1])
        length = -1
        while True:
            line = io.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        total = 0
        chunks = []
        while length < 0 or total < length:
            want = DOWNLOAD_CHUNK if length < 0 else min(DOWNLOAD_CHUNK, length - total)
            chunk = io.read(want)
            if not chunk:
                break
            total += len(chunk)
            if sink is not None:
                sink(chunk)
            else:
                chunks.append(chunk)
    finally:
        try:
            s.close()
        except Exception:
            pass
    return status, (total if sink is not None else b"".join(chunks))


def _urllib():
    """``(Request, urlopen, HTTPError, URLError)`` on CPython, else ``None``."""
    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError
    except ImportError:
        return None
    return Request, urlopen, HTTPError, URLError


def _status_of(resp):
    for name in ("status_code", "status", "code"):
        val = getattr(resp, name, None)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return 0


def _transport(method, url, headers, body, timeout, sink=None):
    """Run one request. ``sink(chunk)`` streams the body; else it is returned."""
    headers = dict(headers or {})
    if isinstance(body, str):
        body = body.encode("utf-8")

    # 1) CPython
    mods = _urllib()
    if mods is not None:
        Request, urlopen, HTTPError, URLError = mods
        req = Request(url, data=body, headers=headers, method=method)
        try:
            resp = urlopen(req, timeout=timeout)
        except HTTPError as err:
            raw = b""
            try:
                raw = err.read()
            except Exception:
                pass
            return int(getattr(err, "code", 0) or 0), raw
        except URLError as err:
            raise GPhotosError(str(getattr(err, "reason", err)))
        try:
            status = int(getattr(resp, "status", 200) or 200)
            if sink is None:
                return status, resp.read()
            total = 0
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                sink(chunk)
            return status, total
        finally:
            resp.close()

    # 2) MicroPython requests / CircuitPython adafruit_requests
    req = _find_requests()
    if req is not None:
        kwargs = {"data": body, "headers": headers, "stream": sink is not None}
        try:
            resp = req.request(method, url, timeout=timeout, **kwargs)
        except TypeError:
            resp = req.request(method, url, **kwargs)
        except AttributeError:
            # settimeout unsupported on this port
            resp = req.request(method, url, **kwargs)
        try:
            status = _status_of(resp)
            if sink is None:
                raw = getattr(resp, "content", None)
                if raw is None:
                    raw = resp.raw.read()
                return status, bytes(raw)
            total = 0
            iter_content = getattr(resp, "iter_content", None)
            if iter_content is not None:
                for chunk in iter_content(DOWNLOAD_CHUNK):
                    if chunk:
                        total += len(chunk)
                        sink(chunk)
            else:
                raw = resp.raw
                while True:
                    chunk = raw.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    sink(chunk)
            return status, total
        finally:
            try:
                resp.close()
            except Exception:
                pass

    # 3) raw socket
    return _socket_request(method, url, headers, body, timeout, sink)


def http_request(method, url, headers=None, data=None, timeout=20.0):
    """Portable HTTPS request → ``(status, body_bytes)``.

    Raises :class:`GPhotosError` only when no response arrived at all.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _transport(method.upper(), url, headers, data, timeout)


def http_download(url, path, headers=None, timeout=30.0):
    """Stream a GET to ``path`` → ``(status, bytes_written)``.

    The file holds whatever the server sent (an error body on non-2xx), so
    callers delete it unless the status is 200.
    """
    f = open(path, "wb")
    try:
        return _transport("GET", url, headers, None, timeout, sink=f.write)
    finally:
        f.close()


# ----------------------------------------------------------------------
# Credentials
# ----------------------------------------------------------------------


def load_tokens(path=None):
    """Read the tokens JSON (``{}`` when missing/invalid)."""
    data = json_loads(_read_text(path or tokens_path()))
    return data if isinstance(data, dict) else {}


def credentials_ok(tokens):
    """True when ``client_id`` and ``refresh_token`` are present."""
    return bool(tokens and tokens.get("client_id") and tokens.get("refresh_token"))


# ----------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------


class GPhotosEngine:
    """Picker API client with prefs + thumbnail cache (blocking calls)."""

    sim = False

    def __init__(
        self,
        tokens=None,
        tokens_file=None,
        prefs_file=None,
        cache_path=None,
        timeout=20.0,
        max_items=DEFAULT_MAX_ITEMS,
        cache_max=DEFAULT_CACHE_MAX,
    ):
        self.tokens_file = tokens_file or tokens_path()
        self.prefs_file = prefs_file or prefs_path()
        self.cache_path = cache_path or cache_dir()
        self.tokens = tokens if tokens is not None else load_tokens(self.tokens_file)
        self.timeout = timeout
        self.max_items = max_items
        self.cache_max = cache_max
        self.access_token = ""
        self._token_at = None
        self._token_ttl_ms = 0
        self.session = None
        self.items = []
        self._urls_at = None
        self.last_error = ""
        self.prefs = None

    # ----- credentials / tokens ---------------------------------------

    def has_credentials(self):
        return credentials_ok(self.tokens)

    def _token_expired(self):
        if self._token_at is None or not self.access_token:
            return True
        return _elapsed_ms(self._token_at) >= self._token_ttl_ms

    def ensure_token(self, force=False):
        """Mint an access token from the refresh token when needed."""
        if not force and not self._token_expired():
            return True
        if not self.has_credentials():
            self.last_error = "no credentials - run tools/gphotos_auth.py"
            return False
        t = self.tokens
        body = form_encode(
            [
                ("client_id", t.get("client_id", "")),
                ("client_secret", t.get("client_secret", "")),
                ("refresh_token", t.get("refresh_token", "")),
                ("grant_type", "refresh_token"),
            ]
        )
        status, raw = self._request(
            "POST",
            TOKEN_URL,
            {"Content-Type": "application/x-www-form-urlencoded"},
            body,
        )
        data = json_loads(raw)
        token = data.get("access_token") if status == 200 else None
        if not token:
            err = data.get("error") or ""
            if isinstance(err, dict):
                err = err.get("status") or err.get("message") or ""
            desc = data.get("error_description") or ""
            text = ("%s: %s" % (err, desc)) if (err and desc) else (err or desc)
            if status:
                self.last_error = ("token refresh: HTTP %d %s" % (status, text)).rstrip()
            elif not self.last_error:
                self.last_error = "token refresh failed"
            self.access_token = ""
            self._token_at = None
            return False
        ttl = _to_int(data.get("expires_in")) or 3600
        self.access_token = token
        self._token_at = _mono_ms()
        self._token_ttl_ms = max(30, ttl - TOKEN_MARGIN_S) * 1000
        self.last_error = ""
        return True

    def auth_headers(self):
        return {"Authorization": "Bearer " + self.access_token}

    # ----- raw HTTP ----------------------------------------------------

    def _request(self, method, url, headers=None, data=None):
        try:
            return http_request(method, url, headers=headers, data=data, timeout=self.timeout)
        except Exception as err:
            self.last_error = "network: %s" % err
            return 0, b""

    def _api(self, method, url, body=None, content_type=None, retry=True):
        """Authorized JSON call → ``(status, dict)``; refreshes once on 401."""
        if not self.ensure_token():
            return 0, {}
        headers = self.auth_headers()
        if body is not None:
            headers["Content-Type"] = content_type or "application/json"
        status, raw = self._request(method, url, headers, body)
        if status == 401 and retry and self.ensure_token(force=True):
            return self._api(method, url, body, content_type, retry=False)
        return status, json_loads(raw)

    def _api_error(self, what, status, data):
        err = data.get("error") if isinstance(data, dict) else None
        msg = ""
        if isinstance(err, dict):
            msg = err.get("message") or err.get("status") or ""
        elif isinstance(err, str):
            msg = err
        if status == 0:
            return self.last_error or ("%s: no response" % what)
        return "%s: HTTP %d %s" % (what, status, msg) if msg else "%s: HTTP %d" % (what, status)

    @staticmethod
    def _session_gone(status, data):
        if status in (404, 410):
            return True
        err = data.get("error") if isinstance(data, dict) else None
        text = ""
        if isinstance(err, dict):
            text = ("%s %s" % (err.get("status", ""), err.get("message", ""))).lower()
        return status == 400 and ("expired" in text or "not found" in text)

    # ----- sessions ----------------------------------------------------

    @staticmethod
    def _session_from(data, previous=None):
        pc = data.get("pollingConfig") or {}
        prev = previous or {}
        return {
            "id": data.get("id") or prev.get("id") or "",
            "pickerUri": data.get("pickerUri") or prev.get("pickerUri") or "",
            "expireTime": data.get("expireTime") or prev.get("expireTime") or "",
            "mediaItemsSet": bool(data.get("mediaItemsSet")),
            "pollInterval": parse_duration_s(
                pc.get("pollInterval"), prev.get("pollInterval", 5.0)
            ),
            "timeoutIn": parse_duration_s(pc.get("timeoutIn"), prev.get("timeoutIn", 1800.0)),
        }

    def create_session(self):
        """Start a picker session; returns the session dict (``pickerUri``…)."""
        status, data = self._api("POST", PICKER_BASE + "/sessions", body=b"{}")
        if status != 200 or not data.get("id") or not data.get("pickerUri"):
            self.last_error = self._api_error("create session", status, data)
            return None
        self.session = self._session_from(data)
        self.items = []
        self._urls_at = None
        self.last_error = ""
        self._save_prefs()
        return self.session

    def poll_interval_s(self):
        s = self.session or {}
        return max(2.0, float(s.get("pollInterval") or 5.0))

    def poll_session(self):
        """Refresh session state; True once the user finished picking."""
        s = self.session
        if not s or not s.get("id"):
            self.last_error = "no session"
            return False
        status, data = self._api("GET", PICKER_BASE + "/sessions/" + quote(s["id"]))
        if status == 200 and data.get("id"):
            self.session = self._session_from(data, s)
            self.last_error = ""
            self._save_prefs()
            return self.session["mediaItemsSet"]
        if self._session_gone(status, data):
            self.last_error = "session expired - pick again"
            self.session = None
            self._save_prefs()
            return False
        self.last_error = self._api_error("poll session", status, data)
        return False

    def delete_session(self):
        """Drop the picker session (Google forgets the picks); keeps the list."""
        s = self.session
        self.session = None
        self._urls_at = None
        self._save_prefs()
        if not s or not s.get("id"):
            return True
        status, data = self._api("DELETE", PICKER_BASE + "/sessions/" + quote(s["id"]))
        if status not in (200, 204) and not self._session_gone(status, data):
            self.last_error = self._api_error("delete session", status, data)
            return False
        return True

    # ----- media items -------------------------------------------------

    def list_items(self):
        """Fetch every picked item (fresh ``baseUrl``s) → list or ``None``."""
        s = self.session
        if not s or not s.get("id"):
            self.last_error = "no session"
            return None
        items = []
        token = ""
        while True:
            url = "%s/mediaItems?sessionId=%s&pageSize=%d" % (PICKER_BASE, quote(s["id"]), PAGE_SIZE)
            if token:
                url += "&pageToken=" + quote(token)
            status, data = self._api("GET", url)
            if status != 200:
                if self._session_gone(status, data):
                    self.last_error = "session expired - pick again"
                    self.session = None
                    self._save_prefs()
                else:
                    self.last_error = self._api_error("list media items", status, data)
                return None
            for raw in data.get("mediaItems") or []:
                item = normalize_item(raw)
                if item.get("id"):
                    items.append(item)
                if len(items) >= self.max_items:
                    break
            token = data.get("nextPageToken") or ""
            if not token or len(items) >= self.max_items:
                break
        self.items = items
        self._urls_at = _mono_ms()
        self.last_error = ""
        self._save_prefs()
        return items

    def urls_valid(self):
        """True while the cached ``baseUrl``s are still usable."""
        if self._urls_at is None or not self.items:
            return False
        if _elapsed_ms(self._urls_at) >= URL_TTL_S * 1000:
            return False
        for item in self.items:
            if item.get("baseUrl"):
                return True
        return False

    def refresh_urls(self):
        """Re-list to get fresh ``baseUrl``s (keeps the same items)."""
        if self.urls_valid():
            return True
        return self.list_items() is not None

    def item_by_id(self, item_id):
        for item in self.items:
            if item.get("id") == item_id:
                return item
        return None

    # ----- thumbnail cache ---------------------------------------------

    def cache_name(self, item, w, h, crop=False):
        return "%s_%dx%d%s" % (item_hash(item.get("id", "")), int(w), int(h), "c" if crop else "")

    def cached_path(self, item, w, h, crop=False):
        """Existing cache file for this item/size, or ``""``."""
        base = _path_join(self.cache_path, self.cache_name(item, w, h, crop))
        for ext in (".jpg", ".png"):
            if _exists(base + ext):
                return base + ext
        return ""

    def _download(self, url, path, retry=True):
        if not self.ensure_token():
            return 0
        try:
            status, n = http_download(url, path, headers=self.auth_headers(), timeout=self.timeout)
        except Exception as err:
            self.last_error = "download: %s" % err
            _remove(path)
            return 0
        if status == 401 and retry and self.ensure_token(force=True):
            return self._download(url, path, retry=False)
        if status != 200 or not n:
            self.last_error = "download: HTTP %d" % status
            _remove(path)
            return 0
        return n

    def thumbnail_path(self, item, w, h, crop=False):
        """Path of a cached w×h image for ``item`` (downloading it if needed).

        ``crop=True`` asks Google for an exact w×h center crop (list tiles);
        ``crop=False`` fits the photo inside w×h (full-screen view). Returns
        ``""`` on failure (see :attr:`last_error`).
        """
        if not item or not item.get("id"):
            self.last_error = "no item"
            return ""
        path = self.cached_path(item, w, h, crop)
        if path:
            return path
        if not _ensure_dir(self.cache_path):
            self.last_error = "cache dir unavailable: " + self.cache_path
            return ""
        fresh = item
        if not item.get("baseUrl") or not self.urls_valid():
            if not self.refresh_urls():
                return ""
            fresh = self.item_by_id(item["id"]) or item
            if not fresh.get("baseUrl"):
                self.last_error = "item no longer in the picked set"
                return ""
        url = thumb_url(fresh["baseUrl"], w, h, crop)
        base = _path_join(self.cache_path, self.cache_name(item, w, h, crop))
        tmp = base + ".part"
        if not self._download(url, tmp):
            return ""
        head = b""
        try:
            with open(tmp, "rb") as f:
                head = f.read(8)
        except OSError:
            pass
        ext = sniff_ext(head)
        if not ext:
            _remove(tmp)
            self.last_error = "download: not an image"
            return ""
        final = base + ext
        _remove(final)
        try:
            os.rename(tmp, final)
        except OSError:
            self.last_error = "cache write failed"
            _remove(tmp)
            return ""
        self._evict_cache()
        return final

    def _evict_cache(self):
        """Keep at most ``cache_max`` files: drop orphans first, then oldest."""
        if os is None or self.cache_max <= 0:
            return
        try:
            names = [n for n in os.listdir(self.cache_path) if not n.endswith(".part")]
        except OSError:
            return
        if len(names) <= self.cache_max:
            return
        keep = set(item_hash(it.get("id", "")) for it in self.items)
        orphans = [n for n in names if n[:8] not in keep]
        for n in orphans:
            _remove(_path_join(self.cache_path, n))
            names.remove(n)
            if len(names) <= self.cache_max:
                return

        def _mtime(name):
            try:
                return os.stat(_path_join(self.cache_path, name))[8]
            except (OSError, IndexError):
                return 0

        names.sort(key=_mtime)
        while len(names) > self.cache_max:
            _remove(_path_join(self.cache_path, names.pop(0)))

    def clear_cache(self):
        if os is None:
            return
        try:
            names = os.listdir(self.cache_path)
        except OSError:
            return
        for n in names:
            _remove(_path_join(self.cache_path, n))

    # ----- prefs -------------------------------------------------------

    def _load_prefs(self):
        if self.prefs is None:
            data = json_loads(_read_text(self.prefs_file))
            self.prefs = data if isinstance(data, dict) else {}
        return self.prefs

    def _save_prefs(self):
        prefs = self._load_prefs()
        prefs["session"] = dict(self.session) if self.session else None
        prefs["items"] = [
            {
                "id": it.get("id", ""),
                "filename": it.get("filename", ""),
                "createTime": it.get("createTime", ""),
                "type": it.get("type", ""),
                "mime": it.get("mime", ""),
                "width": it.get("width", 0),
                "height": it.get("height", 0),
            }
            for it in self.items
        ]
        if json is None:
            return False
        try:
            body = json.dumps(prefs)
        except Exception:
            return False
        return _write_text(self.prefs_file, body)

    def get_pref(self, key, default=None):
        val = self._load_prefs().get(key)
        return default if val is None else val

    def set_pref(self, key, value):
        self._load_prefs()[key] = value
        return self._save_prefs()

    def restore(self):
        """Load the saved session + picked list; True when items exist."""
        prefs = self._load_prefs()
        session = prefs.get("session")
        self.session = dict(session) if isinstance(session, dict) and session.get("id") else None
        items = []
        for raw in prefs.get("items") or []:
            if isinstance(raw, dict) and raw.get("id"):
                it = dict(raw)
                it["baseUrl"] = ""
                items.append(it)
        self.items = items
        self._urls_at = None
        return bool(items)

    def forget(self, clear_cache=False):
        """Drop session + list (and optionally the cached thumbnails)."""
        self.session = None
        self.items = []
        self._urls_at = None
        self._save_prefs()
        if clear_cache:
            self.clear_cache()

    # ----- labels ------------------------------------------------------

    def count_label(self):
        n = len(self.items)
        if n == 1:
            return "1 photo"
        return "%d photos" % n
