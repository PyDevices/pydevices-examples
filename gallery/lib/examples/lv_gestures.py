# deps: lvgl
"""
lv_gestures.py

LVGL multi-touch gesture smoke example (pinch scale).

* Single-touch (mouse / CST8xx-class): drag/tap still work; pinch inactive.
* Multi-touch (GT911 / real SDL fingers): pinch scales the box via
  ``LV_EVENT_GESTURE`` + ``event_get_pinch_scale``.

Requires LVGL built with ``LV_USE_FLOAT`` + ``LV_USE_GESTURE_RECOGNITION``
(feature-detected; falls back to a single-touch label if missing).

Interactive (same as ``lv_test_timer``)::

    python -i utils/path.py
    import lv_gestures
"""

import sys

_file = __file__.replace("\\", "/").split("/")
if len(_file) >= 2 and _file[-2] == "examples":  # noqa: SIM108
    _src = "/".join(_file[:-2]) or "."
else:
    _src = "."
if _src not in sys.path:
    sys.path.insert(0, _src)

from board_config import display_drv  # noqa: E402
import display_driver as dd  # noqa: E402
import lvgl as lv  # noqa: E402
from display_driver import app  # noqa: E402

# Struct present when LV_USE_GESTURE_RECOGNITION is on (all ports).
_GESTURE_OK = hasattr(lv, "indev_touch_data_t") and hasattr(lv, "INDEV_GESTURE")


def _event_gesture_type(e):
    fn = getattr(lv, "event_get_gesture_type", None)
    if fn is not None:
        return fn(e)
    return e.get_gesture_type()


def _event_pinch_scale(e):
    fn = getattr(lv, "event_get_pinch_scale", None)
    if fn is not None:
        return fn(e)
    return e.get_pinch_scale()


def build_ui():
    inst = dd.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        scr = lv.screen_active()
        scr.set_style_bg_color(lv.color_hex(0x202020), 0)

        title = lv.label(scr)
        title.set_text("LVGL gestures")
        title.align(lv.ALIGN.TOP_MID, 0, 8)

        status = lv.label(scr)
        if _GESTURE_OK:
            status.set_text("Pinch with 2 fingers (or tap with 1)")
        else:
            status.set_text("Gesture APIs unavailable (float/gesture off)")
        status.align(lv.ALIGN.TOP_MID, 0, 28)

        scale_lbl = lv.label(scr)
        scale_lbl.set_text("scale: 1.00")
        scale_lbl.align(lv.ALIGN.TOP_MID, 0, 48)

        contact_lbl = lv.label(scr)
        contact_lbl.set_text("contacts: 0  max: 0  dual: 0ms")
        contact_lbl.align(lv.ALIGN.TOP_MID, 0, 68)

        hint = lv.label(scr)
        hint.set_text("2-finger pinch on a touchscreen (browser OK)")
        hint.align(lv.ALIGN.TOP_MID, 0, 88)

        box = lv.obj(scr)
        box.set_size(120, 120)
        box.center()
        box.set_style_bg_color(lv.color_hex(0x4080FF), 0)
        box.set_style_radius(12, 0)

        base_w = 120
        base_h = 120
        state = {
            "scale": 1.0,
            "max_contacts": 0,
            "dual_ms": 0,
            "dual_max_ms": 0,
            "gestures": 0,
            "_dual_since": None,
        }

        def _pointer_dev():
            drv = getattr(dd, "_driver_ref", None)
            if drv is not None:
                for vd in getattr(drv, "virtual_devices", ()) or ():
                    for d in getattr(vd, "devices", ()) or ():
                        if getattr(d, "type", None) == dd.POINTER:
                            return d
            if getattr(app, "touch_dev", None) is not None:
                return app.touch_dev
            return None

        def _ease_pinch_thresholds():
            # Defaults (0.75 / 1.5) need a large motion; ease for laptop touchscreens.
            drv = getattr(dd, "_driver_ref", None)
            if drv is None:
                return
            for vd in getattr(drv, "virtual_devices", ()) or ():
                for d in getattr(vd, "devices", ()) or ():
                    indev = getattr(d, "user_data", None)
                    if indev is None:
                        continue
                    set_down = getattr(lv, "indev_set_pinch_down_threshold", None)
                    set_up = getattr(lv, "indev_set_pinch_up_threshold", None)
                    if set_down is not None:
                        set_down(indev, 0.92)
                    elif hasattr(indev, "set_pinch_down_threshold"):
                        indev.set_pinch_down_threshold(0.92)
                    if set_up is not None:
                        set_up(indev, 1.12)
                    elif hasattr(indev, "set_pinch_up_threshold"):
                        indev.set_pinch_up_threshold(1.12)

        def _on_contact_timer(_t):
            dev = _pointer_dev()
            pts = getattr(dev, "points", ()) or ()
            n = len(pts)
            state["max_contacts"] = max(state["max_contacts"], n)
            now = lv.tick_get()
            if n >= 2:
                if state["_dual_since"] is None:
                    state["_dual_since"] = now
                state["dual_ms"] = (now - state["_dual_since"]) & 0xFFFFFFFF
                state["dual_max_ms"] = max(state["dual_max_ms"], state["dual_ms"])
            else:
                state["_dual_since"] = None
                state["dual_ms"] = 0
            contact_lbl.set_text(
                "contacts: {}  max: {}  dual: {}ms  g: {}".format(
                    n,
                    state["max_contacts"],
                    state["dual_max_ms"],
                    state["gestures"],
                )
            )

        def _on_gesture(e):
            if not _GESTURE_OK:
                return
            try:
                gtype = _event_gesture_type(e)
            except Exception:
                return
            if gtype != lv.INDEV_GESTURE.PINCH:
                return
            try:
                scale = float(_event_pinch_scale(e))
            except Exception:
                return
            if scale <= 0:
                return
            state["scale"] = scale
            state["gestures"] = state["gestures"] + 1
            w = max(40, min(280, int(base_w * scale)))
            h = max(40, min(280, int(base_h * scale)))
            box.set_size(w, h)
            box.center()
            scale_lbl.set_text("scale: {:.2f}".format(scale))

        if _GESTURE_OK:
            scr.add_event_cb(_on_gesture, lv.EVENT.GESTURE, None)
            _ease_pinch_thresholds()
        lv.timer_create(_on_contact_timer, 50, None)

        btn = lv.button(scr)
        btn.set_size(100, 40)
        btn.align(lv.ALIGN.BOTTOM_MID, 0, -12)
        bl = lv.label(btn)
        bl.set_text("Tap")
        bl.center()

        taps = {"n": 0}

        def _on_click(_e):
            taps["n"] += 1
            bl.set_text("Tap {}".format(taps["n"]))

        btn.add_event_cb(_on_click, lv.EVENT.CLICKED, None)
        return box, scale_lbl, taps
    finally:
        if inst is not None:
            inst.enable()


# Canonical interactive entry - no app loop here. build_ui imports
# display_driver (wires LVGL into the shared app); App.run keeps
# the app alive or returns immediately on an interactive REPL with a
# self-driving timer.
build_ui()
