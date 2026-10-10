"""Steps: the step counter, what you're doing (still, walking, running), the
accelerometer live, and whether a wrist tilt or a double tap wakes the
screen."""

import lvgl as lv

from . import services as sv
from . import ui


def main(scope):
    scr = ui.screen(scope, "Steps")
    lbl_steps = ui.label(scr, "-", sv.big)
    lbl_activity = ui.label(scr, "", sv.small, sv.MUTED)
    lbl_accel = ui.label(scr, "", sv.small)
    accel = sv.accel
    if sv.features:
        r = ui.row(scr)
        for attr, text in (("wake_on_tilt", "Tilt wakes"), ("wake_on_tap", "2 taps wake")):
            cell = lv.obj(r)
            cell.remove_style_all()
            cell.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
            cell.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            cell.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
            ui.label(cell, text, sv.small)
            sw = lv.switch(cell)
            if getattr(sv, attr):
                sw.add_state(lv.STATE.CHECKED)
            sw.add_event_cb(_toggle(attr, sw), lv.EVENT.VALUE_CHANGED, None)
        ui.button(scr, "Reset steps", accel.reset_steps)
    elif accel is None:
        ui.missing(scr, "no accelerometer")
    else:
        ui.missing(scr, "no step counter on this chip")

    def update():
        if sv.features:
            lbl_steps.set_text("%d" % accel.steps)
            lbl_activity.set_text(accel.activity)
        if accel is not None:
            x, y, z = accel.acceleration
            lbl_accel.set_text("x %+.2f  y %+.2f  z %+.2f g" % (x, y, z))

    sv.use(scope, update)
    update()


def _toggle(attr, sw):
    def cb(e):
        setattr(sv, attr, sw.has_state(lv.STATE.CHECKED))

    return cb
