# deps: appdev
"""Guided touch capture via appdev (no LVGL). Prints coords on MOUSEBUTTONUP."""

import sys

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
import appdev
import events

from multimer import auto as timer

FG, BG, ARM = 0xFFFF, 0x0000, 12
W, H = display_drv.width, display_drv.height
# Inboard targets (round panels clip the corners).
TARGETS = (
    (W // 4, H // 4),
    (W // 2, H // 4),
    (3 * W // 4, H // 2),
    (W // 2, 3 * H // 4),
)

idx = 0
results = []
_busy = False


def get_results():
    return list(results)


def _out(msg):
    sys.stdout.write(msg + "\n")
    flush = getattr(sys.stdout, "flush", None)
    if flush:
        flush()


def _plus(x, y, c):
    display_drv.fill_rect(x - ARM, y, 2 * ARM + 1, 1, c)
    display_drv.fill_rect(x, y - ARM, 1, 2 * ARM + 1, c)


def _show():
    display_drv.fill_rect(0, 0, W, H, BG)
    x, y = TARGETS[idx]
    _plus(x, y, FG)
    display_drv.show()
    _out("[%d/%d] tap (%d, %d)" % (idx + 1, len(TARGETS), x, y))


def _on_up(e):
    global idx, _busy
    # Ignore re-entrant UPs while we sleep/redraw (timer can poll mid-handler).
    if _busy or e.button != 1 or idx >= len(TARGETS):
        return
    _busy = True
    try:
        gx, gy = e.pos
        tx, ty = TARGETS[idx]
        results.append(((tx, ty), (gx, gy)))
        _out(
            "got (%d, %d)  target (%d, %d)  err (%d, %d)"
            % (gx, gy, tx, ty, gx - tx, gy - ty)
        )
        idx += 1
        timer.sleep_ms(400)
        if idx >= len(TARGETS):
            _out("done %s" % (results,))
            display_drv.fill_rect(0, 0, W, H, BG)
            display_drv.show()
        else:
            _show()
            timer.sleep_ms(400)
    finally:
        _busy = False


touch = getattr(display_drv, "touch_device", None)
if touch is not None:
    touch.rotation_table = (0, 0, 0, 0)

_show()
app.on(events.MOUSEBUTTONUP, _on_up)