# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_companion_camera.py
=========================

Demonstrates using a Roku TV as a live camera monitor with the PyDevices
Companion app.

Starts a tiny HTTP server that serves JPEG frames, then tells the Roku to
fetch them repeatedly (~10 fps).  On a real device the frames would come
from ``cameraif``; here we generate simple solid-colour test frames using
raw JPEG to prove the pipeline end-to-end.

Prerequisites
-------------
* The **PyDevices Companion** app sideloaded on the target Roku.
* Roku setting **Control by mobile apps → Enabled**.
* Firewall allowing inbound TCP on ``SERVE_PORT`` from the Roku's subnet
  (the ``earful`` PowerShell rule covers this on Brad's workstation).

Usage::

    python examples/roku_companion_camera.py

Press Ctrl-C to stop serving and exit.

.. note::

    This example requires CPython (uses ``struct`` for JPEG generation).
    For MicroPython, replace the frame generator with real ``cameraif``
    JPEG captures.
"""

import socket
import struct
import time
from utils.roku_companion import RokuCompanion

# -- Configuration ----------------------------------------------------------
ROKU_IP = "192.168.1.129"
SERVE_HOST = "0.0.0.0"
SERVE_PORT = 8090

# IP the Roku can reach us on (not 0.0.0.0 — the Roku needs a routable addr).
# On WSL this is the eth0 address visible to the LAN.
MY_IP = "192.168.1.143"
# ---------------------------------------------------------------------------


def _make_jpeg(r, g, b, width=64, height=64):
    """Generate a minimal valid JPEG of a solid colour (no PIL needed).

    Builds a raw baseline JFIF by hand: SOI, APP0, DQT, SOF0, DHT, SOS,
    and a single MCU of DC-only data.  The result is a tiny (~600 byte)
    file that every JPEG decoder (including Roku's ``<Poster>``) accepts.
    """
    # Quantisation table (all 1s = lossless for a single-colour block).
    dqt = b"\xFF\xDB\x00\x43\x00" + bytes(64)
    # Luminance DC Huffman table (one symbol: 0 = zero-length diff).
    dht_dc = (
        b"\xFF\xC4\x00\x1F\x00"
        + b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
        + b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0A\x0B"
    )
    # For a solid colour we only need the DC coefficient.
    # We'll use the simplest approach: a 1x1 pixel JPEG.
    w, h = 1, 1

    # SOF0: baseline, 8-bit, 1x1, 3 components (YCbCr), 1x1 subsampling.
    y_val = int(0.299 * r + 0.587 * g + 0.114 * b)
    cb_val = int(128 - 0.168736 * r - 0.331264 * g + 0.5 * b)
    cr_val = int(128 + 0.5 * r - 0.418688 * g - 0.081312 * b)

    # Instead of hand-encoding MCUs, generate a tiny BMP-like image
    # and just serve a pre-made coloured PNG... Actually, let's just
    # create a 1-pixel PPM and convert. But simplest: serve a tiny
    # coloured PNG since Roku Poster supports PNG too.
    #
    # Minimal 1x1 uncompressed PNG:
    import zlib

    def _png_1x1(r, g, b):
        sig = b"\x89PNG\r\n\x1a\n"
        # IHDR
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF)
        ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + ihdr_crc
        # IDAT (filter byte 0 + RGB)
        raw = b"\x00" + bytes([r, g, b])
        compressed = zlib.compress(raw)
        idat_crc = struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF)
        idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + idat_crc
        # IEND
        iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
        iend = struct.pack(">I", 0) + b"IEND" + iend_crc
        return sig + ihdr + idat + iend

    return _png_1x1(r, g, b)


def serve_frames(port):
    """HTTP server that cycles through coloured frames."""
    colours = [
        (255, 0, 0, "Red"),
        (0, 255, 0, "Green"),
        (0, 0, 255, "Blue"),
        (255, 255, 0, "Yellow"),
        (255, 0, 255, "Magenta"),
        (0, 255, 255, "Cyan"),
    ]
    frames = [(name, _make_jpeg(r, g, b)) for r, g, b, name in colours]

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((SERVE_HOST, port))
    srv.listen(5)
    print("Frame server listening on port", port)

    count = 0
    try:
        while True:
            client, addr = srv.accept()
            try:
                client.recv(1024)  # consume the HTTP request
                name, data = frames[count % len(frames)]
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
                    idx = (count // 10) % len(frames)
                    print("Served %d frames (current: %s)" % (count, frames[idx][0]))
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
