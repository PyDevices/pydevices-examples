# deps: palettes
# gallery: binaries
"""
apollo.py — Apollo Guidance Computer DSKY emulator.

Written for 320×480 displays. Other resolutions may show or behave oddly
(scrolling, touch mapping, and layout assume that viewport size).
"""
import gc
import sys

try:
    from gc import mem_free
except ImportError:
    try:
        from psutil import virtual_memory

        def mem_free():
            return virtual_memory().free
    except ImportError:

        def mem_free():
            return 0


def _pkg_dir(file):
    path = str(file).replace("\\", "/")
    return path.rsplit("/", 1)[0] if "/" in path else "."


_PKG_DIR = _pkg_dir(__file__)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

gc.collect()
mem = mem_free()
print(f"Free memory at start: {mem:,}")

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
import dsky
import time

from multimer import ticks_add, ticks_diff, ticks_ms

_last_time = (0, 0, 0, 0, 0, 0)
_key_busy = False
_scrolling = False
_scroll_i = 0
_scroll_end = 0
_key_release_at = None
_pending_key = None


def _init_apollo():
    dsky.init_screen()
    display_drv.show()

    dsky.write_string("42", dsky.prog_pos)
    dsky.write_string("01", dsky.verb_pos)
    dsky.write_string("23", dsky.noun_pos)
    display_drv.show()


def _update_time():
    global _last_time
    y, mo, d, h, m, s, *_ = time.localtime()
    if s != _last_time[5]:
        dsky.write_string(f"{h:02}:{m:02}:{s:02}", dsky.data2_pos)
        if (y, mo, d) != _last_time[:3]:
            dsky.write_string(f"{y-2000:02}.{mo:02}.{d:02}", dsky.data1_pos)
        _last_time = (y, mo, d, h, m, s)
        gc.collect()
        dsky.write_string(f"{mem-mem_free():7}", dsky.data3_pos)
        display_drv.show()


def _scroll_step():
    global _scrolling, _scroll_i
    if not _scrolling:
        return
    display_drv.vscsad(_scroll_i)
    display_drv.show()
    _scroll_i += 1
    if _scroll_i >= _scroll_end:
        _scrolling = False


def _start_scroll():
    global _scrolling, _scroll_i, _scroll_end
    start = display_drv.vscsad()
    if start is False:
        return
    _scroll_i = start
    _scroll_end = display_drv.height + 1
    _scrolling = True


def _key_release():
    global _key_busy, _pending_key, _key_release_at
    if _pending_key is not None:
        dsky.set_button(_pending_key, False)
        _pending_key = None
    dsky.set_acty(False)
    display_drv.show()
    _key_busy = False
    _key_release_at = None


def _handle_key(key):
    global _key_busy, _pending_key, _key_release_at
    _key_busy = True
    dsky.set_acty(True)
    dsky.set_button(key, True)
    _pending_key = key

    if key < len(dsky.light_status):
        dsky.set_light(key)
    else:
        _start_scroll()

    _key_release_at = ticks_add(ticks_ms(), 200)


def _tick(_=None):
    if app.quit_requested if app else False:
        return

    _update_time()

    if _key_release_at is not None and ticks_diff(_key_release_at, ticks_ms()) >= 0:
        _key_release()

    if _scrolling:
        _scroll_step()
        return

    if _key_busy:
        return

    # Keypad is wired to app events; read() drains presses filled by auto-service.
    if keys := dsky.keypad.read():
        for key in keys:
            _handle_key(key)


_init_apollo()
app.every(_tick, period=20, async_=app.timer_async)