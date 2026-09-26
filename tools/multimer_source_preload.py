#!/usr/bin/env python3
"""Apply in-process settings, then run a script in the same interpreter.

Usage (cwd is ``lib/``)::

    <python> ../tools/multimer_source_preload.py [--source-workspace] [--env NAME=VALUE]... SOURCE SCRIPT [ARGS...]

``SOURCE`` is a multimer wake source (``signal``, ``pending``, ``asyncio``,
``machine``, ``wasm``, ``native``, ``none``), or ``-`` to keep automatic
selection.

Environment variables cover direct runs, but Windows MicroPython / CPython
launched from WSL cannot see exported ones, so a sweep across interpreters sets
``MULTIMER_SOURCE`` inside the child, makes multimer choose its source at once,
and checks that the one it got is the one asked for. Other ``--env`` values go
through ``displaydev.env_set()``. The target script keeps the real command line
(``sys.argv`` is read-only on CircuitPython), so scripts must locate their own
flags anywhere in ``sys.argv`` rather than at a fixed index.

Exits 2 on bad usage and 3 when the source is unavailable on this host.
"""

import sys

USAGE = "usage: multimer_source_preload.py [--source-workspace] [--env NAME=VALUE]... SOURCE SCRIPT [ARGS...]"


def _env_set(key, value):
    """Set a real process environment value on CPython and small ports."""
    import os

    changed = False
    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            environ[key] = value
            changed = True
        except Exception:
            pass
    putenv = getattr(os, "putenv", None)
    if putenv is not None:
        try:
            putenv(key, value)
            changed = True
        except Exception:
            pass
    if not changed:
        raise ImportError("process environment cannot be changed")


def force_source(name):
    """Make multimer select ``name`` now; return the source it got.

    multimer reads ``MULTIMER_SOURCE`` when it first needs a wake source, and a
    forced source that cannot start falls back to ``none`` without raising. So
    select it here, before the script arms anything, and raise when the source
    in use is not the one asked for.
    """
    _env_set("MULTIMER_SOURCE", name)
    import multimer
    from multimer import _dispatch

    _dispatch._ensure_source()
    info = multimer.info()
    active = info.get("source")
    if active != name:
        raise RuntimeError(
            "multimer chose {!r}: {}".format(active, info.get("source_error", "already selected"))
        )
    return active


def _bootstrap_path(source_workspace=False):
    """Mirror ``utils/path.py``: make ``lib`` / ``utils`` importable from ``src``."""
    directories = ["utils", "lib", "."]
    if source_workspace:
        # The LVGL matrix validates coordinated sibling branches before their
        # packages and frozen interpreter copies are released.
        directories.extend(
            (
                "../../pydevices/drivers",
                "../../pydevices/utils",
                "../../pydevices/lib",
                "../../lvgl-bindings/python",
            )
        )
    for directory in directories:
        if directory not in sys.path:
            sys.path.insert(0, directory)


def _parse(argv):
    """Split ``argv`` into (source_workspace, env pairs, source, script). Returns None on bad usage."""
    env = []
    source_workspace = False
    rest = argv[1:]
    while rest and rest[0] in ("--source-workspace", "--env"):
        if rest[0] == "--source-workspace":
            source_workspace = True
            rest = rest[1:]
        else:
            if len(rest) < 2 or "=" not in rest[1]:
                return None
            name, _, value = rest[1].partition("=")
            env.append((name, value))
            rest = rest[2:]
    if len(rest) < 2:
        return None
    return source_workspace, env, rest[0], rest[1]


def main(argv):
    parsed = _parse(argv)
    if parsed is None:
        print(USAGE)
        return 2
    source_workspace, env, source, script = parsed

    _bootstrap_path(source_workspace)

    if env:
        from displaydev import env_set

        for name, value in env:
            env_set(name, value)
            print(f"PRELOAD_ENV={name}={value}")

    if source != "-":
        try:
            active = force_source(source)
        except (ImportError, RuntimeError, ValueError) as exc:
            print(f"MULTIMER_SOURCE_UNAVAILABLE={source!r}: {exc}")
            return 3
        print(f"MULTIMER_SOURCE_FORCED={active}")

    with open(script) as fh:
        code = fh.read()
    globals_ = {"__name__": "__main__", "__file__": script}
    exec(compile(code, script, "exec"), globals_)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
