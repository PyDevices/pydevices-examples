"""
make_captures.py -- regenerate the analyzer's screenshots (CPython + Pillow).

Runs ``capture.py`` under MicroPython to render raw RGB565 frames, then writes
PNG stills and an animated GIF into ``docs/screenshots/``::

    python make_captures.py [--micropython PATH] [--out DIR]

Needs Pillow; the PyDevices toolbox Python has it.
"""

import argparse
import os
import subprocess
import tempfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FPS = 30
LOOP_FRAMES = 8 * FPS  # fake_music loops every 8 s


def render(mp, w, h, frames, style, start):
    fd, raw = tempfile.mkstemp(suffix=".raw")
    os.close(fd)
    try:
        out = subprocess.run(
            [mp, "capture.py", str(w), str(h), str(frames), str(FPS), style, raw, str(start)],
            cwd=HERE,
            check=True,
            capture_output=True,
            text=True,
        )
        print(out.stdout.strip())
        with open(raw, "rb") as f:
            data = f.read()
    finally:
        os.remove(raw)
    size = w * h * 2
    return [to_image(data[i : i + size], w, h) for i in range(0, len(data), size)]


def to_image(buf, w, h):
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        c = buf[2 * i] | (buf[2 * i + 1] << 8)
        r, g, b = (c >> 11) & 0x1F, (c >> 5) & 0x3F, c & 0x1F
        rgb[3 * i] = (r << 3) | (r >> 2)
        rgb[3 * i + 1] = (g << 2) | (g >> 4)
        rgb[3 * i + 2] = (b << 3) | (b >> 2)
    return Image.frombytes("RGB", (w, h), bytes(rgb))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--micropython", default=os.path.expanduser("~/gh/pydevices/bin/micropython"))
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "screenshots"))
    ap.add_argument("--still-at", type=float, default=2.26, help="seconds into the loop")
    args = ap.parse_args()
    mp, out = args.micropython, args.out
    still = LOOP_FRAMES + int(args.still_at * FPS)

    # Stills: warm up one loop so the peak caps are in play, keep one frame.
    for w, h, style, name in (
        (800, 480, "smooth", "spectrum_800x480.png"),
        (320, 170, "smooth", "spectrum_320x170.png"),
        (800, 480, "segmented", "spectrum_800x480_segmented.png"),
    ):
        (img,) = render(mp, w, h, still + 1, style, still)
        img.save(os.path.join(out, name))
        print("wrote", name)

    # The loop: second pass through the 8 s loop, so it starts warm and wraps.
    frames = render(mp, 800, 480, 2 * LOOP_FRAMES, "smooth", LOOP_FRAMES)
    pal = frames[len(frames) // 3].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    path = os.path.join(out, "spectrum_800x480.gif")
    q[0].save(
        path, save_all=True, append_images=q[1:], duration=1000 // FPS, loop=0, optimize=False
    )
    print("wrote spectrum_800x480.gif,", len(q), "frames")


if __name__ == "__main__":
    main()
