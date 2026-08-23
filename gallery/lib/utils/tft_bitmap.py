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

from pygraphics import Area


def bitmap(canvas, bitmap, x, y, index=0):
    """
    Draw a bitmap on display at the specified column and row

    Args:
        bitmap (bitmap_module): The module containing the bitmap to draw
        x (int): column to start drawing at
        y (int): row to start drawing at
        index (int): Optional index of bitmap to draw from multiple bitmap
            module
    """
    width = bitmap.WIDTH
    height = bitmap.HEIGHT
    to_col = x + width - 1
    to_row = y + height - 1
    if x < 0 or y < 0 or canvas.width <= to_col or canvas.height <= to_row:
        return

    bitmap_size = height * width
    buffer_len = bitmap_size * 2
    bpp = bitmap.BPP
    bs_bit = bpp * bitmap_size * index  # if index > 0 else 0
    palette = bitmap.PALETTE
    needs_swap = canvas.needs_swap if hasattr(canvas, "needs_swap") else False
    buffer = bytearray(buffer_len)

    for i in range(0, buffer_len, 2):
        color_index = 0
        for _ in range(bpp):
            color_index = (color_index << 1) | (
                (bitmap.BITMAP[bs_bit >> 3] >> (7 - (bs_bit & 7))) & 1
            )
            bs_bit += 1

        color = palette[color_index]
        if needs_swap:
            buffer[i] = color >> 8
            buffer[i + 1] = color & 0xFF
        else:
            buffer[i] = color & 0xFF
            buffer[i + 1] = color >> 8

    canvas.blit_rect(buffer, x, y, width, height)
    return Area(x, y, width, height)


def pbitmap(canvas, bitmap, x, y, index=0):
    """
    Draw a bitmap on display at the specified column and row one row at a time

    Args:
        bitmap (bitmap_module): The module containing the bitmap to draw
        x (int): column to start drawing at
        y (int): row to start drawing at
        index (int): Optional index of bitmap to draw from multiple bitmap
            module

    """
    width = bitmap.WIDTH
    height = bitmap.HEIGHT
    bitmap_size = height * width
    bpp = bitmap.BPP
    bs_bit = bpp * bitmap_size * index  # if index > 0 else 0
    palette = bitmap.PALETTE
    needs_swap = canvas.needs_swap if hasattr(canvas, "needs_swap") else False
    buffer = bytearray(bitmap.WIDTH * 2)

    for row in range(height):
        for col in range(width):
            color_index = 0
            for _ in range(bpp):
                color_index <<= 1
                color_index |= (bitmap.BITMAP[bs_bit // 8] & 1 << (7 - (bs_bit % 8))) > 0
                bs_bit += 1
            color = palette[color_index]
            if needs_swap:
                buffer[col * 2] = color & 0xFF
                buffer[col * 2 + 1] = color >> 8 & 0xFF
            else:
                buffer[col * 2] = color >> 8 & 0xFF
                buffer[col * 2 + 1] = color & 0xFF

        to_col = x + width - 1
        to_row = y + row
        if canvas.width > to_col and canvas.height > to_row:
            canvas.blit_rect(buffer, x, y + row, width, height)
    return Area(x, y, width, height)
