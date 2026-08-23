# SPDX-FileCopyrightText: 2020 Peter Hinch, 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT

"""
`displaybuf`
====================================================

FrameBuffer wrapper for using framebuf based GUIs with displaydev.
Works with MicroPython Nano-GUI, Micro-GUI and MicroPython-Touch from Peter Hinch,
but may also be used without them.

Usage:
    'color_setup.py'
        from displaybuf import DisplayBuffer as SSD
        from board_config import display_drv

        format = SSD.RGB565  # or .GS8 or .GS4_HMSB

        ssd = SSD(display_drv, format)

    'main.py'
        from color_setup import ssd
        <your code here>
"""

import gc
import sys

from displaydev import alloc_buffer, color332, color565, color565_swapped
import pygraphics

_has_viper_tools = False
if sys.implementation.name == "micropython":
    try:
        from viper_tools import _bounce4, _bounce8

        _has_viper_tools = True
    except Exception:
        pass

if not _has_viper_tools:

    def _bounce8(*args, **kwargs):
        raise NotImplementedError(
            ".GS8 and .GS4_HMSB DisplayBuffer formats are only implemented in viper_tools.py for MicroPython."
        )

    _bounce4 = _bounce8


gc.collect()


_display_drv_get_attrs = {
    "set_vscroll",
    "tfa",
    "bfa",
    "vsa",
    "vscroll",
    "translate_point",
    "blit_rect",
}
_display_drv_set_attrs = {"vscroll"}


class DisplayBuffer(pygraphics.FrameBuffer):
    """
    Wrap a displaydev driver with a framebuf-compatible logical framebuffer.

    Call ``show()`` to copy the buffer to the physical display. Supported formats:
    ``DisplayBuffer.RGB565``, ``DisplayBuffer.GS8``, ``DisplayBuffer.GS4_HMSB``.
    """

    rgb = None  # Function to convert r, g, b to a color value; used by Nano-GUI and Micro-GUI.
    colors_registered = 0  # For .color().  Not used in Nano-GUI or Micro-GUI.

    RGB565 = pygraphics.RGB565
    GS8 = pygraphics.GS8
    GS4_HMSB = pygraphics.GS4_HMSB

    def __init__(self, display_drv, format=pygraphics.RGB565, stride=8):
        """
        Allocate a logical framebuffer backed by ``display_drv``.

        Args:
            display_drv: A displaydev driver (BusDisplay, SDLDisplay, etc.).
            format: One of ``RGB565``, ``GS8``, or ``GS4_HMSB``.
            stride: Lines per chunk for GS8/GS4 bounce buffers (MicroPython viper).

        Attributes:
            show: Bound to ``_show16``, ``_show8``, or ``_show4`` — call to flush buffer to panel.
        """
        gc.collect()
        self.display_drv = display_drv
        self.vscrdef = display_drv.vscrdef
        self.vscsad = display_drv.vscsad
        height = display_drv.height
        width = display_drv.width
        BPP = display_drv.color_depth // 8
        self.palette = BoolPalette(
            format
        )  # a 2-value color palette for rendering monochrome glyphs
        # with ssd.blit(glyph_buf, x, y, key=-1, palette=ssd.palette)

        # If byte swapping is required and the display bus is capable of having byte swapping disabled,
        # disable it and set a flag so we can swap the color bytes as they are created.
        if self.display_drv.requires_byteswap:
            # self.display_drv.disable_auto_byteswap(True) returns True if it was successful, False if not.
            self.needs_swap = self.display_drv.disable_auto_byteswap(True)
        else:
            self.needs_swap = False

        # Set the DisplayBuffer.rgb function to the appropriate one for the format and byte swapping
        if format == DisplayBuffer.GS8:
            DisplayBuffer.rgb = color332
        else:
            if self.needs_swap:
                DisplayBuffer.rgb = color565_swapped
            else:
                DisplayBuffer.rgb = color565

        # Set the show function to the appropriate one for the format and
        # allocate the buffer.  Also create the line buffer and lut if needed.
        gc.collect()
        if format == DisplayBuffer.RGB565:
            buffer = bytearray(width * height * BPP)
            self.show = self._show16
        elif format == DisplayBuffer.GS8:
            self._stride = stride
            self._bounce_buf = alloc_buffer(width * self._stride * BPP)
            buffer = bytearray(width * height)
            self.show = self._show8
        elif format == DisplayBuffer.GS4_HMSB:
            DisplayBuffer.lut = bytearray(0x00 for _ in range(32))
            self._stride = stride
            self._bounce_buf = alloc_buffer(width * self._stride * BPP)
            buffer = bytearray(width * height // 2)
            self.show = self._show4
        else:
            raise ValueError(f"Unsupported format: {format}")

        super().__init__(buffer, width, height, format)
        self._mvb = memoryview(self.buffer)
        self.show()  # Clear the display
        gc.collect()

    def __getattr__(self, name):
        if name in _display_drv_get_attrs:
            return getattr(self.display_drv, name)
        raise AttributeError(f"{self.__class__.__name__} object has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name in _display_drv_set_attrs:
            return setattr(self.display_drv, name, value)
        super().__setattr__(name, value)

    def blit_transparent(self, buf, x, y, w, h, key):
        """Key-color blit into the logical framebuffer (returns dirty Area)."""
        return pygraphics.blit_transparent(self, buf, x, y, w, h, key)

    @property
    def color_palette(self):
        """Registered RGB888 palette used with GS4_HMSB / Nano-GUI color helpers."""
        return self._color_palette

    @color_palette.setter
    def color_palette(self, palette):
        if len(palette) > 16:
            raise ValueError("Palette must be 16 colors or less")
        self._color_palette = palette
        for index, color in enumerate(palette):
            r, g, b = color >> 16 & 0xFF, color >> 8 & 0xFF, color & 0xFF
            self.color(r, g, b, index)

    @staticmethod
    def color(r, g, b, idx=None):
        """
        Get an RGB565 or RGB332 value for a color and optionally register it in the display's LUT.
        This is a convenience function for using this framework WITHOUT Nano-GUI or Micro-GUI.
        Those packages have their own methods of registering colors.

        Args:
            r (int): Red component (0-255)
            g (int): Green component (0-255)
            b (int): Blue component (0-255)
            idx (int): Optional index to register the color in the display's LUT (0-15);
                ignored if the display doesn't use a LUT in its current format

        Raises:
            ValueError: If 16 colors have already been registered or if the index is out of range

        Returns:
            (int): RGB565 color value in RG565 format;
                 RGB332 color value in GS8 format;
                 the index of the registered color in the LUT in GS4_HMSB format
        """
        c = DisplayBuffer.rgb(r, g, b)  # Convert the color to RGB565 or RGB332
        if not hasattr(DisplayBuffer, "lut"):  # If the ssd doesn't use a LUT in its current format
            return c  # Return the color as-is
        if idx is None:  # If no index was provided
            if (
                DisplayBuffer.colors_registered < 16
            ):  # If there are fewer than 16 colors registered
                idx = DisplayBuffer.colors_registered  # Set the index to the next index
                DisplayBuffer.colors_registered += 1  # Increment the number of colors registered
            else:  # If there are already 16 colors registered
                raise ValueError("16 colors have already been registered")
        if not 0 <= idx <= 15:  # If the index is out of range
            raise ValueError("Color numbers must be 0..15")
        offset = idx << 1  # Multiply by 2 (2 bytes per 16-bit color)
        DisplayBuffer.lut[offset] = c & 0xFF  # Set the lower 8 bits of the color
        DisplayBuffer.lut[offset + 1] = c >> 8  # Set the upper 8 bits of the color
        return idx  # Return the index of the registered color

    def _show16(self, area=None):
        """Copy RGB565 buffer (or ``area`` sub-rectangle) to the display."""
        if area is not None:
            x, y, w, h = area
            for row in range(y, y + h):
                buffer_begin = (row * self.width + x) * 2
                buffer_end = buffer_begin + w * 2
                self.display_drv.blit_rect(self.buffer[buffer_begin:buffer_end], x, row, w, 1)
        else:
            self.display_drv.blit_rect(self.buffer, 0, 0, self.width, self.height)

    def _show8(self, area=None):
        # Note:  area is ignored for now in _show8
        # Convert the 8 bit RGB332 values to 16 bit RGB565 values and then copy the line
        # to the display, line by line.
        swap = self.needs_swap
        buf = self._mvb
        bb = self._bounce_buf
        wd = self.width
        ht = self.height
        lines = self._stride
        stride = lines * wd
        chunks, remainder = divmod(ht, lines)
        for chunk in range(chunks):
            start = chunk * stride
            _bounce8(bb, buf[start:], stride, swap)
            self.display_drv.blit_rect(bb, 0, chunk * lines, wd, lines)
        if remainder:
            start = chunks * stride
            _bounce8(bb, buf[start:], remainder * wd, swap)
            self.display_drv.blit_rect(bb, 0, chunks * lines, wd, remainder)

    def _show4(self, area=None):
        # Note:  area is ignored for now in _show4
        # Convert the 4 bit index values to 16 bit RGB565 values using a lookup table
        # and then copy the line to the display, line by line.
        clut = DisplayBuffer.lut
        buf = self._mvb
        bb = self._bounce_buf
        wd = self.width
        ht = self.height
        lines = self._stride
        stride = lines * wd // 2  # 2 pixels per byte
        chunks, remainder = divmod(ht, lines)
        for chunk in range(chunks):
            start = chunk * stride
            _bounce4(bb, buf[start:], stride, clut)
            self.display_drv.blit_rect(bb, 0, chunk * lines, wd, lines)
        if remainder:
            start = chunks * stride
            _bounce4(bb, buf[start:], remainder * wd // 2, clut)
            self.display_drv.blit_rect(bb, 0, chunks * lines, wd, remainder)


class BoolPalette(pygraphics.FrameBuffer):
    """Two-entry palette for blitting monochrome glyphs into a color framebuffer.

    Supports destinations with up to 16-bit color. Used as
    ``DisplayBuffer.palette`` with ``ssd.blit(glyph, x, y, key=-1, palette=…)``.
    """

    # Copyright (c) Peter Hinch 2021
    # Released under the MIT license see LICENSE
    def __init__(self, format):
        """Allocate a 2x1 framebuffer in ``format`` for fg/bg colors.

        Args:
            format: A ``pygraphics`` framebuf format constant (e.g. ``RGB565``).
        """
        buf = bytearray(4)  # OK for <= 16 bit color
        super().__init__(buf, 2, 1, format)

    def fg(self, color):
        """Set the foreground (glyph-on) color.

        Args:
            color: Destination pixel value in the palette's format.
        """
        self.pixel(1, 0, color)

    def bg(self, color):
        """Set the background (glyph-off) color.

        Args:
            color: Destination pixel value in the palette's format.
        """
        self.pixel(0, 0, color)
