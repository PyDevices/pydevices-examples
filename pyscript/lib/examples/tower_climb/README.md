# tower_climb — developer notes

This folder is a self-contained slice of the pydevices-examples repo: game source, assets,
trace hooks, and local tooling. It is meant to be movable out of the main tree
later; paths are resolved from `__file__` via `_paths.py` rather than hard-coded
repo locations.

These notes cover how the example was built and debugged, not how to play the
game.

## Origins and iteration

The example started as a vertical-scrolling platformer (software camera, no
hardware rotation), loosely inspired by `bmp565_scroll_sprite.py` and classic
climbers. Early work focused on:

- Scalable layout from a 320×480 reference (`Layout` in `tower_climb.py`)
- Landing/collision physics stable enough for repeated jumps up procedurally
  placed branches
- The shared periodic timer via ``appdev.App`` for display refresh
  (see `https://github.com/PyDevices/pydevices/blob/main/docs/app-and-board-config.md` for the timer/display split)

Gameplay bugs (flicker, respawn deaths, camera clamp at the crown, bot pathing)
were fixed iteratively using the trace stream and bot playtests below rather than
manual play alone.

Levels are randomized each round (`_build_level()`). Pass `--seed N` for
a reproducible RNG state when bisecting a layout. Developer hazard pacing is
controlled by the `DIFFICULTY` constant at the top of `tower_climb.py`.

## Package layout

```
tower_climb/
  tower_climb.py          # main game loop
  tower_climb_trace.py    # JSONL trace recorder
  _cfg.py                 # argv flags (--bot, --trace, …)
  _paths.py               # package/asset path helpers
  assets/                 # BMPs + gen_tower_assets.py
  tools/
    playtest.py           # headless bot run + live trace watch
    record_win.sh         # recommended video capture
    record.sh             # legacy desktop capture
  trace/                  # default trace output (gitignored)
```

Run from repo root unless noted:

```bash
# Headless bot playtest (recommended smoke test)
.venv/bin/python lib/examples/tower_climb/tools/playtest.py

# Regenerate BMP assets (CPython only)
.venv/bin/python lib/examples/tower_climb/assets/gen_tower_assets.py

# Play under PGDisplay (needs a display, e.g. DISPLAY=:1)
cd lib && PYTHONPATH=lib ../.venv/bin/python examples/tower_climb/tower_climb.py
```

## Recording: desktop capture vs PGDisplay frames

Two approaches exist in `tools/`. Prefer **`record_win.sh`**.

### Old method — full Linux desktop (`tools/record.sh`)

Uses **ffmpeg x11grab** on the pygame window after locating it with `xwininfo`:

- Captures whatever is on screen at the grab rectangle (desktop compositor,
  window chrome, scaling, vsync timing).
- Frame timing follows the display server, not the game’s logical frame rate.
- In practice, recordings often contained **many duplicate frames**: a short
  clip could look like only a few seconds of motion even when the bot played
  much longer.
- Fragile: depends on finding the correct X11 window title and geometry.

This script remains as a reference for the old workflow. It launches the game
with `--record --trace …` (enables the built-in bot) and writes an optional
trace to `trace/record.jsonl`.

### New method — logical framebuffer export (`tools/record_win.sh`)

Implemented in pydevices-examples’s **PGDisplay** backend, driven from the game via
`--video PATH`:

1. `tower_climb.py` calls `display_drv.open_frame_recorder(path, fps=…)` when
   `--video` is set.
2. On every `PGDisplay.show()`, the driver exports the **logical** RGB24
   framebuffer (`_buffer`, 320×480 for this game) through
   `FFmpegFrameRecorder` in pydevices `utils/frame_recorder.py`.
3. ffmpeg encodes raw RGB24 piped on stdin to H.264 MP4.

Properties:

- One encoded frame per game `show()` — duration matches gameplay.
- Resolution is the game’s logical size, not the scaled pygame window.
- Supported by the desktop ``PGDisplay`` and ``SDLDisplay`` backends.
- Unit tests: pydevices `tests/test_pgdisplay_frame_recorder.py`.

Typical invocation (what `record_win.sh` runs):

```bash
cd lib
DISPLAY=:1 PYTHONPATH=lib \
  ../.venv/bin/python examples/tower_climb/tower_climb.py \
  --bot --hold-win \
  --video /path/to/out.mp4 --video-fps 12 \
  --trace examples/tower_climb/trace/record-win.jsonl
```

`--hold-win` keeps the win screen visible for extra frames so the
recording does not end on the first victory frame. Optional `--hold-frames N`
overrides the default hold length (48 when recording, else 150).

## Debug tooling

### JSONL trace (`tower_climb_trace.py`)

Pass `--trace PATH`. Each line is one JSON object with a
`kind` field. Default playtest output:
`trace/playtest.jsonl` (directory is gitignored except `.gitkeep`).

Common event kinds:

| `kind` | When |
|--------|------|
| `init` | Round start: platforms, gems, hazards, `goal_y`, layout |
| `frame` | Once per tick: player pose, velocity, camera, keys, hitbox, nearby platforms |
| `land` | Landing resolution (`land_up`, spike, etc.) |
| `life_lost` | Life lost (`reason`: `fall`, `hazard`, `spike`, …) |
| `snap` | Player snapped to ground (spawn/respawn) |
| `resolve_x` | Horizontal collision correction |
| `win` | Tree top reached |
| `end` | Trace file closed |

Example (pretty-printed):

```json
{"kind":"init","frame":0,"goal_y":-176,"platforms":[...],"gems":[...]}
{"kind":"frame","frame":1,"player":{"y":382.05,"lives":3,"score":0},...}
{"kind":"win","frame":75,"score":525,"y":-181}
```

Tracing is what made it practical to tune physics and bot behaviour: you can see
exactly which platform was under the feet, when coyote time expired, and when
the camera stopped at `CAM_MIN`.

### Bot playtest (`tools/playtest.py`)

Runs the game headlessly (`SDL_VIDEODRIVER=dummy`) with `--bot --trace …`,
tails the trace file in real time, prints climb progress every second, and
**fails fast** if the bot stalls (no vertical improvement for 15s by default).

```bash
.venv/bin/python lib/examples/tower_climb/tools/playtest.py
.venv/bin/python lib/examples/tower_climb/tools/playtest.py --timeout 120 --stall-s 15
```

Exit code 0 prints `OK: tree top reached` and a JSON summary.

### Built-in bot (`--bot`)

Simple climb AI in `_bot_tick()`: dodge falling spikes, smash ice when standing
on it, jump toward the nearest branch above, aim for the crown when close. Not
perfect on every random layout; playtest win rate is the guardrail.

### Asset generator (`assets/gen_tower_assets.py`)

Procedural RGB565 BMP generator for `climber.bmp`, `tower_tiles.bmp`, and
`tower_bg.bmp`. Marked as temporary until art is final; sizes are fixed so the
game does not need layout changes when art is regenerated.

## Repo integration (outside this folder)

These pieces live in the main pydevices-examples tree and are **dependencies** if you
extract only `tower_climb/`:

- `board_config`, `displaydev`, `appdev`, `pygraphics`, `multimer`
- `FFmpegFrameRecorder` / `PGDisplay.open_frame_recorder` (recording)
- `tools/example_test_manifest.toml` entry for CI smoke tests
- pydevices `tests/test_pgdisplay_frame_recorder.py`

The example matrix runs via:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
  .venv/bin/python tools/example_test_kit.py --no-unit-tests \
  --only-interpreter cpython-venv --only-example tower_climb
```

## Quick reference — game argv (`_cfg.py`)

| Flag | Effect |
|------|--------|
| `--bot` | Enable built-in climb bot |
| `--record` | Implies `--bot` (legacy x11grab workflow) |
| `--hold-win` | Hold win screen for recording |
| `--hold-frames N` | Override hold length |
| `--trace PATH` | Write JSONL trace to path |
| `--seed N` | Fix RNG seed for level generation |
| `--video PATH` | PGDisplay frame recorder output path |
| `--video-fps N` | Encode frame rate (default 12) |

Host shell scripts may still use env vars for *their own* defaults (output
paths, ffmpeg duration); they pass argv into the game. The game itself does
not call getenv.
