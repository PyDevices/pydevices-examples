"""Portable, idempotent search-path configuration for PyDevices interpreters.

Applies the documented interpreter search path when the environment has not
already supplied it:

    MicroPython / CircuitPython -- ``MICROPYPATH``
        ``.:.frozen:lib:utils:~/.micropython/lib:/usr/lib/micropython``
    Every other interpreter -- ``PYTHONPATH``
        ``.:lib:utils``

Importing this module is *optional*: with the matching variable exported as
documented, every entry is already on ``sys.path`` and importing here is a
no-op. Entries are only ever added -- nothing is removed or reordered, so a
host that arranges its own path keeps that arrangement.

``~/.micropython/lib`` and ``/usr/lib/micropython`` are MicroPython and
CircuitPython package locations, which is why ``PYTHONPATH`` omits them:
adding them on CPython puts a MIP tree ahead of ``site-packages`` and shadows
pip-installed packages with ``.py`` sources meant for another interpreter.

See https://github.com/PyDevices/pydevices/blob/main/docs/install-workflows.md
"""

import os
import sys


def _env_get(name):
    """Portable getenv (CPython / MicroPython / CircuitPython)."""
    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            val = environ.get(name)
            if val:
                return val
        except Exception:
            pass
    getenv = getattr(os, "getenv", None)
    if getenv is not None:
        try:
            return getenv(name)
        except Exception:
            return None
    return None


def _implementation_name():
    impl = getattr(sys, "implementation", None)
    name = getattr(impl, "name", None) if impl is not None else None
    return str(name or "").lower()


# MicroPython and CircuitPython read MICROPYPATH; everything else reads
# PYTHONPATH. The two variables document different entries, so the interpreter
# decides which set belongs on sys.path.
USES_MICROPYPATH = _implementation_name() in ("micropython", "circuitpython")
PATH_VAR = "MICROPYPATH" if USES_MICROPYPATH else "PYTHONPATH"

_IS_WINDOWS = os.sep == "\\" or getattr(sys, "platform", "") == "win32"


def _documented_targets():
    """The entries ``PATH_VAR`` is documented to contain, in order."""
    if not USES_MICROPYPATH:
        return ["", "lib", "utils"]

    # Home without os.path, which CircuitPython does not ship.
    home = _env_get("HOME") or _env_get("USERPROFILE") or "~"
    home = home.replace("\\", "/").rstrip("/")
    targets = ["", ".frozen", "lib", "utils", home + "/.micropython/lib"]
    # The documented Windows MICROPYPATH has no /usr/lib/micropython.
    if not _IS_WINDOWS:
        targets.append("/usr/lib/micropython")
    return targets


def _cwd():
    getcwd = getattr(os, "getcwd", None)
    if getcwd is None:
        return ""
    try:
        return getcwd().replace("\\", "/").rstrip("/")
    except Exception:
        return ""


_CWD = _cwd()
_HOME = (_env_get("HOME") or _env_get("USERPROFILE") or "").replace("\\", "/").rstrip("/")


def _is_absolute(p):
    # POSIX root, or a Windows drive such as "C:/Users".
    return p.startswith("/") or (len(p) > 1 and p[1] == ":")


def _norm(path):
    """Comparison key for one search-path entry.

    Relative entries resolve against the current directory so that ``lib`` and
    the absolute form CPython stores for it (sys.path entries are absolutized
    at startup since 3.11) compare equal -- otherwise exporting the documented
    variable would not be detected and entries would be added twice.
    """
    p = path.replace("\\", "/").rstrip("/")
    if p == ".frozen":
        return ".frozen"  # virtual MicroPython path; never resolved
    if p.startswith("~/") and _HOME:
        p = _HOME + p[1:]
    elif p in ("", "."):
        p = _CWD
    elif not _is_absolute(p) and _CWD:
        p = _CWD + "/" + p
    if _IS_WINDOWS:
        p = p.lower()
    return p


TARGETS = _documented_targets()


def apply(path=None):
    """Add missing documented entries to *path* (default ``sys.path``).

    Present entries keep their position; missing ones are inserted at the
    front in documented order, matching what exporting ``PATH_VAR`` would
    have produced. Returns the entries added, so a second call returns ``[]``.
    """
    if path is None:
        path = sys.path

    seen = []
    for p in path:
        key = _norm(p)
        if key not in seen:
            seen.append(key)

    # Walk the documented order, keeping an anchor just past the last
    # documented entry seen in *path*. Missing entries go in at the anchor so
    # they land in documented order *relative to the ones already there* --
    # inserting them all at the front would push, say, ``lib`` ahead of an
    # already-present ``.frozen`` and shadow frozen modules with mounted ones.
    missing = []
    anchor = 0
    for target in TARGETS:
        key = _norm(target)
        if key in seen:
            for index, entry in enumerate(path):
                if _norm(entry) == key:
                    anchor = max(anchor, index + 1)
                    break
            continue
        seen.append(key)
        missing.append(target)
        path.insert(anchor, target)
        anchor += 1
    return missing


added = apply()
if added:
    print(
        "path.py: {} entries added: {}".format(PATH_VAR, ":".join(entry or "." for entry in added))
    )
else:
    print("path.py: {} already satisfied".format(PATH_VAR))
