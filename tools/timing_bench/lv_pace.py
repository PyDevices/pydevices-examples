"""Frame pacing and CPU for an LVGL app, old or new timing layer, same script.

Builds a screen with an animated arc (a fresh frame every LVGL refresh) and
records the time of every REFR_READY event for DURATION_MS. Reports the
present-to-present intervals (p50/p99/max, in ms), how many frames LVGL
refreshed, and process CPU. Also counts the timer callbacks LVGL's loop ran,
where the layer exposes it.

usage: lv_pace.py OLD|NEW [duration_ms]
Needs board_config, display_driver, lvgl and multimer on the path.
"""

import os
import sys

try:
    from time import ticks_diff, ticks_us
except ImportError:
    import time as _t

    def ticks_us():
        return _t.perf_counter_ns() // 1000

    def ticks_diff(a, b):
        return a - b


try:
    import json
except ImportError:
    import ujson as json


def cpu_time_ms():
    try:
        import time

        return int(time.process_time() * 1000)
    except (ImportError, AttributeError):
        pass
    try:
        with open("/proc/self/stat") as f:
            fields = f.read().split(")")[-1].split()
        return (int(fields[11]) + int(fields[12])) * 10
    except Exception:
        return -1


argv = getattr(sys, "argv", [])
api = argv[1] if len(argv) > 1 else (os.getenv("PACE_API") or "NEW")
duration = int(argv[2]) if len(argv) > 2 else int(os.getenv("PACE_MS") or 5000)

import board_config  # noqa: E402
import display_driver  # noqa: E402
import lvgl as lv  # noqa: E402

if api == "OLD":
    from multimer import auto as timer

    sleep_ms = timer.sleep_ms
else:
    import multimer

    sleep_ms = multimer.sleep_ms

scr = lv.screen_active()
arc = lv.arc(scr)
arc.set_size(120, 120)
arc.center()
label = lv.label(scr)
label.set_text("pace")
label.align(lv.ALIGN.TOP_MID, 0, 8)

angle = [0]


def _step(_t):
    # An LVGL timer, so the arc changes on LVGL's own schedule and every
    # refresh has something to draw.
    angle[0] = (angle[0] + 2) % 100
    arc.set_value(angle[0])


_lv_timer = None
if not os.getenv("PACE_STATIC"):
    _lv_timer = lv.timer_create(_step, 16, None)

stamps = []
disp = lv.display_get_default()
wanted_hist = {}
if api == "NEW":
    _loop = display_driver.event_loop.current_instance()
    _orig_next = _loop._next_delay

    def _counting_next(wanted, work_ms):
        d = _orig_next(wanted, work_ms)
        wanted_hist[d] = wanted_hist.get(d, 0) + 1
        return d

    _loop._next_delay = _counting_next


def _refr_ready(e):
    stamps.append(ticks_us())


disp.add_event_cb(_refr_ready, lv.EVENT.REFR_READY, None)

cpu0 = cpu_time_ms()
t0 = ticks_us()
while ticks_diff(ticks_us(), t0) < duration * 1000:
    sleep_ms(5)
wall = ticks_diff(ticks_us(), t0)
cpu1 = cpu_time_ms()

out = {
    "api": api,
    "impl": sys.implementation.name,
    "frames": len(stamps),
    "duration_ms": duration,
    "static": bool(os.getenv("PACE_STATIC")),
    "cpu_pct": round(100.0 * (cpu1 - cpu0) * 1000 / wall, 1) if cpu0 >= 0 else -1,
}
if len(stamps) >= 3:
    ints = sorted(ticks_diff(b, a) for a, b in zip(stamps, stamps[1:]))
    n = len(ints)
    out.update(
        {
            "int_p50": ints[n // 2] / 1000,
            "int_p99": ints[min(n - 1, n * 99 // 100)] / 1000,
            "int_max": ints[-1] / 1000,
            "int_min": ints[0] / 1000,
        }
    )
out["driver"] = getattr(display_driver, "__file__", "?")
loop = display_driver.event_loop.current_instance()
if api == "NEW" and loop is not None:
    out["wanted_hist"] = dict(sorted(wanted_hist.items()))
    out["passes"] = loop.passes
    out["slow_passes"] = loop.slow_passes
    out["lvgl_timer_fired"] = loop.timer.fired
    drv = display_driver._driver_ref
    out["presents"] = getattr(drv, "presents", None)
    out["max_gap_ms"] = multimer.info()["max_gap_ms"]
print("PACE=" + json.dumps(out))
try:
    display_driver.app.request_quit()
except Exception:
    pass
