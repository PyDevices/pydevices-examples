#!/usr/bin/env python3
"""LVGL keypad-mapping diagnostic for the PyDevices integration workspace.

Run from the pydevices-examples repository root::

    micropython tools/lvgl_input_probe.py --selftest
    cd lib && micropython ../tools/lvgl_input_probe.py

The core keyboard/keypad contract probe lives in the sibling pydevices
repository at ``tools/input_probe.py``. This file owns only the LVGL mapping
layer supplied by ``display_driver``.
"""

import sys

_file = __file__.replace("\\", "/")
_tools = _file.rsplit("/", 1)[0] if "/" in _file else "."
_root = _tools.rsplit("/", 1)[0] if "/" in _tools else "."
_workspace = _root.rsplit("/", 1)[0] if "/" in _root else ".."
for _path in (
    _workspace + "/pydevices/lib",
    _workspace + "/pydevices/tools",
    _root + "/lib",
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import input_probe as core_probe  # noqa: E402

import events  # noqa: E402
import keys  # noqa: E402


def _load_lvgl():
    import display_driver
    import lvgl as lv

    return display_driver, lv


def _lv_label(lv, mapped):
    if mapped is None:
        return "None"
    for name in (
        "UP",
        "DOWN",
        "LEFT",
        "RIGHT",
        "ENTER",
        "ESC",
        "NEXT",
        "PREV",
        "BACKSPACE",
        "DEL",
        "HOME",
        "END",
    ):
        if getattr(lv.KEY, name, None) == mapped:
            return "lv.KEY.%s" % name
    if isinstance(mapped, int) and 32 <= mapped <= 126:
        return "char %r" % chr(mapped)
    return "raw %r" % (mapped,)


class _Result:
    def __init__(self):
        self.ok = 0
        self.fail = 0

    def check(self, name, condition, detail=""):
        if condition:
            self.ok += 1
            print("PASS  %s" % name)
        else:
            self.fail += 1
            print("FAIL  %s  %s" % (name, detail))


def run_selftest():
    display_driver, lv = _load_lvgl()
    map_key = display_driver._lv_key_from_event

    class Ev:
        def __init__(self, key, mod=0, name=""):
            self.key = key
            self.mod = mod
            self.name = name

    result = _Result()
    mapped = map_key(Ev(keys.K_UP))
    result.check("lv_arrows_are_caret", mapped == lv.KEY.UP, _lv_label(lv, mapped))
    mapped = map_key(Ev(keys.K_TAB))
    result.check("lv_tab_is_next", mapped == lv.KEY.NEXT, _lv_label(lv, mapped))
    result.check("lv_modifier_dropped", map_key(Ev(keys.K_LSHIFT)) is None)
    result.check("lv_f1_dropped", map_key(Ev(keys.K_F1)) is None)
    result.check("lv_shift_letter", map_key(Ev(keys.K_a, keys.KMOD_LSHIFT)) == ord("A"))
    result.check("lv_shift_digit", map_key(Ev(keys.K_1, keys.KMOD_LSHIFT)) == ord("!"))
    result.check("lv_tracked_mods", map_key(Ev(keys.K_a), keys.KMOD_LSHIFT) == ord("A"))
    print("----")
    print("%d passed, %d failed" % (result.ok, result.fail))
    return 0 if result.fail == 0 else 1


def run_interactive():
    display_driver, lv = _load_lvgl()
    app = display_driver.app
    map_key = display_driver._lv_key_from_event
    downs = {}

    def _on_key(event):
        if event.type == events.KEYDOWN:
            downs[event.key] = downs.get(event.key, 0) + 1
        line = core_probe.format_key_event(event, downs=downs)
        try:
            line += "  lv→%s" % _lv_label(lv, map_key(event))
        except Exception as exc:
            line += "  lv→ERR:%s" % exc
        print(line)

    print("lvgl_input_probe: focus the display window, then press keys.")
    print("Try letters, Shift+letter, Shift+1, arrows, Tab, modifiers, and F1.")
    for event_type in (events.KEYDOWN, events.KEYUP):
        app.on(event_type, _on_key)
    app.run()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return run_selftest()
    run_interactive()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0) from None
