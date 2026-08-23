"""
uctypes shim for CircuitPython.

nano-gui's writer.py imports ``bytearray_at`` and ``addressof`` for fast color
glyph blits. CircuitPython unix has no ``uctypes`` module; this provides the
subset nano-gui needs by retaining glyph buffers and copying on ``bytearray_at``.
"""

_refs = {}


def addressof(obj):
    key = id(obj)
    _refs[key] = obj
    return key


def bytearray_at(addr, n):
    obj = _refs[addr]
    if isinstance(obj, bytearray):
        return obj
    return bytearray(memoryview(obj)[:n])
