"""The watch face: the time from the watch's clock, the date, the battery
and today's steps. Tap it for the other apps."""

import lvgl as lv

from . import services as sv
from . import ui


def main(scope):
    scr = ui.screen(scope, center=True)
    lbl_time = ui.label(scr, "--:--", sv.huge)
    lbl_secs = ui.label(scr, "", sv.font, sv.MUTED)
    lbl_date = ui.label(scr, "", sv.font)
    lbl_batt = ui.label(scr, "", sv.small, sv.MUTED)
    lbl_steps = ui.label(scr, "", sv.small, sv.MUTED)
    ui.label(scr, "tap for apps", sv.small, sv.MUTED)

    def update():
        y, mo, d, wd, h, mi, s = sv.now()
        lbl_time.set_text("%02d:%02d" % (h, mi))
        lbl_secs.set_text("%02d" % s)
        lbl_date.set_text("%s %d %s" % (sv.WEEKDAYS[wd % 7], d, sv.MONTHS[(mo - 1) % 12]))
        lbl_batt.set_text(sv.battery_text())
        lbl_steps.set_text("%d steps" % sv.accel.steps if sv.features else "")

    def tapped(e):
        if sv.awake_for() > 300:
            sv.go("home")

    scr.add_event_cb(tapped, lv.EVENT.CLICKED, None)
    sv.use(scope, update)
    update()
