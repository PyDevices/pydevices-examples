# The benchmark scripts and their raw results

Two scripts, run the same way on the current multimer and on the redesign.
The Numbers section of pydevices' `docs/timing-design.md` is made from the
`.jsonl` files here. The `results-*.jsonl` files without a host suffix are the
cloud session's (a 4-core container); files named `results-<host>.jsonl` were
measured on Brad's bench by the local session, each row carrying its `host`.

`bench_timer.py OLD|NEW idle|busy [period_ms] [duration_ms]` arms one
periodic timer and records every callback. `OLD` uses `multimer.auto`
(`MULTIMER_BACKEND` chooses the provider); `NEW` uses `multimer.Timer`
(`MULTIMER_SOURCE` chooses the wake source). It prints one `BENCH=` JSON
line. Runs were made with `PYTHONPATH`/`MICROPYPATH` pointing at the
pydevices tree under test (`lib` and `utils`), `SDL_VIDEODRIVER=dummy`, one
run at a time, nothing else running.

`lv_pace.py` builds an LVGL screen with an arc moved by a 16 ms LVGL timer,
records `REFR_READY` events for `PACE_MS` (3000) and prints one `PACE=`
line. `PACE_API=OLD|NEW`, `PACE_STATIC=1` for the static-screen case. The
path also has `lvgl-bindings/python` (the driver under test) and
`pydevices/board_configs/desktop` on it. Both interpreters were run
headless with SDL's dummy video driver.

Results:

- `results-current-multimer.jsonl`: the current layer, every provider this
  host has, idle and busy.
- `results-redesign.jsonl`: the redesign's `signal` and `pending` sources on
  CPython, `signal` on unix MicroPython, `none` on CircuitPython.
- `results-lvgl-pacing.jsonl`: the frame-pacing runs, including the ones
  before the double-present fix (the earlier `NEW` MicroPython rows with
  `cpu_pct` around 20 and no `"static"` key).
