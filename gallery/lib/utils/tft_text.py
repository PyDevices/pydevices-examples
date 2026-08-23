"""
MIT License

Copyright (c) 2024 Brad Barnett

Copyright (c) 2020-2023 Russ Hughes

Copyright (c) 2019 Ivan Belokobylskiy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

The file is based on Russ Hughes's st7789_mpy driver from
https://github.com/russhughes/st7789_mpy

which is based on devbis' st7789py_mpy module from
https://github.com/devbis/st7789py_mpy.

"""

from sys import implementation

from micropython import const

from pygraphics import Area

_viper = False
if implementation.name == "micropython":
    try:
        from viper_tools import _pack8, _pack16

        _viper = True
    except Exception:
        pass

if not _viper:
    import struct

    _BIT7 = 0x80
    _BIT6 = 0x40
    _BIT5 = 0x20
    _BIT4 = 0x10
    _BIT3 = 0x08
    _BIT2 = 0x04
    _BIT1 = 0x02
    _BIT0 = 0x01

    def _pack8(glyphs: memoryview, idx: int, fg_color: int, bg_color: int):
        buffer = bytearray(128)
        fg = struct.pack("<H", fg_color & 0xFFFF)
        bg = struct.pack("<H", bg_color & 0xFFFF)
        for i in range(0, 128, 16):
            byte = glyphs[idx]
            buffer[i : i + 2] = fg if byte & _BIT7 else bg
            buffer[i + 2 : i + 4] = fg if byte & _BIT6 else bg
            buffer[i + 4 : i + 6] = fg if byte & _BIT5 else bg
            buffer[i + 6 : i + 8] = fg if byte & _BIT4 else bg
            buffer[i + 8 : i + 10] = fg if byte & _BIT3 else bg
            buffer[i + 10 : i + 12] = fg if byte & _BIT2 else bg
            buffer[i + 12 : i + 14] = fg if byte & _BIT1 else bg
            buffer[i + 14 : i + 16] = fg if byte & _BIT0 else bg
            idx += 1
        return buffer

    def _pack16(glyphs: memoryview, idx: int, fg_color: int, bg_color: int):
        buffer = bytearray(256)
        fg = struct.pack("<H", fg_color & 0xFFFF)
        bg = struct.pack("<H", bg_color & 0xFFFF)
        for i in range(0, 256, 16):
            byte = glyphs[idx]
            buffer[i : i + 2] = fg if byte & _BIT7 else bg
            buffer[i + 2 : i + 4] = fg if byte & _BIT6 else bg
            buffer[i + 4 : i + 6] = fg if byte & _BIT5 else bg
            buffer[i + 6 : i + 8] = fg if byte & _BIT4 else bg
            buffer[i + 8 : i + 10] = fg if byte & _BIT3 else bg
            buffer[i + 10 : i + 12] = fg if byte & _BIT2 else bg
            buffer[i + 12 : i + 14] = fg if byte & _BIT1 else bg
            buffer[i + 14 : i + 16] = fg if byte & _BIT0 else bg
            idx += 1
        return buffer


WHITE = const(0xFFFF)
BLACK = const(0x0000)


def text(canvas, font, text, x0, y0, color=WHITE, background=BLACK):
    """
    Draw text on display in specified font and colors. 8 and 16 bit wide
    fonts are supported.

    Args:
        font (module): font module to use.
        text (str): text to write
        x0 (int): column to start drawing at
        y0 (int): row to start drawing at
        color (int): 565 encoded color to use for characters
        background (int): 565 encoded color to use for background
    """
    if font.WIDTH == 8:
        return _text8(canvas, font, text, x0, y0, color, background)
    else:
        return _text16(canvas, font, text, x0, y0, color, background)


def _text8(canvas, font, text, x0, y0, fg_color=WHITE, bg_color=BLACK):
    """
    Internal method to write characters with width of 8 and
    heights of 8 or 16.

    Args:
        font (module): font module to use
        text (str): text to write
        x0 (int): column to start drawing at
        y0 (int): row to start drawing at
        color (int): 565 encoded color to use for characters
        background (int): 565 encoded color to use for background
    """

    x_pos = x0
    for char in text:
        ch = ord(char)
        if (
            font.FIRST <= ch < font.LAST
            and x_pos + font.WIDTH <= canvas.width
            and y0 + font.HEIGHT <= canvas.height
        ):
            if font.HEIGHT == 8:
                passes = 1
                size = 8
                each = 0
            else:
                passes = 2
                size = 16
                each = 8

            for line in range(passes):
                idx = (ch - font.FIRST) * size + (each * line)
                buffer = _pack8(font.FONT, idx, fg_color, bg_color)
                canvas.blit_rect(buffer, x_pos, y0 + 8 * line, 8, 8)

            x_pos += 8
    return Area(x0, y0, x_pos - x0, font.HEIGHT)


def _text16(canvas, font, text, x0, y0, fg_color=WHITE, bg_color=BLACK):
    """
    Internal method to draw characters with width of 16 and heights of 16
    or 32.

    Args:
        font (module): font module to use
        text (str): text to write
        x0 (int): column to start drawing at
        y0 (int): row to start drawing at
        color (int): 565 encoded color to use for characters
        background (int): 565 encoded color to use for background
    """

    x_pos = x0
    for char in text:
        ch = ord(char)
        if (
            font.FIRST <= ch < font.LAST
            and x_pos + font.WIDTH <= canvas.width
            and y0 + font.HEIGHT <= canvas.height
        ):
            each = 16
            if font.HEIGHT == 16:
                passes = 2
                size = 32
            else:
                passes = 4
                size = 64

            for line in range(passes):
                idx = (ch - font.FIRST) * size + (each * line)
                buffer = _pack16(font.FONT, idx, fg_color, bg_color)
                canvas.blit_rect(buffer, x_pos, y0 + 8 * line, 16, 8)
        x_pos += 16
    return Area(x0, y0, x_pos - x0, font.HEIGHT)
