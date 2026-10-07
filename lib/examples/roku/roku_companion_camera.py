# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_companion_camera.py
=========================

Demonstrates using a Roku TV as a live camera monitor with the PyDevices
Companion app.

Starts a tiny HTTP server, then tells the Roku to fetch frames from it
repeatedly (~10 fps). On a real device the frames would come from
``cameraif``; here each one is drawn with ``pygraphics`` (a colour field that
changes every ten frames, with the frame number on it) and encoded with
``pngio`` (built into MicroPython; pydevices-desktop's over Pillow on CPython).

Prerequisites
-------------
* The **PyDevices Companion** channel on the target Roku
  (``tools/roku_companion_app/`` in this repository).
* Roku setting **Control by mobile apps → Enabled**.
* Inbound TCP on ``SERVE_PORT`` allowed from the Roku's subnet.

Usage::

    python roku_companion_camera.py ROKU_IP

Press Ctrl-C to stop serving and exit.
"""

import socket
import time

from utils.roku_companion import RokuCompanion, get_local_ip, roku_host

import pngio
from pygraphics import RGB565, FrameBuffer

# -- Configuration ----------------------------------------------------------
ROKU_IP = roku_host()
SERVE_HOST = "0.0.0.0"
SERVE_PORT = 8090

# IP the Roku can reach us on (not 0.0.0.0 — the Roku needs a routable addr).
# On WSL this is the eth0 address visible to the LAN.
MY_IP = get_local_ip(ROKU_IP)
# ---------------------------------------------------------------------------


WIDTH, HEIGHT = 160, 90
COLOURS = (
    ("Red", 0xF800),
    ("Green", 0x07E0),
    ("Blue", 0x001F),
    ("Yellow", 0xFFE0),
    ("Magenta", 0xF81F),
    ("Cyan", 0x07FF),
)


_png = pngio.PngEncoder()


def make_frame(n):
    """Frame *n* as PNG bytes: a colour field that changes every ten frames,
    with the frame number in black."""
    name, colour = COLOURS[(n // 10) % len(COLOURS)]
    buf = bytearray(WIDTH * HEIGHT * 2)
    fb = FrameBuffer(buf, WIDTH, HEIGHT, RGB565)
    fb.fill(colour)
    fb.text("%s %d" % (name, n), 8, 8, 0x0000)
    return name, _png.encode(buf, WIDTH, HEIGHT)


def serve_frames(port):
    """HTTP server that cycles through coloured frames."""

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((SERVE_HOST, port))
    srv.listen(5)
    print("Frame server listening on port", port)

    count = 0
    try:
        while True:
            client, _addr = srv.accept()
            try:
                client.recv(1024)  # consume the HTTP request
                name, data = make_frame(count)
                resp = (
                    b"HTTP/1.0 200 OK\r\n"
                    b"Content-Type: image/png\r\n"
                    b"Content-Length: %d\r\n"
                    b"Connection: close\r\n"
                    b"\r\n" % len(data)
                )
                client.sendall(resp + data)
                count += 1
                if count % 10 == 0:
                    print("Served %d frames (last: %s)" % (count, name))
            except Exception as e:
                print("Frame serve error:", e)
            finally:
                try:
                    client.close()
                except Exception:
                    pass
    except KeyboardInterrupt:
        print("\nStopping frame server.")
    finally:
        srv.close()


def main():
    tv = RokuCompanion(ROKU_IP)

    print("Launching camera view on Roku at", ROKU_IP)
    tv.camera("http://%s:%d/frame.png" % (MY_IP, SERVE_PORT))

    # Give the Roku a moment to launch the app before we start serving.
    time.sleep(1)

    # Block here serving frames until Ctrl-C.
    serve_frames(SERVE_PORT)


main()
