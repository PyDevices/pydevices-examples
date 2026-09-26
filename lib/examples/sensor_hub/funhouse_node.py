"""The FunHouse as a sensor node for the house hub (Batch 2).

It reads the FunHouse's own sensors -- temperature and humidity (AHT20),
pressure (DPS310), ambient light (GPIO18) and motion (the PIR on GPIO16), through its board_config roles --
posts them to the hub every few seconds, and shows a small status on its
240x240 screen. The DotStars are switched off at start and left off.

    from sensor_hub import funhouse_node
    funhouse_node.run("192.168.1.147", node="funhouse")

The P4's house app serves the hub over HTTP only, so readings go by
``POST /api/publish`` (``via="udp"`` suits a hub that listens on UDP 5005).
"""

import gc
import time

import framebuf
from machine import Pin

import board_config
from board_config import display_drv

try:
    from sensor_hub.publish import send
except ImportError:
    from publish import send

import wifi

W = display_drv.width
BG = 0x0000


def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


OK = rgb(80, 220, 120)
WARN = rgb(255, 170, 40)
TXT = rgb(230, 230, 230)
DIM = rgb(120, 140, 160)

_CW = W // 2  # 1x text width in px; drawn at 2x
_mono = bytearray(_CW // 8 * 8)
_mfb = framebuf.FrameBuffer(_mono, _CW, 8, framebuf.MONO_HLSB)
_tables = {}  # color -> 256 entries: one mono byte -> 16 px (2x wide) of RGB565
_shown = {}  # row -> (text, color) last drawn
# A copy of every pixel sent to the panel (native RGB565), since the ST7789 on
# this board cannot be read back. save_screen() writes it out as a capture.
_shadow = bytearray(W * display_drv.height * 2)


def save_screen(path="/screen.raw"):
    """Write what the panel shows: W x H RGB565, little-endian, row-major."""
    with open(path, "wb") as f:
        f.write(_shadow)
    return W, display_drv.height


def _table(color):
    t = _tables.get(color)
    if t is None:
        on = bytes((color & 0xFF, color >> 8)) * 2  # native order; the driver swaps
        off = b"\x00\x00" * 2
        t = _tables[color] = [
            b"".join(on if b & (0x80 >> i) else off for i in range(8)) for b in range(256)
        ]
    return t


def line(row, text, color=TXT):
    """Draw one 16-px-tall line (8x8 font at 2x) at text row ``row``, if it changed."""
    text = text[: W // 16]
    if _shown.get(row) == (text, color):
        return
    _shown[row] = (text, color)
    _mfb.fill(0)
    _mfb.text(text, 0, 0, 1)
    t = _table(color)
    nb = _CW // 8
    rows = []
    for y in range(8):
        r = b"".join(t[b] for b in _mono[y * nb : (y + 1) * nb])
        rows.append(r)
        rows.append(r)
    buf = bytearray(b"".join(rows))
    y0 = 8 + row * 20
    _shadow[y0 * W * 2 : (y0 + 16) * W * 2] = buf
    display_drv.blit_rect(buf, 0, y0, W, 16)


def dotstars_off():
    """Latch all five DotStars dark by bit-banging clock 15 / data 14.

    No SPI object, so GPIO21 (the TFT backlight) is never claimed as MISO.
    """
    clk = Pin(15, Pin.OUT, value=0)
    dat = Pin(14, Pin.OUT, value=0)
    for b in b"\x00" * 4 + b"\xe0\x00\x00\x00" * 5 + b"\xff" * 4:
        for i in range(8):
            dat.value((b >> (7 - i)) & 1)
            clk.value(1)
            clk.value(0)


class Sensors:
    """The FunHouse's sensors, through its board_config roles."""

    def read(self):
        bc = board_config
        r = {}
        try:
            r["temp"] = round(bc.temperature.temperature, 2)  # AHT20
            r["humidity"] = round(bc.humidity.relative_humidity, 1)
        except Exception as e:
            print("aht20:", repr(e))
        try:
            r["pressure"] = round(bc.pressure.pressure, 2)  # DPS310, hPa
        except Exception as e:
            print("dps310:", repr(e))
        try:
            r["light"] = round(bc.light.read_u16() * 100 / 65535, 1)  # % of full scale
        except Exception as e:
            print("light:", repr(e))
        r["motion"] = bc.motion.value()  # PIR
        return r


def run(hub="192.168.1.147", node="funhouse", every=2.0, via="http"):
    display_drv.fill_rect(0, 0, W, display_drv.height, BG)
    dotstars_off()
    line(0, node, OK)
    line(1, "joining wifi", DIM)
    wifi.connect_from_secrets()
    import network

    sta = network.WLAN(network.STA_IF)
    ip = sta.ifconfig()[0]
    line(1, ip, DIM)
    line(2, "hub " + hub, DIM)
    s = Sensors()
    sent = failed = 0
    last_ok = None
    t0 = time.ticks_ms()
    while True:
        t = time.ticks_ms()
        r = s.read()
        try:
            r["rssi"] = sta.status("rssi")
        except Exception:
            pass
        try:
            send(hub, node, r, via=via)
            sent += 1
            last_ok = t
        except Exception as e:
            failed += 1
            print("send failed:", repr(e))
            if not sta.isconnected():
                try:
                    wifi.connect_from_secrets()
                except Exception as e2:
                    print("reconnect failed:", repr(e2))
        rate = sent * 1000 / max(1, time.ticks_diff(time.ticks_ms(), t0))
        print(node, sent, failed, r)
        line(3, "T  %.1f C" % r.get("temp", float("nan")))
        line(4, "RH %.0f %%" % r.get("humidity", float("nan")))
        line(5, "P  %.1f hPa" % r.get("pressure", float("nan")))
        line(6, "L  %.0f %%" % r.get("light", float("nan")))
        line(7, "PIR " + ("MOTION" if r["motion"] else "-"), WARN if r["motion"] else TXT)
        line(8, "RSSI %s dBm" % r.get("rssi", "?"))
        line(9, "sent %d fail %d" % (sent, failed), OK if not failed else WARN)
        line(10, "%.2f/s mem %dk" % (rate, gc.mem_free() // 1024), DIM)
        gc.collect()
        wait = int(every * 1000) - time.ticks_diff(time.ticks_ms(), t)
        if wait > 0:
            time.sleep_ms(wait)
