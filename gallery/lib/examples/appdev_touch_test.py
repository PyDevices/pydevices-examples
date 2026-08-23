# deps: pygraphics
"""
appdev_touch_test.py - Touch rotation test.
Tests the touch driver and finds the correct rotation masks for the touch screen.
Sets the rotation to each of 4 possible values and asks the user to touch the rectangle in each of the 4 corners.
Then it prints the touch_rotation_table that should be set in board_config.py.
"""

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
import appdev
from pygraphics import round_rect, text16

demo = False

FG_COLOR = -1  # white
BG_COLOR = 0  # black

text = "Touch here"
text_width = len(text) * 8

SWAP_XY = 0b001
REVERSE_X = 0b010
REVERSE_Y = 0b100

_ZONE_MASKS = {
    (0, 1, 2, 3): 0b0,
    (1, 0, 3, 2): REVERSE_X,
    (2, 3, 0, 1): REVERSE_Y,
    (3, 2, 1, 0): REVERSE_X | REVERSE_Y,
    (0, 2, 1, 3): SWAP_XY,
    (2, 0, 3, 1): SWAP_XY | REVERSE_X,
    (1, 3, 0, 2): SWAP_XY | REVERSE_Y,
    (3, 1, 2, 0): SWAP_XY | REVERSE_X | REVERSE_Y,
}


def set_rotation_table(table):
    if display_drv.touch_device is not None:
        if display_drv.touch_device.type == appdev.POINTER:
            display_drv.touch_device.rotation_table = table


def _draw_target(x, y, half_width, half_height):
    round_rect(
        display_drv,
        x * half_width + 10,
        y * half_height + 10,
        half_width - 20,
        half_height - 20,
        10,
        FG_COLOR,
        True,
    )
    text16(
        display_drv,
        text,
        x * half_width + ((half_width - text_width) // 2),
        y * half_height + ((half_height - 8) // 2),
        BG_COLOR,
    )
    display_drv.show()


def _clear_target(x, y, half_width, half_height):
    display_drv.fill_rect(
        x * half_width,
        y * half_height,
        half_width - 1,
        half_height - 1,
        BG_COLOR,
    )
    display_drv.show()


def _report(touch_rotation_table):
    if not demo:
        set_rotation_table(touch_rotation_table)
        print("Set the `touch_rotation_table` in board_config.py to the following:")
    else:
        print("Demo complete.")
    out_text = f"touch_rotation_table = {tuple(touch_rotation_table)}"
    print("    ", out_text, "\n")
    text16(
        display_drv,
        out_text,
        (display_drv.width - len(out_text) * 8) // 2,
        (display_drv.height - 8) // 2,
        FG_COLOR,
    )
    display_drv.show()


# Callback-driven state machine (one path for sync and async).
_st = {
    "rotation": 0,
    "x": 0,
    "y": 0,
    "touched_zones": [],
    "touch_rotation_table": [],
    "half_width": 0,
    "half_height": 0,
    "done": False,
}


def _show_current_target():
    _draw_target(_st["x"], _st["y"], _st["half_width"], _st["half_height"])


def _advance_or_finish():
    _st["x"] += 1
    if _st["x"] > 1:
        _st["x"] = 0
        _st["y"] += 1
    if _st["y"] > 1:
        # finished one rotation
        mask = _ZONE_MASKS.get(tuple(_st["touched_zones"]))
        if mask is None:
            print("Invalid touch sequence. Starting over...\n")
            _start_over()
            return
        _st["touch_rotation_table"].append(mask)
        print(f"rotation={_st['rotation']} {mask=} ({mask:#05b})\n")
        _st["rotation"] += 90
        if _st["rotation"] >= 360:
            _report(_st["touch_rotation_table"])
            _st["done"] = True
            return
        _st["touched_zones"] = []
        _st["x"] = 0
        _st["y"] = 0
        display_drv.rotation = _st["rotation"]
        _st["half_width"] = display_drv.width // 2
        _st["half_height"] = display_drv.height // 2
        display_drv.fill_rect(0, 0, display_drv.width - 1, display_drv.height - 1, BG_COLOR)
    _show_current_target()


def _start_over():
    _st["rotation"] = 0
    _st["x"] = 0
    _st["y"] = 0
    _st["touched_zones"] = []
    _st["touch_rotation_table"] = []
    display_drv.rotation = 0
    _st["half_width"] = display_drv.width // 2
    _st["half_height"] = display_drv.height // 2
    display_drv.fill_rect(0, 0, display_drv.width - 1, display_drv.height - 1, BG_COLOR)
    print("Touch the rectangle in each corner for 4 rotations.\n")
    _show_current_target()


def _on_click(e):
    if _st["done"] or e.button != 1:
        return
    touched_point = e.pos
    zone = (touched_point[1] // _st["half_height"]) * 2 + (
        touched_point[0] // _st["half_width"]
    )
    _st["touched_zones"].append(zone)
    print(f"{touched_point=} in {zone=}")
    _clear_target(_st["x"], _st["y"], _st["half_width"], _st["half_height"])
    _advance_or_finish()


if not demo:
    set_rotation_table((0, 0, 0, 0))

_start_over()
app.on(app.events.MOUSEBUTTONDOWN, _on_click)