"""TV remote: Home, volume and mute for a Roku TV, sent from the watch's IR
LED. Point the watch at the TV.

Set ``TV_*`` if your TV isn't a Roku."""

from . import services as sv
from . import ui

# Roku TV infrared codes: extended NEC, address 0xEA 0xC7.
TV_ADDRESS = (0xEA, 0xC7)
TV_KEYS = (("Home", 0x03), ("Vol +", 0x0F), ("Vol -", 0x10), ("Mute", 0x20))


def main(scope):
    scr = ui.screen(scope, "TV remote")
    lbl = ui.label(scr, "Point the watch at the TV", sv.small, sv.MUTED)
    if sv.ir is None:
        ui.missing(scr, "no IR LED")
        sv.use(scope)
        return
    from ir_nec import send

    def key(name, code):
        def cb():
            send(sv.ir, TV_ADDRESS[0], code, address2=TV_ADDRESS[1], repeats=1)
            lbl.set_text("sent %s" % name)
            sv.event("IR " + name)
            sv.buzz(1)

        return cb

    r = ui.row(scr)
    for name, code in TV_KEYS:
        ui.button(r, name, key(name, code), width=sv.W // 2 - 16)
    sv.use(scope)
