# deps: pygraphics
# utils: console
"""
console_advanced_demo.py
========================

`Console` doing the job it exists for: being the system terminal.

Three things are on show here.

1. **`os.dupterm(console)`** — on MicroPython (unix and most MCU ports) this
   mirrors the REPL onto the display.  Everything the REPL prints, including
   tracebacks and its line-editing escape sequences, is rendered by the
   console.  CircuitPython and CPython have no `os.dupterm`, so the demo just
   says so and keeps going as a plain terminal.

2. **An injectable reader** — `Console` never imports an input stack; it takes
   any object with `read()` / `readinto()`.  `KeyReader` below merges two
   sources into one: `appdev` key events (so the display window's keyboard
   drives the REPL) and whatever is already waiting on the port's stdin (so the
   terminal you launched from keeps working).  On the unix port `os.dupterm`
   routes *all* terminal input through this object, which is why the stdin tap
   matters; a console left with the default `reader=None` gets that tap on its
   own.

3. **Status labels** — the title bar and the three status fields take plain
   strings or zero-argument callables.  Callables are re-evaluated on a timer;
   because an `appdev.App` is passed in, the console borrows the app's timer
   instead of allocating one of its own.

Run it from an interactive interpreter so there is a REPL to mirror::

    micropython -i examples/console_advanced_demo.py

Without `-i` the script still runs; there is just nothing typing at the far end.
"""

import board_config
import appdev

app = appdev.App(board_config)

import gc
import os
import sys

from console import Console
import events
import keys
from multimer import ticks_diff, ticks_ms

try:
    import pydevices_test_mode

    _test_mode = pydevices_test_mode.ENABLED
except ImportError:
    _test_mode = False


def _stdin_tap():
    """A non-blocking peek at stdin, or None where that is not possible."""
    try:
        import select
    except ImportError:
        return None
    try:
        poller = select.poll()
        poller.register(sys.stdin, select.POLLIN)
    except (AttributeError, OSError, TypeError):
        return None

    def ready():
        return bool(poller.poll(0))

    return ready


class KeyReader:
    """Queue `appdev` key events as bytes for `Console(reader=...)`.

    Deliberately small: this is the shape a reader has to have, not a complete
    keyboard driver.  Printable ASCII, the common editing keys, and the arrow
    keys the REPL's line editor understands are enough to type at a prompt.
    Anything already waiting on stdin is passed through as well, so the
    launching terminal and the display window both reach the REPL.
    """

    _KEYS = {
        keys.K_RETURN: b"\r",
        keys.K_BACKSPACE: b"\x08",
        keys.K_TAB: b"\t",
        keys.K_ESCAPE: b"\x1b",
        keys.K_UP: b"\x1b[A",
        keys.K_DOWN: b"\x1b[B",
        keys.K_RIGHT: b"\x1b[C",
        keys.K_LEFT: b"\x1b[D",
    }

    def __init__(self, app):
        self._buf = b""
        self._stdin_ready = _stdin_tap()
        self._stdin = getattr(sys.stdin, "buffer", None)
        app.on(events.KEYDOWN, self._on_key)

    def _on_key(self, e):
        data = self._KEYS.get(e.key)
        if data is None:
            if not 0x20 <= e.key < 0x7F:
                return
            char = chr(e.key)
            if e.mod & keys.KMOD_SHIFT:
                char = char.upper()
            elif e.mod & keys.KMOD_CTRL:
                char = chr(e.key & 0x1F)
            data = char.encode()
        self._buf += data

    def read(self, nbytes=1):
        """Return queued bytes, or None for "nothing yet" (never b"", which is EOF)."""
        if not self._buf and self._stdin is not None and self._stdin_ready():
            self._buf += self._stdin.read(1) or b""
        if not self._buf:
            return None
        data, self._buf = self._buf[:nbytes], self._buf[nbytes:]
        return data


def free_memory():
    """Free bytes, however this interpreter reports them."""
    if hasattr(gc, "mem_free"):
        return "free {:,}".format(gc.mem_free())
    try:
        from psutil import virtual_memory

        return "free {:,}".format(virtual_memory().free)
    except ImportError:
        return ""


maj, minor = sys.implementation.version[:2]
_start = ticks_ms()

console = Console(
    board_config.display_drv,
    font=8,
    title="{} {}.{}".format(sys.implementation.name, maj, minor),
    left=sys.platform,
    middle=lambda: "up {}s".format(ticks_diff(ticks_ms(), _start) // 1000),
    right=free_memory,
    app=app,
    reader=KeyReader(app),
    # The app owns display refresh, so the console does not also call show() --
    # except under the example harness, which runs the app without it.
    auto_show=_test_mode,
)

console.write("console_advanced_demo\n", fg=Console.BRIGHT_GREEN)
console.write("{} columns x {} rows\n".format(console.cols, console.rows))
console.write("-" * console.cols + "\n")

if _test_mode:
    console.write("Test mode: skipping os.dupterm.\n", fg=Console.BRIGHT_YELLOW)
elif hasattr(os, "dupterm"):
    console.write("os.dupterm active -- the REPL is on the display.\n")
    console.write("Type here; try help() or console.cls().\n", fg=Console.GREY)
    os.dupterm(console)
else:
    console.write(
        "No os.dupterm on this port; running as a plain terminal.\n",
        fg=Console.BRIGHT_YELLOW,
    )
    for index in range(16):
        console.write("color {:2d} ".format(index), fg=index)
        console.write("reverse\n", fg=Console.BLACK, bg=index)

#### Things to try at the mirrored REPL
# console.cls()                    # clear the text area
# console.label(Console.LEFT, "hi", Console.BRIGHT_RED)
# console.hide()                   # release the display
# console.show()                   # take it back, text intact
