"""Power: battery voltage, charge and state, screen brightness, sleep, and
the memory the apps are using."""

import gc

import lvgl as lv

from . import services as sv
from . import ui


def main(scope):
    scr = ui.screen(scope, "Power")
    lbl = ui.label(scr, "", sv.small)
    lbl_mem = ui.label(scr, "", sv.small, sv.MUTED)
    ui.label(scr, "Brightness", sv.small, sv.MUTED)
    slider = lv.slider(scr)
    slider.set_width(lv.pct(85))
    slider.set_range(5, 100)
    slider.set_value(int(sv.brightness * 100), 0)

    def on_bright(e):
        sv.set_brightness(slider.get_value() / 100)

    slider.add_event_cb(on_bright, lv.EVENT.VALUE_CHANGED, None)
    r = ui.row(scr)
    ui.button(r, "Screen off", sv.screen_off)
    if sv.sleep is not None:
        ui.button(r, "Deep sleep", sv.deep_sleep)

    ticks = [0]

    def memory():
        # Once a second: a collection first, so the number is what's in use.
        ticks[0] += 1
        if ticks[0] % 4 != 1 or not hasattr(gc, "mem_alloc"):
            return
        gc.collect()
        la = sv.launcher
        text = "heap in use %d KB" % (gc.mem_alloc() // 1024)
        if la is not None:
            text += "\n%d switches, last %s ms" % (la.switches, la.last[1] if la.last else "-")
        lbl_mem.set_text(text)

    def update():
        memory()
        battery = sv.battery
        if battery is None:
            lbl.set_text("no battery reading")
            return
        lines = [sv.battery_text()]
        v = battery.voltage
        if v is not None:
            lines.append("battery %.2f V" % v)
        state = getattr(battery, "charge_state", None)
        if state is not None:
            lines.append("charger: " + state)
        vbus = getattr(battery, "vbus_voltage", None)
        if vbus:
            lines.append("USB %.2f V" % vbus)
        lbl.set_text("\n".join(lines))

    sv.use(scope, update)
    update()
