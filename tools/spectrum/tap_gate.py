"""Audio meter gate, the tap half: audiometer metering the drum machine through
audiopump's tap, with no USB anywhere (media modules roadmap, Gate 6).

Upload beside drum_machine and run this instead of it. Once the app is up, an
LVGL timer presses PLAY, attaches a tap and a meter to the drum machine's pump,
and reads the levels 30 times a second. (From LVGL's own timers, not a
machine.Timer: a hardware timer's callback lands in the middle of LVGL's loop,
and PLAY pressed from there left the sequencer stuck on its first step.)
After SECONDS it writes /tapgate.txt:

- analyses a second (60 while audio flows);
- the kick band's swing: its loudest less its quietest level in each beat
  (half a second at the drum machine's 120 bpm), so a meter that dances shows
  a swing of tens of dB and a stuck one shows zero;
- the meter's cost, which in tap mode runs on the reader's thread, as a share
  of one core against the wall clock.

Everything stays in RAM until the end: nothing is written while it runs.
"""

import sys
import time

import audiometer

import appdev

SECONDS = 30
VOLUME = 50  # the drum machine sets 85; a gate needs to be heard, not loud
BANDS = 32
KICK_HZ = 60.0
_LOG = "/tapgate.txt"

state = {"t0": None, "meter": None, "rows": [], "seq": 0, "done": False, "err": None}


def kick_band():
    lo, hi = 35.0, 20000.0
    r = (hi / lo) ** (1 / BANDS)
    i = 0
    while lo * r ** (i + 1) < KICK_HZ:
        i += 1
    return i


KICK = kick_band()


def start(dm):
    from audiodev import pump
    import lvgl as lv

    m = dm.machine
    m.audio_out.set_volume(VOLUME)
    m.play_btn.add_state(lv.STATE.CHECKED)
    m._on_play(None)
    mod = pump.module()
    tap = mod.Tap(frames=4096, channel_count=m.fmt.channels)
    mod.tap(tap)
    meter = audiometer.Meter(BANDS)
    meter.attach(tap, m.fmt.rate)
    state["meter"] = meter
    state["t0"] = time.ticks_ms()
    state["rate"] = (m.fmt.rate, m.fmt.channels)


def finish():
    st = state["meter"].stats()
    rows = state["rows"]
    el = time.ticks_diff(rows[-1][0], rows[0][0]) if len(rows) > 1 else 1
    swings = []
    beat = []
    edge = rows[0][0] if rows else 0
    for t, _seq, lv in rows:
        if time.ticks_diff(t, edge) >= 500:
            if beat:
                swings.append((max(beat) - min(beat)) / 2)
            beat = []
            edge = t
        beat.append(lv[KICK])
    lines = [
        "TAP rate=%d channels=%d bands=%d kick band %d" % (state["rate"] + (BANDS, KICK)),
        "TAP analyses %d in %.1f s: %.1f a second"
        % (st["analyses"], el / 1000, st["analyses"] * 1000 / el),
        "TAP kick band swing per beat, dB: min %.1f median %.1f max %.1f over %d beats"
        % (min(swings), sorted(swings)[len(swings) // 2], max(swings), len(swings))
        if swings
        else "TAP no beats",
        "TAP cost: feed %.2f%% analysis %.2f%% of a core, worst analysis %d us, lapped %d"
        % (
            100 * st["feed_us"] / st["elapsed_us"],
            100 * st["analysis_us"] / st["elapsed_us"],
            st["max_analysis_us"],
            st["lapped"],
        ),
        "TAP a beat of the kick band: " + " ".join("%d" % r[2][KICK] for r in rows[30:60]),
        "TAP DONE",
    ]
    with open(_LOG, "w") as f:
        f.write("\n".join(lines) + "\n")


def tick(_t=None):
    if state["done"]:
        return
    try:
        if state["meter"] is None:
            # the package's app module, or the app run as a plain file
            dm = sys.modules.get("drum_machine.drum_machine") or sys.modules.get("drum_machine")
            if dm is not None and hasattr(dm, "machine"):
                start(dm)
            return
        seq, lv, _pk, _rms = state["meter"].levels()
        if seq != state["seq"]:
            state["seq"] = seq
            state["rows"].append((time.ticks_ms(), seq, bytes(lv)))
        if time.ticks_diff(time.ticks_ms(), state["t0"]) > SECONDS * 1000:
            state["done"] = True
            finish()
    except Exception as e:
        state["done"] = True
        with open(_LOG, "w") as f:
            sys.print_exception(e, f)


_run = appdev.App.run


def _run_with_gate(app, *args, **kwargs):
    import lvgl as lv

    lv.timer_create(tick, 33, None)
    return _run(app, *args, **kwargs)


appdev.App.run = _run_with_gate
import drum_machine  # noqa: E402,F401  (runs the app; never returns)
