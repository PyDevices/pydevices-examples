# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
`roku_companion`
====================================================

Lightweight API wrapper for the PyDevices Companion Roku app.

Sends ECP deep-link commands to a sideloaded "PyDevices Companion" channel
on a Roku TV, enabling:

* **Text-to-Speech** — speak arbitrary text through the TV speakers
  (``roTextToSpeech``).
* **Camera Monitor** — display a live MJPEG-style feed by rapidly fetching
  JPEG frames from a URL served by ``cameraif`` (or any HTTP JPEG source).
* **Dashboard** — show sensor readings, status text, or notifications on
  the TV screen.

The module is self-contained: it uses only ``socket`` (no ``urllib`` /
``urequests`` needed) so it works identically on MicroPython, MicroPython
for Windows, CircuitPython, and CPython.

Usage::

    from utils.roku_companion import RokuCompanion

    tv = RokuCompanion("192.0.2.10")
    tv.say("Hello from PyDevices!")
    tv.dashboard("Temperature: 72°F  Humidity: 45%")
    tv.camera("http://192.0.2.20:8080/frame.jpg")

Requires
--------
* The **PyDevices Companion** Roku app sideloaded on the target TV
  (see ``roku_companion_app/`` in ``.scratch``).
* Roku setting **Control by mobile apps → Enabled**.

Network Discovery
-----------------
``roku_engine`` in the ``roku_remote`` example implements SSDP and mDNS
device discovery.  Those protocols work on native network stacks
(``python.exe`` / ``micropython.exe`` on Windows, real hardware) but
**not** from WSL / Linux behind NAT — multicast doesn't bridge.  When
running from WSL, pass the Roku's IP address directly.
"""

import socket

try:
    from pygraphics import RGB565, encode_png
except ImportError:
    try:
        from pygraphics._framebuf_plus import RGB565
        from pygraphics._png import encode_png
    except ImportError:
        RGB565 = 1
        encode_png = None

try:
    from displaydev.fbdisplay import FBDisplay
except ImportError:
    try:
        from displaydev import DisplayDriver as FBDisplay
    except ImportError:

        class FBDisplay:
            """Fallback DisplayDriver stub if displaydev is not installed."""

            def __init__(self, buffer, width=320, height=240, **kwargs):
                self._raw_buffer = buffer
                self._width = width
                self._height = height
                self.color_depth = 16

            @property
            def width(self):
                return self._width

            @property
            def height(self):
                return self._height

            def fill_rect(self, x, y, w, h, c):
                pass

            def pixel(self, x, y, c=None):
                return 0

            def show(self, _timer=None):
                pass


# ECP port (standard for all Roku devices).
_ECP_PORT = 8060

# Sideloaded dev channel ID.
_DEV_CHANNEL = "dev"

# Remote buttons as the channel's onKeyEvent names them, and the keys.K_* code
# each becomes. Home, Power, Volume, Mute and the shortcut buttons never reach
# a channel. A name not listed here still arrives, with key code 0.
_REMOTE_KEYS = (
    ("up", "K_UP"),
    ("down", "K_DOWN"),
    ("left", "K_LEFT"),
    ("right", "K_RIGHT"),
    ("OK", "K_RETURN"),
    ("back", "K_AC_BACK"),
    ("options", "K_MENU"),  # the * button
    ("play", "K_AUDIOPLAY"),
    ("rewind", "K_AUDIOPREV"),  # keys has no rewind/fast-forward codes yet
    ("fastforward", "K_AUDIONEXT"),
    ("replay", "K_AC_REFRESH"),  # instant replay
)

# Held buttons stop repeating once the TV has not asked for a frame this long;
# it asks at least once a second (plus Wi-Fi delay) while the channel is up.
_REMOTE_GONE_SECONDS = 3.0

# Longest a frame request waits for a new frame before the current one is resent.
_HOLD_SECONDS = 1.0


def _get_local_ip(target_host):
    """Find the local IP address routable to target_host."""
    import os

    env_ip = os.getenv("PYDEVICES_MY_IP")
    if env_ip:
        return env_ip
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_host, 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    # WSL in its default NAT mode has a 172.x address the TV can't reach.
    # (WSL's mirrored networking mode shares the PC's LAN address instead.)
    if ip.startswith("172."):
        raise OSError(
            "this machine's address %s isn't reachable from the TV; set PYDEVICES_MY_IP "
            "to its LAN address, or use WSL's mirrored networking mode" % ip
        )
    return ip


def _percent_encode(s):
    """Minimal URL percent-encoding (ASCII-safe, works on MicroPython)."""
    out = []
    for ch in str(s):
        o = ord(ch)
        if (
            0x30 <= o <= 0x39  # 0-9
            or 0x41 <= o <= 0x5A  # A-Z
            or 0x61 <= o <= 0x7A  # a-z
            or ch in "-_.~"
        ):
            out.append(ch)
        else:
            try:
                raw = ch.encode("utf-8")
            except (AttributeError, UnicodeEncodeError):
                raw = bytes([o & 0xFF])
            for b in raw:
                out.append("%%%02X" % b)
    return "".join(out)


def _build_query(params):
    """Build a URL query string from a dict."""
    parts = []
    for k, v in params.items():
        parts.append("%s=%s" % (_percent_encode(k), _percent_encode(v)))
    return "&".join(parts)


def _ecp_post(host, path, timeout=5.0):
    """Fire-and-forget HTTP POST to a Roku ECP endpoint.

    Uses a raw socket so the module has zero import dependencies beyond
    ``socket``.
    """
    addr = socket.getaddrinfo(host, _ECP_PORT)[0][-1]
    req = "POST %s HTTP/1.0\r\nHost: %s:%d\r\nContent-Length: 0\r\n\r\n" % (
        path,
        host,
        _ECP_PORT,
    )
    print("[RokuCompanion] ECP POST -> http://%s:%d%s" % (host, _ECP_PORT, path))
    s = socket.socket()
    try:
        try:
            s.settimeout(timeout)
        except OSError:
            pass
        s.connect(addr)
        s.sendall(req.encode("utf-8"))
        # Read status response
        try:
            resp = s.recv(256).decode("utf-8", errors="ignore")
            status_line = resp.split("\r\n")[0] if resp else "no response"
            print("[RokuCompanion] ECP Response: %s" % status_line)
        except OSError:
            print("[RokuCompanion] ECP Sent (no response read)")
    except Exception as e:
        print("[RokuCompanion] ECP Error: %s" % e)
    finally:
        try:
            s.close()
        except OSError:
            pass


def _now():
    """Seconds on a clock that never steps backwards (WSL resyncs its wall clock)."""
    import time

    try:
        return time.monotonic()
    except AttributeError:
        return time.ticks_ms() / 1000


def _spawn(fn, *args):
    """Run fn(*args) on a new thread; False when the runtime has no threads."""
    try:
        import threading

        threading.Thread(target=fn, args=args, daemon=True).start()
        return True
    except ImportError:
        pass
    try:
        import _thread

        _thread.start_new_thread(fn, args)
        return True
    except ImportError:
        return False


def _at_exit(fn):
    """Call fn when the program ends, where the runtime offers a hook."""
    try:
        import atexit

        atexit.register(fn)
    except ImportError:
        pass


def _session_url(url):
    """*url* with a token unique to this session. The channel appends
    ``t=<frame number>`` to every fetch, counting from 1 each session, and the
    Roku caches images by URL: without the token a new session's
    ``frame.png?t=1`` is the old session's cached picture, and the TV replays
    earlier runs instead of fetching new frames."""
    import time

    try:
        token = time.ticks_ms()
    except AttributeError:
        token = int(time.time() * 1000)
    return "%s%ss=%d" % (url, "&" if "?" in url else "?", token & 0x7FFFFFFF)


def _ecp_get(host, path, timeout=5.0):
    """HTTP GET from a Roku ECP endpoint; the response body, or "" on failure."""
    addr = socket.getaddrinfo(host, _ECP_PORT)[0][-1]
    req = "GET %s HTTP/1.0\r\nHost: %s:%d\r\n\r\n" % (path, host, _ECP_PORT)
    s = socket.socket()
    chunks = []
    try:
        try:
            s.settimeout(timeout)
        except OSError:
            pass
        s.connect(addr)
        s.sendall(req.encode("utf-8"))
        while True:
            data = s.recv(1024)
            if not data:
                break
            chunks.append(data)
    except Exception as e:
        print("[RokuCompanion] ECP GET error: %s" % e)
    finally:
        try:
            s.close()
        except OSError:
            pass
    resp = b"".join(chunks).decode("utf-8", "ignore")
    return resp.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in resp else ""


def roku_host():
    """The Roku TV's address for an example: the first command-line argument,
    or the ``ROKU_IP`` environment variable."""
    import sys

    if len(sys.argv) > 1:
        return sys.argv[1]
    try:
        import os

        host = os.getenv("ROKU_IP")
    except (ImportError, AttributeError):
        host = None
    if not host:
        raise SystemExit("pass the Roku's IP address as the first argument, or set ROKU_IP")
    return host


def get_local_ip(target_host):
    """This machine's address as the Roku at *target_host* would reach it."""
    return _get_local_ip(target_host)


class RokuCompanion:
    """Control the PyDevices Companion app on a Roku TV.

    Parameters
    ----------
    host : str
        IP address (or hostname) of the Roku TV on the local network.
    timeout : float
        Socket timeout in seconds for ECP requests (default 5).
    """

    def __init__(self, host, timeout=5.0):
        self.host = host
        self.timeout = timeout

    def _launch(self, params):
        """Send parameters to the Companion app.

        When it's already the TV's active app they go as an ECP ``input``
        event, which the running channel handles in place. Otherwise the
        channel is launched with them. Launching a channel that's already
        running restarts it, and every update blanked and redrew the screen.
        """
        query = _build_query(params)
        if self._is_active():
            _ecp_post(self.host, "/input?%s" % query, self.timeout)
        else:
            _ecp_post(self.host, "/launch/%s?%s" % (_DEV_CHANNEL, query), self.timeout)

    def _is_active(self):
        """Whether the Companion app is the TV's active app."""
        body = _ecp_get(self.host, "/query/active-app", self.timeout)
        return ('id="%s"' % _DEV_CHANNEL) in body

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def say(self, text):
        """Speak *text* aloud through the TV speakers using ``roTextToSpeech``.

        Example::

            tv.say("Front door motion detected")
        """
        self._launch({"mode": "tts", "text": str(text)})

    def dashboard(self, text):
        """Display *text* on the TV as a full-screen dashboard message.

        Useful for sensor readings, status updates, or notifications.

        Example::

            tv.dashboard("Temp: 72°F  Humidity: 45%")
        """
        self._launch({"mode": "dashboard", "text": str(text)})

    def home(self):
        """Press Home: leave whatever channel is up for the TV's home screen."""
        _ecp_post(self.host, "/keypress/Home", self.timeout)

    def close_channel(self):
        """Close the Companion channel, leaving the TV on its home screen.

        Does nothing when another channel is on screen, so a program that ends
        while someone watches something else leaves them watching it.
        """
        if self._is_active():
            _ecp_post(self.host, "/input?mode=quit", self.timeout)

    def camera(self, url):
        """Stream live JPEG frames from *url* on the TV.

        The Companion app fetches the URL repeatedly (~10 fps) as
        individual JPEG images, displaying each on a full-screen
        ``<Poster>`` node.  This is the simplest way to push a
        ``cameraif`` MJPEG feed to a Roku without transcoding.

        Example::

            tv.camera("http://192.0.2.20:8080/frame.jpg")
        """
        self._launch({"mode": "camera", "url": _session_url(str(url))})


class _FrameServer:
    """Lightweight HTTP server serving the latest PNG frame to the Roku TV."""

    def __init__(self, host="", port=8090):
        self.port = port
        self.host = host
        self.frame = None
        self._running = False
        self._threaded = False
        self._served_count = 0
        self._version = 0
        self._last_req = None
        # One (accepted, requested, sent, version, request line, connection)
        # per fetch, and
        # one (time, version) per update_frame(), when trace is a list.
        self.trace = None
        self.updates = None
        # (remote button name, pressed, arrival time), drained by get_events().
        self.key_events = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            addr = socket.getaddrinfo(host, port, socket.AF_INET)[0][-1]
        except Exception:
            addr = (host, port)
        self._sock.bind(addr)
        self._sock.listen(4)
        print("[FrameServer] Bound on %s:%d" % (host or "0.0.0.0", port))
        self._start()

    def update_frame(self, frame_bytes):
        self.frame = frame_bytes
        self._version += 1
        if self.updates is not None:
            self.updates.append((_now(), self._version))

    def _start(self):
        self._running = True
        try:
            import threading

            t = threading.Thread(target=self._loop, daemon=True)
            t.start()
            self._threaded = True
            print("[FrameServer] Started daemon thread")
        except ImportError:
            try:
                import _thread

                _thread.start_new_thread(self._loop, ())
                self._threaded = True
                print("[FrameServer] Started _thread background thread")
            except ImportError:
                # Single-threaded environment: polled cooperatively
                self._threaded = False
                print("[FrameServer] Running single-threaded (cooperative poll)")
                try:
                    self._sock.setblocking(False)
                except OSError:
                    pass

    def _loop(self):
        try:
            self._sock.settimeout(0.5)
        except OSError:
            pass
        while self._running:
            try:
                conn, addr = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            accepted = _now()
            self._served_count += 1
            conn_id = self._served_count
            print("[FrameServer] Connection #%d from %s" % (conn_id, addr[0]))
            # One thread per connection: a kept-alive connection must not
            # hold the accept loop.
            if not _spawn(self._serve, conn, conn_id, accepted):
                self._serve(conn, conn_id, accepted, keep_alive=False)

    def _serve(self, conn, conn_id, accepted, keep_alive=True):
        """Answer requests on one connection until the client closes it or goes idle."""
        buf = b""
        sent_version = None
        try:
            conn.settimeout(5.0)
            while self._running:
                while b"\r\n\r\n" not in buf:
                    chunk = conn.recv(1024)
                    if not chunk:
                        return
                    buf += chunk
                requested = _now()
                head, buf = buf.split(b"\r\n\r\n", 1)
                lines = head.decode("utf-8", "ignore").split("\r\n")
                first_line = lines[0]
                headers = " ".join(lines[1:]).lower()
                persist = (
                    keep_alive
                    and first_line.endswith("HTTP/1.1")
                    and "connection: close" not in headers
                )
                if first_line.startswith("GET /key?"):
                    self._remote_key(first_line, requested)
                    conn.sendall(
                        (
                            b"HTTP/1.1 204 No Content\r\n"
                            if persist
                            else b"HTTP/1.0 204 No Content\r\n"
                        )
                        + (b"Connection: keep-alive\r\n" if persist else b"Connection: close\r\n")
                        + b"Content-Length: 0\r\n\r\n"
                    )
                    if not persist:
                        return
                    continue
                delta = 0.0 if self._last_req is None else requested - self._last_req
                self._last_req = requested
                print("[FrameServer] #%d %s (delta: %.3fs)" % (conn_id, first_line, delta))
                if persist and sent_version is not None:
                    self._wait_for_new_frame(sent_version)
                version = self._version
                sent_version = version
                data = self.frame or b""
                conn.sendall(
                    (b"HTTP/1.1 200 OK\r\n" if persist else b"HTTP/1.0 200 OK\r\n")
                    + b"Content-Type: image/png\r\n"
                    b"Content-Length: "
                    + str(len(data)).encode("ascii")
                    + b"\r\n"
                    + (b"Connection: keep-alive\r\n" if persist else b"Connection: close\r\n")
                    + b"Cache-Control: no-cache\r\n\r\n"
                    + data
                )
                if self.trace is not None:
                    self.trace.append((accepted, requested, _now(), version, first_line, conn_id))
                if not persist:
                    return
        except OSError:
            pass  # idle timeout or the client went away
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _remote_key(self, first_line, when):
        """Queue a remote button from "GET /key?k=<name>&p=<0|1> HTTP/1.1"."""
        query = first_line.split(" ")[1].split("?", 1)[1]
        fields = dict(item.split("=", 1) for item in query.split("&") if "=" in item)
        name = fields.get("k", "")
        pressed = fields.get("p") in ("1", "true")
        print("[FrameServer] remote %s %s" % (name, "down" if pressed else "up"))
        self.key_events.append((name, pressed, when))

    def _wait_for_new_frame(self, sent_version, limit=_HOLD_SECONDS):
        """Hold a request until show() has drawn a frame this connection has not had.

        The TV asks again the moment a frame lands, so answering at once would
        resend the same frame; holding sends each frame once, as soon as it
        exists. After `limit` seconds the current frame goes anyway, so a still
        screen keeps its connection alive.
        """
        import time

        deadline = _now() + limit
        while self._running and self._version == sent_version and _now() < deadline:
            time.sleep(0.002)

    def poll(self):
        """Non-blocking service of pending connections (for single-threaded runtimes)."""
        if self._threaded:
            return
        try:
            self._sock.setblocking(False)
            conn, addr = self._sock.accept()
        except OSError:
            return
        self._served_count += 1
        print("[FrameServer/poll] Connection from %s" % (addr[0],))
        try:
            data = self.frame or b""
            resp = (
                b"HTTP/1.0 200 OK\r\n"
                b"Content-Type: image/png\r\n"
                b"Content-Length: " + str(len(data)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n\r\n"
            ) + data
            conn.sendall(resp)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self._running = False
        print("[FrameServer] Closed")
        try:
            self._sock.close()
        except OSError:
            pass


class RokuDisplay(FBDisplay):
    """FBDisplay subclass that renders directly to a Roku TV.

    Inherits all DisplayDriver drawing operations (fill_rect, blit_rect, pixel, etc.),
    drawing into an in-memory RGB565 framebuffer.  On show(), encodes the frame
    to PNG using pygraphics and serves it to the PyDevices Companion app on the TV.

    Parameters
    ----------
    tv : RokuCompanion or str
        RokuCompanion instance or Roku TV IP address.
    width : int
        Display width in pixels (default 320).
    height : int
        Display height in pixels (default 240).
    port : int
        HTTP frame server port (default 8090).
    my_ip : str, optional
        Local IP routable by the Roku (defaults to detected LAN IP).
    key_repeat : (float, float) or None
        Seconds before a held remote button repeats, and between repeats
        (default 0.4, 0.1); None for no repeats. See get_events().
    """

    def __init__(
        self, tv, width=320, height=240, port=8090, my_ip=None, key_repeat=(0.4, 0.1), **kwargs
    ):
        if isinstance(tv, str):
            self.tv = RokuCompanion(tv)
        else:
            self.tv = tv

        self.port = port
        self.local_ip = my_ip or _get_local_ip(self.tv.host)
        self._raw_buf = bytearray(width * height * 2)

        super().__init__(self._raw_buf, width=width, height=height, **kwargs)

        self._server = None
        self._launched = False
        self.key_repeat = key_repeat
        self._held = {}  # remote button name -> (key name, code, next repeat)
        print(
            "[RokuDisplay] Initialized: %dx%d, stream host %s:%d"
            % (width, height, self.local_ip, port)
        )

    def show(self, _timer=None):
        """Encode the current framebuffer to PNG and update the Roku stream."""
        if encode_png is None:
            raise RuntimeError("pygraphics.encode_png is required for RokuDisplay")

        png_bytes = encode_png(self._raw_buf, width=self.width, height=self.height, format=RGB565)
        print(
            "[RokuDisplay] Encoded %dx%d frame -> %d bytes PNG"
            % (self.width, self.height, len(png_bytes))
        )

        if self._server is None:
            self._server = _FrameServer(host="", port=self.port)

        self._server.update_frame(png_bytes)

        if not self._launched:
            frame_url = "http://%s:%d/frame.png" % (self.local_ip, self.port)
            print("[RokuDisplay] Launching TV camera mode with URL: %s" % frame_url)
            self.tv.camera(frame_url)
            self._launched = True
            _at_exit(self.close)

        if hasattr(self._server, "poll"):
            self._server.poll()

    def get_events(self):
        """Remote button presses since the last call, as events.Key records.

        Pass it as ``App(host_read=display.get_events)`` and the remote drives
        an app like a keyboard: arrows, OK (K_RETURN), Back (K_AC_BACK) and the
        media buttons, mapped in _REMOTE_KEYS.

        The remote sends one press and one release however long a button is
        held, so held buttons repeat here, as a keyboard's do: another KEYDOWN
        ``key_repeat[0]`` seconds after the press, then every
        ``key_repeat[1]``. Set ``key_repeat = None`` to turn that off.
        """
        server = self._server
        if server is None:
            return []
        import events
        import keys

        out = []
        queued = server.key_events
        if queued:
            server.key_events = []
            codes = dict(_REMOTE_KEYS)
            for name, pressed, when in queued:
                code = getattr(keys, codes.get(name, ""), 0)
                key_name = keys.keyname(code) if code else name
                if pressed:
                    out.append(events.Key(events.KEYDOWN, key_name, code, 0, 0, None))
                    if self.key_repeat:
                        self._held[name] = (key_name, code, when + self.key_repeat[0])
                else:
                    self._held.pop(name, None)
                    out.append(events.Key(events.KEYUP, key_name, code, 0, 0, None))

        if self._held:
            now = _now()
            last = server._last_req
            if last is None or now - last > _REMOTE_GONE_SECONDS:
                # The channel went away (Home, say) before sending a release.
                for key_name, code, _due in self._held.values():
                    out.append(events.Key(events.KEYUP, key_name, code, 0, 0, None))
                self._held = {}
            elif self.key_repeat:
                for name, (key_name, code, due) in list(self._held.items()):
                    if now >= due:
                        out.append(events.Key(events.KEYDOWN, key_name, code, 0, 0, None))
                        self._held[name] = (key_name, code, max(due + self.key_repeat[1], now))
        return out

    def close(self):
        """Close the TV's Companion channel and the frame server. Safe to call twice.

        Runs when the program ends (appdev's quit, or at exit), so a finished
        app leaves the TV on its home screen rather than frozen on its last
        frame.
        """
        if self._launched:
            self._launched = False
            try:
                self.tv.close_channel()
            except OSError:
                pass
        if self._server is not None:
            self._server.close()
            self._server = None

    def _deinit(self):
        """DisplayDriver's cleanup hook, run by quit() and deinit()."""
        self.close()


class RokuDisplayWrapper:
    """Wrapper that adapts an existing FBDisplay (or DisplayDriver) for Roku TV streaming.

    Decorates an existing display instance via composition, intercepting show()
    to encode and stream the underlying framebuffer to the Roku TV.

    Parameters
    ----------
    display : DisplayDriver
        An existing display instance (e.g. FBDisplay).
    tv : RokuCompanion or str
        RokuCompanion instance or Roku TV IP address.
    port : int
        HTTP frame server port (default 8090).
    my_ip : str, optional
        Local IP routable by the Roku (defaults to detected LAN IP).
    """

    def __init__(self, display, tv, port=8090, my_ip=None):
        self.display = display
        if isinstance(tv, str):
            self.tv = RokuCompanion(tv)
        else:
            self.tv = tv

        self.port = port
        self.local_ip = my_ip or _get_local_ip(self.tv.host)
        self._server = None
        self._launched = False
        print(
            "[RokuDisplayWrapper] Initialized with display %s, stream host %s:%d"
            % (display, self.local_ip, port)
        )

    def show(self, *args, **kwargs):
        """Invoke underlying display show(), then stream the frame to the Roku TV."""
        try:
            self.display.show(*args, **kwargs)
        except AttributeError:
            pass

        if encode_png is None:
            raise RuntimeError("pygraphics.encode_png is required for RokuDisplayWrapper")

        raw_buf = getattr(self.display, "_raw_buffer", None)
        if raw_buf is None:
            raw_buf = getattr(self.display, "buffer", None)

        w = getattr(self.display, "width", 320)
        h = getattr(self.display, "height", 240)

        png_bytes = encode_png(raw_buf, width=w, height=h, format=RGB565)
        print("[RokuDisplayWrapper] Encoded %dx%d frame -> %d bytes PNG" % (w, h, len(png_bytes)))

        if self._server is None:
            self._server = _FrameServer(host="", port=self.port)

        self._server.update_frame(png_bytes)

        if not self._launched:
            frame_url = "http://%s:%d/frame.png" % (self.local_ip, self.port)
            print("[RokuDisplayWrapper] Launching TV camera mode with URL: %s" % frame_url)
            self.tv.camera(frame_url)
            self._launched = True
            _at_exit(self.close)

        if hasattr(self._server, "poll"):
            self._server.poll()

    @property
    def format(self):
        return getattr(self.display, "format", 2)

    def close(self):
        """Close the TV's Companion channel, the frame server and the wrapped display."""
        if self._launched:
            self._launched = False
            try:
                self.tv.close_channel()
            except OSError:
                pass
        if self._server is not None:
            self._server.close()
            self._server = None
        if hasattr(self.display, "close"):
            self.display.close()

    def __getattr__(self, name):
        """Delegate all other attribute and method accesses to the wrapped display."""
        if not hasattr(self.display, name):
            raise AttributeError(name)
        return getattr(self.display, name)


class RokuAudioSink:
    """PCM sink for Roku TV audio streaming."""

    def __init__(self, tv, port=8091, format=None, my_ip=None, **kwargs):
        if isinstance(tv, str):
            self.tv = RokuCompanion(tv)
        else:
            self.tv = tv

        self.port = port
        self.local_ip = my_ip or _get_local_ip(self.tv.host)

        if format is None:

            class Format:
                pass

            self.format = Format()
            self.format.rate = 44100
            self.format.channels = 2
            self.format.bits = 16
            self.format.signed = True
        else:
            self.format = format

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            addr = socket.getaddrinfo("", self.port, socket.AF_INET)[0][-1]
        except Exception:
            addr = ("", self.port)
        self._sock.bind(addr)
        self._sock.listen(2)

        self._running = True
        self._client = None
        self._launched = False

        try:
            import threading

            self._threaded = True
            self._thread = threading.Thread(target=self._server_loop, daemon=True)
            self._thread.start()
        except ImportError:
            try:
                import _thread

                self._threaded = True
                _thread.start_new_thread(self._server_loop, ())
            except ImportError:
                self._threaded = False

    def poll(self):
        try:
            self._sock.settimeout(0.0)
            conn, addr = self._sock.accept()
        except OSError:
            return

        print("[RokuAudio] Connection from %s" % (addr[0],))
        try:
            conn.settimeout(1.0)
            try:
                conn.recv(1024)
            except OSError:
                pass

            resp = b"HTTP/1.0 200 OK\r\nContent-Type: audio/wav\r\nConnection: close\r\n\r\n"

            import struct

            rate = self.format.rate
            channels = self.format.channels
            bits = self.format.bits

            header = b"RIFF\xff\xff\xff\xffWAVEfmt \x10\x00\x00\x00\x01\x00"
            header += struct.pack("<H", channels)
            header += struct.pack("<I", rate)
            byte_rate = rate * channels * (bits // 8)
            block_align = channels * (bits // 8)
            header += struct.pack("<I", byte_rate)
            header += struct.pack("<H", block_align)
            header += struct.pack("<H", bits)
            header += b"data\xff\xff\xff\xff"

            conn.setblocking(True)
            conn.sendall(resp + header)

            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = conn

        except OSError as e:
            print("[RokuAudio] Send error: %s" % e)
            try:
                conn.close()
            except OSError:
                pass

    def _server_loop(self):
        try:
            self._sock.settimeout(0.5)
        except OSError:
            pass
        while self._running:
            self.poll()

    def open(self):
        pass

    def queued_size(self):
        return 0

    def write(self, buf):
        if not self._threaded:
            self.poll()
        if not self._launched:
            audio_url = "http://%s:%d/stream.wav" % (self.local_ip, self.port)
            print("[RokuAudio] Launching TV audio mode with URL: %s" % audio_url)
            self.tv._launch({"mode": "audio", "url": audio_url})
            self._launched = True

        if self._client:
            try:
                self._client.sendall(buf)
            except OSError:
                self._client.close()
                self._client = None
        else:
            import time

            bytes_per_sec = self.format.rate * self.format.channels * (self.format.bits // 8)
            time.sleep(len(buf) / bytes_per_sec)

    def close(self):
        self._running = False
        if self._client:
            try:
                self._client.close()
            except OSError:
                pass
        try:
            self._sock.close()
        except OSError:
            pass
