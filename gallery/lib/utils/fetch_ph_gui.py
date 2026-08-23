"""
fetch_ph_gui.py - Install one Peter Hinch GUI into utils/gui/.

Supported ``which`` values (full upstream repo names):
  micropython-nano-gui, micropython-micro-gui, micropython-touch

Only one ``gui/`` tree is active at a time. If a different core is present, the
directory is emptied before installing. Host compatibility changes are
in-memory only (no edits under ``gui/``).

Callers must define ``SSD`` on their setup module before calling fetch, because
``gui.core.colors`` imports ``SSD`` from ``color_setup`` / ``hardware_setup`` /
``touch_setup``.
"""

_CORE_FILES = {
    "micropython-nano-gui": "nanogui.py",
    "micropython-micro-gui": "ugui.py",
    "micropython-touch": "tgui.py",
}

_PACKAGES = {
    "micropython-nano-gui": "github:PyDevices/pydevices-examples/packages/micropython-nano-gui.json",
    "micropython-micro-gui": "github:PyDevices/pydevices-examples/packages/micropython-micro-gui.json",
    "micropython-touch": "github:PyDevices/pydevices-examples/packages/micropython-touch.json",
}

# colors.py imports SSD from color_setup, which re-enters fetch_ph_gui while
# gui.core.* is mid-import during patching. Treat nested calls as success.
_IN_FETCH = False

# Cross-process lock directory under utils/ — parallel matrix interpreters share
# this tree and otherwise race on empty/install of utils/gui/.
_LOCK_NAME = ".gui_fetch_lock"
_LOCK_WAIT_S = 90
_LOCK_POLL_S = 0.1
_LOCK_PID_NAME = "pid"


def _utils_dir():
    # CPython (esp. Windows PE under WSL UNC) needs native separators so mip
    # can mkdir/open install targets. MP/CP have no ``os.path``.
    import sys

    if sys.implementation.name == "cpython":
        import os

        return os.path.dirname(__file__)
    f = (
        getattr(sys.modules.get(__name__), "__file__", None)
        or getattr(sys.modules.get("fetch_ph_gui"), "__file__", None)
        or __file__
    )
    f = f.replace("\\", "/")
    if "/" in f:
        return f.rsplit("/", 1)[0]
    import os

    for candidate in ("/utils", "utils", "lib/utils", "."):
        try:
            os.stat(candidate)
            return candidate
        except OSError:
            pass
    return "."


def _gui_dir():
    import os
    import sys

    if sys.implementation.name == "cpython":
        return os.path.join(_utils_dir(), "gui")
    for candidate in (_utils_dir() + "/gui", "/utils/gui", "utils/gui", "gui", "lib/utils/gui"):
        try:
            os.stat(candidate)
            return candidate
        except OSError:
            pass
    return _utils_dir() + "/gui"


def _lock_path():
    import sys

    base = _utils_dir()
    if sys.implementation.name == "cpython":
        import os

        return os.path.join(base, _LOCK_NAME)
    return base + "/" + _LOCK_NAME


def _lock_pid_path():
    import sys

    if sys.implementation.name == "cpython":
        import os

        return os.path.join(_lock_path(), _LOCK_PID_NAME)
    return _lock_path() + "/" + _LOCK_PID_NAME


def _pid_alive(pid):
    """Best-effort: True if ``pid`` looks alive; False if clearly dead."""
    if pid is None or pid <= 0:
        return False
    try:
        import os

        if hasattr(os, "kill"):
            os.kill(pid, 0)
            return True
        return False
    except OSError:
        return False
    except Exception:
        return False


def _read_lock_pid():
    path = _lock_pid_path()
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except Exception:
        return None


def _write_lock_pid():
    import os

    path = _lock_pid_path()
    try:
        with open(path, "w") as fh:
            fh.write(str(os.getpid()))
    except Exception:
        pass


def _force_clear_lock():
    """Remove a lock dir left by a crashed / killed matrix worker."""
    path = _lock_path()
    pid_path = _lock_pid_path()
    try:
        import os

        try:
            os.remove(pid_path)
        except OSError:
            pass
        os.rmdir(path)
        return
    except Exception:
        pass
    try:
        import uos

        try:
            uos.remove(pid_path)
        except OSError:
            pass
        uos.rmdir(path)
    except Exception:
        pass


def _acquire_gui_lock():
    """Exclusive mkdir lock; returns True if acquired within ``_LOCK_WAIT_S``.

    Writes a pid file so a later waiter can steal the lock if the holder died
    (fail-fast matrix kills leave empty ``.gui_fetch_lock`` dirs behind).
    """
    import time

    path = _lock_path()
    deadline = time.time() + _LOCK_WAIT_S
    stole = False
    while time.time() < deadline:
        try:
            import os

            os.mkdir(path)
            _write_lock_pid()
            return True
        except OSError:
            pass
        except ImportError:
            try:
                import uos

                uos.mkdir(path)
                _write_lock_pid()
                return True
            except OSError:
                pass
        holder = _read_lock_pid()
        # Empty/stale lock (no pid, or dead holder): steal once per wait.
        if not stole and (holder is None or not _pid_alive(holder)):
            stole = True
            _force_clear_lock()
            continue
        time.sleep(_LOCK_POLL_S)
    return False


def _release_gui_lock():
    _force_clear_lock()


# The last file every one of the three packages installs. The core marker below
# is written 2nd of ~70, so an install that dies partway (a timed-out matrix
# cell, a killed process) leaves gui/core/<marker>.py behind with the rest of
# the tree missing -- and _detect_core() would report the core as installed
# forever after, so every later run failed importing gui.primitives. Requiring
# the file mip writes last means a partial tree reads as absent and is
# reinstalled instead of poisoning the directory.
_TAIL_FILE = "widgets/textbox.py"


def _tree_complete():
    import os
    import sys

    if sys.implementation.name == "cpython":
        path = os.path.join(_gui_dir(), *_TAIL_FILE.split("/"))
    else:
        path = _gui_dir() + "/" + _TAIL_FILE
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def _detect_core():
    """Return which repo name is installed, or None. Uses files only (no import)."""
    import os
    import sys

    if not _tree_complete():
        return None

    found = []
    if sys.implementation.name == "cpython":
        core = os.path.join(_gui_dir(), "core")
        for which, fname in _CORE_FILES.items():
            try:
                os.stat(os.path.join(core, fname))
                found.append(which)
            except OSError:
                pass
    else:
        for which, fname in _CORE_FILES.items():
            try:
                os.stat(_gui_dir() + "/core/" + fname)
                found.append(which)
            except OSError:
                pass
    if len(found) == 1:
        return found[0]
    return None


def _purge_gui_modules():
    import sys

    for name in list(sys.modules):
        if name == "gui" or name.startswith("gui."):
            del sys.modules[name]


def _rmtree(path):
    import os

    try:
        names = os.listdir(path)
    except OSError:
        return
    for name in names:
        child = path + "/" + name
        try:
            os.remove(child)
        except OSError:
            _rmtree(child)
            try:
                os.rmdir(child)
            except OSError:
                pass
    try:
        os.rmdir(path)
    except OSError:
        pass


def _empty_gui():
    _purge_gui_modules()
    _rmtree(_gui_dir())


def _gui_exists():
    import os

    try:
        os.listdir(_gui_dir())
        return True
    except OSError:
        return False


def _patch_time_ticks():
    """CPython lacks MicroPython time.ticks_*; ugui/tgui import them at load."""
    import time

    if not hasattr(time, "ticks_ms"):

        def ticks_ms():
            return int(time.time() * 1000)

        def ticks_diff(a, b):
            return a - b

        def ticks_add(a, b):
            return a + b

        time.ticks_ms = ticks_ms
        time.ticks_diff = ticks_diff
        time.ticks_add = ticks_add
        if not hasattr(time, "sleep_ms"):

            def sleep_ms(ms):
                time.sleep(ms / 1000.0)

            time.sleep_ms = sleep_ms


def _patch_machine_pin():
    """Stub machine.Pin on hosts that lack it.

    Covers CPython desktop, MicroPython-WASM, and unix MicroPython (``machine``
    exists but has no ``Pin`` — only ``PinBase`` / ``Signal``). Unix MP's
    native ``machine`` rejects ``setattr`` (``AttributeError``), so when Pin is
    missing we replace ``sys.modules['machine']`` with a thin proxy that exposes
    the stub and forwards other attributes.

    Uses a plain class instance rather than ``types.ModuleType(name)`` — the
    latter's attribute exists on MicroPython-WASM but its constructor raises
    ``TypeError: can't create 'module' instances`` (native interpreter
    limitation). A plain object works identically for ``sys.modules``
    caching: ``import machine`` returns whatever is registered there.
    """
    import sys

    class Pin:
        IN = 0
        OUT = 1
        OPEN_DRAIN = 2
        PULL_UP = 1
        PULL_DOWN = 2

        def __init__(self, *args, **kwargs):
            self._v = 1

        def value(self, v=None):
            if v is None:
                return self._v
            self._v = v
            return None

        def irq(self, *args, **kwargs):
            return None

    mod = sys.modules.get("machine")
    if mod is None:
        try:
            import machine as mod  # noqa: F811
        except ImportError:
            mod = None

    if mod is not None and hasattr(mod, "Pin"):
        return

    if mod is not None:
        try:
            mod.Pin = Pin
            if hasattr(mod, "Pin"):
                return
        except (AttributeError, TypeError):
            pass

        class _MachineProxy:
            def __init__(self, real, pin):
                self._real = real
                self.Pin = pin

            def __getattr__(self, name):
                return getattr(self._real, name)

        sys.modules["machine"] = _MachineProxy(mod, Pin)
        return

    class _FakeMachineModule:
        pass

    fake = _FakeMachineModule()
    fake.Pin = Pin
    sys.modules["machine"] = fake


def _prime_primitives():
    """Make gui.primitives lazy imports work on CPython (MP-style __import__)."""
    try:
        import importlib

        from gui import primitives
    except ImportError:
        return

    attrs = getattr(primitives, "_attrs", None)
    if not attrs:
        return

    def _getattr(attr):
        mod = attrs.get(attr, None)
        if mod is None:
            raise AttributeError(attr)
        value = getattr(importlib.import_module("." + mod, "gui.primitives"), attr)
        setattr(primitives, attr, value)
        return value

    primitives.__getattr__ = _getattr


def _patch_utime():
    """Alias utime -> time on CPython (after ticks_* are installed)."""
    import sys
    import time

    if "utime" in sys.modules:
        return
    try:
        import utime  # noqa: F401

        return
    except ImportError:
        sys.modules["utime"] = time


class _AsyncioCompat:
    """Asyncio facade that protects host event loops (PyScript, Jupyter) from asyncio.run / new_event_loop calls."""

    def __init__(self, backend):
        self._backend = backend

    def _running(self):
        import sys

        if sys.platform in ("emscripten", "webassembly", "wasi"):
            return True
        current_task = getattr(self._backend, "current_task", None)
        if current_task is not None:
            try:
                return current_task() is not None
            except Exception:
                pass
        get_running_loop = getattr(self._backend, "get_running_loop", None)
        if get_running_loop is not None:
            try:
                get_running_loop()
                return True
            except Exception:
                pass
        return False

    def run(self, coro):
        """Run normally, or schedule ``coro`` when a host loop already exists."""
        if self._running():
            return self._backend.create_task(coro)
        return self._backend.run(coro)

    def new_event_loop(self):
        """Create a loop normally, but never replace an active host loop."""
        if self._running():
            try:
                return self._backend.get_running_loop()
            except Exception:
                try:
                    return self._backend.get_event_loop()
                except Exception:
                    pass
        return self._backend.new_event_loop()

    def sleep(self, delay):
        """Sleep while ensuring a zero-delay yield reaches the browser host loop."""
        return self._backend.sleep(0.001 if delay <= 0 else delay)

    def sleep_ms(self, delay):
        """Millisecond sleep with a browser-safe minimum for cooperative yields."""
        sleeper = getattr(self._backend, "sleep_ms", None)
        if sleeper is not None:
            return sleeper(1 if delay <= 0 else delay)
        return self._backend.sleep(0.001 if delay <= 0 else delay / 1000.0)

    def __getattr__(self, name):
        return getattr(self._backend, name)


def _install_asyncio_compat():
    """Install host-loop-safe asyncio facade as both asyncio and uasyncio."""
    import sys

    existing = sys.modules.get("asyncio")
    if existing is not None and isinstance(existing, _AsyncioCompat):
        sys.modules["uasyncio"] = existing
        return existing

    real = None
    if existing is not None and hasattr(existing, "create_task"):
        real = existing
    else:
        try:
            import asyncio as real
        except ImportError:
            try:
                import uasyncio as real
            except ImportError:
                real = None

    if real is None:
        return None

    compat = _AsyncioCompat(real)
    sys.modules["asyncio"] = compat
    sys.modules["uasyncio"] = compat
    return compat


def _patch_uasyncio():
    """Alias uasyncio -> asyncio with host-loop-safe async compat facade."""
    return _install_asyncio_compat()


def _patch_micropython_const():
    """Provide ``const`` builtin used by ugui/tgui on MicroPython."""
    import builtins

    if hasattr(builtins, "const"):
        return
    try:
        from micropython import const as _const
    except ImportError:

        def _const(x):
            return x

    builtins.const = _const


def _apply_patches(which):
    _patch_uasyncio()
    if which in ("micropython-micro-gui", "micropython-touch"):
        _patch_micropython_const()
        _patch_time_ticks()
        _patch_utime()
        _patch_machine_pin()
        _prime_primitives()


def fetch_ph_gui(which, apply_patches=True):
    """Ensure ``which`` GUI is in utils/gui/ and optionally patched.

    Returns True when ready. Pass ``apply_patches=False`` when pre-seeding
    (e.g. PyScript loader) before the setup module defines ``SSD`` — callers
    that import ``color_setup`` / ``hardware_setup`` / ``touch_setup`` will
    call again with patches enabled.

    Uses ``mip.install`` (firmware on MicroPython; portable ``mip.py`` from
    pydevices ``utils/`` on CPython / Pyodide / CircuitPython).
    """
    global _IN_FETCH

    if which not in _CORE_FILES:
        raise ValueError(
            "which must be micropython-nano-gui, micropython-micro-gui, or micropython-touch"
        )

    if _IN_FETCH:
        return _detect_core() == which

    # Fast path without lock when the desired core is already present.
    if _detect_core() == which:
        if apply_patches:
            _apply_patches(which)
        return True

    if not _acquire_gui_lock():
        # Another process may have finished installing while we waited.
        if _detect_core() == which:
            if apply_patches:
                _apply_patches(which)
            return True
        return False

    _IN_FETCH = True
    try:
        present = _detect_core()
        if present == which:
            if apply_patches:
                _apply_patches(which)
            return True

        if present is not None or _gui_exists():
            _empty_gui()

        try:
            import mip
        except ImportError:
            return False

        try:
            mip.install(_PACKAGES[which], target=_utils_dir(), mpy=False)
        except Exception:
            return False

        _purge_gui_modules()
        if _detect_core() == which:
            if apply_patches:
                _apply_patches(which)
            return True
        return False
    finally:
        _IN_FETCH = False
        _release_gui_lock()
