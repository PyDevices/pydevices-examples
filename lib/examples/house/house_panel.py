# house_panel.py -- the smart-home house display.
#
# The P4 is the house panel: it shows every room's sensor node from the
# sensor hub, flags thresholds (a damp bathroom, a warm room, motion), and casts
# itself to the 65" TV on request -- video and audio by Miracast, the ECP
# controls (power, volume, mute, input) from roku_cast. An alert chimes through
# the shared pump-and-cast producer, so it sounds on the P4 and on the TV.
#
# Data: real nodes that publish to the hub (the FunHouse, from the sensor hub's
# funhouse_node) take the first cards; a small simulator fills the other rooms
# with the same readings a node would publish.
#
# Needs the cast example beside this one (roku_cast, castfast, micecast) and
# the sensor_hub example.
import time, math, framebuf, random

_f = __file__.replace("\\", "/")
HERE = _f.rsplit("/", 1)[0] if "/" in _f else "."

from board_config import fb, display_drv, touch_read
from sensor_hub.hub import Hub
from roku_cast import RokuScreen
from audiodev import AudioFormat

TV = "192.168.1.129"      # your Roku's IP address
W = 720
H = 720
RATE = 48000
BLOCK_BYTES = 1920

ticks_ms = time.ticks_ms
ticks_diff = time.ticks_diff


def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


BG = rgb(10, 12, 20)
CARD = rgb(26, 30, 44)
INK = rgb(224, 230, 240)
DIM = rgb(120, 130, 150)
OK = rgb(60, 190, 120)
WARN = rgb(235, 90, 70)
COOL = rgb(90, 160, 235)
ACCENT = rgb(150, 120, 245)



def big_text(s, x, y, scale, color):
    n = len(s)
    tmp = framebuf.FrameBuffer(bytearray(8 * 8 * 2 * n), 8 * n, 8, framebuf.RGB565)
    tmp.fill(0)
    tmp.text(s, 0, 0, 0xFFFF)
    for j in range(8):
        py = y + j * scale
        if py < 0 or py > H - scale:
            continue
        for i in range(8 * n):
            if tmp.pixel(i, j):
                px = x + i * scale
                if 0 <= px <= W - scale:
                    display_drv.fill_rect(px, py, scale, scale, color)


# --------------------------------------------------------------------------
# The house: a stand-in for the FunHouse until it is plugged in. Each room is a
# node that publishes temperature, humidity, light and motion once a second.
# --------------------------------------------------------------------------
class SimHouse:
    ROOMS = ("living", "bedroom", "kitchen", "bath")

    def __init__(self):
        self.t = 0
        self.state = {
            "living":  {"temp": 21.5, "humidity": 45.0, "light": 60.0, "motion": 0},
            "bedroom": {"temp": 20.0, "humidity": 47.0, "light": 8.0, "motion": 0},
            "kitchen": {"temp": 22.5, "humidity": 50.0, "light": 78.0, "motion": 1},
            "bath":    {"temp": 23.0, "humidity": 52.0, "light": 35.0, "motion": 0},
        }

    def step(self):
        self.t += 1
        for i, (name, r) in enumerate(self.state.items()):
            r["temp"] += math.sin(self.t / 18.0 + i) * 0.12 + (random.random() - 0.5) * 0.1
            r["temp"] = max(17.0, min(28.0, r["temp"]))
            r["light"] += (random.random() - 0.5) * 6
            r["light"] = max(0.0, min(100.0, r["light"]))
        # A shower cycle in the bath: humidity climbs past the damp threshold,
        # motion on, then it clears -- so the alert and its chime are seen.
        ph = self.t % 45
        b = self.state["bath"]
        if ph < 16:
            b["humidity"] = min(74.0, b["humidity"] + 2.2)
            b["motion"] = 1
        else:
            b["humidity"] = max(46.0, b["humidity"] - 1.4)
            b["motion"] = 0
        # someone in the kitchen now and then
        self.state["kitchen"]["motion"] = 1 if (self.t % 12) < 7 else 0
        self.state["living"]["motion"] = 1 if (self.t % 20) < 9 else 0

    def lines(self):
        for name, r in self.state.items():
            yield "%s temp=%.1f humidity=%.0f light=%.0f motion=%d" % (
                name, r["temp"], r["humidity"], r["light"], r["motion"])


# --------------------------------------------------------------------------
# Thresholds -> alerts.
# --------------------------------------------------------------------------
_KEYS = {"temperature": "temp", "pir": "motion", "hum": "humidity", "lux": "light"}


def latest(series):
    """The newest value per series, under the panel's names (a real node may
    say temperature or pir; the sim and the dashboard say temp and motion)."""
    return {_KEYS.get(k, k): (v[-1] if v else 0) for k, v in series.items()}


def room_list(snap):
    """(rooms on the panel, all rooms): real nodes first, then the simulated
    rooms fill the four card slots; alerts run over every room."""
    nodes = snap["nodes"]
    real = sorted(n for n, e in nodes.items() if e.get("via") != "sim")
    rooms = real + [r for r in SimHouse.ROOMS if r not in real]
    return rooms[:4], rooms


def alerts_for(node, cur):
    # (key, text): key is stable while the condition holds, so an alert chimes
    # once, not every second as its value drifts.
    a = []
    if cur.get("humidity", 0) >= 60:
        a.append((node + ":damp", "%s damp %.0f%%" % (node, cur["humidity"])))
    if cur.get("temp", 0) >= 26:
        a.append((node + ":warm", "%s warm %.1fC" % (node, cur["temp"])))
    return a


# --------------------------------------------------------------------------
# Audio: silence normally, a two-note chime on an alert. The same producer
# feeds the pump (the P4's speaker) and, while casting, the TV.
# --------------------------------------------------------------------------
def _tone_blocks(hz, ms, amp, phase0=0.0):
    frames = RATE * ms // 1000
    frames = ((frames + 479) // 480) * 480
    out = []
    phase = phase0
    step = 2 * math.pi * hz / RATE
    i = 0
    while i < frames:
        b = bytearray(BLOCK_BYTES)
        for k in range(480):
            v = int(amp * math.sin(phase))
            phase += step
            hi = (v >> 8) & 0xFF
            lo = v & 0xFF
            b[4 * k] = lo; b[4 * k + 1] = hi      # little-endian: the speaker's and the castif ring's format
            b[4 * k + 2] = lo; b[4 * k + 3] = hi
        out.append(bytes(b))
        i += 480
    return out, phase


class HouseAudio:
    def __init__(self, log=print):
        self.log = log
        c1, ph = _tone_blocks(880, 130, 5000)
        c2, _ = _tone_blocks(1175, 200, 5000, ph)
        self.chime = c1 + c2
        self.silence = bytes(BLOCK_BYTES)
        self.pos = -1
        self.stream = None
        try:
            from castfast import pump_stream
            self.stream = pump_stream(AudioFormat(RATE, 2, 16), volume=85, log=log)
        except Exception as e:
            log("house audio: no pump output (%r)" % (e,))
            self.stream = None

    def cast_feed(self, log=print):
        """The cast's audio producer: block() paced by the clock, into this
        stream (the speaker) and the cast alike. One producer, two listeners."""
        from castfast import PumpFeed
        return PumpFeed(self.block, stream=self.stream, log=log)

    def chime_now(self, feeding=False):
        # arm the chime for block(); with a cast feeding the speaker from
        # block() that is all it takes, otherwise burst it into the pump here
        self.pos = 0
        s = self.stream
        if feeding:
            return
        if s is not None:
            for blk in self.chime:
                try:
                    if s.space() >= BLOCK_BYTES:
                        s.write(blk)
                except Exception:
                    break

    def block(self):
        # the cast's audio callback: chime while armed, else silence. The pump
        # already got the chime from chime_now(), so this only feeds the TV.
        if 0 <= self.pos < len(self.chime):
            b = self.chime[self.pos]
            self.pos += 1
            if self.pos >= len(self.chime):
                self.pos = -1
            return b
        return self.silence

    def close(self):
        if self.stream is not None:
            try:
                self.stream.deinit()
            except Exception:
                pass
            self.stream = None


# --------------------------------------------------------------------------
# The panel.
# --------------------------------------------------------------------------
CARD_W = 344
CARD_H = 250
SLOTS = ((16, 168), (360, 168), (16, 430), (360, 430))   # four card slots, row-major
CAST_BTN = (W - 214, 18, 196, 64)


def in_rect(x, y, r):
    return r[0] <= x <= r[0] + r[2] and r[1] <= y <= r[1] + r[3]


def draw_card(name, cur, alert, slot=0):
    x, y = SLOTS[slot]
    edge = WARN if alert else CARD
    display_drv.fill_rect(x, y, CARD_W, CARD_H, CARD)
    display_drv.fill_rect(x, y, CARD_W, 6, edge)
    big_text(name.upper(), x + 16, y + 16, 4, INK if not alert else WARN)
    t = cur.get("temp", 0)
    hum = cur.get("humidity", 0)
    big_text("%.1f C" % t, x + 16, y + 70, 5, WARN if t >= 26 else INK)
    big_text("%.0f %% RH" % hum, x + 16, y + 128, 4, WARN if hum >= 60 else COOL)
    # Light as a bar: a scale-2 "light NN" was unreadable at panel scale.
    # a real node may report lux (hundreds); the bar is 0..100, and a zero-width
    # fill is out of range for the framebuffer, so clamp and skip
    lv = min(100, max(0, cur.get("light", 0)))
    bw = CARD_W - 132
    display_drv.fill_rect(x + 16, y + 192, bw, 26, rgb(38, 44, 60))
    lw = int(bw * lv / 100)
    if lw > 0:
        display_drv.fill_rect(x + 16, y + 192, lw, 26, rgb(232, 200, 90))
    if cur.get("motion", 0):
        display_drv.fill_rect(x + CARD_W - 116, y + 184, 112, 46, ACCENT)
        big_text("MOVE", x + CARD_W - 108, y + 195, 3, 0x0000)


def draw_panel(snap, alert_texts, casting, hubname, rooms=None):
    display_drv.fill(BG)
    display_drv.fill_rect(0, 0, W, 96, rgb(18, 22, 34))
    big_text("PyDevices House", 16, 30, 4, INK)
    # cast button
    bx, by, bw, bh = CAST_BTN
    display_drv.fill_rect(bx, by, bw, bh, WARN if casting else OK)
    big_text("STOP TV" if casting else "SHOW TV", bx + 18, by + 22, 3, 0x0000)
    # alert banner
    if alert_texts:
        display_drv.fill_rect(0, 104, W, 56, WARN)
        big_text(("! " + "  ".join(alert_texts))[:29], 12, 118, 3, 0x0000)
    else:
        display_drv.fill_rect(0, 104, W, 56, rgb(18, 40, 28))
        big_text("all rooms nominal", 12, 118, 3, OK)
    if rooms is None:
        rooms = room_list(snap)[0]
    for slot, name in enumerate(rooms[:4]):
        node = snap["nodes"].get(name)
        cur = latest(node["series"]) if node else {}
        draw_card(name, cur, bool(alerts_for(name, cur)), slot)
    # the DSI panel samples the framebuffer only on refresh: without this the
    # glass keeps whatever it last showed while the cast (same buffer) moves on
    display_drv.show()


# --------------------------------------------------------------------------
# The app.
# --------------------------------------------------------------------------
def run(seconds=0, auto_cast_after=0, log=print):
    """Show the house panel. seconds=0 runs until stopped; auto_cast_after>0
    starts the TV cast that many seconds in (for an unattended proof)."""
    sim = SimHouse()
    hub = Hub(name="house")
    audio = HouseAudio(log=log)
    tv = RokuScreen(TV, name="PyDevices House", log=log)
    casting = False
    prev = set()
    t0 = ticks_ms()
    last_ingest = -10000
    last_touch = -10000
    last_draw = -10000
    auto_done = auto_cast_after <= 0

    log("house panel up; TV on:", tv.is_on())
    while True:
        now = ticks_ms()
        if seconds and ticks_diff(now, t0) >= seconds * 1000:
            break
        if ticks_diff(now, last_ingest) >= 1000:
            last_ingest = now
            sim.step()
            for line in sim.lines():
                hub.ingest(line, "sim")
        snap = hub.snapshot()
        items = []
        panel_rooms, all_rooms = room_list(snap)
        for name in all_rooms:
            node = snap["nodes"].get(name)
            cur = latest(node["series"]) if node else {}
            items += alerts_for(name, cur)
        keys = set(k for k, _ in items)
        texts = [t for _, t in items]
        fresh = keys - prev
        if fresh:
            log("ALERT:", ", ".join(sorted(fresh)))
            audio.chime_now()
        prev = keys
        # A full redraw holds the GIL ~0.2 s. While casting, the cast runs in a
        # Python thread and shares that GIL, so redraw rarely (once a second is
        # plenty for a house panel) to keep the stream smooth enough for the TV
        # to foreground it. The Phase 1 C task removes this trade-off.
        draw_ms = 1000 if casting else 250
        if ticks_diff(now, last_draw) >= draw_ms:
            last_draw = now
            draw_panel(snap, texts, casting, hub.name, panel_rooms)

        # touch: toggle the cast (debounced)
        try:
            pts = touch_read()
        except Exception:
            pts = None
        if pts and ticks_diff(now, last_touch) > 700:
            p = pts[0]
            px = p[0] if isinstance(p, (tuple, list)) else getattr(p, "x", 0)
            py = p[1] if isinstance(p, (tuple, list)) else getattr(p, "y", 0)
            if in_rect(px, py, CAST_BTN):
                last_touch = now
                if casting:
                    tv.stop_cast(); casting = False; log("cast stopped")
                else:
                    casting = bool(tv.start_cast(fb, audio=audio.block, seconds=3600))
                    log("cast started:", casting)

        # unattended proof: auto-start the cast once
        if not auto_done and ticks_diff(now, t0) >= auto_cast_after * 1000:
            auto_done = True
            casting = bool(tv.start_cast(fb, audio=audio.block, seconds=3600))
            log("auto cast started:", casting)

        time.sleep_ms(120)

    if casting:
        tv.stop_cast()
    audio.close()
    log("house panel done")


if __name__ == "__main__":
    run()
