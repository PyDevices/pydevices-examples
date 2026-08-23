"""Minimal CST816 driver for CircuitPython (Waveshare RP2040-Touch-LCD-1.28)."""

import time
from micropython import const

import digitalio

_ADDR = const(0x15)
_GESTURE = const(0x01)
_CHIP_ID = const(0xA7)
_DIS_AUTOSLEEP = const(0xFE)


class CST816:
    def __init__(self, i2c, rst_pin=None, address=_ADDR):
        self.i2c = i2c
        self.address = address
        self._cmd = bytearray(1)
        self.rst = None
        if rst_pin is not None:
            self.rst = digitalio.DigitalInOut(rst_pin)
            self.rst.switch_to_output(value=True)
            self.reset()
        self.disable_autosleep()
        cid = self._read_reg(_CHIP_ID, 1)[0]
        if cid not in (0xB4, 0xB5, 0xB6, 0xB7, 0x11):
            raise RuntimeError("CST816 not found, id=%r" % cid)

    def reset(self):
        if not self.rst:
            return
        self.rst.value = False
        time.sleep(0.001)
        self.rst.value = True
        time.sleep(0.05)

    def disable_autosleep(self):
        self._write_reg(_DIS_AUTOSLEEP, 0x01)

    def _write_reg(self, reg, val):
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto(self.address, bytes((reg, val)))
        finally:
            self.i2c.unlock()

    def _read_reg(self, reg, n):
        self._cmd[0] = reg
        out = bytearray(n)
        while not self.i2c.try_lock():
            pass
        try:
            self.i2c.writeto_then_readfrom(self.address, self._cmd, out)
        finally:
            self.i2c.unlock()
        return out

    def get_point(self):
        """Return ``(x, y)`` or ``None`` — appdev ``touch_read`` shape."""
        buf = self._read_reg(_GESTURE, 6)
        fingers = buf[1]
        if not (0 < fingers < 6):
            return None
        x = ((buf[2] & 0x0F) << 8) | buf[3]
        y = ((buf[4] & 0x0F) << 8) | buf[5]
        if x > 239 or y > 239:
            return None
        return (x, y)
