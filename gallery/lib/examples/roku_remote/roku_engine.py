# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
`roku_engine`
====================================================

Roku External Control Protocol (ECP) client — no display, event, or UI imports.

Talks HTTP on port 8060 and discovers devices via SSDP (``ST: roku:ecp``),
with a portable unicast ``:8060`` / ``/query/device-info`` scan fallback when
multicast is blocked (common on WSL NAT and some host firewalls).
Prefs are persisted (``~/.roku_prefs`` on desktop, ``/roku_prefs`` on MCU):
saved TVs, most-recent host/serial, chosen front end, and LVGL chrome knobs
(``ui_shadows`` / ``ui_gradients`` / ``show_progress`` default off;
``playback_poll_s`` default 5). Missing prefs are fine (empty defaults).
Shared by every Roku front end (``roku_graphics``, ``roku_widgets``,
``roku_lvgl``, and the ``roku_remote`` launcher): all UI-agnostic ECP,
discovery, and label/action helpers live here so the display layer is fully
replaceable.

Requires the Roku setting **Control by mobile apps → Enabled**. WiFi must
already be associated on microcontroller targets; unix MicroPython uses the
host network.

Usage::

    from roku_engine import RokuEngine

    eng = RokuEngine()
    devices = eng.discover(timeout=3)
    if devices:
        eng.set_host(devices[0]["host"])
    eng.connect()
    eng.press("Home")
    apps = eng.query_apps()
"""

import sys

try:
    import socket
except ImportError:  # pragma: no cover — e.g. CircuitPython unix without socket
    socket = None

try:
    import time
except ImportError:  # pragma: no cover
    time = None


# Default host: empty → discover / set manually. Edit for a fixed target.
ROKU_HOST = ""
ROKU_PORT = 8060

# When True, front-end modules skip auto ``run()`` on import (``roku_remote``
# owns launch). The example kit imports front ends directly, so leave False.
_LAUNCHER_OWNS_RUN = False

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
SSDP_ST = "roku:ecp"

# Persistent prefs (desktop home vs MCU root). Plain open()/read/write.
_PREFS_HOME_NAME = ".roku_prefs"
_PREFS_MCU_NAME = "/roku_prefs"

# Front-end ids stored in prefs / offered on the MORE switcher.
FRONTEND_IDS = ("lvgl", "widgets", "pygraphics")
FRONTEND_LABELS = {
    "lvgl": "lvgl",
    "widgets": "widgets",
    "graphics": "pygraphics",
}
FRONTEND_BUTTONS = {
    "lvgl": "LVGL",
    "widgets": "WIDGETS",
    "graphics": "GFX",
}
DEFAULT_FRONTEND = "lvgl"

# Documented ECP keypress names (remote + TV extras).
ECP_KEYS = (
    "Home",
    "Rev",
    "Fwd",
    "Play",
    "Select",
    "Left",
    "Right",
    "Down",
    "Up",
    "Back",
    "InstantReplay",
    "Info",
    "Backspace",
    "Search",
    "Enter",
    "FindRemote",
    "VolumeDown",
    "VolumeMute",
    "VolumeUp",
    "PowerOff",
    "PowerOn",
    "ChannelUp",
    "ChannelDown",
    "InputTuner",
    "InputHDMI1",
    "InputHDMI2",
    "InputHDMI3",
    "InputHDMI4",
    "InputAV1",
    "ClosedCaption",
)

ECP_KEY_SET = frozenset(ECP_KEYS)


def _quote_lit(ch):
    """URL-encode one character for Lit_ keypresses (ASCII-safe on MP)."""
    o = ord(ch)
    if ch == " ":
        return "%20"
    if 0x21 <= o <= 0x7E and ch not in "/%?#&=+":
        return ch
    # UTF-8 percent-encode
    try:
        raw = ch.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        raw = bytes([o & 0xFF])
    return "".join("%%%02X" % b for b in raw)


def _xml_tag(text, tag):
    """Return first inner text of <tag>...</tag>, or ''."""
    if not text:
        return ""
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeError:
            text = str(text)
    open_tag = "<" + tag
    i = text.find(open_tag)
    if i < 0:
        # case-insensitive fallback
        lower = text.lower()
        i = lower.find(open_tag.lower())
        if i < 0:
            return ""
    gt = text.find(">", i)
    if gt < 0:
        return ""
    # self-closing
    if text[gt - 1] == "/":
        return ""
    close = "</" + tag + ">"
    j = text.find(close, gt + 1)
    if j < 0:
        close = "</" + tag.lower() + ">"
        j = text.lower().find(close, gt + 1)
        if j < 0:
            return ""
        # recover original slice end using length
        return text[gt + 1 : gt + 1 + (j - (gt + 1))].strip()
    return text[gt + 1 : j].strip()


def _xml_attrs(open_tag_src):
    """Parse key=\"value\" attributes from an opening tag string."""
    attrs = {}
    if not open_tag_src:
        return attrs
    i = 0
    s = open_tag_src
    while i < len(s):
        # find name=
        while i < len(s) and s[i] in " \t\r\n/<>":
            i += 1
        if i >= len(s) or s[i] == ">":
            break
        j = i
        while j < len(s) and s[j] not in "=\t\r\n />":
            j += 1
        name = s[i:j]
        while j < len(s) and s[j] in " \t":
            j += 1
        if j >= len(s) or s[j] != "=":
            i = j
            continue
        j += 1
        while j < len(s) and s[j] in " \t":
            j += 1
        if j >= len(s):
            break
        quote = s[j]
        if quote in "\"'":
            j += 1
            k = s.find(quote, j)
            if k < 0:
                break
            attrs[name] = s[j:k]
            i = k + 1
        else:
            k = j
            while k < len(s) and s[k] not in " \t>/":
                k += 1
            attrs[name] = s[j:k]
            i = k
    return attrs


def _xml_unescape(text):
    """Decode common XML entities (``&amp;`` → ``&``, etc.)."""
    if not text:
        return ""
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&apos;", "'")
    return text


def ascii_label(text):
    """Unescape XML, then replace non-ASCII / control chars with spaces.

    UI-agnostic helper shared by the front ends for safe single-line labels on
    bitmap fonts. Kept in the engine so ``roku_graphics`` / ``roku_widgets`` /
    ``roku_lvgl`` render identical device / app text.
    """
    out = []
    for ch in _xml_unescape(text or ""):
        o = ord(ch)
        out.append(ch if 32 <= o <= 126 else " ")
    return "".join(out)


def pad_slash_breaks(text):
    """Insert `` / `` at bare ``/`` so wrap-friendly UIs can break there.

    Only when *neither* adjacent character is already a space. If either side
    already has a space, that ``/`` is left unchanged.

    Example: ``Movies/Shows`` → ``Movies / Shows``; ``Movies /Shows`` unchanged.
    """
    s = text or ""
    out = []
    n = len(s)
    for i, ch in enumerate(s):
        if ch == "/":
            left_sp = i > 0 and s[i - 1] == " "
            right_sp = i + 1 < n and s[i + 1] == " "
            if not left_sp and not right_sp:
                out.append(" / ")
            else:
                out.append("/")
        else:
            out.append(ch)
    return "".join(out)


def app_label(text):
    """ASCII-safe app name with slash padding for line-break opportunities."""
    return pad_slash_breaks(ascii_label(text))


def format_delete_status(name, fits, tail=""):
    """Build a delete-confirm status line fitted by ``fits(str) -> bool``.

    Full form: ``Delete Name?`` (+ optional ``tail``, e.g. ``\\npress Scan``).
    When truncated: ``Delete Pref...?`` — the ``...`` replaces the space that
    would sit before ``?`` (no space between the ellipsis and ``?``).
    """
    name = ascii_label(name or "").strip() or "?"
    tail = tail or ""
    full = "Delete %s?" % name + tail
    if fits(full):
        return full
    lo = 0
    hi = len(name)
    best = "Delete...?" + tail
    while lo <= hi:
        mid = (lo + hi) // 2
        pref = name[:mid].rstrip()
        cand = "Delete %s...?" % pref + tail
        if fits(cand):
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def format_delete_status_chars(name, max_chars, tail=""):
    """Like :func:`format_delete_status` with a character budget for the whole string."""
    limit = max(8, int(max_chars or 0))

    def fits(s):
        return len(s) <= limit

    return format_delete_status(name, fits, tail=tail)


def _parse_clock_ms(text):
    """Parse ECP clock text like ``6916 ms`` into an int millisecond count."""
    if text is None:
        return None
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return None
    text = text.strip().lower().replace(",", "")
    if not text:
        return None
    # Prefer the first integer/float token (ignore a trailing ``ms`` unit).
    token = text.split()[0] if text.split() else text
    if token.endswith("ms"):
        token = token[:-2]
    try:
        return int(float(token))
    except (TypeError, ValueError):
        return None


def _format_clock_ms(ms):
    """Format milliseconds as ``m:ss`` or ``h:mm:ss`` (empty if unknown)."""
    if ms is None:
        return ""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return ""
    if ms < 0:
        return ""
    sec = ms // 1000
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def _parse_media_player(text):
    """Parse ``/query/media-player`` XML into a small state dict."""
    if not text:
        return {}
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeError:
            text = str(text)
    i = text.find("<player")
    if i < 0:
        return {}
    gt = text.find(">", i)
    if gt < 0:
        return {}
    attrs = _xml_attrs(text[i : gt + 1])
    plugin = {}
    pi = text.find("<plugin", i)
    if pi >= 0:
        pgt = text.find(">", pi)
        if pgt >= 0:
            plugin = _xml_attrs(text[pi : pgt + 1])
    fmt = {}
    fi = text.find("<format", i)
    if fi >= 0:
        fgt = text.find(">", fi)
        if fgt >= 0:
            fmt = _xml_attrs(text[fi : fgt + 1])
    return {
        "state": attrs.get("state", "") or "",
        "error": attrs.get("error", "") or "",
        "app": _xml_unescape(plugin.get("name", "") or ""),
        "app_id": plugin.get("id", "") or "",
        "captions": (fmt.get("captions", "") or "").lower(),
        "video": (fmt.get("video", "") or "").lower(),
        "audio": (fmt.get("audio", "") or "").lower(),
        "drm": (fmt.get("drm", "") or "").lower(),
        "position_ms": _parse_clock_ms(_xml_tag(text, "position")),
        "duration_ms": _parse_clock_ms(_xml_tag(text, "duration")),
    }


def _parse_apps(xml_text):
    """Parse /query/apps XML into list of {id, name, type, version}."""
    if isinstance(xml_text, bytes):
        try:
            xml_text = xml_text.decode("utf-8")
        except UnicodeError:
            xml_text = str(xml_text)
    apps = []
    lower = xml_text.lower()
    pos = 0
    while True:
        i = lower.find("<app", pos)
        if i < 0:
            break
        # Avoid matching the wrapper <apps> tag.
        after = i + 4
        if after < len(lower) and lower[after] not in " \t\r\n/>":
            pos = after
            continue
        gt = xml_text.find(">", i)
        if gt < 0:
            break
        open_src = xml_text[i : gt + 1]
        if open_src.rstrip().endswith("/>"):
            pos = gt + 1
            continue
        close_i = lower.find("</app>", gt)
        if close_i < 0:
            break
        name = _xml_unescape(xml_text[gt + 1 : close_i].strip())
        attrs = _xml_attrs(open_src)
        apps.append(
            {
                "id": attrs.get("id", ""),
                "name": name,
                "type": attrs.get("type", ""),
                "version": attrs.get("version", ""),
            }
        )
        pos = close_i + 6
    return apps


def _parse_ssdp_headers(data):
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            text = data.decode("latin-1")
    else:
        text = data
    headers = {}
    for line in text.split("\r\n"):
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        headers[key.strip().lower()] = val.strip()
    return headers


def _host_from_location(location):
    """Extract host from http://host:8060/ LOCATION header."""
    if not location:
        return ""
    loc = location.strip()
    if "://" in loc:
        loc = loc.split("://", 1)[1]
    loc = loc.split("/", 1)[0]
    if loc.startswith("["):
        # ipv6 [addr]:port
        end = loc.find("]")
        if end > 0:
            return loc[1:end]
    if ":" in loc:
        # host:port — last split for ipv4
        parts = loc.rsplit(":", 1)
        try:
            int(parts[1])
            return parts[0]
        except (ValueError, IndexError):
            return loc
    return loc


def _parse_http_url(url):
    """Split ``http://host[:port]/path`` → (host, port, path)."""
    u = url
    if "://" in u:
        scheme, u = u.split("://", 1)
        if scheme.lower() != "http":
            raise ValueError("only http:// URLs supported")
    hostport, path = (u.split("/", 1) + [""])[:2]
    path = "/" + path
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            raise ValueError("bad IPv6 URL host")
        host = hostport[1:end]
        rest = hostport[end + 1 :]
        port = int(rest[1:]) if rest.startswith(":") else 80
    elif ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
    else:
        host, port = hostport, 80
    return host, port, path


def _http_request_socket(method, url, timeout=5.0, data=b"", read_response=True):
    """Minimal HTTP/1.0 over ``socket`` (no urllib/urequests required).

    ``read_response=False``: send the request and close immediately (no recv
    peek). Roku ECP applies ``/keypress/`` on request; a 120ms peek was adding
    idle stall to every MCU tap on the LVGL pump thread.
    """
    host, port, path = _parse_http_url(url)
    if isinstance(data, str):
        data = data.encode("utf-8")
    elif data is None:
        data = b""
    req = "%s %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n" % (
        method,
        path,
        host if port == 80 else "%s:%d" % (host, port),
    )
    if method != "GET" or data:
        req += "Content-Length: %d\r\n" % len(data)
    req += "\r\n"
    payload = req.encode("utf-8") + data

    addr = _sockaddr(host, port, socket.SOCK_STREAM)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    chunks = []
    try:
        try:
            sock.settimeout(timeout)
        except OSError:
            pass
        sock.connect(addr)
        view = memoryview(payload)
        sent = 0
        while sent < len(payload):
            n = sock.send(view[sent:])
            if n is None or n <= 0:
                break
            sent += n

        if read_response:
            while True:
                try:
                    chunk = sock.recv(2048)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    if not read_response:
        # Optimistic OK once the POST bytes were written.
        return 200, b""

    raw = b"".join(chunks) if chunks else b""
    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        raise RuntimeError("HTTP response missing header separator")
    header_blob = raw[:sep]
    body = raw[sep + 4 :]
    status_line = header_blob.split(b"\r\n", 1)[0]
    parts = status_line.split(b" ", 2)
    try:
        status = int(parts[1]) if len(parts) >= 2 else 0
    except (ValueError, IndexError):
        status = 0
    # Honor Content-Length when present (ignore trailers / keep-alive noise).
    for line in header_blob.split(b"\r\n")[1:]:
        if line.lower().startswith(b"content-length:"):
            try:
                clen = int(line.split(b":", 1)[1].strip())
            except (ValueError, IndexError):
                break
            if clen >= 0:
                body = body[:clen]
            break
    return status, body


def http_request(method, url, timeout=5.0, data=None):
    """
    Portable HTTP GET/POST → (status_code, body_bytes).

    Tries urllib, then urequests/requests, then a minimal socket client
    (needed on Windows MicroPython where ``~`` in ``sys.path`` is not
    expanded and host ``urequests`` is often missing).
    """
    method = method.upper()
    body = data if data is not None else b""
    if isinstance(body, str):
        body = body.encode("utf-8")

    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError

        req = Request(url, data=body if method != "GET" else None, method=method)
        if method != "GET":
            req.add_header("Content-Length", str(len(body)))
        try:
            with urlopen(req, timeout=timeout) as resp:
                return int(getattr(resp, "status", 200) or 200), resp.read()
        except HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:
                pass
            return int(getattr(e, "code", 0) or 0), raw
        except URLError as e:
            raise RuntimeError(str(getattr(e, "reason", e))) from e
    except ImportError:
        pass

    # MicroPython Request may not support method=; fall through
    except TypeError:
        try:
            from urllib.request import Request, urlopen
            from urllib.error import HTTPError, URLError

            req = Request(url, data=body if method != "GET" else None)
            if method != "GET":
                req.get_method = lambda: method  # type: ignore[attr-defined]
            try:
                with urlopen(req, timeout=timeout) as resp:
                    return int(getattr(resp, "status", 200) or 200), resp.read()
            except HTTPError as e:
                raw = b""
                try:
                    raw = e.read()
                except Exception:
                    pass
                return int(getattr(e, "code", 0) or 0), raw
            except URLError as e:
                raise RuntimeError(str(getattr(e, "reason", e))) from e
        except ImportError:
            pass

    for mod_name in ("urequests", "requests"):
        try:
            mod = __import__(mod_name)
        except ImportError:
            continue
        fn = getattr(mod, method.lower(), None)
        if fn is None and method == "GET":
            fn = getattr(mod, "get", None)
        if fn is None and method == "POST":
            fn = getattr(mod, "post", None)
        if fn is None:
            continue
        try:
            if method == "GET":
                resp = fn(url, timeout=timeout)
            else:
                resp = fn(url, data=body, timeout=timeout)
        except TypeError:
            # older urequests without timeout
            if method == "GET":
                resp = fn(url)
            else:
                resp = fn(url, data=body)
        try:
            if hasattr(resp, "content"):
                raw = resp.content
            elif hasattr(resp, "text"):
                text = resp.text
                raw = text.encode("utf-8") if isinstance(text, str) else text
            elif callable(getattr(resp, "read", None)):
                raw = resp.read()
            else:
                raw = bytes(resp) if resp is not None else b""
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            status = getattr(resp, "status_code", getattr(resp, "status", 200))
            return int(status or 200), raw or b""
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()

    try:
        return _http_request_socket(method, url, timeout=timeout, data=body)
    except Exception as e:
        raise RuntimeError("HTTP via socket failed: " + str(e)) from e


def _sockaddr(host, port, socktype=None):
    """Resolve ``(host, port)`` to a stack sockaddr (tuple or buffer).

    MicroPython unix ``connect`` / ``sendto`` often require the sockaddr from
    ``getaddrinfo`` (a ``bytearray``), not a plain ``(host, port)`` tuple.
    """
    if socket is None:
        raise OSError("socket module not available")
    if socktype is None:
        socktype = socket.SOCK_STREAM
    try:
        return socket.getaddrinfo(host, port, socket.AF_INET, socktype)[0][-1]
    except Exception:
        return (host, port)


def _local_ipv4_from_fib_trie():
    """Linux ``/proc/net/fib_trie`` host LOCAL addresses (MicroPython unix)."""
    try:
        f = open("/proc/net/fib_trie")
    except OSError:
        return ""
    try:
        lines = f.read().split("\n")
    finally:
        try:
            f.close()
        except Exception:
            pass
    in_local = False
    candidates = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("Local:"):
            in_local = True
            i += 1
            continue
        if in_local and (line.startswith("Main:") or line.startswith("Id ")):
            break
        if in_local and "|--" in line:
            part = line.split("|--", 1)[-1].strip().split()[0]
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if "/32 host LOCAL" in nxt:
                bits = part.split(".")
                if len(bits) == 4:
                    try:
                        a = int(bits[0])
                        d = int(bits[3])
                    except ValueError:
                        i += 1
                        continue
                    # Skip loopback / network / broadcast; WSL DNS stub.
                    if a != 127 and d not in (0, 255) and part != "10.255.255.254":
                        candidates.append(part)
        i += 1
    for ip in candidates:
        if ip.startswith("192.168.") or ip.startswith("10."):
            return ip
        parts = ip.split(".")
        if len(parts) == 4:
            try:
                a, b = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            if a == 172 and 16 <= b <= 31:
                return ip
    return candidates[0] if candidates else ""


def _prefix_from_default_route():
    """``/24`` of the default gateway from ``/proc/net/route`` (Linux)."""
    try:
        f = open("/proc/net/route")
    except OSError:
        return ""
    try:
        next(f)
        for line in f:
            parts = line.split()
            if len(parts) < 3 or parts[1] != "00000000":
                continue
            try:
                g = int(parts[2], 16)
            except ValueError:
                continue
            return "%d.%d.%d" % (g & 255, (g >> 8) & 255, (g >> 16) & 255)
    except Exception:
        return ""
    finally:
        try:
            f.close()
        except Exception:
            pass
    return ""


def _valid_station_ipv4(ip):
    """True for a usable unicast IPv4 (not empty / 0.0.0.0 / APIPA)."""
    if not ip or ip == "0.0.0.0" or str(ip).startswith("169.254"):
        return False
    parts = str(ip).split(".")
    if len(parts) != 4:
        return False
    try:
        return all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False


def _local_ipv4_from_wlan():
    """MicroPython STA ifconfig — works when UDP getsockname is empty (esp-hosted)."""
    try:
        import network
    except ImportError:
        return ""
    try:
        wlan = network.WLAN(network.STA_IF)
        if not wlan.active() or not wlan.isconnected():
            return ""
        ip = wlan.ifconfig()[0]
        return ip if _valid_station_ipv4(ip) else ""
    except Exception:
        return ""


def _ipv4_from_sockname(name):
    """Extract dotted IPv4 from CPython ``(host, port)`` or MicroPython sockaddr bytes."""
    if isinstance(name, (tuple, list)) and name:
        host = name[0]
        if isinstance(host, str) and _valid_station_ipv4(host):
            return host
        # socket.sockaddr() → (AF_INET, addr_bytes, port)
        if (
            len(name) >= 2
            and isinstance(name[1], (bytes, bytearray))
            and len(name[1]) >= 4
        ):
            b = name[1]
            return "%d.%d.%d.%d" % (b[0], b[1], b[2], b[3])
    if (
        socket is not None
        and isinstance(name, (bytes, bytearray))
        and hasattr(socket, "sockaddr")
    ):
        try:
            return _ipv4_from_sockname(socket.sockaddr(name))
        except (OSError, ValueError, TypeError, IndexError):
            pass
    return ""


def _local_ipv4():
    """Best-effort primary IPv4 (UDP connect + getsockname, WLAN, else Linux proc)."""
    if socket is not None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(_sockaddr("8.8.8.8", 80, socket.SOCK_DGRAM))
                if hasattr(s, "getsockname"):
                    ip = _ipv4_from_sockname(s.getsockname())
                    if _valid_station_ipv4(ip):
                        return ip
            finally:
                s.close()
        except (OSError, AttributeError, ValueError, TypeError, IndexError):
            pass
    ip = _local_ipv4_from_wlan()
    if ip:
        return ip
    return _local_ipv4_from_fib_trie()


def _prefix24(ip):
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return ""
    return "%s.%s.%s" % (parts[0], parts[1], parts[2])


def _windows_lan_prefixes():
    """
    Extra /24 prefixes from the Windows host (WSL NAT is not the LAN).

    Uses powershell.exe when present; empty on MCU / plain Linux.
    """
    try:
        import subprocess
    except ImportError:
        return []
    try:
        out = subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Get-NetIPAddress -AddressFamily IPv4 | "
                "Where-Object { $_.IPAddress -notlike '127.*' "
                "-and $_.InterfaceAlias -notmatch 'WSL|vEthernet|Loopback|Bluetooth' } | "
                "Select-Object -ExpandProperty IPAddress",
            ],
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except Exception:
        return []
    if isinstance(out, bytes):
        try:
            out = out.decode("utf-8", "replace")
        except Exception:
            out = out.decode("latin-1")
    prefixes = []
    for line in out.replace("\r", "\n").split("\n"):
        p = _prefix24(line.strip())
        # Skip APIPA / link-local — not useful for LAN Roku discovery.
        if not p or p.startswith("169.254"):
            continue
        if p not in prefixes:
            prefixes.append(p)
    return prefixes


def _is_wsl_nat_ipv4(ip):
    """True when this looks like Hyper-V WSL NAT (not mirrored LAN)."""
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    # WSL2 NAT is commonly 172.16–31.x; mirrored mode uses the real LAN IP.
    if not (a == 172 and 16 <= b <= 31):
        return False
    try:
        with open("/proc/version") as f:
            ver = f.read().lower()
        return "microsoft" in ver or "wsl" in ver
    except Exception:
        return False


def _scan_prefixes():
    """IPv4 /24 bases to probe for ECP (LAN prefixes preferred over WSL NAT)."""
    prefixes = []
    local_ip = _local_ipv4()
    local = _prefix24(local_ip)
    if local and not local.startswith("169.254"):
        prefixes.append(local)
    route = _prefix_from_default_route()
    if route and route not in prefixes and not route.startswith("169.254"):
        prefixes.append(route)
    # Only shell out to Windows when still on WSL NAT — mirrored LAN already
    # shares the Wi-Fi /24 and powershell during discover blocks the UI.
    if _is_wsl_nat_ipv4(local_ip) or not prefixes:
        for p in _windows_lan_prefixes():
            if p not in prefixes:
                prefixes.insert(0, p)
    return prefixes


def _tcp_open(host, port, timeout=0.25):
    """True if TCP connect to host:port succeeds (MP/CPython portable)."""
    s = None
    try:
        addr = _sockaddr(host, port, socket.SOCK_STREAM)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(addr)
        return True
    except (OSError, TypeError, ValueError, IndexError):
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except OSError:
                pass


def _tcp_open_retry(host, port, timeout=1.0, attempts=2):
    """Retry flaky ECP listeners (some Rokus miss a single short connect)."""
    for _ in range(max(1, int(attempts))):
        if _tcp_open(host, port, timeout):
            return True
    return False


def _nonblock_connect_ok(sock, poll_events=0):
    """True if a non-blocking ``connect`` finished successfully.

    CPython/Winsock expose ``getpeername``; unix MicroPython often does not, so
    fall back to ``SO_ERROR`` or POLLOUT without POLLERR/POLLHUP.
    """
    if sock is None:
        return False
    if hasattr(sock, "getpeername"):
        try:
            sock.getpeername()
            return True
        except OSError:
            return False
    try:
        so_err = getattr(socket, "SO_ERROR", None)
        if so_err is not None:
            return sock.getsockopt(socket.SOL_SOCKET, so_err) == 0
    except (OSError, AttributeError, TypeError):
        pass
    try:
        import select

        err_bits = getattr(select, "POLLERR", 0) | getattr(select, "POLLHUP", 0)
        out_bit = getattr(select, "POLLOUT", 0)
        if poll_events and out_bit and (poll_events & out_bit):
            return not (poll_events & err_bits)
    except ImportError:
        pass
    return False


def _ecp_device(host, port=ROKU_PORT, timeout=1.5):
    """Return discovery dict if host speaks Roku ECP, else None."""
    try:
        status, body = http_request(
            "GET", "http://%s:%d/query/device-info" % (host, port), timeout=timeout
        )
    except Exception:
        return None
    if not status or status >= 400 or not body:
        return None
    if b"device-info" not in body and b"<device-info" not in body:
        return None
    text = body
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeError:
            text = text.decode("latin-1")
    name = (
        _xml_tag(text, "user-device-name")
        or _xml_tag(text, "friendly-device-name")
        or _xml_tag(text, "model-name")
        or host
    )
    serial = (_xml_tag(text, "serial-number") or "").strip()
    return {
        "host": host,
        "name": name,
        "serial": serial,
        "location": "http://%s:%d/" % (host, port),
        "usn": "",
        "st": "scan:ecp",
    }


def _default_scan_workers():
    """Fewer parallel connects on ``network`` STA targets (esp-hosted / MCU)."""
    try:
        import network  # noqa: F401

        return 4
    except ImportError:
        return 24


def unicast_scan_supported():
    """True when a full ``/24`` unicast sweep is safe.

    MicroPython builds that expose ``network`` (ESP STA, esp-hosted, …) stall
    for a long time under a 254-host probe and can wedge the UI. Desktop
    CPython and Windows PE (no ``network``) keep Select **FULL**.
    """
    try:
        import sys

        if getattr(sys.implementation, "name", "") != "micropython":
            return True
    except Exception:
        return True
    try:
        import network  # noqa: F401

        return False
    except ImportError:
        return True


def _probe_hosts_poll(hosts, port, connect_timeout, batch_size=32):
    """Parallel TCP probe via ``select.poll`` (no threads — Windows MP)."""
    import select

    if not hasattr(select, "poll"):
        raise ImportError("select.poll")
    timeout_ms = max(50, int(float(connect_timeout) * 1000))
    batch_size = max(1, int(batch_size))
    open_hosts = []
    poll_mask = select.POLLOUT
    for attr in ("POLLERR", "POLLHUP"):
        poll_mask |= getattr(select, attr, 0)

    for i in range(0, len(hosts), batch_size):
        batch = hosts[i : i + batch_size]
        poller = select.poll()
        socks = {}  # canonical key id(sock) -> (host, sock)
        fd_to_key = {}  # fileno -> id(sock): CPython poll() returns int fds
        for host in batch:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.setblocking(False)
                except (OSError, AttributeError):
                    s.settimeout(0)
                addr = _sockaddr(host, port, socket.SOCK_STREAM)
                try:
                    s.connect(addr)
                    # Immediate success (rare on non-blocking)
                    if _nonblock_connect_ok(s, getattr(select, "POLLOUT", 0)):
                        open_hosts.append(host)
                        s.close()
                        continue
                except OSError:
                    pass
                socks[id(s)] = (host, s)
                try:
                    fd_to_key[s.fileno()] = id(s)
                except (AttributeError, OSError):
                    pass
                poller.register(s, poll_mask)
            except (OSError, TypeError, ValueError, IndexError):
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass

        pending = set(socks)
        # Portable per-batch deadline (ticks on MCU, wall clock on CPython).
        # Prior code only armed a deadline when ``time.ticks_ms`` existed, so on
        # CPython the loop had no timeout and filtered hosts (no RST, no connect)
        # kept ``pending`` non-empty forever, hanging the whole scan.
        deadline = _monotonic_deadline_ms(connect_timeout)
        # Fallback bound for interpreters with no clock at all.
        max_iters = max(1, timeout_ms // 50 + 2)
        iters = 0
        while pending:
            if deadline is not None:
                if _monotonic_expired(deadline):
                    break
            elif iters >= max_iters:
                break
            iters += 1
            try:
                ready = poller.poll(50)
            except OSError:
                break
            for item in ready:
                obj = item[0]
                ev = item[1] if len(item) > 1 else 0
                # CPython poll() yields int fds; MicroPython yields the socket.
                if isinstance(obj, int):
                    key = fd_to_key.get(obj)
                else:
                    key = id(obj)
                if key is None or key not in socks:
                    continue
                host, s = socks[key]
                if _nonblock_connect_ok(s, ev):
                    open_hosts.append(host)
                try:
                    poller.unregister(s)
                except (OSError, KeyError, ValueError):
                    pass
                try:
                    s.close()
                except OSError:
                    pass
                pending.discard(key)
                del socks[key]

        for key in list(pending):
            host, s = socks[key]
            try:
                poller.unregister(s)
            except (OSError, KeyError, ValueError):
                pass
            try:
                s.close()
            except OSError:
                pass
    return open_hosts


def _probe_hosts_parallel(hosts, port, connect_timeout, workers=None):
    """Return hosts with open TCP ``port``.

    Prefers ``select.poll`` (works without ``_thread`` — Windows MicroPython),
    then CPython futures / MP ``_thread``, then sequential connects.
    """
    if workers is None:
        workers = _default_scan_workers()
    n_workers = max(1, int(workers))

    # Non-threaded parallel path first — Windows MP has no ``_thread``.
    try:
        return _probe_hosts_poll(
            hosts, port, connect_timeout, batch_size=max(8, n_workers)
        )
    except (ImportError, AttributeError, OSError):
        pass

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        open_hosts = []
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = {
                pool.submit(_tcp_open, host, port, connect_timeout): host
                for host in hosts
            }
            for fut in as_completed(futs):
                host = futs[fut]
                try:
                    ok = fut.result()
                except Exception:
                    ok = False
                if ok:
                    open_hosts.append(host)
        return open_hosts
    except ImportError:
        pass

    try:
        import _thread
    except ImportError:
        return [h for h in hosts if _tcp_open(h, port, connect_timeout)]

    # MicroPython: no concurrent.futures — small _thread pool.
    # Chunk large /24 lists; a single 254-host wait can hang on esp-hosted.
    chunk = 32
    if len(hosts) > chunk:
        open_all = []
        for i in range(0, len(hosts), chunk):
            open_all.extend(
                _probe_hosts_parallel(
                    hosts[i : i + chunk], port, connect_timeout, n_workers
                )
            )
        return open_all

    queue = list(hosts)
    qi = [0]
    qlock = _thread.allocate_lock()
    rlock = _thread.allocate_lock()
    open_hosts = []
    remaining = [len(queue)]

    def _worker():
        while True:
            with qlock:
                if qi[0] >= len(queue):
                    return
                host = queue[qi[0]]
                qi[0] += 1
            try:
                ok = _tcp_open(host, port, connect_timeout)
            except Exception:
                ok = False
            with rlock:
                if ok:
                    open_hosts.append(host)
                remaining[0] -= 1

    started = 0
    for _ in range(min(n_workers, max(1, len(queue)))):
        try:
            _thread.start_new_thread(_worker, ())
            started += 1
        except Exception:
            break
    if started == 0:
        return [h for h in hosts if _tcp_open(h, port, connect_timeout)]
    # Bound wait so a stuck connect cannot freeze discovery forever.
    deadline = None
    if time is not None and hasattr(time, "ticks_ms"):
        per = max(50, int(float(connect_timeout) * 1000))
        slack = ((len(queue) + started - 1) // started) * per + 5000
        deadline = time.ticks_add(time.ticks_ms(), slack)
    while remaining[0] > 0:
        if deadline is not None and time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            break
        if time is not None:
            try:
                time.sleep(0.05)
            except Exception:
                pass
    return open_hosts


def _env_get(name):
    """Portable getenv (CPython / MicroPython / CircuitPython)."""
    try:
        import os
    except ImportError:
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
        import os

        expanduser = getattr(getattr(os, "path", None), "expanduser", None)
        if expanduser is not None:
            home = expanduser("~")
            if home and home != "~":
                return home
    except Exception:
        pass
    return ""


def _prefs_path():
    """Desktop: ``~/.roku_prefs``. MCU: ``/roku_prefs``."""
    home = _user_home_dir()
    if home and home not in (".", "/"):
        return _path_join(home, _PREFS_HOME_NAME)
    return _PREFS_MCU_NAME


def _read_text_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""


def _write_text_file(path, text):
    try:
        with open(path, "w") as f:
            f.write(text)
        return True
    except OSError:
        return False


def _normalize_known_device(item):
    """Return ``{host, name, serial}`` or ``None`` if host is empty."""
    if not item:
        return None
    host = (item.get("host") or "").strip()
    if not host:
        return None
    return {
        "host": host,
        "name": (item.get("name") or "").strip(),
        "serial": (item.get("serial") or "").strip(),
    }


def _default_prefs():
    return {
        "frontend": DEFAULT_FRONTEND,
        "last_host": "",
        "last_serial": "",
        "devices": [],
        # LVGL chrome / load (MCU-friendly defaults).
        "ui_shadows": False,
        "ui_gradients": False,
        "show_progress": False,
        "playback_poll_s": 5,
    }


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off", ""):
        return False
    return default


def _normalize_prefs(data):
    """Coerce *data* into a prefs dict (missing fields → defaults)."""
    out = _default_prefs()
    if not isinstance(data, dict):
        return out
    fe = (data.get("frontend") or "").strip()
    if fe in FRONTEND_IDS:
        out["frontend"] = fe
    out["last_host"] = (data.get("last_host") or "").strip()
    out["last_serial"] = (data.get("last_serial") or "").strip()
    out["ui_shadows"] = _as_bool(data.get("ui_shadows"), False)
    out["ui_gradients"] = _as_bool(data.get("ui_gradients"), False)
    out["show_progress"] = _as_bool(data.get("show_progress"), False)
    try:
        poll = int(data.get("playback_poll_s", out["playback_poll_s"]))
    except (TypeError, ValueError):
        poll = out["playback_poll_s"]
    if poll < 1:
        poll = 1
    if poll > 60:
        poll = 60
    out["playback_poll_s"] = poll
    devices = data.get("devices")
    if isinstance(devices, list):
        clean = []
        seen = {}
        for item in devices:
            if isinstance(item, dict):
                row = _normalize_known_device(item)
            else:
                row = _normalize_known_device({"host": str(item)})
            if row and row["host"] not in seen:
                seen[row["host"]] = True
                clean.append(row)
        out["devices"] = clean
    return out


def _devices_from_list(data):
    """Normalize a JSON list of device dicts / host strings."""
    out = []
    seen = {}
    for item in data or []:
        if isinstance(item, dict):
            row = _normalize_known_device(item)
        else:
            row = _normalize_known_device({"host": str(item)})
        if row and row["host"] not in seen:
            seen[row["host"]] = True
            out.append(row)
    return out


def _load_prefs():
    """Load prefs; missing or unreadable file → empty defaults."""
    path = _prefs_path()
    text = _read_text_file(path)
    if text and text.strip():
        try:
            import json

            data = json.loads(text)
            if isinstance(data, dict):
                return _normalize_prefs(data)
            if isinstance(data, list):
                prefs = _default_prefs()
                prefs["devices"] = _devices_from_list(data)
                return prefs
        except Exception:
            pass
    return _default_prefs()


def _write_prefs(prefs):
    """Overwrite the prefs file. Returns True on success."""
    clean = _normalize_prefs(prefs)
    clean["devices"] = sorted(
        clean["devices"],
        key=lambda r: (r.get("name") or r.get("host") or "").lower(),
    )
    path = _prefs_path()
    try:
        import json

        body = json.dumps(clean)
    except Exception:
        # Minimal fallback without json: devices only (lose frontend/MRU).
        lines = []
        for row in clean["devices"]:
            if row.get("name"):
                lines.append("%s\t%s" % (row["host"], row["name"]))
            else:
                lines.append(row["host"])
        body = "\n".join(lines)
        if body:
            body += "\n"
    return _write_text_file(path, body)


def _load_known_hosts():
    """Return list of ``{host, name, serial}`` from prefs (Select cache)."""
    return list(_load_prefs().get("devices") or [])


def _write_known_hosts(rows):
    """Replace the prefs device list with *rows* (already normalized)."""
    prefs = _load_prefs()
    clean = []
    seen = {}
    for item in rows or []:
        row = _normalize_known_device(item)
        if not row or row["host"] in seen:
            continue
        seen[row["host"]] = True
        clean.append(row)
    prefs["devices"] = clean
    # Drop MRU if that TV was removed from the list.
    last = (prefs.get("last_host") or "").strip()
    if last and last not in seen:
        prefs["last_host"] = ""
        prefs["last_serial"] = ""
    return _write_prefs(prefs)


def _save_known_hosts(devices):
    """Merge *devices* into prefs (additive).

    - Never removes a cached TV unless the caller rewrites via
      :func:`_remove_known_host`.
    - When a device reports ``serial``, a prior entry with the same serial but a
      different IP is replaced (DHCP move) so the list does not grow duplicates.
    """
    by_host = {}
    by_serial = {}
    for item in _load_known_hosts():
        row = _normalize_known_device(item)
        if not row:
            continue
        by_host[row["host"]] = row
        if row["serial"]:
            by_serial[row["serial"]] = row

    for item in devices or []:
        row = _normalize_known_device(item)
        if not row:
            continue
        serial = row["serial"]
        host = row["host"]
        if serial:
            prev = by_serial.get(serial)
            if prev and prev.get("host") and prev["host"] != host:
                by_host.pop(prev["host"], None)
        else:
            prev_host = by_host.get(host)
            if prev_host and prev_host.get("serial") and not serial:
                row["serial"] = prev_host["serial"]
                serial = row["serial"]
        prev = by_host.get(host) or {}
        if not row["name"]:
            row["name"] = prev.get("name") or ""
        if not row["serial"]:
            row["serial"] = prev.get("serial") or ""
        by_host[host] = row
        if row["serial"]:
            by_serial[row["serial"]] = row

    return _write_known_hosts(list(by_host.values()))


def _remove_known_host(host):
    """Drop one cached host (user-initiated). Returns True if something changed."""
    host = (host or "").strip()
    if not host:
        return False
    rows = _load_known_hosts()
    kept = [r for r in rows if (r.get("host") or "") != host]
    if len(kept) == len(rows):
        return False
    return _write_known_hosts(kept)


def other_frontends(current=None):
    """Return front-end ids other than *current* (default: prefs frontend)."""
    cur = (current or get_frontend() or DEFAULT_FRONTEND).strip()
    return [f for f in FRONTEND_IDS if f != cur]


def get_frontend():
    """Chosen front end id from prefs (default ``lvgl``)."""
    fe = (_load_prefs().get("frontend") or "").strip()
    return fe if fe in FRONTEND_IDS else DEFAULT_FRONTEND


def set_frontend(name):
    """Persist front-end choice. Returns True on success."""
    name = (name or "").strip()
    if name not in FRONTEND_IDS:
        return False
    prefs = _load_prefs()
    prefs["frontend"] = name
    return _write_prefs(prefs)


def get_ui_pref(key, default=None):
    """Return one UI pref (``ui_shadows``, ``ui_gradients``, …)."""
    prefs = _load_prefs()
    if key in prefs:
        return prefs[key]
    return default


def set_ui_pref(key, value):
    """Persist one UI pref. Returns True on success."""
    if key not in (
        "ui_shadows",
        "ui_gradients",
        "show_progress",
        "playback_poll_s",
    ):
        return False
    prefs = _load_prefs()
    if key == "playback_poll_s":
        try:
            poll = int(value)
        except (TypeError, ValueError):
            return False
        if poll < 1:
            poll = 1
        if poll > 60:
            poll = 60
        prefs[key] = poll
    else:
        prefs[key] = _as_bool(value, False)
    return _write_prefs(prefs)


def _restart_is_browser():
    """True on PyScript / Jupyter / WASM where process restart is unavailable."""
    if getattr(sys, "platform", "") in ("emscripten", "webassembly"):
        return True
    try:
        import pyscript  # noqa: F401

        return True
    except ImportError:
        pass
    try:
        get_ipython()  # noqa: F821
        return True
    except NameError:
        return False


def _restart_is_jupyter():
    try:
        get_ipython()  # noqa: F821
        return True
    except NameError:
        return False


# Distinct from SDL window-close (usually 0) so a host shell can relaunch.
# Supported desktop relaunch path — from ``pydevices-examples/lib``:
#   while true; do micropython -m examples.roku_remote; [ $? -eq 42 ] || break; done
# PowerShell:
#   while ($true) { micropython -m examples.roku_remote; if ($LASTEXITCODE -ne 42) { break } }
# (bash ``while cmd; do`` is wrong — exit 42 fails the while-condition.)
RESTART_EXIT_CODE = 42


def restart_app():
    """Restart after a front-end prefs change.

    * PyScript / Jupyter / WASM: return a short status (``reload page`` /
      ``restart kernel``); caller shows it — no process exit.
    * MCU: ``machine.reset()`` / ``microcontroller.reset()`` (does not return).
    * Desktop: ``app.request_quit(42)`` so SDL teardown runs, then the
      process exits 42 from ``App.run``. Relaunch with a host shell loop
      (see ``RESTART_EXIT_CODE``); there is no in-process ``execv`` path.
    """
    if _restart_is_browser():
        if _restart_is_jupyter():
            return "restart kernel"
        return "reload page"

    try:
        import machine

        machine.reset()
    except (ImportError, AttributeError):
        pass
    try:
        import microcontroller

        microcontroller.reset()
    except (ImportError, AttributeError):
        pass

    # Clean app shutdown (same path as window close), then exit 42.
    try:
        module = sys.modules.get("display_driver")
        if module is not None:
            app = module.app
        else:
            import appdev

            app = appdev.App.current()
        app.request_quit(RESTART_EXIT_CODE)
        return None
    except Exception:
        pass

    try:
        sys.exit(RESTART_EXIT_CODE)
    except SystemExit:
        raise
    except Exception:
        pass
    raise SystemExit(RESTART_EXIT_CODE)


def format_switch_status(frontend, fits=None, tail="\nREMOTE or tap again"):
    """Status text for MORE front-end switch confirm (same shape as delete).

    Default tail: confirm with REMOTE, or tap the same front-end button again
    to cancel.
    """
    label = FRONTEND_LABELS.get(frontend, frontend or "?")
    line = "Switch to %s?" % label
    text = line + (tail or "")
    if fits is None or fits(text):
        return text
    # Names are short; if the band is tiny, drop the tail first.
    if fits(line):
        return line
    return "Switch?"


def _set_last_device(host, serial):
    prefs = _load_prefs()
    prefs["last_host"] = (host or "").strip()
    prefs["last_serial"] = (serial or "").strip()
    return _write_prefs(prefs)


def _reprobe_known_hosts(missing_hosts, on_device=None, timeout=1.5, cancel_check=None):
    """ECP-probe *missing_hosts*; return newly confirmed device dicts."""
    found = []
    for host in missing_hosts or []:
        try:
            if cancel_check and cancel_check():
                break
        except Exception:
            pass
        host = (host or "").strip()
        if not host:
            continue
        if not _tcp_open_retry(host, ROKU_PORT, max(float(timeout), 1.0), 2):
            continue
        info = _ecp_device(host, timeout=timeout)
        if not info:
            continue
        found.append(info)
        if on_device is not None:
            try:
                on_device(info)
            except Exception:
                pass
    return found


def discover_rokus_scan(
    prefixes=None,
    port=ROKU_PORT,
    connect_timeout=1.0,
    priority_hosts=None,
    workers=None,
    on_device=None,
    find_all=False,
    cancel_check=None,
):
    """
    Unicast scan: TCP :8060 then GET /query/device-info.

    Portable fallback when SSDP multicast is blocked (WSL NAT, host firewall).
    No third-party dependency. Parallel via ``select.poll`` (no threads),
    ``concurrent.futures`` (CPython), or ``_thread``; sequential only if none.

    ``connect_timeout`` defaults to 1.0s. Keep ``workers`` modest — 64-way
    floods drop some Rokus that answer fine alone (seen with a 65" TCL).
    On MicroPython ``network`` targets the default is 4 workers.
    ``priority_hosts`` are probed first with a longer retry (rescans).
    ``on_device(info)`` is called as each ECP device is confirmed (progressive UI).
    ``find_all`` continues after the first hit (device picker / full LAN search).
    Default False is only for rare one-shot probes; ``RokuEngine.discover``
    always passes True. ``connect()`` does not auto-discover.
    Asleep sets typically close ECP and will not appear.
    ``cancel_check`` is an optional zero-arg callable; when it returns true the
    sweep stops between host chunks (Select Cancel).
    """
    if workers is None:
        workers = _default_scan_workers()
    if prefixes is None:
        prefixes = _scan_prefixes()
    priority_hosts = tuple(priority_hosts or ())
    if not prefixes and not priority_hosts:
        return []

    def _cancelled():
        try:
            return bool(cancel_check and cancel_check())
        except Exception:
            return False

    hosts = []
    for prefix in prefixes:
        for i in range(1, 255):
            hosts.append("%s.%d" % (prefix, i))

    found = []
    found_hosts = {}

    def _accept(host):
        if host in found_hosts:
            return None
        info = _ecp_device(host, port=port)
        if not info:
            return None
        found_hosts[host] = True
        found.append(info)
        if on_device is not None:
            try:
                on_device(info)
            except Exception:
                pass
        return info

    seen = {}
    # Prefer previously-found IPs — full-subnet floods can miss flaky listeners.
    for host in priority_hosts:
        if _cancelled():
            return found
        host = (host or "").strip()
        if not host or host in seen:
            continue
        seen[host] = True
        if _tcp_open_retry(host, port, max(connect_timeout, 1.5), 3):
            _accept(host)

    if found and not find_all:
        return found

    rest = [h for h in hosts if h not in seen]
    # Probe in worker-sized chunks. When not find_all, stop after the first
    # confirmed Roku (legacy one-shot). Engine.discover always uses find_all.
    step = max(8, int(workers))
    for i in range(0, len(rest), step):
        if _cancelled():
            break
        chunk = rest[i : i + step]
        for host in _probe_hosts_parallel(chunk, port, connect_timeout, workers):
            if _cancelled():
                break
            _accept(host)
        if found and not find_all:
            break

    return found


def _ssdp_set_multicast_if(sock, local_ip):
    """Pin SSDP multicast to *local_ip* (needed on multi-homed Windows/WSL hosts)."""
    if not local_ip:
        return False
    try:
        packed = socket.inet_aton(local_ip)
    except (OSError, AttributeError, ValueError, TypeError):
        return False
    # IPPROTO_IP=0; IP_MULTICAST_IF=9 on Winsock (and often on POSIX).
    candidates = []
    ipproto = getattr(socket, "IPPROTO_IP", None)
    mcast_if = getattr(socket, "IP_MULTICAST_IF", None)
    if ipproto is not None and mcast_if is not None:
        candidates.append((ipproto, mcast_if))
    candidates.append((0, 9))
    for level, opt in candidates:
        try:
            sock.setsockopt(level, opt, packed)
            return True
        except (OSError, AttributeError, TypeError):
            continue
    return False


def _monotonic_deadline_ms(seconds):
    """End tick for a relative wait (avoids SNTP steps breaking ``time.time()``)."""
    if time is None:
        return None
    ms = max(1, int(float(seconds) * 1000))
    if hasattr(time, "ticks_ms") and hasattr(time, "ticks_add"):
        return time.ticks_add(time.ticks_ms(), ms)
    # CPython: no ticks_ms — wall clock is normally fine there.
    return ("wall", time.time() + float(seconds))


def _monotonic_expired(deadline):
    if deadline is None:
        return False
    if isinstance(deadline, tuple) and deadline and deadline[0] == "wall":
        return time.time() >= deadline[1]
    if time is not None and hasattr(time, "ticks_diff"):
        return time.ticks_diff(deadline, time.ticks_ms()) <= 0
    return False


def discover_rokus(
    timeout=3.0, retries=2, scan_fallback=True, ssdp=True, cancel_check=None
):
    """
    Discover Roku ECP devices.

    Returns a list of dicts: ``{host, location, usn, st[, name]}``.

    SSDP M-SEARCH when ``ssdp`` is true. If that finds nothing (or ``ssdp`` is
    false) and ``scan_fallback`` is true, unicast-scans /24 subnets for ECP on
    port 8060. SSDP wait uses a monotonic tick deadline — wall ``time.time()``
    is unsafe on MCU targets where SNTP steps the clock during discovery.
    Prefer ``ssdp=False`` from UI threads that share multimer soft timers if
    blocking ``recvfrom`` + timer re-entry deadlocks under librt.
    ``cancel_check`` stops the SSDP listen / unicast fallback early when true.
    """
    devices = []

    def _cancelled():
        try:
            return bool(cancel_check and cancel_check())
        except Exception:
            return False

    if ssdp:
        message = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: %s:%d\r\n"
            'MAN: "ssdp:discover"\r\n'
            "ST: %s\r\n"
            "MX: 2\r\n"
            "\r\n"
        ) % (SSDP_ADDR, SSDP_PORT, SSDP_ST)

        found = {}
        deadline = _monotonic_deadline_ms(timeout)
        # After the first reply, keep listening long enough for siblings on the
        # LAN (0.6s was cutting multi-TV homes short once multicast works).
        grace_deadline = [None]
        grace_secs = 2.0
        local_ip = _local_ipv4()

        for _ in range(max(1, int(retries))):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                except (OSError, AttributeError):
                    pass
                # Multicast TTL: Linux IP_MULTICAST_TTL=33; Winsock=10 (IPPROTO_IP=0).
                for ttl_opt in (
                    getattr(socket, "IP_MULTICAST_TTL", None),
                    33,
                    10,
                ):
                    if ttl_opt is None:
                        continue
                    try:
                        sock.setsockopt(0, ttl_opt, 2)
                        break
                    except (OSError, AttributeError):
                        pass
                # Multi-homed Windows (LAN + WSL/VPN/APIPA): without this, M-SEARCH
                # often leaves the wrong NIC and zero Rokus reply.
                mcast_if_ok = _ssdp_set_multicast_if(sock, local_ip)
                try:
                    # Winsock often needs an explicit bind before multicast replies arrive.
                    sock.bind(_sockaddr("0.0.0.0", 0, socket.SOCK_DGRAM))
                except (OSError, AttributeError, TypeError):
                    pass
                try:
                    sock.settimeout(0.4)
                except OSError:
                    pass

                payload = message.encode("utf-8") if isinstance(message, str) else message
                try:
                    sock.sendto(
                        payload, _sockaddr(SSDP_ADDR, SSDP_PORT, socket.SOCK_DGRAM)
                    )
                except (OSError, TypeError) as e:
                    sock.close()
                    raise RuntimeError("SSDP send failed: " + str(e)) from e

                while True:
                    if _cancelled():
                        break
                    if _monotonic_expired(deadline):
                        break
                    if grace_deadline[0] is not None and _monotonic_expired(
                        grace_deadline[0]
                    ):
                        break
                    try:
                        data, _addr = sock.recvfrom(2048)
                    except OSError:
                        if deadline is None:
                            break
                        if _monotonic_expired(deadline):
                            break
                        continue
                    headers = _parse_ssdp_headers(data)
                    st = headers.get("st", "")
                    location = headers.get("location", "")
                    if "roku" not in st.lower() and "roku" not in location.lower():
                        # still accept LOCATION pointing at :8060
                        if ":8060" not in location:
                            continue
                    host = _host_from_location(location)
                    if not host:
                        continue
                    is_new = host not in found
                    found[host] = {
                        "host": host,
                        "location": location,
                        "usn": headers.get("usn", ""),
                        "st": st or SSDP_ST,
                    }
                    if grace_deadline[0] is None:
                        grace_deadline[0] = _monotonic_deadline_ms(grace_secs)
                    if deadline is None:
                        # single-response mode when no time module
                        break
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
            if (
                found
                and grace_deadline[0] is not None
                and _monotonic_expired(grace_deadline[0])
            ):
                break

        devices = list(found.values())
    if _cancelled():
        return devices
    if devices or not scan_fallback:
        return devices
    if not unicast_scan_supported():
        return devices
    return discover_rokus_scan(find_all=True, cancel_check=cancel_check)


class RokuEngine:
    """Stateful ECP client for one Roku target."""

    def __init__(self, host=None, port=ROKU_PORT, timeout=5.0):
        self.host = host if host is not None else ROKU_HOST
        self.port = int(port)
        self.timeout = float(timeout)
        self.last_error = ""
        self.connected = False
        self.device_info = {}
        self.apps = []
        self.active_app = {}
        self.active_screensaver = ""
        self.media_player = ""
        self.media_state = {}
        # Hide plaque clock when ECP reuses the same position (many apps stall it).
        self._last_position_ms = None
        self._position_changed_at = 0.0
        self.discovered = []
        self._discover_cancel = False
        # Optional inject for tests: callable(method, url, timeout, data) -> (status, body)
        self._http = None
        # Keep-alive TCP for MCU ``press(..., wait=False)`` — avoids a fresh
        # connect (50–450ms) on every D-pad tap on the LVGL pump thread.
        self._ecp_sock = None
        self._ecp_sock_host = ""
        # After a no-drain send, consume the HTTP response before the next reuse.
        self._ecp_need_drain = False
        self._ecp_last_reuse = False
        self._ecp_last_conn_close = False

    def cancel_discover(self):
        """Ask an in-flight :meth:`discover` to stop at the next checkpoint."""
        self._discover_cancel = True

    def _ecp_sock_close(self):
        sock = getattr(self, "_ecp_sock", None)
        self._ecp_sock = None
        self._ecp_sock_host = ""
        self._ecp_need_drain = False
        if sock is None:
            return
        try:
            sock.close()
        except OSError:
            pass

    def _ecp_sock_drain(self, sock):
        """Consume one HTTP response so the keep-alive socket stays usable.

        A non-blocking peek left unread bytes / half-closed sockets; the next
        ``send`` then failed and forced a fresh TCP connect (H4 logs: reuse
        alternating False/True every tap).
        """
        self._ecp_last_conn_close = False
        buf = b""
        try:
            sock.settimeout(0.04)
        except OSError:
            pass
        try:
            # Headers
            while b"\r\n\r\n" not in buf and len(buf) < 1536:
                try:
                    chunk = sock.recv(256)
                except OSError:
                    break
                if not chunk:
                    # Peer closed — drop socket so the next ensure reconnects.
                    self._ecp_sock_close()
                    return
                buf += chunk
            sep = buf.find(b"\r\n\r\n")
            if sep < 0:
                return
            header = buf[:sep]
            body = buf[sep + 4 :]
            hdr_l = header.lower()
            if b"connection: close" in hdr_l:
                self._ecp_last_conn_close = True
            clen = 0
            for line in header.split(b"\r\n")[1:]:
                if line.lower().startswith(b"content-length:"):
                    try:
                        clen = int(line.split(b":", 1)[1].strip())
                    except (ValueError, IndexError):
                        clen = 0
                    break
            # Body (usually empty for /keypress/)
            while clen > 0 and len(body) < clen and len(body) < 2048:
                try:
                    chunk = sock.recv(256)
                except OSError:
                    break
                if not chunk:
                    self._ecp_sock_close()
                    return
                body += chunk
            if self._ecp_last_conn_close:
                self._ecp_sock_close()
        finally:
            try:
                if getattr(self, "_ecp_sock", None) is not None:
                    sock.settimeout(0.25)
            except OSError:
                pass

    def _ecp_sock_ensure(self, timeout):
        host = (self.host or "").strip()
        if not host:
            raise OSError("no host")
        sock = getattr(self, "_ecp_sock", None)
        if sock is not None and self._ecp_sock_host == host:
            self._ecp_last_reuse = True
            # Prior fire-and-forget POST left a response on the wire — clear it
            # before the next send so keep-alive stays valid. Prefer draining on
            # the idle pump (see ``ecp_idle_drain``) so tap→send stays ~10ms.
            if getattr(self, "_ecp_need_drain", False):
                self._ecp_sock_drain(sock)
                self._ecp_need_drain = False
                sock = getattr(self, "_ecp_sock", None)
                if sock is None:
                    # Peer closed during drain — fall through to reconnect.
                    pass
                else:
                    return sock
            else:
                return sock
        self._ecp_last_reuse = False
        self._ecp_sock_close()
        addr = _sockaddr(host, int(self.port), socket.SOCK_STREAM)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
        except OSError:
            pass
        sock.connect(addr)
        self._ecp_sock = sock
        self._ecp_sock_host = host
        return sock

    def ecp_idle_drain(self):
        """Consume a pending keep-alive response when no tap is in flight.

        Call from the UI soft-pump so the next tap's ``press(wait=False)`` is
        usually a pure send (~10ms) instead of drain+send (~60–100ms).
        """
        if not getattr(self, "_ecp_need_drain", False):
            return False
        sock = getattr(self, "_ecp_sock", None)
        if sock is None:
            self._ecp_need_drain = False
            return False
        self._ecp_sock_drain(sock)
        self._ecp_need_drain = False
        return True

    def _press_keepalive(self, key, timeout, drain=True):
        """POST ``/keypress/`` on a reused TCP socket (MCU tap hot path).

        ``drain=False``: send only (Roku acts on the request). Response is
        consumed on the next ensure/reuse so tap→wire stays a few ms.
        """
        path = "/keypress/" + key
        host = (self.host or "").strip()
        host_hdr = host if int(self.port) == 80 else "%s:%d" % (host, int(self.port))
        payload = (
            "POST %s HTTP/1.1\r\nHost: %s\r\nContent-Length: 0\r\n"
            "Connection: keep-alive\r\n\r\n" % (path, host_hdr)
        ).encode()

        def _send(sock):
            view = memoryview(payload)
            sent = 0
            while sent < len(payload):
                n = sock.send(view[sent:])
                if n is None or n <= 0:
                    raise OSError("short send")
                sent += n
            if drain:
                self._ecp_sock_drain(sock)
                self._ecp_need_drain = False
            else:
                self._ecp_need_drain = True

        try:
            _send(self._ecp_sock_ensure(timeout))
        except Exception:
            self._ecp_sock_close()
            try:
                _send(self._ecp_sock_ensure(timeout))
            except Exception as e:
                self._ecp_sock_close()
                self.last_error = str(e)
                return False
        self.connected = True
        self.last_error = ""
        return True

    def set_host(self, host, port=None):
        self.host = (host or "").strip()
        if port is not None:
            self.port = int(port)
        self.connected = False
        self.last_error = ""
        self._ecp_sock_close()
        # Host-specific caches must not survive a TV switch.
        self.apps = []
        self.active_app = {}
        self.active_screensaver = ""
        self.device_info = {}
        self.media_player = ""
        self.media_state = {}
        self._last_position_ms = None
        self._position_changed_at = 0.0

    @property
    def base_url(self):
        return "http://%s:%d" % (self.host, self.port)

    def power_is_on(self):
        """True when ``power-mode`` from device-info is ``PowerOn``."""
        mode = (self.device_info or {}).get("power-mode") or ""
        return mode == "PowerOn"

    @staticmethod
    def _is_tv_input(app):
        """True for TV inputs: ``type=tvin`` and/or ``id`` like ``tvinput.hdmi1``."""
        if not app:
            return False
        t = (app.get("type") or "").strip().lower()
        aid = (app.get("id") or "").strip().lower()
        return t == "tvin" or aid.startswith("tvinput.")

    def inputs(self):
        """TV tuner / HDMI / AV entries from the last apps query."""
        out = []
        seen = {}
        for app in self.apps or []:
            if not self._is_tv_input(app):
                continue
            hid = app.get("id") or ""
            if hid in seen:
                continue
            seen[hid] = True
            out.append(app)
        return out

    def store_apps(self):
        """Installed channels for the APPS UI (excludes TV inputs)."""
        out = []
        seen = {}
        for app in self.apps or []:
            if self._is_tv_input(app):
                continue
            hid = app.get("id") or ""
            if hid in seen:
                continue
            seen[hid] = True
            out.append(app)
        return out

    def media_active(self):
        """True when media-player reports play / pause / buffer."""
        state = ((self.media_state or {}).get("state") or "").lower()
        return state in ("play", "pause", "buffer")

    def captions_track_hint(self):
        """True when format reports a captions value other than ``none``/empty."""
        cap = ((self.media_state or {}).get("captions") or "").lower()
        return bool(cap) and cap not in ("none", "off", "false")

    def playback_app_label(self):
        """App / connection feedback for the plaque (no play/pause word)."""
        if self.last_error and not self.connected:
            return "err: " + self.last_error
        if not self.host:
            return "no host"
        if not self.connected:
            return "offline"
        ms = self.media_state or {}
        app = (
            (self.active_app or {}).get("name")
            or ms.get("app")
            or ""
        )
        saver = (self.active_screensaver or "").strip()
        if saver:
            app_l = app.lower()
            if not app or app_l in ("roku", "home"):
                return "screensaver"
            return app
        if app:
            return app
        # Only trust power-mode when we have device-info and nothing is playing.
        # Empty device_info (never queried) must not mask a live media-player.
        if self.device_info and not self.power_is_on():
            return "OFF"
        name = self.device_info.get("user-device-name") or self.device_info.get(
            "model-name", ""
        )
        return name or "ready"

    def playback_state_label(self):
        """Player ``state`` attribute from media-player (unfiltered; may be empty)."""
        return ((self.media_state or {}).get("state") or "").strip()

    def playback_status(self):
        """Combined app + state (single-line UIs / back-compat)."""
        app = self.playback_app_label()
        state = self.playback_state_label()
        if app and state:
            return app + " " + state
        return app or state

    def _track_position(self, pos):
        """Record when ``position_ms`` last changed (for stale-clock hiding)."""
        if pos is None:
            self._last_position_ms = None
            self._position_changed_at = 0.0
            return
        if pos != self._last_position_ms:
            self._last_position_ms = pos
            try:
                self._position_changed_at = float(time.time()) if time else 0.0
            except Exception:
                self._position_changed_at = 0.0

    def _position_is_stale(self):
        """True when ECP ``position`` has not changed for 3+ seconds."""
        if not self._position_changed_at or time is None:
            return False
        try:
            return float(time.time()) - self._position_changed_at >= 3.0
        except Exception:
            return False

    def position_label(self):
        """Right-plaque clock: ``m:ss`` or ``m:ss/m:ss`` when media reports times.

        Returns empty when position has not advanced for 3+ seconds — many apps
        (Netflix, Prime, …) leave ECP ``position`` stuck while ``state=play``.
        """
        ms = self.media_state or {}
        pos = ms.get("position_ms")
        if pos is None:
            return ""
        if self._position_is_stale():
            return ""
        left = _format_clock_ms(pos)
        if not left:
            return ""
        dur = ms.get("duration_ms")
        if dur is not None and dur > 0:
            right = _format_clock_ms(dur)
            if right:
                return left + "/" + right
        return left

    def progress_fraction(self):
        """``position_ms / duration_ms`` in ``0.0..1.0``, or ``None`` if unusable.

        Requires a positive duration and a non-stale position (same 3s rule as
        :meth:`position_label`). Used for the under-plaque scrub rail.
        """
        ms = self.media_state or {}
        pos = ms.get("position_ms")
        dur = ms.get("duration_ms")
        if pos is None or dur is None:
            return None
        if self._position_is_stale():
            return None
        try:
            pos = int(pos)
            dur = int(dur)
        except (TypeError, ValueError):
            return None
        if dur <= 0:
            return None
        if pos < 0:
            pos = 0
        if pos > dur:
            pos = dur
        return float(pos) / float(dur)

    def refresh_playback(self):
        """Query active-app + media-player together; return ``playback_status()``.

        One refresh cycle always updates app name, play/pause state, and
        position/duration (when the player reports them) from the same pair of
        ECP GETs so the plaque stays coherent.
        """
        try:
            self.query_active_app()
        except Exception:
            pass
        try:
            self.query_media_player()
        except Exception:
            pass
        # A successful media/app probe means we can talk to the device even if a
        # prior keypress timed out and left last_error set.
        if self.active_app or self.media_state:
            self.connected = True
        return self.playback_status()

    # --- Presentation helpers (UI-agnostic strings from engine state) ------

    def play_label(self):
        """Transport Play/Pause caption from media-player state.

        ``PAUSE`` while playing/buffering, ``PLAY`` while paused, else ``P/PA``.
        """
        state = ((self.media_state or {}).get("state") or "").lower()
        if state in ("play", "buffer"):
            return "PAUSE"
        if state == "pause":
            return "PLAY"
        return "P/PA"

    def power_label(self):
        """``ON`` / ``OFF`` for the power key face, from ``power-mode``."""
        return "ON" if self.power_is_on() else "OFF"

    def power_key(self):
        """The ECP key that toggles power from the current state."""
        return "PowerOff" if self.power_is_on() else "PowerOn"

    def input_short_label(self, app, max_chars=4):
        """Short ASCII label for a ``type=tvin`` input (TV / H1 / H2 / AV / …)."""
        aid = (app.get("id") or "").lower()
        name = ascii_label(app.get("name") or "").strip()
        lab = ""
        if "dtv" in aid or "tuner" in aid or name.upper() in ("LIVE TV", "TV"):
            lab = "TV"
        elif "hdmi" in aid:
            for ch in aid:
                if ch.isdigit():
                    lab = "H" + ch
                    break
            if not lab:
                lab = "HDMI"
        elif "cvbs" in aid or "av" in aid:
            lab = "AV"
        elif name:
            up = name.upper()
            if "HDMI" in up:
                for ch in up:
                    if ch.isdigit():
                        lab = "H" + ch
                        break
                if not lab:
                    lab = "HDMI"
            elif "TV" in up:
                lab = "TV"
            elif "AV" in up or "COMPOSITE" in up:
                lab = "AV"
            else:
                lab = name
        else:
            lab = aid.split(".")[-1] if aid else "?"
        lab = ascii_label(lab).strip() or "?"
        if max_chars > 0 and len(lab) > max_chars:
            lab = lab[:max_chars]
        return lab

    # --- Composite actions (ECP + state, no drawing) -----------------------

    def press_refresh(self, key):
        """Send ``key`` then refresh playback state. Returns the press result."""
        ok = self.press(key)
        try:
            self.refresh_playback()
        except Exception:
            pass
        return ok

    def launch_refresh(self, app_id, query=""):
        """Launch ``app_id`` then refresh playback state. Returns the launch result."""
        ok = self.launch(app_id, query)
        try:
            self.refresh_playback()
        except Exception:
            pass
        return ok

    def mark_power_optimistic(self):
        """Flip cached ``power-mode`` for an immediate UI redraw; return the key.

        Lets a front end repaint the power face before the (blocking) ECP call
        runs on a worker. Pair with :meth:`press_refresh` on the returned key.
        """
        key = self.power_key()
        if not self.device_info:
            self.device_info = {}
        self.device_info["power-mode"] = "DisplayOff" if key == "PowerOff" else "PowerOn"
        return key

    def toggle_power(self):
        """Blocking convenience: flip power, send the key, resync device state.

        Returns the ECP key that was sent. Front ends that want an optimistic
        redraw should instead call :meth:`mark_power_optimistic` on the main
        thread and :meth:`press_refresh` on a worker.
        """
        key = self.mark_power_optimistic()
        self.press(key)
        try:
            self.query_device_info()
            self.refresh_playback()
        except Exception:
            pass
        return key

    @property
    def status(self):
        if self.last_error and not self.connected:
            return "err: " + self.last_error
        if not self.host:
            return "no host"
        if not self.connected:
            return "offline " + self.host
        return self.playback_status()

    def _request(self, method, path, data=b"", timeout=None):
        if not self.host:
            self.last_error = "no host"
            return 0, b""
        url = self.base_url + path
        t = self.timeout if timeout is None else float(timeout)
        try:
            if self._http is not None:
                status, body = self._http(method, url, t, data)
            else:
                status, body = http_request(method, url, timeout=t, data=data)
        except Exception as e:
            self.last_error = str(e)
            # Do not clear ``connected`` on transient socket errors — a single
            # failed keypress must not make the plaque say "offline" while the
            # TV is still playing.
            return 0, b""
        if status and 200 <= status < 400:
            self.connected = True
            self.last_error = ""
        elif status and status >= 400:
            self.last_error = "HTTP %d %s" % (status, path)
        return status, body

    def discover(
        self, timeout=1.5, retries=1, scan_fallback=True, ssdp=True, on_device=None
    ):
        """Find reachable Rokus (SSDP + cache reprobe, optional unicast /24).

        Cache hosts are probed first (and reported via ``on_device``) so the UI
        can populate quickly. Select **SCAN** passes ``scan_fallback=False``
        (SSDP + known-host reprobe only). Select **FULL** passes ``True`` so a
        unicast ``/24`` runs when :func:`unicast_scan_supported` (skipped on
        MicroPython ``network`` STA targets where the sweep wedges the UI).
        Does not pick a target host — callers use Select / ``set_host`` /
        ``resume_last_host``.
        """
        self._discover_cancel = False

        def _cancelled():
            return bool(self._discover_cancel)

        try:
            known = _load_known_hosts()
            priority = []
            seen_pri = {}
            for host in [
                d.get("host") for d in (self.discovered or []) if d.get("host")
            ] + [d.get("host") for d in known if d.get("host")]:
                host = (host or "").strip()
                if host and host not in seen_pri:
                    seen_pri[host] = True
                    priority.append(host)
            found = []
            path = "none"
            # Always enumerate every reachable TV (Scan / Select / CLI).
            find_all = True
            if ssdp and not _cancelled():
                # Keep scan_fallback out of discover_rokus so on_device still runs
                # on the unicast path; enrich SSDP hits with ECP names for the UI.
                found = discover_rokus(
                    timeout=timeout,
                    retries=retries,
                    scan_fallback=False,
                    ssdp=True,
                    cancel_check=_cancelled,
                )
                path = "ssdp" if found else "ssdp_empty"
                enriched = []
                for info in found:
                    if _cancelled():
                        break
                    named = _ecp_device(
                        info.get("host") or "", timeout=min(self.timeout, 1.5)
                    )
                    if named:
                        info = named
                    enriched.append(info)
                    if on_device is not None:
                        try:
                            on_device(info)
                        except Exception:
                            pass
                found = enriched
            # Re-probe persisted / session-known hosts SSDP missed (UDP flakiness).
            if priority and not _cancelled():
                have = {d.get("host") for d in found if d.get("host")}
                missing = [h for h in priority if h not in have]
                if missing:
                    recovered = _reprobe_known_hosts(
                        missing,
                        on_device=on_device,
                        timeout=min(self.timeout, 1.5),
                        cancel_check=_cancelled,
                    )
                    if recovered:
                        found = list(found) + list(recovered)
                        path = (path or "none") + "+reprobe"
            # Full unicast /24 when scan_fallback is on (Select FULL). Select SCAN
            # passes False so SSDP + cache reprobe stay fast. On MicroPython +
            # network (MCU STA) skip the /24 — it wedges lwIP for tens of seconds.
            if scan_fallback and unicast_scan_supported() and not _cancelled():
                have = {d.get("host") for d in found if d.get("host")}

                def _on_new(info):
                    host = (info or {}).get("host")
                    if not host or host in have:
                        return
                    have.add(host)
                    if on_device is not None:
                        try:
                            on_device(info)
                        except Exception:
                            pass

                scanned = discover_rokus_scan(
                    priority_hosts=priority,
                    on_device=_on_new if on_device is not None else None,
                    find_all=find_all,
                    connect_timeout=0.35,
                    cancel_check=_cancelled,
                )
                if not found:
                    found = scanned
                    path = "scan_fallback"
                else:
                    for info in scanned or []:
                        host = (info or {}).get("host")
                        if host and host not in {
                            d.get("host") for d in found if d.get("host")
                        }:
                            found.append(info)
                    if scanned:
                        path = (path or "none") + "+scan"
            elif scan_fallback and not unicast_scan_supported():
                path = (path or "none") + "+no_subnet"
            # Keep whatever we found even when Cancelled — Select keeps the list.
            self.discovered = found
            if _cancelled():
                self.last_error = ""
            else:
                self.last_error = "" if self.discovered else "no Roku found"
            if found:
                _save_known_hosts(found)
        except Exception as e:
            self.discovered = []
            self.last_error = str(e)
        return self.discovered

    def cached_devices(self):
        """Persistent Select-page list (``{host, name, serial}``); never auto-pruned."""
        return _load_known_hosts()

    def remember_devices(self, devices):
        """Merge *devices* into the persistent cache (additive / serial IP update)."""
        return _save_known_hosts(devices)

    def forget_device(self, host):
        """User-initiated remove of one cached TV."""
        return _remove_known_host(host)

    def refresh_cached_names(self):
        """Soft-probe each cached host; refresh name/serial; never drop unreachable.

        Returns the full cache after merging any successful probes. Used when
        opening the Select page — not a network scan.
        """
        known = _load_known_hosts()
        touched = []
        for item in known:
            host = (item.get("host") or "").strip()
            if not host:
                continue
            info = _ecp_device(host, timeout=min(self.timeout, 1.5))
            if info:
                touched.append(info)
        if touched:
            _save_known_hosts(touched)
        return _load_known_hosts()

    def resume_last_host(self):
        """Probe prefs MRU host; connect when reachable (serial must match if set).

        ``ROKU_HOST`` (if set) overrides the MRU host and skips the serial check.
        Missing prefs / empty MRU → False (caller opens Select).
        Offline / serial mismatch → False with ``last_error`` set (Select).
        """
        forced = (ROKU_HOST or "").strip()
        prefs = _load_prefs()
        host = forced or (prefs.get("last_host") or "").strip()
        want_serial = "" if forced else (prefs.get("last_serial") or "").strip()
        if not host:
            return False
        self.set_host(host)
        info = self.query_device_info()
        if not info:
            self.connected = False
            self.last_error = "last TV offline"
            return False
        live = (info.get("serial-number") or "").strip()
        if want_serial and live and live != want_serial:
            self.connected = False
            self.last_error = "TV changed"
            return False
        return self.connect()

    def connect(self, discover_if_empty=True):
        """Ping device-info for the current host.

        Does not auto-discover or pick a TV. ``discover_if_empty`` is retained for
        call-site compatibility and ignored — empty host → failure. Use
        ``resume_last_host``, Select + ``set_host``, or an explicit host first.
        """
        del discover_if_empty
        if not self.host:
            self.last_error = "no host"
            self.connected = False
            return False
        info = self.query_device_info()
        self.connected = bool(info)
        if self.connected:
            serial = info.get("serial-number") or ""
            try:
                self.remember_devices(
                    [
                        {
                            "host": self.host,
                            "name": info.get("user-device-name")
                            or info.get("model-name")
                            or "",
                            "serial": serial,
                        }
                    ]
                )
            except Exception:
                pass
            try:
                _set_last_device(self.host, serial)
            except Exception:
                pass
            try:
                self.refresh_playback()
            except Exception:
                pass
            try:
                if not self.apps:
                    self.query_apps()
            except Exception:
                pass
        return self.connected

    def press(self, key, timeout=None, wait=True):
        """ECP ``/keypress/``. Optional ``timeout`` caps socket wait (MCU taps).

        Uses the socket HTTP client directly so urequests/urlopen cannot ignore
        short timeouts (ESP32 taps were stalling 3–7s despite timeout=1.5).

        ``wait=False``: send the POST and return without reading the HTTP
        response (MCU remote taps). Roku applies the key on request; the
        keep-alive response is drained on the next press.
        """
        if key not in ECP_KEY_SET and not str(key).startswith("Lit_"):
            self.last_error = "unknown key: " + str(key)
            return False
        if not self.host:
            self.last_error = "no host"
            return False
        t = self.timeout if timeout is None else float(timeout)
        if t <= 0:
            t = 1.0
        url = self.base_url + "/keypress/" + key
        try:
            if self._http is not None:
                status, _ = self._http("POST", url, t, b"")
            elif not wait:
                return self._press_keepalive(key, t, drain=False)
            else:
                status, _ = _http_request_socket(
                    "POST", url, timeout=t, data=b"", read_response=True
                )
        except Exception as e:
            self.last_error = str(e)
            return False
        if status and 200 <= status < 400:
            self.connected = True
            self.last_error = ""
            return True
        if status:
            self.last_error = "HTTP %d /keypress/%s" % (status, key)
        return False

    def keydown(self, key):
        if key not in ECP_KEY_SET and not str(key).startswith("Lit_"):
            self.last_error = "unknown key: " + str(key)
            return False
        status, _ = self._request("POST", "/keydown/" + key, b"")
        return 200 <= status < 300

    def keyup(self, key):
        if key not in ECP_KEY_SET and not str(key).startswith("Lit_"):
            self.last_error = "unknown key: " + str(key)
            return False
        status, _ = self._request("POST", "/keyup/" + key, b"")
        return 200 <= status < 300

    def type_text(self, text):
        ok = True
        for ch in text:
            lit = "Lit_" + _quote_lit(ch)
            if not self.press(lit):
                ok = False
        return ok

    def launch(self, app_id, query=""):
        path = "/launch/" + str(app_id)
        if query:
            path += ("&" if "?" in query else "?") + query.lstrip("?&")
        status, _ = self._request("POST", path, b"")
        return 200 <= status < 300

    def install(self, app_id):
        status, _ = self._request("POST", "/install/" + str(app_id), b"")
        return 200 <= status < 300

    def input_params(self, params):
        """POST /input?k=v&... custom events to the current app."""
        if isinstance(params, dict):
            parts = []
            for k, v in params.items():
                parts.append("%s=%s" % (k, v))
            qs = "&".join(parts)
        else:
            qs = str(params).lstrip("?")
        status, _ = self._request("POST", "/input?" + qs, b"")
        return 200 <= status < 300

    def query_device_info(self):
        status, body = self._request("GET", "/query/device-info")
        if not body or status >= 400:
            self.device_info = {}
            return {}
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        info = {}
        for tag in (
            "udn",
            "serial-number",
            "device-id",
            "vendor-name",
            "model-name",
            "model-number",
            "model-region",
            "is-tv",
            "is-stick",
            "user-device-name",
            "software-version",
            "software-build",
            "power-mode",
            "network-type",
            "network-name",
            "supports-find-remote",
            "supports-audio-volume-control",
            "supports-tv-power-control",
            "supports-ethernet",
            "wifi-mac",
            "ethernet-mac",
        ):
            val = _xml_tag(text, tag)
            if val:
                info[tag] = val
        self.device_info = info
        return info

    def query_apps(self):
        status, body = self._request("GET", "/query/apps")
        if not body or status >= 400:
            self.apps = []
            return []
        self.apps = _parse_apps(body)
        return self.apps

    def query_active_app(self):
        status, body = self._request("GET", "/query/active-app")
        if not body or status >= 400:
            self.active_app = {}
            self.active_screensaver = ""
            return {}
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        # Optional <screensaver id="…" name="…"/> sibling (ECP docs).
        saver = ""
        si = text.find("<screensaver")
        if si >= 0:
            sgt = text.find(">", si)
            if sgt >= 0:
                sattrs = _xml_attrs(text[si : sgt + 1])
                saver = _xml_unescape(
                    sattrs.get("name", "") or sattrs.get("id", "") or ""
                )
                if not saver:
                    saver = "screensaver"
        self.active_screensaver = saver
        # <app id="12">Netflix</app> or screensaver sibling
        apps = _parse_apps(text)
        if apps:
            self.active_app = apps[0]
        else:
            name = _xml_tag(text, "app")
            self.active_app = {"id": "", "name": name} if name else {}
        return self.active_app

    def query_media_player(self):
        status, body = self._request("GET", "/query/media-player")
        if not body or status >= 400:
            self.media_player = ""
            self.media_state = {}
            self._track_position(None)
            return ""
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        self.media_player = text.strip()
        self.media_state = _parse_media_player(self.media_player)
        self._track_position((self.media_state or {}).get("position_ms"))
        return self.media_player

    def query_tv_channels(self):
        status, body = self._request("GET", "/query/tv-channels")
        if not body or status >= 400:
            return ""
        return body.decode("utf-8") if isinstance(body, bytes) else body

    def query_tv_active_channel(self):
        status, body = self._request("GET", "/query/tv-active-channel")
        if not body or status >= 400:
            return ""
        return body.decode("utf-8") if isinstance(body, bytes) else body

    def query_icon(self, app_id):
        """Return raw icon bytes (PNG/JPEG) or b''."""
        status, body = self._request("GET", "/query/icon/" + str(app_id))
        if not body or status >= 400:
            return b""
        return body

    # --- Developer-mode helpers (engine API; light UI dump) ---

    def query_raw(self, path):
        """GET an arbitrary ECP path; return decoded text or ''."""
        if not path.startswith("/"):
            path = "/" + path
        status, body = self._request("GET", path)
        if not body:
            return ""
        if isinstance(body, bytes):
            try:
                return body.decode("utf-8")
            except UnicodeError:
                return repr(body[:80])
        return body

    def query_chanperf(self, duration_seconds=None):
        path = "/query/chanperf"
        if duration_seconds is not None:
            path += "?duration-seconds=" + str(duration_seconds)
        return self.query_raw(path)

    def query_sgnodes(self, which="all"):
        return self.query_raw("/query/sgnodes/" + which)

    def query_registry(self, channel_id="dev"):
        return self.query_raw("/query/registry/" + str(channel_id))

    def query_graphics_frame_rate(self):
        return self.query_raw("/query/graphics-frame-rate")

    def query_app_state(self, app_id):
        return self.query_raw("/query/app-state/" + str(app_id))

    def query_app_object_counts(self, app_id):
        return self.query_raw("/query/app-object-counts/" + str(app_id))

    def exit_app(self, force=False):
        path = "/exit-app"
        if force:
            path += "/true"
        status, _ = self._request("POST", path, b"")
        return 200 <= status < 300

    def fwbeacons_track(self, channel_id=None):
        path = "/fwbeacons/track"
        if channel_id:
            path += "/" + str(channel_id)
        status, _ = self._request("POST", path, b"")
        return 200 <= status < 300

    def fwbeacons_untrack(self):
        status, _ = self._request("POST", "/fwbeacons/untrack", b"")
        return 200 <= status < 300

    def query_fwbeacons(self):
        return self.query_raw("/query/fwbeacons")

    def sgrendezvous_track(self, channel_id=None):
        path = "/query/sgrendezvous/track"
        if channel_id:
            path += "/" + str(channel_id)
        status, _ = self._request("POST", path, b"")
        return 200 <= status < 300

    def sgrendezvous_untrack(self):
        status, _ = self._request("POST", "/query/sgrendezvous/untrack", b"")
        return 200 <= status < 300

    def query_sgrendezvous(self):
        return self.query_raw("/query/sgrendezvous")

    def query_r2d2_bitmaps(self):
        return self.query_raw("/query/r2d2-bitmaps")

    def is_tv(self):
        return str(self.device_info.get("is-tv", "")).lower() in ("true", "1")

    def supports_volume(self):
        return str(self.device_info.get("supports-audio-volume-control", "")).lower() in (
            "true",
            "1",
        ) or self.is_tv()


def start_page_for_engine(engine):
    """Probe MRU via ``engine.resume_last_host`` → ``\"remote\"`` or ``\"devices\"``."""
    try:
        if engine is not None and engine.resume_last_host():
            return "remote"
    except Exception as exc:
        try:
            engine.last_error = "mru: %s" % exc
        except Exception:
            pass
    return "devices"


# MicroPython-friendly: avoid dataclass / typing
if __name__ == "__main__":
    eng = RokuEngine()
    print("discover:", eng.discover())
    if eng.discovered:
        eng.set_host(eng.discovered[0]["host"])
        print("connect:", eng.connect())
        print("status:", eng.status)
        print("apps:", len(eng.query_apps()))
    else:
        print("last_error:", eng.last_error, file=sys.stderr)