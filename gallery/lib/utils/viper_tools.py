"""
Viper tools for PyDevices
=========================
This module contains Viper functions for PyDevices. These functions are consolidated here to
allow publishing of the main module without the Viper code.
"""

import micropython

if 0:

    class ptr8:
        pass

    class ptr16:
        pass

    class uint:
        pass


@micropython.viper
def byteswap_viper(buf: ptr8, buf_size: int):  # noqa: F821
    """
    Swap the bytes in a buffer of 16-bit values in place.

    Args:
        buf: The buffer to swap the bytes in.
        buf_size: The size of the buffer in bytes
    """
    for i in range(0, buf_size, 2):
        tmp = buf[i]
        buf[i] = buf[i + 1]
        buf[i + 1] = tmp


#  _bounce8 and _bounce4 for displaybuf
@micropython.viper
def _bounce8(dest: ptr8, source: ptr8, length: int, swap: bool):  # noqa: F821
    # Convert a line in 8 bit RGB332 format to 16 bit RGB565 format.
    # Each byte becomes 2 in destination. Source format:
    # <R2 R1 R0 G2 G1 G0 B1 B0>
    # dest:
    # swap==False: <R2 R1 R0 00 00 G2 G1 G0> <00 00 00 B1 B0 00 00 00>
    # swap==True:  <00 00 00 B1 B0 00 00 00> <R2 R1 R0 00 00 G2 G1 G0>

    if swap:
        lsb = 0
        msb = 1
    else:
        lsb = 1
        msb = 0
    n = 0
    for x in range(length):
        c = source[x]
        dest[n + lsb] = (c & 0xE0) | ((c & 0x1C) >> 2)  # Red Green
        dest[n + msb] = (c & 0x03) << 3  # Blue
        n += 2


@micropython.viper
def _bounce4(dest: ptr16, source: ptr8, length: int, lut: ptr16):  # noqa: F821
    # Convert a line in 4+4 bit index format to two * 16 bit RGB565 format
    # using a color lookup table. Each byte becomes 4 in destination.
    # Source format:  <C03 C02 C01 C00 C13 C12 C11 C10>
    # Dest format: the same as self.rgb * 2
    n = 0
    for x in range(length):
        c = source[x]  # Get the indices of the 2 pixels
        dest[n] = lut[c >> 4]  # lookup top 4 bits for even pixels
        n += 1
        dest[n] = lut[c & 0x0F]  # lookup bottom 4 bits for odd pixels
        n += 1


_BIT7 = micropython.const(0x80)
_BIT6 = micropython.const(0x40)
_BIT5 = micropython.const(0x20)
_BIT4 = micropython.const(0x10)
_BIT3 = micropython.const(0x08)
_BIT2 = micropython.const(0x04)
_BIT1 = micropython.const(0x02)
_BIT0 = micropython.const(0x01)


@micropython.viper
def _pack8(glyphs, idx: uint, fg_color: uint, bg_color: uint):  # noqa: F821
    buffer = bytearray(128)
    bitmap = ptr16(buffer)  # noqa: F821
    glyph = ptr8(glyphs)  # noqa: F821

    for i in range(0, 64, 8):
        byte = glyph[idx]
        bitmap[i] = fg_color if byte & uint(_BIT7) else bg_color
        bitmap[i + 1] = fg_color if byte & uint(_BIT6) else bg_color
        bitmap[i + 2] = fg_color if byte & uint(_BIT5) else bg_color
        bitmap[i + 3] = fg_color if byte & uint(_BIT4) else bg_color
        bitmap[i + 4] = fg_color if byte & uint(_BIT3) else bg_color
        bitmap[i + 5] = fg_color if byte & uint(_BIT2) else bg_color
        bitmap[i + 6] = fg_color if byte & uint(_BIT1) else bg_color
        bitmap[i + 7] = fg_color if byte & uint(_BIT0) else bg_color
        idx += 1

    return buffer


@micropython.viper
def _pack16(glyphs, idx: uint, fg_color: uint, bg_color: uint):  # noqa: F821
    buffer = bytearray(256)
    bitmap = ptr16(buffer)  # noqa: F821
    glyph = ptr8(glyphs)  # noqa: F821

    for i in range(0, 128, 16):
        byte = glyph[idx]

        bitmap[i] = fg_color if byte & uint(_BIT7) else bg_color
        bitmap[i + 1] = fg_color if byte & uint(_BIT6) else bg_color
        bitmap[i + 2] = fg_color if byte & uint(_BIT5) else bg_color
        bitmap[i + 3] = fg_color if byte & uint(_BIT4) else bg_color
        bitmap[i + 4] = fg_color if byte & uint(_BIT3) else bg_color
        bitmap[i + 5] = fg_color if byte & uint(_BIT2) else bg_color
        bitmap[i + 6] = fg_color if byte & uint(_BIT1) else bg_color
        bitmap[i + 7] = fg_color if byte & uint(_BIT0) else bg_color
        idx += 1

        byte = glyph[idx]
        bitmap[i + 8] = fg_color if byte & uint(_BIT7) else bg_color
        bitmap[i + 9] = fg_color if byte & uint(_BIT6) else bg_color
        bitmap[i + 10] = fg_color if byte & uint(_BIT5) else bg_color
        bitmap[i + 11] = fg_color if byte & uint(_BIT4) else bg_color
        bitmap[i + 12] = fg_color if byte & uint(_BIT3) else bg_color
        bitmap[i + 13] = fg_color if byte & uint(_BIT2) else bg_color
        bitmap[i + 14] = fg_color if byte & uint(_BIT1) else bg_color
        bitmap[i + 15] = fg_color if byte & uint(_BIT0) else bg_color
        idx += 1

    return buffer
