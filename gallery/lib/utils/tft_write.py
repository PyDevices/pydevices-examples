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

from micropython import const

from pygraphics import Area

WHITE = const(0xFFFF)
BLACK = const(0x0000)


def write(canvas, font, string, x, y, fg=WHITE, bg=BLACK):
    """
    Write a string using a converted true-type font on the display starting
    at the specified column and row

    Args:
        font (font): The module containing the converted true-type font
        string (str): The string to write
        x (int): column to start writing
        y (int): row to start writing
        fg (int): foreground color, optional, defaults to WHITE
        bg (int): background color, optional, defaults to BLACK
    """
    buffer_len = font.HEIGHT * font.MAX_WIDTH * 2
    buffer = bytearray(buffer_len)
    fg_hi = fg & 0xFF
    fg_lo = fg >> 8

    bg_hi = bg & 0xFF
    bg_lo = bg >> 8

    x_pos = x
    for character in string:
        try:
            char_index = font.MAP.index(character)
            offset = char_index * font.OFFSET_WIDTH
            bs_bit = font.OFFSETS[offset]
            if font.OFFSET_WIDTH > 1:
                bs_bit = (bs_bit << 8) + font.OFFSETS[offset + 1]

            if font.OFFSET_WIDTH > 2:
                bs_bit = (bs_bit << 8) + font.OFFSETS[offset + 2]

            char_width = font.WIDTHS[char_index]
            buffer_needed = char_width * font.HEIGHT * 2

            for i in range(0, buffer_needed, 2):
                if font.BITMAPS[bs_bit // 8] & 1 << (7 - (bs_bit % 8)) > 0:
                    buffer[i] = fg_hi
                    buffer[i + 1] = fg_lo
                else:
                    buffer[i] = bg_hi
                    buffer[i + 1] = bg_lo

                bs_bit += 1

            to_col = x_pos + char_width - 1
            to_row = y + font.HEIGHT - 1
            if canvas.width > to_col and canvas.height > to_row:
                canvas.blit_rect(buffer[:buffer_needed], x_pos, y, char_width, font.HEIGHT)

            x_pos += char_width

        except ValueError:
            pass
    return Area(x, y, x_pos - x, font.HEIGHT)


def write_width(font, string):
    """
    Returns the width in pixels of the string if it was written with the
    specified font

    Args:
        font (font): The module containing the converted true-type font
        string (string): The string to measure

    Returns:
        (int): The width of the string in pixels

    """
    width = 0
    for character in string:
        try:
            char_index = font.MAP.index(character)
            width += font.WIDTHS[char_index]
        except ValueError:
            pass

    return width
