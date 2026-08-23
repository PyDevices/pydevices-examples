# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
console.py - a scrolling character terminal on any PyDevices display.

:class:`Console` turns a display driver into a fixed-cell text terminal with an
optional title bar and a three-field status bar.  It is a stream
(:class:`io.IOBase`), so on ports that provide ``os.dupterm`` the whole REPL can
be mirrored onto the display::

    import os
    from board_config import display_drv
    from console import Console

    console = Console(display_drv, title="REPL")
    os.dupterm(console)

``os.dupterm`` is the primary use case and exists on MicroPython (unix and most
MCU ports).  Everywhere else the same object is still a useful log/terminal
widget: call :meth:`Console.write`, pass it to ``print(..., file=console)``, or
hand it to anything that wants a text stream.

Requirements
------------

* ``pygraphics`` for glyph rendering.
* A display driver exposing ``width``, ``height``, ``fill_rect(x, y, w, h, c)``
  and ``blit_rect(buf, x, y, w, h)``.  Hardware vertical scrolling
  (``vscrdef`` / ``vscsad``) is used when the driver actually implements it and
  is emulated by repainting when it does not.

Nothing else is imported at module scope.  ``appdev`` and ``multimer`` are used
only to refresh dynamic status labels, both optionally: pass ``app=`` to borrow
an :class:`appdev.App` timer, or let the console stand up its own ``multimer``
timer when no app is available (as in a bare ``os.dupterm`` REPL session).

Colors
------

Colors are the sixteen ANSI indices, named on the class
(``Console.RED``, ``Console.BRIGHT_CYAN``, ...).  They are translated to the
display's native color depth once, at construction, into :attr:`Console.palette`.
Retint any entry in place::

    console.palette[Console.GREEN] = my_green   # native display color

Supported escape sequences
--------------------------

``CSI m`` (SGR 0/1/7/22/27/30-37/39/40-47/49/90-97/100-107), ``CSI A/B/C/D``
(cursor movement), ``CSI G`` / ``CSI H`` / ``CSI f`` (absolute positioning),
``CSI J`` (erase in display), ``CSI K`` (erase in line), ``CSI s`` / ``CSI u``
(save / restore cursor).  Anything else is parsed and discarded rather than
printed as garbage.  Escape sequences may be split across ``write()`` calls.
"""

import io
import sys

import pygraphics

# --- ANSI palette, as 24-bit RGB; converted to the display's depth at init ----
_RGB = (
    (0x00, 0x00, 0x00),  # 0  black
    (0xAA, 0x00, 0x00),  # 1  red
    (0x00, 0xAA, 0x00),  # 2  green
    (0xAA, 0x55, 0x00),  # 3  yellow / brown
    (0x00, 0x00, 0xAA),  # 4  blue
    (0xAA, 0x00, 0xAA),  # 5  magenta
    (0x00, 0xAA, 0xAA),  # 6  cyan
    (0xAA, 0xAA, 0xAA),  # 7  white
    (0x55, 0x55, 0x55),  # 8  bright black / grey
    (0xFF, 0x55, 0x55),  # 9  bright red
    (0x55, 0xFF, 0x55),  # 10 bright green
    (0xFF, 0xFF, 0x55),  # 11 bright yellow
    (0x55, 0x55, 0xFF),  # 12 bright blue
    (0xFF, 0x55, 0xFF),  # 13 bright magenta
    (0x55, 0xFF, 0xFF),  # 14 bright cyan
    (0xFF, 0xFF, 0xFF),  # 15 bright white
)

_FORMATS = {
    1: pygraphics.MONO_HMSB,
    2: pygraphics.GS2_HMSB,
    4: pygraphics.GS4_HMSB,
    8: pygraphics.GS8,
    16: pygraphics.RGB565,
    24: pygraphics.RGB888,
}

_BLANK = 0x20  # space
_BAR_FG = 0  # black text on...
_BAR_BG = 15  # ...a bright white bar


def _encode(rgb, depth):
    """Convert an ``(r, g, b)`` triple to a color of the given bit depth."""
    r, g, b = rgb
    if depth == 16:
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    if depth >= 24:
        return (r << 16) | (g << 8) | b
    if depth == 8:
        return (r & 0xE0) | ((g & 0xE0) >> 3) | (b >> 6)
    lum = (r * 77 + g * 151 + b * 28) >> 8
    if depth == 4:
        return lum >> 4
    if depth == 2:
        return lum >> 6
    return 1 if lum > 0x7F else 0


def _has_hw_scroll(display_drv):
    """True when ``display_drv`` really implements hardware vertical scrolling.

    ``displaydev.DisplayDriver`` defines ``vscrdef`` / ``vscsad`` as bookkeeping
    no-ops, so ``hasattr`` alone would claim scrolling on drivers that only
    inherit them (``fbdisplay``, for one).  Compare against the base class when
    it can be imported; assume the methods are real when it cannot.
    """
    if not (hasattr(display_drv, "vscrdef") and hasattr(display_drv, "vscsad")):
        return False
    try:
        from displaydev import DisplayDriver
    except ImportError:
        return True
    return getattr(type(display_drv), "vscsad", None) is not getattr(DisplayDriver, "vscsad", None)


def _default_reader():
    """Return the port's own stdin when ``os.dupterm`` would otherwise steal it.

    On the MicroPython unix and Windows ports ``os.dupterm`` routes *all*
    terminal input through the duplicated object, so a console with no reader
    leaves the REPL with no keyboard at all.  MCU ports keep polling their real
    console alongside dupterm objects, so there this fallback is off: reading
    stdin from inside the dupterm read path would recurse into it.
    """
    try:
        import os

        if not hasattr(os, "dupterm"):
            return None
    except ImportError:
        return None
    if sys.platform not in ("linux", "darwin", "win32"):
        return None
    return getattr(sys.stdin, "buffer", None)


class Console(io.IOBase):
    """A fixed-cell text terminal drawn on a display driver.

    Args:
        display_drv: Display with ``width``, ``height``, ``fill_rect`` and
            ``blit_rect``.
        font (int | tuple | pygraphics.Font): ``8``, ``14`` or ``16`` to select
            a built-in 8-pixel-wide romfont, a :class:`pygraphics.Font`, or a
            ``(width, height)`` cell size when ``char_writer`` does the drawing.
        fg (int): Default foreground color index (0-15).
        bg (int): Default background color index (0-15).
        title (str | callable): Title-bar text.  ``None`` (default) reserves no
            title bar; ``""`` reserves an empty one to fill in later.
        left (str | callable): Left status field; ``None`` reserves no field.
        middle (str | callable): Middle status field.
        right (str | callable): Right status field.
        app: Optional :class:`appdev.App`.  When given, callable labels are
            refreshed from its timer instead of a private one.
        refresh_ms (int): Period for refreshing callable labels.  ``0``
            disables the timer; call :meth:`refresh` yourself.
        reader: Object with ``read`` and/or ``readinto`` supplying input bytes
            for ``os.dupterm``.  ``None`` (default) falls back to the port's own
            stdin where ``os.dupterm`` would otherwise take it over; pass
            ``False`` for an output-only console.
        auto_show (bool): Call ``display_drv.show()`` after each write.
            Defaults to ``True`` when ``app`` is ``None`` (nothing else is
            refreshing the display) and ``False`` when an app owns refresh.
        char_writer (callable): Optional ``(char, x, y, fg, bg)`` glyph writer
            replacing the built-in one.  ``fg`` / ``bg`` are native display
            colors, and ``font`` must give the cell size.
        hw_scroll (bool): Force hardware (``True``) or repaint (``False``)
            scrolling.  ``None`` (default) auto-detects.

    Attributes:
        palette (list): The sixteen ANSI colors in the display's native format.
        cursor (bool): Whether to draw the underline cursor; takes effect on the
            next write.
    """

    # Label positions
    TITLE = 0
    LEFT = 1
    MIDDLE = 2
    RIGHT = 3

    # Color indices
    BLACK = 0
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7
    GREY = 8
    BRIGHT_RED = 9
    BRIGHT_GREEN = 10
    BRIGHT_YELLOW = 11
    BRIGHT_BLUE = 12
    BRIGHT_MAGENTA = 13
    BRIGHT_CYAN = 14
    BRIGHT_WHITE = 15

    def __init__(
        self,
        display_drv,
        *,
        font=8,
        fg=BRIGHT_WHITE,
        bg=BLACK,
        title=None,
        left=None,
        middle=None,
        right=None,
        app=None,
        refresh_ms=1000,
        reader=None,
        auto_show=None,
        char_writer=None,
        hw_scroll=None,
    ):
        for method in ("fill_rect", "blit_rect"):
            if not hasattr(display_drv, method):
                raise ValueError("display_drv needs a {}() method".format(method))

        self.display_drv = display_drv
        self._app = app
        self._refresh_ms = refresh_ms
        self._reader = _default_reader() if reader is None else (reader or None)
        self.cursor = True
        self._auto_show = (app is None) if auto_show is None else auto_show
        self._show = getattr(display_drv, "show", None)

        depth = getattr(display_drv, "color_depth", None) or getattr(display_drv, "bpp", 16)
        if depth not in _FORMATS:
            raise ValueError("unsupported color depth: {}".format(depth))
        self._depth = depth
        self.palette = [_encode(rgb, depth) for rgb in _RGB]

        self._default_fg = fg
        self._default_bg = bg
        self._fg = fg
        self._bg = bg
        self._bold = False
        self._reverse = False
        self._saved_pos = (0, 0)

        self._init_font(font, char_writer)

        self._labels = {}
        for pos, value in (
            (self.TITLE, title),
            (self.LEFT, left),
            (self.MIDDLE, middle),
            (self.RIGHT, right),
        ):
            if value is not None:
                self._labels[pos] = [value, _BAR_FG, _BAR_BG]

        self._hw = _has_hw_scroll(display_drv) if hw_scroll is None else hw_scroll
        self._timer = None
        self._subscription = None
        self._state = 0
        self._params = ""
        self._hidden = False

        self.show()

    # ------------------------------------------------------------- properties

    @property
    def rows(self):
        """Number of text lines in the scrolling area."""
        return self._rows

    @property
    def cols(self):
        """Number of characters per line."""
        return self._cols

    @property
    def cell_size(self):
        """``(width, height)`` of one character cell, in pixels."""
        return (self._cw, self._chh)

    @property
    def cursor_pos(self):
        """Cursor position as ``(row, col)``, zero-based."""
        return (self._row, self._col)

    # ------------------------------------------------------------------ setup

    def _init_font(self, font, char_writer):
        """Resolve cell metrics and the glyph-drawing strategy."""
        self._char_writer = char_writer
        if char_writer is not None:
            if not isinstance(font, tuple):
                raise ValueError("font must be a (width, height) cell size with a char_writer")
            self._cw, self._chh = font
            self._cell_buf = None
            self._cell_fb = None
            return

        if isinstance(font, int):
            if font not in (8, 14, 16):
                raise ValueError("built-in fonts are 8, 14 or 16 pixels tall")
            self._cw, self._chh = 8, font
            method = {8: "text8", 14: "text14", 16: "text16"}[font]

            def draw_glyph(fb, s, x, y, c):
                getattr(fb, method)(s, x, y, c)

            self._draw_glyph = draw_glyph
        else:  # a pygraphics.Font, whose text() already has this signature
            self._cw, self._chh = font.width, font.height
            self._draw_glyph = font.text

        self._cell_buf = memoryview(bytearray(self._cw * self._chh * self._depth // 8))
        self._cell_fb = pygraphics.FrameBuffer(
            self._cell_buf, self._cw, self._chh, _FORMATS[self._depth]
        )

    def _alloc_row_fb(self):
        """Allocate a full-width scratch row, used to repaint a line in one blit.

        Only worth it when scrolling is emulated (every scroll repaints the
        screen).  Falls back to per-cell blits if the allocation fails.
        """
        self._row_buf = None
        self._row_fb = None
        if self._hw or self._char_writer is not None:
            return
        try:
            width = self._cols * self._cw
            buf = memoryview(bytearray(width * self._chh * self._depth // 8))
            self._row_fb = pygraphics.FrameBuffer(buf, width, self._chh, _FORMATS[self._depth])
            self._row_buf = buf
        except MemoryError:
            self._row_buf = None
            self._row_fb = None

    def _layout(self):
        """Recompute the grid for the display's current size and bars."""
        self.width = self.display_drv.width
        self.height = self.display_drv.height
        ch = self._chh

        self._tfa = ch if self.TITLE in self._labels else 0
        bar = 0
        for pos in self._labels:
            if pos != self.TITLE:
                bar = ch
                break
        self._rows = max(1, (self.height - self._tfa - bar) // ch)
        self._vsa = self._rows * ch
        self._bfa = self.height - self._tfa - self._vsa
        self._cols = max(1, self.width // self._cw)

        size = self._cols * self._rows
        self._chars = bytearray(_BLANK for _ in range(size))
        self._attrs = bytearray(self._blank_attr for _ in range(size))
        self._origin = 0
        self._row = 0
        self._col = 0
        self._alloc_row_fb()

    # ----------------------------------------------------------- grid helpers

    @property
    def _blank_attr(self):
        return (self._default_bg << 4) | self._default_fg

    @property
    def _attr(self):
        """Current graphic rendition packed as ``bg << 4 | fg``."""
        fg = self._fg | 8 if self._bold else self._fg
        bg = self._bg
        if self._reverse:
            fg, bg = bg, fg
        return (bg << 4) | fg

    def _brow(self, row):
        """Buffer row backing screen row ``row``."""
        return (self._origin + row) % self._rows

    def _ypos(self, brow):
        """Top pixel of buffer row ``brow``."""
        return self._tfa + brow * self._chh

    def _put_glyph(self, code, x, y, fg, bg):
        """Draw one character cell at pixel ``(x, y)`` using color indices."""
        fg, bg = self.palette[fg], self.palette[bg]
        char = chr(code)
        if self._char_writer is not None:
            self._char_writer(char, x, y, fg, bg)
            return
        self._cell_fb.fill(bg)
        if code > _BLANK:
            self._draw_glyph(self._cell_fb, char, 0, 0, fg)
        self.display_drv.blit_rect(self._cell_buf, x, y, self._cw, self._chh)

    def _draw_cell(self, row, col):
        """Repaint one cell from the character buffer."""
        brow = self._brow(row)
        i = brow * self._cols + col
        attr = self._attrs[i]
        self._put_glyph(self._chars[i], col * self._cw, self._ypos(brow), attr & 0x0F, attr >> 4)

    def _draw_row(self, row):
        """Repaint a whole screen row, in one blit when a row buffer exists."""
        brow = self._brow(row)
        y = self._ypos(brow)
        base = brow * self._cols
        if self._row_fb is None:
            for col in range(self._cols):
                self._draw_cell(row, col)
            return
        for col in range(self._cols):
            attr = self._attrs[base + col]
            code = self._chars[base + col]
            x = col * self._cw
            self._row_fb.fill_rect(x, 0, self._cw, self._chh, self.palette[attr >> 4])
            if code > _BLANK:
                self._draw_glyph(self._row_fb, chr(code), x, 0, self.palette[attr & 0x0F])
        self.display_drv.blit_rect(self._row_buf, 0, y, self._cols * self._cw, self._chh)

    def _repaint(self):
        """Repaint the whole text area from the character buffer."""
        for row in range(self._rows):
            self._draw_row(row)

    def _blank_row(self, row):
        """Clear one screen row in the buffer and on the display."""
        base = self._brow(row) * self._cols
        blank = self._blank_attr
        for i in range(base, base + self._cols):
            self._chars[i] = _BLANK
            self._attrs[i] = blank
        self.display_drv.fill_rect(
            0, self._ypos(self._brow(row)), self.width, self._chh, self.palette[self._default_bg]
        )

    def _erase(self, row, first, last):
        """Blank cells ``first`` through ``last`` (inclusive) of a screen row."""
        if last < first:
            return
        brow = self._brow(row)
        base = brow * self._cols
        blank = self._blank_attr
        for i in range(base + first, base + last + 1):
            self._chars[i] = _BLANK
            self._attrs[i] = blank
        x = first * self._cw
        self.display_drv.fill_rect(
            x,
            self._ypos(brow),
            (last - first + 1) * self._cw,
            self._chh,
            self.palette[self._default_bg],
        )

    def _scroll_up(self):
        """Move the text area up one line, clearing the newly exposed row."""
        if self._hw:
            self._origin = (self._origin + 1) % self._rows
            self.display_drv.vscsad(self._tfa + self._origin * self._chh)
            self._blank_row(self._rows - 1)
            return
        cols = self._cols
        blank = self._blank_attr
        self._chars[:-cols] = self._chars[cols:]
        self._attrs[:-cols] = self._attrs[cols:]
        for i in range(len(self._chars) - cols, len(self._chars)):
            self._chars[i] = _BLANK
            self._attrs[i] = blank
        self._repaint()

    # --------------------------------------------------------------- lifecycle

    def show(self):
        """Lay out the console and paint it, preserving any existing text.

        Also call this after rotating or resizing the display.
        """
        self._hidden = False
        old = None
        if hasattr(self, "_chars"):
            old = (
                self._chars,
                self._attrs,
                self._cols,
                self._rows,
                self._origin,
                self._row,
                self._col,
            )
        self._layout()

        if self._hw:
            self.display_drv.vscrdef(self._tfa, self._vsa, self._bfa)
            self.display_drv.vscsad(self._tfa)
        self.display_drv.fill_rect(0, 0, self.width, self.height, self.palette[self._default_bg])

        if old is not None:
            self._restore(*old)
        self._repaint()
        for pos in self._labels:
            self._draw_label(pos)
        self._ensure_timer()
        self._draw_cursor(True)
        self._present()

    def _restore(self, chars, attrs, cols, rows, origin, row, col):
        """Copy text from a previous layout into the current one, bottom-aligned.

        Keeps the newest lines, which is what a terminal user cares about, and
        keeps the cursor the same distance from the bottom.
        """
        keep = min(rows, self._rows)
        width = min(cols, self._cols)
        for r in range(keep):
            src = ((origin + rows - keep + r) % rows) * cols
            dst = self._brow(self._rows - keep + r) * self._cols
            for c in range(width):
                self._chars[dst + c] = chars[src + c]
                self._attrs[dst + c] = attrs[src + c]
        from_bottom = min(rows - 1 - row, self._rows - 1)
        self._row = self._rows - 1 - from_bottom
        self._col = min(col, self._cols - 1)

    def hide(self):
        """Stop the label timer and blank the display so something else can use it."""
        self._hidden = True
        self._stop_timer()
        if self._hw:
            self.display_drv.vscsad(0)
        self.display_drv.fill_rect(0, 0, self.width, self.height, self.palette[self.BLACK])
        self._present()

    def cls(self):
        """Clear the text area and home the cursor."""
        blank = self._blank_attr
        for i in range(len(self._chars)):
            self._chars[i] = _BLANK
            self._attrs[i] = blank
        self._origin = 0
        self._row = 0
        self._col = 0
        if self._hw:
            self.display_drv.vscsad(self._tfa)
        self.display_drv.fill_rect(
            0, self._tfa, self.width, self._vsa, self.palette[self._default_bg]
        )
        self._draw_cursor(True)
        self._present()

    def deinit(self):
        """Release the label timer.  Safe to call more than once."""
        self._stop_timer()

    def _present(self):
        if self._auto_show and self._show is not None:
            self._show()

    # -------------------------------------------------------------- label bars

    def label(self, pos, value, fg=None, bg=None):
        """Set a title or status-bar field.

        Args:
            pos: :attr:`TITLE`, :attr:`LEFT`, :attr:`MIDDLE` or :attr:`RIGHT`.
            value: Text, or a zero-argument callable returning text.  A callable
                is re-evaluated every ``refresh_ms``.
            fg (int): Text color index; keeps the current one when ``None``.
            bg (int): Field background color index.

        Note:
            A bar that was not reserved at construction (its argument was
            ``None``) changes the layout, so the console re-lays itself out.
        """
        entry = self._labels.get(pos)
        new_bar = entry is None
        if entry is None:
            entry = [value, _BAR_FG, _BAR_BG]
            self._labels[pos] = entry
        entry[0] = value
        if fg is not None:
            entry[1] = fg
        if bg is not None:
            entry[2] = bg
        if new_bar:
            self.show()
        else:
            self._draw_label(pos)
            self._ensure_timer()
            self._present()

    def refresh(self):
        """Re-evaluate and redraw callable labels.

        Called automatically by the timer; call it yourself when
        ``refresh_ms=0`` or to force an immediate update.
        """
        for pos, entry in self._labels.items():
            if not isinstance(entry[0], str):
                self._draw_label(pos)
        self._present()

    def _label_span(self, pos):
        """Return ``(x, y, w, align)`` in pixels for a label field."""
        if pos == self.TITLE:
            return 0, 0, self.width, 0
        y = self._tfa + self._vsa
        third = self._cols // 3 * self._cw
        if pos == self.LEFT:
            return 0, y, third, -1
        if pos == self.MIDDLE:
            return third, y, third, 0
        return third * 2, y, self.width - third * 2, 1

    def _draw_label(self, pos):
        entry = self._labels.get(pos)
        if entry is None or self._hidden:
            return
        value, fg, bg = entry
        text = value if isinstance(value, str) else str(value())
        x, y, w, align = self._label_span(pos)

        self.display_drv.fill_rect(x, y, w, self._chh, self.palette[bg])
        cells = w // self._cw
        text = text[:cells]
        if align < 0:
            offset = 0
        elif align == 0:
            offset = (cells - len(text)) // 2
        else:
            offset = cells - len(text)
        x += offset * self._cw
        for i, char in enumerate(text):
            self._put_glyph(ord(char) & 0xFF, x + i * self._cw, y, fg, bg)

    # ------------------------------------------------------------------ timer

    def _ensure_timer(self):
        """Start a periodic refresh once a label is dynamic; no-op otherwise."""
        if self._timer is not None or self._subscription is not None:
            return
        if not self._refresh_ms:
            return
        if all(isinstance(entry[0], str) for entry in self._labels.values()):
            return
        if self._app is not None:
            self._subscription = self._app.every(self._refresh_ms, self._tick)
            return
        try:
            from multimer import auto as multimer
        except ImportError:
            return
        if not multimer.Timer:
            return
        self._timer = multimer.Timer(-1)
        self._timer.init(
            mode=multimer.Timer.PERIODIC, period=self._refresh_ms, callback=self._tick
        )

    def _stop_timer(self):
        if self._subscription is not None:
            self._subscription.cancel()
            self._subscription = None
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None

    def _tick(self, _timer=None):
        self.refresh()

    # ----------------------------------------------------------- stream input

    def readinto(self, buf, nbytes=0):
        """Read into ``buf`` for ``os.dupterm``.

        Returns:
            int: Bytes read, or ``None`` when no reader is attached or no input
            is available -- the "try again later" answer the stream protocol
            expects.  Returning ``0`` would look like end-of-file and make
            MicroPython drop the terminal.
        """
        reader = self._reader
        if reader is None:
            return None
        limit = nbytes or len(buf)
        into = getattr(reader, "readinto", None)
        if into is not None:
            return into(buf, limit) if nbytes else into(buf)
        data = reader.read(limit)
        if not data:
            return None
        n = min(len(buf), len(data))
        buf[:n] = data[:n]
        return n

    def read(self, nbytes=1):
        """Read up to ``nbytes`` bytes from the attached reader.

        This is the method ``os.dupterm`` calls for terminal input.  ``None``
        means "nothing yet"; ``b""`` would tell the port the terminal ended.
        """
        reader = self._reader
        if reader is None:
            return None
        direct = getattr(reader, "read", None)
        if direct is not None:
            return direct(nbytes if nbytes and nbytes > 0 else 1)
        buf = bytearray(nbytes if nbytes and nbytes > 0 else 1)
        n = self.readinto(buf, len(buf))
        if not n:
            return None
        return bytes(buf[:n])

    def ioctl(self, op, arg):
        """MicroPython stream control; forwards to the reader when it has one."""
        forward = getattr(self._reader, "ioctl", None)
        if forward is not None:
            return forward(op, arg)
        if op == 3:  # MP_STREAM_POLL
            return arg & 0x0004  # always writable, never readable
        return -1

    def readable(self):
        return self._reader is not None

    def writable(self):
        return True

    def flush(self):
        """Push pending output to the display (a no-op unless ``auto_show``)."""
        try:
            self._present()
        except Exception:
            pass  # interpreter teardown can call this after the display is gone

    # ---------------------------------------------------------- stream output

    def write(self, buf, fg=None, bg=None):
        """Write text or bytes to the console.

        Args:
            buf (bytes | bytearray | str): Data to display.  ``str`` is encoded
                as UTF-8; the font covers the first 256 code points.
            fg (int): Color index for this call only, leaving the stream's own
                SGR state untouched.
            bg (int): Background color index for this call only.

        Returns:
            int: Number of bytes consumed, as ``os.dupterm`` requires.
        """
        data = buf.encode() if isinstance(buf, str) else buf
        override = fg is not None or bg is not None
        if override:
            saved = (self._fg, self._bg, self._bold, self._reverse)
            if fg is not None:
                self._fg = fg
            if bg is not None:
                self._bg = bg
            self._bold = False
            self._reverse = False

        self._draw_cursor(False)
        for byte in data:
            self._feed(byte)
        self._draw_cursor(True)

        if override:
            self._fg, self._bg, self._bold, self._reverse = saved
        self._present()
        return len(data)

    def _feed(self, byte):
        """Push one byte through the escape-sequence state machine."""
        if self._state == 0:
            if byte == 0x1B:
                self._state = 1
            else:
                self._putc(byte)
        elif self._state == 1:
            if byte == 0x5B:  # '['
                self._state = 2
                self._params = ""
            else:  # a two-character sequence we do not implement
                self._state = 0
        elif 0x20 <= byte <= 0x3F:  # CSI parameter or intermediate byte
            if len(self._params) < 16:
                self._params += chr(byte)
        else:
            self._state = 0
            self._csi(chr(byte), self._params)

    def _putc(self, code):
        """Handle one non-escape byte."""
        if code == 0x0A:  # \n
            self._newline()
        elif code == 0x0D:  # \r
            self._col = 0
        elif code == 0x08:  # backspace: move left, leave the glyph alone
            if self._col:
                self._col -= 1
            elif self._row:
                self._row -= 1
                self._col = self._cols - 1
        elif code == 0x09:  # tab
            for _ in range(8 - (self._col % 8)):
                self._advance()
        elif code == 0x0C:  # form feed
            self.cls()
        elif code < 0x20 or code == 0x7F:
            pass  # bell and friends
        else:
            i = self._brow(self._row) * self._cols + self._col
            self._chars[i] = code
            self._attrs[i] = self._attr
            self._draw_cell(self._row, self._col)
            self._advance()

    def _advance(self):
        self._col += 1
        if self._col >= self._cols:
            self._newline()

    def _newline(self):
        self._col = 0
        if self._row + 1 >= self._rows:
            self._scroll_up()
        else:
            self._row += 1

    def _move(self, dcol, drow):
        self._col = min(self._cols - 1, max(0, self._col + dcol))
        self._row = min(self._rows - 1, max(0, self._row + drow))

    def _csi(self, final, params):
        """Act on a parsed ``CSI ... <final>`` sequence."""
        if params.startswith("?"):
            params = params[1:]
        nums = []
        for part in params.split(";"):
            try:
                nums.append(int(part))
            except ValueError:
                nums.append(0)
        n = nums[0]
        count = max(1, n)

        if final == "m":
            self._sgr(nums)
        elif final == "A":
            self._move(0, -count)
        elif final == "B":
            self._move(0, count)
        elif final == "C":
            self._move(count, 0)
        elif final == "D":
            self._move(-count, 0)
        elif final == "G":
            self._col = min(self._cols - 1, max(0, count - 1))
        elif final in ("H", "f"):
            self._row = min(self._rows - 1, max(0, count - 1))
            col = max(1, nums[1]) if len(nums) > 1 else 1
            self._col = min(self._cols - 1, col - 1)
        elif final == "J":
            self._erase_display(n)
        elif final == "K":
            self._erase_line(n)
        elif final == "s":
            self._saved_pos = (self._row, self._col)
        elif final == "u":
            self._row, self._col = self._saved_pos

    def _erase_line(self, mode):
        if mode == 1:
            self._erase(self._row, 0, self._col)
        elif mode == 2:
            self._erase(self._row, 0, self._cols - 1)
        else:
            self._erase(self._row, self._col, self._cols - 1)

    def _erase_display(self, mode):
        if mode == 0:
            self._erase(self._row, self._col, self._cols - 1)
            for row in range(self._row + 1, self._rows):
                self._blank_row(row)
        elif mode == 1:
            for row in range(self._row):
                self._blank_row(row)
            self._erase(self._row, 0, self._col)
        else:
            for row in range(self._rows):
                self._blank_row(row)

    def _sgr(self, nums):
        """Apply a Select Graphic Rendition sequence."""
        for value in nums:
            if value == 0:
                self._fg = self._default_fg
                self._bg = self._default_bg
                self._bold = False
                self._reverse = False
            elif value == 1:
                self._bold = True
            elif value == 22:
                self._bold = False
            elif value == 7:
                self._reverse = True
            elif value == 27:
                self._reverse = False
            elif 30 <= value <= 37:
                self._fg = value - 30
            elif value == 39:
                self._fg = self._default_fg
            elif 40 <= value <= 47:
                self._bg = value - 40
            elif value == 49:
                self._bg = self._default_bg
            elif 90 <= value <= 97:
                self._fg = value - 90 + 8
            elif 100 <= value <= 107:
                self._bg = value - 100 + 8

    def _draw_cursor(self, visible):
        """Draw or erase the underline cursor at the current cell."""
        if not self.cursor or self._hidden:
            return
        if not visible:
            self._draw_cell(self._row, self._col)
            return
        i = self._brow(self._row) * self._cols + self._col
        self.display_drv.fill_rect(
            self._col * self._cw,
            self._ypos(self._brow(self._row)) + self._chh - 2,
            self._cw,
            2,
            self.palette[self._attrs[i] & 0x0F],
        )
