"""framebuf API via pygraphics when frozen ``framebuf`` is unavailable.

On MicroPython unix, the C ``framebuf`` module in ``.frozen`` still wins
because ``path.py`` puts ``.frozen`` ahead of ``utils``.
"""

from pygraphics import (
    GS2_HMSB,
    GS4_HMSB,
    GS8,
    MONO_HLSB,
    MONO_HMSB,
    MONO_VLSB,
    RGB565,
    FrameBuffer,
)

# MicroPython alias (same format value as MONO_VLSB).
MVLSB = MONO_VLSB

__all__ = [
    "GS2_HMSB",
    "GS4_HMSB",
    "GS8",
    "MONO_HLSB",
    "MONO_HMSB",
    "MONO_VLSB",
    "MVLSB",
    "RGB565",
    "FrameBuffer",
]
