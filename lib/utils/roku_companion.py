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

    tv = RokuCompanion("192.168.1.129")
    tv.say("Hello from PyDevices!")
    tv.dashboard("Temperature: 72°F  Humidity: 45%")
    tv.camera("http://192.168.1.50:8080/frame.jpg")

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
        # If on WSL behind NAT, the local adapter is 172.x, but the Windows LAN IP is 192.168.1.143
        if ip.startswith("172.") and target_host.startswith("192.168.1."):
            return "192.168.1.143"
        return ip
    except Exception:
        return "192.168.1.143"
    finally:
        s.close()


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
        """Deep-link into the Companion app with the given parameters."""
        path = "/launch/%s?%s" % (_DEV_CHANNEL, _build_query(params))
        _ecp_post(self.host, path, self.timeout)

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

    def camera(self, url):
        """Stream live JPEG frames from *url* on the TV.

        The Companion app fetches the URL repeatedly (~10 fps) as
        individual JPEG images, displaying each on a full-screen
        ``<Poster>`` node.  This is the simplest way to push a
        ``cameraif`` MJPEG feed to a Roku without transcoding.

        Example::

            tv.camera("http://192.168.1.50:8080/frame.jpg")
        """
        self._launch({"mode": "camera", "url": str(url)})


class _FrameServer:
    """Lightweight HTTP server serving the latest PNG frame to the Roku TV."""

    def __init__(self, host="", port=8090):
        self.port = port
        self.host = host
        self.frame = None
        self._running = False
        self._threaded = False
        self._served_count = 0
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
            self._served_count += 1
            print(
                "[FrameServer] Connection from %s (served frame #%d)"
                % (addr[0], self._served_count)
            )
            try:
                conn.settimeout(1.0)
                try:
                    req_header = conn.recv(1024)
                    first_line = req_header.decode("utf-8", errors="ignore").split("\r\n")[0]
                    import time

                    now = time.time()
                    if not hasattr(self, "_last_req"):
                        self._last_req = now
                    delta = now - self._last_req
                    self._last_req = now
                    print("[FrameServer] Request: %s (delta: %.3fs)" % (first_line, delta))
                except OSError:
                    pass
                data = self.frame or b""
                resp = (
                    b"HTTP/1.0 200 OK\r\n"
                    b"Content-Type: image/png\r\n"
                    b"Content-Length: " + str(len(data)).encode("ascii") + b"\r\n"
                    b"Connection: close\r\n"
                    b"Cache-Control: no-cache\r\n\r\n"
                ) + data
                conn.sendall(resp)
            except OSError as e:
                print("[FrameServer] Send error: %s" % e)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

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
    """

    def __init__(self, tv, width=320, height=240, port=8090, my_ip=None, **kwargs):
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

        if hasattr(self._server, "poll"):
            self._server.poll()

    def close(self):
        """Shut down the background frame server."""
        if self._server is not None:
            self._server.close()
            self._server = None


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

        if hasattr(self._server, "poll"):
            self._server.poll()

    @property
    def format(self):
        return getattr(self.display, "format", 2)

    def close(self):
        """Shut down the frame server and close the wrapped display if supported."""
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
