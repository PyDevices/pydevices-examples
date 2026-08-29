#!/usr/bin/env python3
"""Run a pydevices-examples example immediately and record its desktop window.

Examples:
    python tools/record.py bouncing_balls
    python tools/record.py bouncing_balls 10
    python tools/record.py logo --duration 3 --resolution 320x240 --scale 1
"""

import argparse
import importlib
import os
from pathlib import Path
import sys
import time

from screenshot import (
    _apply_display_overrides,
    _positive_scale,
    _prepare_paths,
    _resolution,
    _resolve_example,
    _run_example,
)


def _default_output(example):
    return Path("docs") / "videos" / f"{Path(example).stem}.mp4"


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", help="example name, script path, or importable module")
    parser.add_argument(
        "seconds",
        nargs="?",
        type=float,
        help="recording duration in seconds (default: 5)",
    )
    parser.add_argument("-d", "--duration", type=float, help="same as positional seconds")
    parser.add_argument("--fps", type=int, default=12, help="output frame rate (default: 12)")
    parser.add_argument(
        "--resolution",
        type=_resolution,
        metavar="WIDTHxHEIGHT",
        help="override the logical display resolution",
    )
    parser.add_argument(
        "--scale",
        type=_positive_scale,
        help="override the desktop window scale",
    )
    parser.add_argument("-o", "--output", type=Path, help="output MP4 path")
    args = parser.parse_args(argv)
    if args.seconds is not None and args.duration is not None:
        parser.error("use either positional seconds or --duration, not both")
    args.duration = args.duration if args.duration is not None else (args.seconds or 5.0)
    if args.duration <= 0:
        parser.error("duration must be greater than zero")
    if args.fps <= 0:
        parser.error("fps must be greater than zero")
    args.output = args.output or _default_output(args.example)
    return args


def _finish_recording(display, output, fps):
    frames = display.close_frame_recorder()
    return f"saved {output} ({frames} frames at {fps} fps, {type(display).__name__})"


def _install_show_recording(deadline, output, fps):
    """Start, feed, and finish recording from the renderer's main thread."""
    state = {"display": None, "finishing": False}

    def arm(display_class):
        original = display_class.show

        def show(display, *args, **kwargs):
            if state["display"] is None:
                output.parent.mkdir(parents=True, exist_ok=True)
                display.open_frame_recorder(str(output), fps=fps)
                state["display"] = display
            if not state["finishing"] and time.monotonic() >= deadline:
                state["finishing"] = True
                try:
                    print(_finish_recording(display, output, fps), flush=True)
                    os._exit(0)
                except Exception as exc:
                    print(f"recording failed: {type(exc).__name__}: {exc}", flush=True)
                    os._exit(1)
            return original(display, *args, **kwargs)

        display_class.show = show

    try:
        from displaydev.sdldisplay import SDLDisplay

        arm(SDLDisplay)
    except ImportError:
        pass
    try:
        from displaydev.pgdisplay import PGDisplay

        arm(PGDisplay)
    except ImportError:
        pass
    return state


def main(argv=None):
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    _prepare_paths(repo_root)
    _apply_display_overrides(args.resolution, args.scale)
    example = _resolve_example(args.example, repo_root)
    output = args.output.resolve()
    os.chdir(repo_root / "lib")
    ffmpeg_executable = importlib.import_module("frame_recorder").ffmpeg_executable

    if ffmpeg_executable() is None:
        raise SystemExit("record.py requires ffmpeg on PATH or the imageio-ffmpeg Python package")

    deadline = time.monotonic() + args.duration
    state = _install_show_recording(deadline, output, args.fps)
    try:
        _run_example(example)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    display = state["display"]
    if display is None:
        print("recording failed: example did not show a recordable desktop display", flush=True)
        return 1
    try:
        print(_finish_recording(display, output, args.fps), flush=True)
        return 0
    except Exception as exc:
        print(f"recording failed: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
