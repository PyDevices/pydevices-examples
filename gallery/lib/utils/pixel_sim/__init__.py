"""
pixel_sim — desktop simulator for addressable-LED matrices (NeoPixel / DotStar).

Develop a pixeldisplay app without hardware.  ``PixelDisplay`` draws into a
``pygraphics.FrameBuffer`` (RGB888, one cell per LED); on ``show()`` that
framebuffer is scaled up and painted as an LED matrix onto the shared desktop /
PyScript / notebook display from the selected ``board_config.py``.

The board config for this simulator is just::

    from pixel_sim import display_drv, app

Poll ``app`` each frame (``app.poll()`` / ``app.quit_requested``) so
the desktop window stays closable — the simulator drives its own draw loop, so
nothing polls for you.

Grid size defaults to 64x16; override with ``PIXEL_SIM_WIDTH`` /
``PIXEL_SIM_HEIGHT`` (honored on CPython and MicroPython).
"""

import os

import board_config as _host

import appdev
from displaydev import color565, color_rgb
from displaydev.pixeldisplay import PixelDisplay
import pygraphics

_host_app = appdev.App(_host)


def _env_int(name, default):
    # MicroPython's ``os`` has no ``environ``; fall back to ``getenv``.
    env = getattr(os, "environ", None)
    value = env.get(name) if env is not None else None
    if value is None and hasattr(os, "getenv"):
        try:
            value = os.getenv(name)
        except Exception:
            value = None
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


PIXEL_WIDTH = _env_int("PIXEL_SIM_WIDTH", 64)
PIXEL_HEIGHT = _env_int("PIXEL_SIM_HEIGHT", 16)

# Reuse the standard scaled desktop/browser/notebook backend as the output surface.
# The host application wires its own optional periodic-refresh app; the simulator
# presents frames itself via PixelDisplay.show(), so stop that shared timer to
# avoid a redundant refresh loop (and its signal-based teardown on CPython).
# The app itself is kept (re-exported below) so apps can still poll it for
# window-close / quit events; poll() is independent of the timer.
_backend = _host.display_drv
if _host_app is not None and hasattr(_host_app, "stop_timer"):
    _host_app.stop_timer()


def _rgb888_from_565(c):
    r, g, b = color_rgb(c)
    return r, g, b


class SimPixelFramebuffer(pygraphics.FrameBuffer):
    """RGB888 grid framebuffer that renders scaled LED blocks to a desktop display.

    A drop-in for the ``pixel_buffer`` that :class:`PixelDisplay` wraps: it
    exposes ``width`` / ``height`` / ``rotation`` and a ``display()`` flush, but
    instead of pushing to a physical strip it paints each cell as a large square
    on ``backend`` (centered, square LEDs, dark gaps for a matrix look).

    ``display()`` builds the scaled LED panel in a scratch RGB565 buffer, then
    performs one ``blit_rect`` on the host backend.  Desktop backends (SDL/pygame)
    call ``render()`` after every ``fill_rect``; painting each LED with
    ``fill_rect`` was ~1024 full compositor passes per frame.
    """

    BOARD_COLOR = 0x0841  # near-black RGB565 "PCB" behind the LEDs

    def __init__(self, width, height, backend):
        self._backend = backend
        buf = bytearray(width * height * 3)
        super().__init__(buf, width, height, pygraphics.RGB888)
        self.rotation = 0
        self._block = max(1, min(backend.width // width, backend.height // height))
        self._gap = max(1, self._block // 8)
        self._ox = (backend.width - self._block * width) // 2
        self._oy = (backend.height - self._block * height) // 2
        self._panel_buf = None
        self._panel_fb = None

    def _panel_size(self):
        return self.width * self._block, self.height * self._block

    def _ensure_panel(self):
        pw, ph = self._panel_size()
        nbytes = pw * ph * 2
        if self._panel_buf is None or len(self._panel_buf) != nbytes:
            self._panel_buf = bytearray(nbytes)
            self._panel_fb = pygraphics.FrameBuffer(self._panel_buf, pw, ph, pygraphics.RGB565)
        return self._panel_fb, pw, ph

    def blit_rgb565_rect(self, buf, x, y, w, h):
        """Bulk RGB565 -> RGB888 copy into the LED grid (avoids per-pixel ``pixel()``)."""
        bpp = 2
        expected = w * h * bpp
        if len(buf) != expected:
            raise ValueError(
                f"The source buffer is not the correct size (got {len(buf)} bytes, expected {expected})"
            )
        src = memoryview(buf)
        dst = self.buffer
        stride = self.width
        for row in range(h):
            dst_row = (y + row) * stride
            src_row = row * w
            for col in range(w):
                src_off = (src_row + col) * bpp
                c = src[src_off] | (src[src_off + 1] << 8)
                r, g, b = _rgb888_from_565(c)
                dst_off = (dst_row + x + col) * 3
                dst[dst_off] = r
                dst[dst_off + 1] = g
                dst[dst_off + 2] = b
        return (x, y, w, h)

    def display(self):
        b = self._backend
        panel_fb, pw, ph = self._ensure_panel()
        panel = self._panel_buf
        panel_fb.fill(self.BOARD_COLOR)

        block = self._block
        gap = self._gap
        inner = block - 2 * gap
        src = self.buffer
        gw = self.width
        gh = self.height

        for y in range(gh):
            row_base = y * gw
            for x in range(gw):
                sidx = (row_base + x) * 3
                c565 = color565(src[sidx], src[sidx + 1], src[sidx + 2])
                lo = c565 & 0xFF
                hi = c565 >> 8
                px = x * block + gap
                py = y * block + gap
                for dy in range(inner):
                    row_off = (py + dy) * pw + px
                    off = row_off * 2
                    for dx in range(inner):
                        o = off + dx * 2
                        panel[o] = lo
                        panel[o + 1] = hi

        b.fill(self.BOARD_COLOR)
        b.blit_rect(panel, self._ox, self._oy, pw, ph)
        b.show()


class SimPixelDisplay(PixelDisplay):
    """PixelDisplay that uses fast bulk blits into :class:`SimPixelFramebuffer`."""

    def blit_rect(self, buf, x, y, w, h):
        inner = self._raw_buffer
        if hasattr(inner, "blit_rgb565_rect"):
            return inner.blit_rgb565_rect(buf, x, y, w, h)
        return super().blit_rect(buf, x, y, w, h)


_pixel_framebuf = SimPixelFramebuffer(PIXEL_WIDTH, PIXEL_HEIGHT, _backend)
display_drv = SimPixelDisplay(_pixel_framebuf)

# Host app coordinator for quit/window-close handling. Its refresh timer is stopped
# (see above); apps still call app.poll() each frame to stay closable.
app = _host_app
