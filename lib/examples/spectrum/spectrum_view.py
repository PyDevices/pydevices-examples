"""
spectrum_view.py -- draws a log-frequency spectrum analyzer with pygraphics.

``SpectrumView`` owns two RGB565 framebuffers the size of the screen: a static
background (gradient, grid, frequency labels) painted once, and the frame that
gets shown. Each frame it copies the background back over only the rows the
bars could have touched, blits the bars on top, and returns that row strip so
the caller can push just those rows to the panel.

A bar is one ``blit`` from a precomputed gradient column, so its cost does not
grow with its height. The reflection is a second, shorter column blitted under
the baseline, and the gaps of the segmented style are a colour key in the
column, so the grid shows through them.

Levels come in as 0..1 per band (0 = the floor, 1 = full scale); the view
applies the rise and fall ballistics and the peak-hold caps itself, so a
source only has to say how loud each band is right now.
"""

import math

from pygraphics import RGB565, Font, FrameBuffer

# Bottom-to-top colour stops of the bars: deep blue, blue, cyan, teal, violet.
PALETTE = (
    (0.00, (10, 24, 110)),
    (0.28, (0, 84, 220)),
    (0.52, (0, 180, 245)),
    (0.70, (30, 240, 225)),
    (0.86, (120, 150, 255)),
    (1.00, (200, 110, 255)),
)
BG_TOP = (1, 3, 10)  # background at the top of the plot
BG_BASE = (4, 10, 26)  # background at the baseline
BG_FLOOR = (2, 5, 14)  # under the baseline (reflection and labels)
GRID = (20, 36, 64)
GRID_MINOR = (13, 24, 46)
BASELINE = (30, 70, 120)
LABEL = (96, 136, 180)
LABEL_DECADE = (150, 205, 240)

LOW_HZ = 20.0
HIGH_HZ = 20000.0
LABELS = (50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)

ATTACK_S = 0.025  # rise time constant
FALL_PER_S = 1.6  # bars fall this much of full scale per second
PEAK_HOLD_S = 0.55  # peak caps hang this long before falling
PEAK_GRAVITY = 2.6  # then accelerate down at this (full scale per s^2)

KEY = 0x0020  # colour key for transparent gradient rows; never a drawn colour


def rgb565(rgb):
    r, g, b = rgb
    c = ((int(r) & 0xF8) << 8) | ((int(g) & 0xFC) << 3) | (int(b) >> 3)
    return c + 1 if c == KEY else c


def mix(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def palette_at(frac):
    if frac <= PALETTE[0][0]:
        return PALETTE[0][1]
    for i in range(1, len(PALETTE)):
        f1, c1 = PALETTE[i]
        if frac <= f1:
            f0, c0 = PALETTE[i - 1]
            return mix(c0, c1, (frac - f0) / (f1 - f0))
    return PALETTE[-1][1]


def band_count_for(plot_w):
    """About one band per 12-16 px, clamped to 16..48."""
    return max(16, min(48, plot_w // (12 if plot_w < 480 else 16)))


def label_text(hz):
    return "{}k".format(hz // 1000) if hz >= 1000 else str(hz)


def band_centres(n):
    """Centre frequency of each of ``n`` log-spaced bands between 20 Hz and 20 kHz."""
    span = HIGH_HZ / LOW_HZ
    return [LOW_HZ * span ** ((i + 0.5) / n) for i in range(n)]


class SpectrumView:
    def __init__(self, width, height, bands=None, style="smooth"):
        self.width = width
        self.height = height
        self.style = style
        self._buf = bytearray(width * height * 2)
        self._bgbuf = bytearray(width * height * 2)
        self.fb = FrameBuffer(self._buf, width, height, RGB565)
        self._bg = FrameBuffer(self._bgbuf, width, height, RGB565)
        self._mv = memoryview(self._buf)
        self._bgmv = memoryview(self._bgbuf)

        # Layout, all from the screen size.
        big = height >= 300
        self.font = Font(height=16 if big else 8)
        fh = self.font.height
        pad = max(3, min(width, height) // 40)
        side = max(pad, (3 * 8) // 2 + 2)  # room for a centred "20k" at the right edge
        plot_w = width - 2 * side
        n = bands or band_count_for(plot_w)
        pitch = plot_w // n
        self.bands = n
        self.pitch = pitch
        self.gap = max(1, pitch // 5)
        self.bar_w = pitch - self.gap
        self.x0 = side + (plot_w - n * pitch) // 2 + self.gap // 2
        self.span_x0 = self.x0 - self.gap // 2  # left edge of the band span
        self.span_w = n * pitch
        self.label_y = height - fh - max(2, pad // 2)
        free = self.label_y - pad - 3
        self.refl_h = max(4, free // 8)
        self.top = pad
        self.baseline = self.label_y - 3 - self.refl_h - 1  # first row below the bars
        self.plot_h = self.baseline - self.top
        self.refl_y = self.baseline + 1
        self.cap_h = max(2, self.plot_h // 120 + 1)
        self.hi_h = max(1, self.plot_h // 180)
        seg_pitch = max(4, self.plot_h // 44)
        self.seg_pitch = seg_pitch if style == "segmented" else 0

        self._paint_background()
        self._build_columns()

        # Ballistics state: bar level, peak level, peak hold timer, peak velocity.
        self.level = [0.0] * n
        self.peak = [0.0] * n
        self.hold = [0.0] * n
        self.pvel = [0.0] * n
        self._last_top = self.baseline
        self.fb.blit(self._bg, 0, 0)

    # --- static art -------------------------------------------------------

    def _bg_row_color(self, y):
        if y >= self.baseline:
            return BG_FLOOR
        t = (y - self.top) / max(1, self.plot_h)
        t = max(0.0, min(1.0, t))
        return mix(BG_TOP, BG_BASE, t * t)

    def _paint_background(self):
        bg = self._bg
        w = self.width
        # Vertical gradient, one hline per row (a one-off cost).
        for y in range(self.height):
            bg.hline(0, y, w, rgb565(self._bg_row_color(y)))
        x0, x1 = self.span_x0, self.span_x0 + self.span_w
        # Horizontal grid: quarters of full scale.
        for q in (1, 2, 3):
            y = self.baseline - (self.plot_h * q) // 4
            bg.hline(x0, y, x1 - x0, rgb565(GRID_MINOR if q != 2 else GRID))
        bg.hline(x0, self.top, x1 - x0, rgb565(GRID_MINOR))
        # Vertical grid and labels at the true log position of each frequency.
        fh = self.font.height
        for hz in LABELS:
            x = self.freq_x(hz)
            decade = hz in (100, 1000, 10000)
            if x < x1 - 1:
                bg.vline(x, self.top, self.plot_h, rgb565(GRID if decade else GRID_MINOR))
            s = label_text(hz)
            tw = self.font.text_width(s)
            tx = max(0, min(self.width - tw, x - tw // 2))
            self.font.text(bg, s, tx, self.label_y, rgb565(LABEL_DECADE if decade else LABEL))
            bg.vline(x, self.label_y - 3, 2, rgb565(LABEL))
        if fh >= 16:
            self.font.text(bg, "Hz", 2, self.label_y, rgb565(LABEL))
        bg.hline(x0, self.baseline, x1 - x0, rgb565(BASELINE))

    def freq_x(self, hz):
        u = math.log(hz / LOW_HZ) / math.log(HIGH_HZ / LOW_HZ)
        return self.span_x0 + int(u * self.span_w + 0.5)

    def _build_columns(self):
        bw, ph, rh = self.bar_w, self.plot_h, self.refl_h
        # Bar column: row 0 is the top of the plot.
        col = bytearray(bw * ph * 2)
        cfb = FrameBuffer(col, bw, ph, RGB565)
        self._hilite = [0] * ph
        self._capcol = [0] * ph
        sp = self.seg_pitch
        for r in range(ph):
            h = ph - r  # height of this row above the baseline, 1..ph
            c = palette_at(h / ph)
            gap = sp and (h % sp == 0)
            cfb.hline(0, r, bw, KEY if gap else rgb565(c))
            self._hilite[r] = rgb565(mix(c, (255, 255, 255), 0.45))
            self._capcol[r] = rgb565(mix(c, (235, 240, 255), 0.7))
        self._col = col
        # Reflection column: row 0 sits just under the baseline and mirrors the
        # bar's bottom row; it fades into the floor and skips every other line.
        rcol = bytearray(bw * rh * 2)
        rfb = FrameBuffer(rcol, bw, rh, RGB565)
        for i in range(rh):
            h = i + 1
            c = palette_at(h / ph)
            fade = 0.75 * (1 - i / rh) ** 1.2
            gap = (i & 1) or (sp and (h % sp == 0))
            rfb.hline(0, i, bw, KEY if gap else rgb565(mix(BG_FLOOR, c, fade)))
        self._rcol = rcol

    # --- per frame ----------------------------------------------------------

    def update(self, targets, dt):
        """Move the bars toward ``targets`` (0..1 per band) over ``dt`` seconds."""
        a = 1 - math.exp(-dt / ATTACK_S)
        fall = FALL_PER_S * dt
        level, peak, hold, pvel = self.level, self.peak, self.hold, self.pvel
        for i in range(self.bands):
            t = targets[i]
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            v = level[i]
            if t > v:
                v += (t - v) * a
            else:
                v = max(t, v - fall)
            level[i] = v
            if v >= peak[i]:
                peak[i] = v
                hold[i] = PEAK_HOLD_S
                pvel[i] = 0.0
            elif hold[i] > 0:
                hold[i] -= dt
            else:
                pvel[i] += PEAK_GRAVITY * dt
                peak[i] = max(v, peak[i] - pvel[i] * dt)

    def render(self):
        """Draw this frame; return ``(y, h)``, the row strip that changed."""
        fb = self.fb
        ph, bw, base = self.plot_h, self.bar_w, self.baseline
        cap_h, hi_h = self.cap_h, self.hi_h
        # The strip to redraw: from the highest thing on screen, this frame or
        # last, down to the bottom of the reflection.
        top = base
        for p in self.peak:
            y = base - int(p * ph) - cap_h - 1
            if y < top:
                top = y
        top = max(self.top, top)
        y0 = min(top, self._last_top)
        self._last_top = top
        y1 = self.refl_y + self.refl_h
        w2 = self.width * 2
        self._mv[y0 * w2 : y1 * w2] = self._bgmv[y0 * w2 : y1 * w2]

        col, rcol, rh = self._col, self._rcol, self.refl_h
        hilite, capcol = self._hilite, self._capcol
        x = self.x0
        pitch = self.pitch
        sp = self.seg_pitch
        for i in range(self.bands):
            h = int(self.level[i] * ph)
            if sp:
                h -= h % sp
            if h > 0:
                r = ph - h
                fb.blit((memoryview(col)[r * bw * 2 :], bw, h, RGB565), x, base - h, KEY)
                if not sp:
                    fb.fill_rect(x, base - h, bw, min(hi_h, h), hilite[r])
                rr = h if h < rh else rh
                fb.blit((rcol, bw, rr, RGB565), x, self.refl_y, KEY)
            ph_ = int(self.peak[i] * ph)
            if ph_ > 0:
                yc = base - ph_ - cap_h - 1
                if yc >= self.top:
                    fb.fill_rect(x, yc, bw, cap_h, capcol[ph - ph_])
            x += pitch
        return y0, y1 - y0

    def strip(self, y, h):
        """The bytes of rows ``y..y+h`` of the frame, for ``blit_rect``."""
        w2 = self.width * 2
        return self._mv[y * w2 : (y + h) * w2]
