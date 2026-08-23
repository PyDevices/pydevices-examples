# deps: lvgl, multimer
"""Minimal LVGL button smoke: tap counts up on the button label.

Uses board_config + display_driver (real panel). Pattern matches the tap
button in ``lv_test_timer.py``.
"""

import display_driver  # noqa: F401 — wires LVGL flush + input + event_loop
import lvgl as lv
from display_driver import app

_taps = 0


def build_ui():
    global _taps
    _taps = 0

    inst = display_driver.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        scr = lv.screen_active()

        btn = lv.button(scr)
        btn.set_size(120, 50)
        btn.align(lv.ALIGN.CENTER, 0, 0)
        btn_lbl = lv.label(btn)
        btn_lbl.set_text("Tap me (0)")
        btn_lbl.center()

        def on_click(_e):
            global _taps
            _taps += 1
            btn_lbl.set_text("Tap me ({})".format(_taps))

        btn.add_event_cb(on_click, lv.EVENT.CLICKED, None)
        return btn
    finally:
        if inst is not None:
            inst.enable()


build_ui()
print("lvgl_test: button on default screen")
