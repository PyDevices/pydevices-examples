#!/usr/bin/env python3
"""Run a pydevices-examples example and save its desktop window as a PNG.

Examples:
    python tools/screenshot.py hello.py
    python tools/screenshot.py bouncing_balls 3
    python tools/screenshot.py logo --delay 2 --resolution 320x240 --scale 1
"""

import argparse
import binascii
import os
from pathlib import Path
import runpy
import struct
import sys
import time
import zlib


def _png_chunk(kind, data):
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", binascii.crc32(payload))


def save_rgb_png(path, pixels, width, height):
    """Write packed top-to-bottom RGB24 pixels as a PNG without Pillow."""
    stride = width * 3
    if len(pixels) != stride * height:
        raise ValueError(
            f"RGB buffer has {len(pixels)} bytes; expected {stride * height} for {width}x{height}"
        )
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        start = y * stride
        rows.extend(pixels[start : start + stride])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(b"\x89PNG\r\n\x1a\n")
        stream.write(_png_chunk(b"IHDR", header))
        stream.write(_png_chunk(b"IDAT", zlib.compress(rows)))
        stream.write(_png_chunk(b"IEND", b""))


def _default_output(example):
    return Path("docs") / "screenshots" / f"{Path(example).stem}.png"


def _resolve_example(example, repo_root):
    path = Path(example)
    candidates = (path, repo_root / "lib" / "examples" / path)
    if not path.suffix:
        candidates += (repo_root / "lib" / "examples" / f"{example}.py",)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return example


def _resolution(value):
    try:
        width_text, height_text = value.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("resolution must be WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("resolution dimensions must be greater than zero")
    return width, height


def _positive_scale(value):
    try:
        scale = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("scale must be a number") from exc
    if scale <= 0:
        raise argparse.ArgumentTypeError("scale must be greater than zero")
    return scale


def _apply_display_overrides(resolution, scale):
    from displaydev import env_set

    if resolution is not None:
        width, height = resolution
        env_set("PYDEVICES_WIDTH", width)
        env_set("PYDEVICES_HEIGHT", height)
    if scale is not None:
        env_set("PYDEVICES_SCALE", scale)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", help="example script path or importable module name")
    parser.add_argument(
        "seconds",
        nargs="?",
        type=float,
        help="seconds to wait before capture (default: 1)",
    )
    parser.add_argument("-d", "--delay", type=float, help="same as positional seconds")
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
    parser.add_argument("-o", "--output", type=Path, help="output PNG path")
    args = parser.parse_args(argv)
    if args.seconds is not None and args.delay is not None:
        parser.error("use either positional seconds or --delay, not both")
    args.delay = args.delay if args.delay is not None else (args.seconds or 1.0)
    if args.delay < 0:
        parser.error("delay must not be negative")
    args.output = args.output or _default_output(args.example)
    return args


def _prepare_paths(repo_root):
    src = repo_root / "lib"
    tools = repo_root / "tools"
    hw = repo_root.parent / "pydevices"
    for path in (
        str(tools),
        str(src),
        str(src / "lib"),
        str(src / "utils"),
        str(hw / "lib"),
        str(hw / "utils"),
        str(hw / "drivers" / "display"),
    ):
        if Path(path).is_dir() and path not in sys.path:
            sys.path.insert(0, path)
    import sibling_repos

    sibling_repos.prepend_sibling_sys_path(repo_root=str(repo_root))


def _run_example(example):
    if isinstance(example, Path):
        runpy.run_path(str(example), run_name="__main__")
    else:
        runpy.run_module(example, run_name="__main__", alter_sys=True)


def _capture(output):
    board_config = sys.modules.get("board_config")
    if board_config is None:
        raise RuntimeError("example did not import board_config before the capture deadline")
    display_drv = board_config.display_drv
    capture = getattr(display_drv, "capture_rgb", None)
    if capture is None:
        raise RuntimeError(f"{type(display_drv).__name__} does not support desktop screenshots")
    pixels, width, height = capture()
    save_rgb_png(output, pixels, width, height)
    return f"saved {output} ({width}x{height}, {type(display_drv).__name__})"


def _install_show_capture(deadline, output):
    """Capture from a display ``show()`` call on the renderer's main thread."""
    state = {"capturing": False}

    def arm(display_class):
        original = display_class.show

        def show(display, *args, **kwargs):
            result = original(display, *args, **kwargs)
            if (
                not state["capturing"]
                and time.monotonic() >= deadline
                and display is getattr(sys.modules.get("board_config"), "display_drv", None)
            ):
                state["capturing"] = True
                try:
                    print(_capture(output), flush=True)
                    os._exit(0)
                except Exception as exc:
                    print(f"screenshot failed: {type(exc).__name__}: {exc}", flush=True)
                    os._exit(1)
            return result

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


def main(argv=None):
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parent.parent
    _prepare_paths(repo_root)
    _apply_display_overrides(args.resolution, args.scale)
    example = _resolve_example(args.example, repo_root)
    output = args.output.resolve()
    os.chdir(repo_root / "lib")

    deadline = time.monotonic() + args.delay
    _install_show_capture(deadline, output)
    try:
        _run_example(example)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    try:
        print(_capture(output), flush=True)
        return 0
    except Exception as exc:
        print(f"screenshot failed: {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
