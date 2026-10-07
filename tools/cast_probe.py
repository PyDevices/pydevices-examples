"""cast_probe.py -- one headless cast, measured the same way on every runtime.

    python cast_probe.py roku <TV>            # RokuDisplay through the Companion channel

Run from lib/ on a desktop, with any of python, python.exe, micropython or
micropython.exe. On a board, set MODE and TARGET below and run it with
mpftp; it joins Wi-Fi from secrets.py first.

It draws a moving bar and a frame number for SECONDS at FPS, and prints one
PROBE line: frames shown, distinct frames the screen fetched, the rate it
fetched them at, and the median time from show() to the wire. On a board the
line also goes to /probe.txt.
"""

import sys
import time

for _p in (".", "utils"):  # run from lib/ on a desktop
    if _p not in sys.path:
        sys.path.append(_p)

MODE = None  # "roku", on a board
TARGET = None  # the TV's address, on a board
SECONDS = 30
FPS = 10
W, H = 480, 270

_argv = getattr(sys, "argv", [])[1:]
mode = _argv[0] if _argv else MODE
target = _argv[1] if len(_argv) > 1 else TARGET


def now():
    try:
        return time.ticks_ms() / 1000
    except AttributeError:
        return time.monotonic()


def sleep(s):
    if s > 0:
        time.sleep(s)


def on_board():
    return sys.platform not in ("linux", "win32", "darwin")


def wifi_up():
    if not on_board():
        return
    import network
    import wifi

    w = network.WLAN(network.STA_IF)
    if not w.isconnected():
        wifi.connect_from_secrets()
    try:
        w.config(pm=network.WLAN.PM_NONE)
    except Exception:
        pass


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def draw(d, i, prev_x):
    """A bar sweeping across, and the frame number as 12 bits along the top."""
    bg, bar = rgb565(0, 24, 64), rgb565(255, 200, 0)
    x = (i * 12) % (W - 40)
    if prev_x is not None:
        d.fill_rect(prev_x, 100, 40, 70, bg)
    d.fill_rect(x, 100, 40, 70, bar)
    for b in range(12):
        d.fill_rect(
            20 + b * 36, 20, 30, 30, rgb565(255, 255, 255) if (i >> b) & 1 else rgb565(40, 40, 40)
        )
    return x


def median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def run_roku():
    try:
        from utils.roku_companion import RokuDisplay
    except ImportError:
        from roku_companion import RokuDisplay
    d = RokuDisplay(target, width=W, height=H)
    d.fill_rect(0, 0, W, H, rgb565(0, 24, 64))
    d.show()  # starts the frame server and the channel
    srv = d._server
    srv.trace = []
    srv.updates = []
    prev = None
    t0 = now()
    i = 0
    while now() - t0 < SECONDS:
        i += 1
        prev = draw(d, i, prev)
        d.show()
        sleep(t0 + i / FPS - now())
    el = now() - t0
    sleep(1.5)  # let the last fetches land
    trace, updates = srv.trace, {v: t for t, v in srv.updates}
    got = sorted({e[3] for e in trace if e[3] in updates})
    lat = [(e[2] - updates[e[3]]) * 1000 for e in trace if e[3] in updates]
    d.close()
    return i, len(got), len(got) / el, median(lat)


def main():
    import gc

    wifi_up()
    if mode == "roku":
        shown, fetched, rate, med = run_roku()
    else:
        raise SystemExit("cast_probe.py roku <TV>")
    gc.collect()
    line = "PROBE %s %s %s shown=%d fetched=%d rate=%.1f/s median_show_to_wire=%.0fms" % (
        mode,
        sys.implementation.name,
        sys.platform,
        shown,
        fetched,
        rate,
        med,
    )
    print(line)
    if on_board():
        with open("/probe.txt", "w") as f:
            f.write(line + "\n")


main()
