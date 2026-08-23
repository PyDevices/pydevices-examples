#!/usr/bin/env python3
"""Generate RGB565 BMP assets for tower_climb.py (run once on CPython).

Temporary generator — remove after assets are approved.

From repo root::

  .venv/bin/python lib/examples/tower_climb/assets/gen_tower_assets.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "lib"))

from pygraphics._bmp565 import write_bmp565_file  # noqa: E402

OUT = Path(__file__).resolve().parent
REF_W = 320


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


TRANSPARENT = rgb565(255, 0, 255)


def rgb_to565(rgb):
    return rgb565(rgb[0], rgb[1], rgb[2])


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_rgb(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))


def mul_rgb(c, f):
    return tuple(max(0, min(255, int(c[i] * f))) for i in range(3))


def buf(w, h, fill=0):
    b = bytearray(w * h * 2)
    lo, hi = fill & 0xFF, fill >> 8
    for i in range(0, len(b), 2):
        b[i] = lo
        b[i + 1] = hi
    return b


def put_px(data, w, x, y, c):
    if 0 <= x < w and 0 <= y < len(data) // (2 * w):
        i = (y * w + x) * 2
        data[i] = c & 0xFF
        data[i + 1] = c >> 8


def put_rgb(data, w, x, y, rgb):
    put_px(data, w, x, y, rgb_to565(rgb))


def fill_rect(data, w, x, y, rw, rh, c):
    for j in range(y, y + rh):
        for i in range(x, x + rw):
            put_px(data, w, i, j, c)


def fill_rect_rgb(data, w, x, y, rw, rh, rgb):
    c = rgb_to565(rgb)
    fill_rect(data, w, x, y, rw, rh, c)


def circle(data, w, cx, cy, r, c, fill=False):
    for y in range(int(cy - r), int(cy + r + 1)):
        for x in range(int(cx - r), int(cx + r + 1)):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if fill and d2 <= r * r:
                put_px(data, w, x, y, c)
            elif not fill and abs(math.sqrt(max(d2, 0)) - r) < 1.1:
                put_px(data, w, x, y, c)


def ellipse_rgb(data, w, cx, cy, rx, ry, rgb, fill=True):
    c = rgb_to565(rgb)
    for y in range(int(cy - ry), int(cy + ry + 1)):
        for x in range(int(cx - rx), int(cx + rx + 1)):
            if ((x - cx) / max(rx, 0.001)) ** 2 + ((y - cy) / max(ry, 0.001)) ** 2 <= 1.0:
                if fill:
                    put_px(data, w, x, y, c)


def line(data, w, x0, y0, x1, y1, c):
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        put_px(data, w, x0, y0, c)
        if x0 == x1 and y0 == y1:
            break
        e2 = err * 2
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def line_rgb(data, w, x0, y0, x1, y1, rgb):
    line(data, w, x0, y0, x1, y1, rgb_to565(rgb))


def hash2(x, y):
    n = x * 374761393 + y * 668265263
    n = (n ^ (n >> 13)) * 1274126177
    return (n ^ (n >> 16)) & 255


def vgrad_rect_rgb(data, w, x, y, rw, rh, top_rgb, bot_rgb):
    for j in range(rh):
        t = j / max(rh - 1, 1)
        c = lerp_rgb(top_rgb, bot_rgb, t)
        for i in range(rw):
            put_rgb(data, w, x + i, y + j, c)


def hgrad_rect_rgb(data, w, x, y, rw, rh, left_rgb, right_rgb):
    for i in range(rw):
        t = i / max(rw - 1, 1)
        c = lerp_rgb(left_rgb, right_rgb, t)
        for j in range(rh):
            put_rgb(data, w, x + i, y + j, c)


def save(name, data, w, h):
    path = OUT / name
    with open(path, "wb") as f:
        write_bmp565_file(f, data, w, h)
    print(f"wrote {path} ({w}x{h})")


def gen_climber():
    # 4 frames x 3 poses (climb, jump, idle) @ 32x40
    fw, fh = 32, 40
    cols, rows = 4, 3
    w, h = fw * cols, fh * rows
    TRANSPARENT = rgb565(255, 0, 255)
    data = buf(w, h, TRANSPARENT)

    SKIN = (255, 214, 178)
    SKIN_SH = (214, 156, 118)
    COAT = (28, 78, 168)
    COAT_SH = (14, 36, 96)
    COAT_HI = (88, 148, 232)
    PANTS = (42, 34, 78)
    PANTS_SH = (24, 18, 44)
    BOOT = (34, 24, 22)
    BOOT_HI = (84, 62, 48)
    GLOVE = (220, 188, 148)
    HELMET = (232, 96, 36)
    HELMET_SH = (168, 52, 18)
    HELMET_HI = (255, 168, 84)
    MALLET_W = (118, 78, 38)
    MALLET_M = (196, 202, 214)
    MALLET_HI = (240, 244, 255)
    HAIR = (58, 34, 20)

    def draw_pixel_body(ox, oy, pose, frame):
        swing = (frame % 4) - 1.5

        # Legs / boots
        if pose == 1:
            leg_pairs = ((9, 30, 5, 8), (18, 28, 5, 8))
        elif pose == 0:
            leg_pairs = ((10 + int(swing), 28, 5, 10), (17 - int(swing), 30, 5, 8))
        else:
            leg_pairs = ((11, 28, 5, 10), (16, 28, 5, 10))
        for lx, ly, lw, lh in leg_pairs:
            fill_rect_rgb(data, w, ox + lx, oy + ly, lw, lh, PANTS)
            fill_rect_rgb(data, w, ox + lx, oy + ly + lh - 2, lw, 2, PANTS_SH)
            fill_rect_rgb(data, w, ox + lx - 1, oy + ly + lh, lw + 2, 4, BOOT)
            put_rgb(data, w, ox + lx, oy + ly + lh + 1, BOOT_HI)

        # Torso with shading
        fill_rect_rgb(data, w, ox + 9, oy + 14, 14, 15, COAT)
        vgrad_rect_rgb(data, w, ox + 9, oy + 14, 5, 15, COAT_HI, COAT)
        fill_rect_rgb(data, w, ox + 20, oy + 14, 3, 15, COAT_SH)
        fill_rect_rgb(data, w, ox + 11, oy + 18, 10, 2, COAT_SH)
        fill_rect_rgb(data, w, ox + 10, oy + 15, 8, 3, COAT_HI)
        # Zip / harness
        line_rgb(data, w, ox + 15, oy + 15, ox + 15, oy + 27, (220, 220, 230))
        fill_rect_rgb(data, w, ox + 13, oy + 22, 6, 2, (255, 196, 40))

        # Head
        ellipse_rgb(data, w, ox + 16, oy + 11, 7, 8, SKIN)
        ellipse_rgb(data, w, ox + 15, oy + 12, 6, 7, SKIN_SH)
        ellipse_rgb(data, w, ox + 16, oy + 10, 7, 8, SKIN)
        # Helmet
        ellipse_rgb(data, w, ox + 16, oy + 7, 9, 6, HELMET)
        fill_rect_rgb(data, w, ox + 8, oy + 5, 16, 4, HELMET)
        fill_rect_rgb(data, w, ox + 10, oy + 4, 12, 2, HELMET_HI)
        fill_rect_rgb(data, w, ox + 8, oy + 8, 3, 2, HELMET_SH)
        # Face
        put_rgb(data, w, ox + 13, oy + 11, (28, 24, 36))
        put_rgb(data, w, ox + 19, oy + 11, (28, 24, 36))
        put_rgb(data, w, ox + 14, oy + 14, (196, 96, 84))
        put_rgb(data, w, ox + 12, oy + 9, HAIR)
        put_rgb(data, w, ox + 20, oy + 9, HAIR)
        # Headlamp
        circle(data, w, ox + 22, oy + 7, 2, rgb_to565((255, 244, 180)), True)
        put_rgb(data, w, ox + 22, oy + 7, (255, 255, 220))

        # Arms + mallet per pose
        if pose == 0:
            fill_rect_rgb(data, w, ox + 4 + int(swing), oy + 13, 5, 11, COAT)
            fill_rect_rgb(data, w, ox + 23 - int(swing), oy + 15, 5, 10, COAT)
            fill_rect_rgb(data, w, ox + 3 + int(swing), oy + 22, 4, 4, GLOVE)
            fill_rect_rgb(data, w, ox + 24 - int(swing), oy + 23, 4, 4, GLOVE)
            fill_rect_rgb(data, w, ox + 1, oy + 7, 16, 4, MALLET_W)
            fill_rect_rgb(data, w, ox + 14, oy + 5, 10, 8, MALLET_M)
            fill_rect_rgb(data, w, ox + 16, oy + 6, 6, 4, MALLET_HI)
        elif pose == 1:
            fill_rect_rgb(data, w, ox + 5, oy + 12, 5, 9, COAT)
            fill_rect_rgb(data, w, ox + 22, oy + 10, 5, 9, COAT)
            fill_rect_rgb(data, w, ox + 4, oy + 19, 4, 4, GLOVE)
            fill_rect_rgb(data, w, ox + 24, oy + 17, 4, 4, GLOVE)
            fill_rect_rgb(data, w, ox + 20, oy + 4, 10, 5, MALLET_W)
            fill_rect_rgb(data, w, ox + 24, oy + 2, 7, 7, MALLET_M)
        else:
            fill_rect_rgb(data, w, ox + 6, oy + 16, 5, 10, COAT)
            fill_rect_rgb(data, w, ox + 21, oy + 15, 5, 10, COAT)
            fill_rect_rgb(data, w, ox + 5, oy + 24, 4, 4, GLOVE)
            fill_rect_rgb(data, w, ox + 23, oy + 23, 4, 4, GLOVE)
            fill_rect_rgb(data, w, ox + 22, oy + 5, 12, 4, MALLET_W)
            fill_rect_rgb(data, w, ox + 28, oy + 3, 8, 8, MALLET_M)
            fill_rect_rgb(data, w, ox + 30, oy + 4, 4, 4, MALLET_HI)

    for fr in range(cols):
        draw_pixel_body(fr * fw, 0, 0, fr)
        draw_pixel_body(fr * fw, fh, 1, fr)
        draw_pixel_body(fr * fw, fh * 2, 2, fr)

    save("climber.bmp", data, w, h)


def _bark_tile(data, w, ox, oy, tw):
    base = (84, 50, 26)
    dark = (42, 24, 12)
    lite = (138, 92, 48)
    moss = (48, 98, 36)
    for j in range(tw):
        for i in range(tw):
            u = i / tw
            v = j / tw
            groove = math.sin(v * math.pi * 3.2 + u * 1.4) * 0.5 + 0.5
            edge = min(u, 1 - u) * 2.0
            c = lerp_rgb(dark, base, 0.35 + groove * 0.45)
            c = lerp_rgb(c, lite, edge * 0.35)
            if hash2(ox + i, oy + j) % 17 == 0:
                c = lerp_rgb(c, moss, 0.55)
            if hash2(ox + i * 3, oy + j * 5) % 29 == 0:
                c = mul_rgb(c, 0.72)
            put_rgb(data, w, ox + i, oy + j, c)
    line_rgb(data, w, ox + 3, oy, ox + 3, oy + tw - 1, mul_rgb(dark, 0.8))
    line_rgb(data, w, ox + 11, oy, ox + 11, oy + tw - 1, mul_rgb(lite, 1.05))


def _branch_tile(data, w, ox, oy, tw, facing):
    wood = (92, 58, 30)
    wood_sh = (52, 32, 16)
    wood_hi = (148, 102, 56)
    bark_rim = (66, 40, 20)
    leaf_d = (18, 96, 34)
    leaf = (42, 142, 52)
    leaf_hi = (98, 198, 72)
    cy = oy + 10
    for j in range(tw):
        for i in range(tw):
            x = i if facing > 0 else tw - 1 - i
            t = x / max(tw - 1, 1)
            dist = abs(j - (10 + math.sin(t * math.pi) * 1.5))
            thick = 5.5 - t * 1.8
            if dist <= thick:
                c = lerp_rgb(wood_sh, wood, 1.0 - t * 0.35)
                if j < 10:
                    c = lerp_rgb(c, wood_hi, 0.45)
                if dist > thick - 1.2:
                    c = mul_rgb(c, 0.75)
                put_rgb(data, w, ox + i, oy + j, c)
            elif j < 9 and ((facing > 0 and i < tw - 5) or (facing < 0 and i > 4)):
                if hash2(i, j) % 5 != 0:
                    put_rgb(data, w, ox + i, oy + j, bark_rim)
    # Small twigs + leaf clusters
    tips = [(3, 5), (7, 3), (11, 6)] if facing > 0 else [(12, 5), (8, 3), (4, 6)]
    for tx, ty in tips:
        px = ox + (tx if facing > 0 else tw - 1 - tx)
        py = oy + ty
        line_rgb(data, w, px, py + 6, px + facing * 2, py, wood_sh)
        ellipse_rgb(data, w, px + facing, py - 1, 3, 2, leaf)
        put_rgb(data, w, px, py, leaf_hi)
    fill_rect_rgb(data, w, ox, oy + 13, tw, 2, mul_rgb(wood_sh, 0.7))


def _ice_tile(data, w, ox, oy, tw):
    deep = (58, 138, 210)
    mid = (136, 206, 246)
    hi = (214, 242, 255)
    for j in range(tw):
        for i in range(tw):
            t = (i + j) / (tw * 2 - 2)
            facet = int(hash2(i * 2, j * 3) % 3)
            c = lerp_rgb(deep, mid, t)
            if facet == 0:
                c = lerp_rgb(c, hi, 0.35)
            if i == j or i + j == tw - 1:
                c = lerp_rgb(c, hi, 0.55)
            put_rgb(data, w, ox + i, oy + j, c)
    line_rgb(data, w, ox + 2, oy + 2, ox + tw - 3, oy + 4, hi)
    put_rgb(data, w, ox + 4, oy + 3, (255, 255, 255))


def _clear_tile(data, w, ox, oy, tw, fill=0):
    fill_rect(data, w, ox, oy, tw, tw, fill)


def _clear_tile_transparent(data, w, ox, oy, tw):
    _clear_tile(data, w, ox, oy, tw, TRANSPARENT)


def _leaf_tile(data, w, ox, oy, tw):
    _clear_tile_transparent(data, w, ox, oy, tw)
    branch = (78, 48, 24)
    for i in range(tw):
        line_rgb(data, w, ox + i, oy + 11, ox + i, oy + 13, branch)
    clusters = [(2, 6, 4, 3), (6, 4, 5, 4), (10, 7, 4, 3), (4, 8, 3, 2)]
    for cx, cy, rx, ry in clusters:
        for j in range(-ry, ry + 1):
            for i in range(-rx, rx + 1):
                if (i / max(rx, 1)) ** 2 + (j / max(ry, 1)) ** 2 <= 1.0:
                    c = (28 + hash2(cx + i, cy + j) % 24, 120 + hash2(cx, cy) % 40, 38)
                    if i < 0:
                        c = mul_rgb(c, 0.82)
                    else:
                        c = lerp_rgb(c, (110, 210, 78), 0.35)
                    put_rgb(data, w, ox + cx + i, oy + cy + j, c)


def _gem_tile(data, w, ox, oy, tw):
    _clear_tile_transparent(data, w, ox, oy, tw)
    core = (228, 28, 148)
    hi = (255, 188, 236)
    shaft = (255, 244, 180)
    pts = [(8, 2), (12, 6), (10, 14), (6, 14), (4, 6)]
    for y in range(tw):
        for x in range(tw):
            if 5 <= x <= 10 and 4 <= y <= 13:
                t = (y - 4) / 9
                c = lerp_rgb(hi, core, t)
                if x < 7:
                    c = lerp_rgb(c, hi, 0.4)
                put_rgb(data, w, ox + x, oy + y, c)
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        line_rgb(data, w, ox + x0, oy + y0, ox + x1, oy + y1, hi)
    line_rgb(data, w, ox + 8, oy, ox + 8, oy + 15, shaft)


def _spike_tile(data, w, ox, oy, tw):
    _clear_tile_transparent(data, w, ox, oy, tw)
    metal = (168, 172, 184)
    rust = (156, 84, 36)
    shadow = (68, 70, 78)
    fill_rect_rgb(data, w, ox, oy + 12, tw, 3, shadow)
    for i in range(4):
        bx = ox + 2 + i * 3
        line_rgb(data, w, bx, oy + 12, bx + 1, oy + 3, metal)
        line_rgb(data, w, bx + 1, oy + 12, bx + 2, oy + 1, rust)
        put_rgb(data, w, bx + 1, oy + 2, (240, 244, 255))


def _cloud_tile(data, w, ox, oy, tw):
    _clear_tile_transparent(data, w, ox, oy, tw)
    base = (228, 236, 248)
    hi = (255, 255, 255)
    sh = (184, 200, 224)
    blobs = [(5, 10, 4, 3), (10, 8, 5, 4), (14, 11, 3, 2)]
    for j in range(tw):
        for i in range(tw):
            c = None
            for cx, cy, rx, ry in blobs:
                if ((i - cx) / max(rx, 1)) ** 2 + ((j - cy) / max(ry, 1)) ** 2 <= 1.0:
                    c = lerp_rgb(sh, base, 0.5 + i / tw * 0.4)
                    if j < cy:
                        c = lerp_rgb(c, hi, 0.55)
            if c:
                put_rgb(data, w, ox + i, oy + j, c)


def gen_tiles():
    tw = 16
    cols, rows = 8, 4
    w, h = tw * cols, tw * rows
    data = buf(w, h, 0)

    drawers = [
        lambda ox, oy: _bark_tile(data, w, ox, oy, tw),
        lambda ox, oy: _branch_tile(data, w, ox, oy, tw, 1),
        lambda ox, oy: _branch_tile(data, w, ox, oy, tw, -1),
        lambda ox, oy: _ice_tile(data, w, ox, oy, tw),
        lambda ox, oy: _leaf_tile(data, w, ox, oy, tw),
        lambda ox, oy: _gem_tile(data, w, ox, oy, tw),
        lambda ox, oy: _spike_tile(data, w, ox, oy, tw),
        lambda ox, oy: _cloud_tile(data, w, ox, oy, tw),
    ]

    for idx, draw in enumerate(drawers):
        ox = (idx % cols) * tw
        oy = (idx // cols) * tw
        draw(ox, oy)

    save("tower_tiles.bmp", data, w, h)


def gen_background():
    w = REF_W
    screens = 10
    h = 480 * screens
    sky_bot = (10, 16, 48)
    sky_mid = (36, 92, 168)
    sky_top = (148, 208, 248)
    data = buf(w, h, rgb_to565(sky_bot))

    for y in range(h):
        t = y / max(h - 1, 1)
        if t < 0.55:
            c = lerp_rgb(sky_bot, sky_mid, t / 0.55)
        else:
            c = lerp_rgb(sky_mid, sky_top, (t - 0.55) / 0.45)
        fill_rect_rgb(data, w, 0, y, w, 1, c)

    # Distant forest silhouettes (parallax layers)
    for layer, alpha in enumerate((0.35, 0.55, 0.8)):
        scroll = layer * 40
        for n in range(18 - layer * 4):
            base_x = (n * (74 - layer * 8) + scroll) % (w + 80) - 40
            base_y = h - 140 - layer * 90 - (n * 131) % (h // 2)
            th = 90 + (n * 29 + layer * 17) % 110
            canopy = (10 + layer * 8, 48 + layer * 18, 24 + layer * 6)
            trunk_c = (24 + layer * 6, 18 + layer * 4, 12)
            tw = 7 + layer * 2
            for y in range(th):
                t = y / max(th - 1, 1)
                width_at = int(tw + (1.0 - t) * (14 + layer * 4))
                x0 = base_x - width_at // 2
                if 0 <= base_y + y < h:
                    fill_rect_rgb(data, w, x0, base_y + y, max(2, width_at), 1, trunk_c)
                if t < 0.42:
                    rad = int((0.42 - t) * (28 + layer * 6))
                    ellipse_rgb(data, w, base_x, base_y + y, rad, max(4, rad // 2), canopy)

    # Atmospheric haze bands
    for n in range(12):
        hy = (n * 401) % h
        alpha = 0.08 + (n % 3) * 0.04
        band = lerp_rgb(sky_mid, (220, 236, 248), alpha)
        fill_rect_rgb(data, w, 0, hy, w, 6 + n % 4, band)

    # Sun glow near canopy altitude
    sun_y = int(h * 0.08)
    sun_x = w // 2 + 40
    for r in range(52, 0, -2):
        t = r / 52
        c = lerp_rgb((255, 236, 140), sky_top, t * 0.85)
        circle(data, w, sun_x, sun_y, r, rgb_to565(c), True)

    # Stars in upper sky
    for n in range(180):
        sy = (n * 97) % int(h * 0.35)
        sx = (n * 43) % w
        b = 180 + hash2(n, sx) % 75
        put_rgb(data, w, sx, sy, (b, b, min(255, b + 20)))
        if hash2(n, sy) % 9 == 0:
            put_rgb(data, w, sx + 1, sy, (255, 255, 220))

    # Layered cumulus clouds
    for n in range(42):
        cy = (n * 151) % h
        cx = (n * 89) % (w - 80)
        scale = 0.7 + (n % 5) * 0.15
        for blob in range(4):
            bx = cx + blob * int(16 * scale)
            by = cy + int(math.sin(blob + n) * 4)
            br = int((10 + blob * 3) * scale)
            c = (232, 240, 252) if blob % 2 == 0 else (248, 252, 255)
            circle(data, w, bx, by, br, rgb_to565(c), True)

    # Soft central tree mass (parallax, not gameplay trunk)
    for y in range(h):
        t = y / max(h - 1, 1)
        wave = int(math.sin(y / 36.0) * 5 + math.sin(y / 17.0) * 2)
        cx = w // 2 + wave
        radius = int(28 + t * 18)
        for dx in range(-radius, radius + 1):
            dist = abs(dx) / max(radius, 1)
            if dist <= 1.0:
                c = lerp_rgb((18, 58, 24), (8, 24, 12), dist)
                if y % 37 < 3:
                    c = lerp_rgb(c, (48, 96, 32), 0.35)
                put_rgb(data, w, cx + dx, y, c)

    save("tower_bg.bmp", data, w, h)


def main():
    gen_climber()
    gen_tiles()
    gen_background()
    print("done")


if __name__ == "__main__":
    main()
