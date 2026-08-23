# gallery: skip
# SPDX-License-Identifier: MIT
"""
key_probe.py — print key codes from the host event pump.

Run from pydevices-examples/lib::

    python examples/car_cluster/key_probe.py

Focus the canvas, then press keys. Output shows SDL-style ``event.key``,
``keys`` name when known, suggested ``lv.KEY`` mapping, and digit/throttle
interpretation for the car cluster.

Press Ctrl+Q (or your platform quit chord) to exit.
"""

import sys

_file = __file__.replace("\\", "/")
_PKG = _file.rsplit("/", 1)[0]
_parts = _file.split("/")
if "examples" in _parts:
    _idx = _parts.index("examples")
    _src = "/".join(_parts[:_idx]) if _idx else "."
else:
    _src = "."
if _src and _src not in sys.path:
    sys.path.insert(0, _src)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import display_driver  # noqa: E402, F401
from display_driver import app  # noqa: E402
import lvgl as lv  # noqa: E402

import events  # noqa: E402
import keys  # noqa: E402

try:
    from input_map import digit_from_key, remap_nav_key
except ImportError:
    digit_from_key = None
    remap_nav_key = None

_LV_KEY_NAMES = {
    lv.KEY.UP: "lv.KEY.UP",
    lv.KEY.DOWN: "lv.KEY.DOWN",
    lv.KEY.LEFT: "lv.KEY.LEFT",
    lv.KEY.RIGHT: "lv.KEY.RIGHT",
    lv.KEY.ENTER: "lv.KEY.ENTER",
    lv.KEY.ESC: "lv.KEY.ESC",
    lv.KEY.NEXT: "lv.KEY.NEXT",
    lv.KEY.PREV: "lv.KEY.PREV",
}


def _key_name(code):
    for name in dir(keys):
        if name.startswith("K_") and getattr(keys, name, None) == code:
            return name
    return "?"


def _on_key(event):
    if event.type not in (events.KEYDOWN, events.KEYUP):
        return
    phase = "DOWN" if event.type == events.KEYDOWN else "UP"
    code = event.key
    name = _key_name(code)
    line = "KEY%s  code=%s  keys.%s" % (phase, code, name)
    if digit_from_key is not None:
        d = digit_from_key(code)
        if d is not None:
            gear = 10 if d == 0 else d
            line += "  digit=%d  gear=%d  throttle=%.2f" % (d, gear, d / 10.0 if d else 0.05)
    if remap_nav_key is not None:
        mapped = remap_nav_key(code)
        if mapped is not None:
            line += "  -> %s (%d)" % (_LV_KEY_NAMES.get(mapped, "lv.KEY"), mapped)
    print(line)


print("key_probe: focus the canvas.")
print("Try: arrow keys, Enter, digits 0-9 (top row and keypad).")
print("Ctrl+Q to quit.\n")

for et in (events.KEYDOWN, events.KEYUP):
    app.on(et, _on_key)
