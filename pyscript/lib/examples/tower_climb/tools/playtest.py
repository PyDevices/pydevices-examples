#!/usr/bin/env python3
"""Run tower_climb with the built-in bot; watch the trace stream in real time."""

import argparse
import json
import os
import subprocess
import sys
import time

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(TOOLS_DIR)
SRC_DIR = os.path.dirname(os.path.dirname(PKG_DIR))
REPO_ROOT = os.path.dirname(SRC_DIR)
GAME_SCRIPT = os.path.join(PKG_DIR, "tower_climb.py")
DEFAULT_TRACE = os.path.join(PKG_DIR, "trace", "playtest.jsonl")


def analyze(path):
    won = False
    min_y = 9999.0
    life_lost = 0
    frames = 0
    last = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["kind"] == "win":
                won = True
            if d["kind"] == "life_lost":
                life_lost += 1
            if d["kind"] == "frame":
                frames += 1
                y = d["player"]["y"]
                min_y = min(min_y, y)
                last = d
    return {
        "won": won,
        "frames": frames,
        "life_lost": life_lost,
        "min_y": min_y if min_y < 9999 else None,
        "last_y": last["player"]["y"] if last else None,
        "last_lives": last["player"]["lives"] if last else None,
        "last_score": last["player"]["score"] if last else None,
    }


def watch_trace(path, proc, *, hard_timeout_s, stall_seconds, stall_improve_y):
    """Tail the JSONL trace; report progress and detect stalls early."""
    offset = 0
    best_y = 9999.0
    last_improve = time.time()
    frames = 0
    goal_y = None
    started = time.time()
    last_report = 0.0
    last_line = None

    while proc.poll() is None:
        now = time.time()
        if now - started > hard_timeout_s:
            return "timeout", {"best_y": best_y, "frames": frames, "last": last_line}

        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()
            for raw in chunk.splitlines():
                if not raw.strip():
                    continue
                d = json.loads(raw)
                last_line = d
                kind = d.get("kind")
                if kind == "init":
                    goal_y = d.get("goal_y")
                    print(f"init goal_y={goal_y} platforms={len(d.get('platforms', []))}")
                elif kind == "win":
                    print(
                        f"win frame={frames} score={d.get('score')} y={d.get('y')}"
                    )
                    return "win", d
                elif kind == "life_lost":
                    print(
                        f"life_lost reason={d.get('reason')} "
                        f"lives={d.get('player', {}).get('lives')}"
                    )
                elif kind == "frame":
                    frames += 1
                    y = float(d["player"]["y"])
                    if y < best_y - stall_improve_y:
                        best_y = y
                        last_improve = now
                    if now - last_report >= 1.0:
                        last_report = now
                        pct = ""
                        if goal_y is not None:
                            span = max(1.0, 400.0 - float(goal_y))
                            pct = f" climb={max(0, min(99, int((400.0 - y) * 100 / span))):2d}%"
                        print(
                            f"frame={d.get('frame', frames):4d} "
                            f"y={y:6.1f} best_y={best_y:6.1f}{pct} "
                            f"lives={d['player']['lives']} score={d['player']['score']:4d}"
                        )

        if frames > 0 and now - last_improve > stall_seconds:
            return "stall", {
                "best_y": best_y,
                "frames": frames,
                "last": last_line,
            }

        time.sleep(0.12)

    return "exit", {"best_y": best_y, "frames": frames, "last": last_line}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--trace",
        default=DEFAULT_TRACE,
        help="JSONL trace path (also passed to the game as --trace)",
    )
    ap.add_argument("--timeout", type=float, default=120, help="Hard wall-clock limit (s)")
    ap.add_argument("--stall-s", type=float, default=15, help="Stall detection window (s)")
    ap.add_argument(
        "--stall-dy",
        type=float,
        default=4,
        help="Minimum Y improvement to reset stall timer",
    )
    ap.add_argument("--seed", type=int, default=None, help="Optional RNG seed for the game")
    args = ap.parse_args()

    trace = args.trace
    os.makedirs(os.path.dirname(trace) or ".", exist_ok=True)
    if os.path.exists(trace):
        os.remove(trace)

    env = os.environ.copy()
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    # board_config in lib/, usdl2 in utils/; examples/ so tower_climb.py resolves
    # as a script (sys.path[0]) without needing this on PYTHONPATH too — kept
    # for parity with a package-style invocation.
    env["PYTHONPATH"] = os.pathsep.join(
        [
            os.path.join(SRC_DIR, "lib"),
            os.path.join(SRC_DIR, "utils"),
            os.path.join(SRC_DIR, "examples"),
        ]
    )
    # Do not set TOWER_CLIMB_*; the game reads argv only.
    python = os.path.join(REPO_ROOT, ".venv", "bin", "python")
    cmd = [python, GAME_SCRIPT, "--bot", "--trace", trace]
    if args.seed is not None:
        cmd.extend(["--seed", str(args.seed)])
    proc = subprocess.Popen(
        cmd,
        cwd=SRC_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    status, detail = watch_trace(
        trace,
        proc,
        hard_timeout_s=args.timeout,
        stall_seconds=args.stall_s,
        stall_improve_y=args.stall_dy,
    )
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    if not os.path.exists(trace):
        print("FAIL: no trace written", file=sys.stderr)
        if out:
            print(out[-2000:], file=sys.stderr)
        return 1

    result = analyze(trace)
    print(json.dumps(result, indent=2))
    print(f"trace: {trace}")

    if status == "stall":
        print(
            f"FAIL: stalled for {args.stall_s:.0f}s without climbing "
            f"{args.stall_dy:.0f}px (best_y={detail.get('best_y')})",
            file=sys.stderr,
        )
        return 1
    if status == "timeout":
        print(f"FAIL: hard timeout after {args.timeout}s", file=sys.stderr)
        return 1
    if not result["won"]:
        print("FAIL: bot did not reach tree top", file=sys.stderr)
        return 1
    print("OK: tree top reached")
    return 0


if __name__ == "__main__":
    sys.exit(main())
