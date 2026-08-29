#!/usr/bin/env python3
"""Apply in-process settings, then run a script in the same interpreter.

Usage (cwd is ``lib/``)::

    <python> ../tools/multimer_backend_preload.py [--source-workspace] [--env NAME=VALUE]... BACKEND SCRIPT [ARGS...]

``BACKEND`` is a provider name accepted by ``multimer.auto``, or ``-`` to keep
automatic selection.

Environment variables cover direct runs, but Windows MicroPython / CPython
launched from WSL cannot see exported ones, so a sweep across interpreters sets
``MULTIMER_BACKEND`` inside the child before importing ``multimer.auto`` and
uses ``displaydev.env_set()`` for other ``--env`` values. The target script keeps the real command line
(``sys.argv`` is read-only on CircuitPython), so scripts must locate their own
flags anywhere in ``sys.argv`` rather than at a fixed index.

Exits 2 on bad usage and 3 when the backend is unavailable on this host.
"""

import sys

USAGE = "usage: multimer_backend_preload.py [--source-workspace] [--env NAME=VALUE]... BACKEND SCRIPT [ARGS...]"


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
    """Split ``argv`` into (env pairs, backend, script). Returns None on bad usage."""
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
    source_workspace, env, backend, script = parsed

    _bootstrap_path(source_workspace)

    if env:
        from displaydev import env_set

        for name, value in env:
            env_set(name, value)
            print(f"PRELOAD_ENV={name}={value}")

    if backend != "-":
        try:
            _env_set("MULTIMER_BACKEND", backend)
            from multimer import auto as timer

            active = timer.name
            if active != backend:
                raise RuntimeError("multimer.auto was already selected as {!r}".format(active))
        except (ImportError, RuntimeError, ValueError) as exc:
            print(f"MULTIMER_BACKEND_UNAVAILABLE={backend!r}: {exc}")
            return 3
        print(f"MULTIMER_BACKEND_FORCED={active}")

    with open(script) as fh:
        code = fh.read()
    globals_ = {"__name__": "__main__", "__file__": script}
    exec(compile(code, script, "exec"), globals_)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
