"""Timer jitter / latency / CPU benchmark, same script on CPython and MicroPython.

Runs a periodic timer for DURATION_MS at PERIOD_MS and records the callback
times in microseconds. Two main-thread modes:

  idle   the main thread waits in the provider's sleep_ms (what an app at a
         REPL prompt or in its run loop looks like)
  busy   the main thread spins in pure Python (what a script that never
         yields looks like; only interrupt-style providers keep firing)

Reports, in one JSON line prefixed BENCH=:
  n           callbacks delivered
  expected    DURATION_MS / PERIOD_MS
  lat_p50/p99/max   NEW only: ms from the timer's deadline to the callback,
                    read from the timer itself (callback latency).
  jit_p50/p99/max   |interval - period| in us: interval jitter
  cpu_pct     process CPU time / wall time, both threads counted
  bursts      callbacks less than period/4 apart (catch-up storms)

usage: bench_timer.py OLD|NEW idle|busy [period_ms] [duration_ms]
  OLD uses the current multimer (multimer.auto, MULTIMER_BACKEND honoured).
  NEW uses the redesign (multimer.Timer / multimer.sleep_ms).
"""

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


try:
    from time import ticks_diff as ticks_diff_ms
    from time import ticks_ms as ticks_ms_host
except ImportError:

    def ticks_ms_host():
        return (ticks_us() // 1000) & ((1 << 29) - 1)

    def ticks_diff_ms(a, b):
        d = (a - b) & ((1 << 29) - 1)
        return ((d + (1 << 28)) & ((1 << 29) - 1)) - (1 << 28)


def cpu_time_ms():
    """Process CPU time (user+sys, all threads) in ms."""
    try:
        import time

        return int(time.process_time() * 1000)
    except (ImportError, AttributeError):
        pass
    try:
        with open("/proc/self/stat") as f:
            fields = f.read().split(")")[-1].split()
        # utime, stime are fields 14 and 15 of the whole line; after ')' they
        # are at index 11 and 12. Clock ticks at 100 Hz on Linux.
        return (int(fields[11]) + int(fields[12])) * 10
    except Exception:
        return -1


def run(api, mode, period_ms, duration_ms):
    stamps = []
    if api == "OLD":
        from multimer import auto as timer

        name = timer.name
        Timer = timer.Timer
        sleep_ms = timer.sleep_ms

        def cb(_t):
            stamps.append(ticks_us())

        tim = Timer(-1)
        tim.init(mode=Timer.PERIODIC, period=period_ms, callback=cb, hard=False)
        deinit = tim.deinit
    else:
        import multimer

        sleep_ms = multimer.sleep_ms
        lateness = []

        def cb(t):
            stamps.append(ticks_us())
            lateness.append(ticks_diff_ms(ticks_ms_host(), t._due))

        tim = multimer.Timer(-1)
        tim.init(mode=multimer.Timer.PERIODIC, period=period_ms, callback=cb)
        name = multimer.info().get("source", "?")
        deinit = tim.deinit

    cpu0 = cpu_time_ms()
    t0 = ticks_us()
    if mode == "idle":
        # Sleep in slices like an app loop does.
        while ticks_diff(ticks_us(), t0) < duration_ms * 1000:
            sleep_ms(5)
    else:
        n = 0
        while ticks_diff(ticks_us(), t0) < duration_ms * 1000:
            n += 1
    wall = ticks_diff(ticks_us(), t0)
    cpu1 = cpu_time_ms()
    deinit()

    expected = duration_ms // period_ms
    out = {
        "api": api,
        "provider": name,
        "mode": mode,
        "period_ms": period_ms,
        "n": len(stamps),
        "expected": expected,
        "cpu_pct": round(100.0 * (cpu1 - cpu0) * 1000 / wall, 1) if cpu0 >= 0 and wall else -1,
        "impl": sys.implementation.name,
    }
    if len(stamps) >= 3:
        per_us = period_ms * 1000
        ints = [ticks_diff(b, a) for a, b in zip(stamps, stamps[1:])]
        jit = sorted(abs(i - per_us) for i in ints)
        bursts = sum(1 for i in ints if i < per_us // 4)
        out.update(
            {
                "jit_p50": jit[len(jit) // 2],
                "jit_p99": jit[min(len(jit) - 1, len(jit) * 99 // 100)],
                "jit_max": jit[-1],
                "bursts": bursts,
                "missed": expected - len(stamps),
            }
        )
        if api == "NEW" and lateness:
            late = sorted(lateness)
            n = len(late)
            out.update(
                {
                    "lat_p50": late[n // 2],
                    "lat_p99": late[min(n - 1, n * 99 // 100)],
                    "lat_max": late[-1],
                }
            )
    print("BENCH=" + json.dumps(out))


if __name__ == "__main__":
    api = sys.argv[1] if len(sys.argv) > 1 else "OLD"
    mode = sys.argv[2] if len(sys.argv) > 2 else "idle"
    period = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    duration = int(sys.argv[4]) if len(sys.argv) > 4 else 5000
    run(api, mode, period, duration)
