#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Generate the simulator's sample photos (CPython + Pillow only).

Six procedural "landscape" scenes, each written as baseline JPEGs at the
sizes ``gphotos_sim.GPhotosSimEngine.asset_path`` looks for:

* ``sim_NN_64.jpg`` / ``sim_NN_96.jpg`` — square list tiles (Google ``-c`` crop)
* ``sim_NN_320x240.jpg`` / ``sim_NN_160x120.jpg`` — landscape scenes (odd NN)
* ``sim_NN_240x320.jpg`` / ``sim_NN_120x160.jpg`` — portrait scenes (even NN)

Run from the repo root::

    .venv/bin/python lib/examples/google_photos/assets/gen_sim_assets.py

Baseline (non-progressive) JPEG is required: TJpgDec cannot decode
progressive files.
"""

import math
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    raise SystemExit("Pillow is required: .venv/bin/pip install pillow")

HERE = os.path.dirname(os.path.abspath(__file__))

# (sky top, sky bottom, hills, sun, water) per scene
_PALETTES = [
    ((0x1E, 0x3A, 0x8A), (0xF9, 0x73, 0x16), (0x14, 0x53, 0x2D), (0xFD, 0xE0, 0x47), (0x0E, 0x74, 0x90)),
    ((0x0F, 0x17, 0x2A), (0x7C, 0x3A, 0xED), (0x1F, 0x29, 0x37), (0xF4, 0xF4, 0xF5), (0x31, 0x2E, 0x81)),
    ((0x38, 0xBD, 0xF8), (0xE0, 0xF2, 0xFE), (0x16, 0xA3, 0x4A), (0xFA, 0xCC, 0x15), (0x06, 0x92, 0xB4)),
    ((0x7F, 0x1D, 0x1D), (0xFB, 0xBF, 0x24), (0x45, 0x1A, 0x03), (0xFE, 0xF3, 0xC7), (0x9A, 0x34, 0x12)),
    ((0x0C, 0x4A, 0x6E), (0x67, 0xE8, 0xF9), (0x0F, 0x76, 0x6E), (0xFF, 0xFF, 0xFF), (0x15, 0x5E, 0x75)),
    ((0x3B, 0x07, 0x64), (0xEC, 0x48, 0x99), (0x2E, 0x10, 0x65), (0xFB, 0x71, 0x85), (0x6B, 0x21, 0xA8)),
]


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def scene(width, height, palette, seed):
    """Sky gradient, sun, rolling hills, and a reflective water band."""
    sky_top, sky_bot, hills, sun, water = palette
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    horizon = int(height * 0.62)
    for y in range(horizon):
        draw.line([(0, y), (width, y)], fill=_lerp(sky_top, sky_bot, y / max(1, horizon - 1)))
    # water below the horizon (darker toward the bottom)
    for y in range(horizon, height):
        t = (y - horizon) / max(1, height - horizon - 1)
        draw.line([(0, y), (width, y)], fill=_lerp(water, _lerp(water, (0, 0, 0), 0.55), t))
    # sun
    r = max(6, min(width, height) // 7)
    cx = int(width * (0.25 + 0.5 * ((seed * 0.37) % 1.0)))
    cy = int(horizon * 0.55)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=sun)
    # hills: two layered sine ridges
    for layer, (amp, freq, shade) in enumerate(((0.10, 1.7, 0.85), (0.16, 0.9, 1.0))):
        pts = []
        for x in range(width + 1):
            y = horizon - int(height * amp * (0.5 + 0.5 * math.sin(freq * x / width * math.pi * 2 + seed + layer)))
            pts.append((x, y))
        pts += [(width, horizon), (0, horizon)]
        draw.polygon(pts, fill=_lerp((0, 0, 0), hills, shade))
    # sun reflection stripes
    for i in range(0, height - horizon, max(3, height // 40)):
        y = horizon + i
        w = max(2, int(r * (1.0 - i / max(1, height - horizon)) * 1.5))
        draw.line([(cx - w, y), (cx + w, y)], fill=_lerp(sun, water, 0.35))
    return img


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else HERE
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for n, palette in enumerate(_PALETTES, start=1):
        portrait = n % 2 == 0
        big = (240, 320) if portrait else (320, 240)
        small = (120, 160) if portrait else (160, 120)
        base = scene(big[0], big[1], palette, seed=n * 1.3)
        variants = {
            "%dx%d" % big: base,
            "%dx%d" % small: base.resize(small, Image.LANCZOS),
        }
        # Square tiles: center crop like Google's ``-c`` parameter.
        side = min(big)
        left = (big[0] - side) // 2
        top = (big[1] - side) // 2
        square = base.crop((left, top, left + side, top + side))
        variants["96"] = square.resize((96, 96), Image.LANCZOS)
        variants["64"] = square.resize((64, 64), Image.LANCZOS)
        for tag, im in variants.items():
            path = os.path.join(out_dir, "sim_%02d_%s.jpg" % (n, tag))
            im.save(path, "JPEG", quality=82, optimize=False, progressive=False, subsampling=0)
            written.append(path)
    total = sum(os.path.getsize(p) for p in written)
    print("wrote %d files (%.1f KiB) to %s" % (len(written), total / 1024.0, out_dir))


if __name__ == "__main__":
    main()
