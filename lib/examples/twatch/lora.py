"""LoRa: the radio's identity, a test packet, and listening for activity.

Set ``LORA_MHZ`` to a frequency your region allows before sending (915 MHz
suits the Americas; Europe uses 868, much of Asia 433)."""

import board_config as board

from . import services as sv
from . import ui

LORA_MHZ = 915.0
LORA_DBM = 10


def main(scope):
    scr = ui.screen(scope, "LoRa")
    lbl = ui.label(scr, "", sv.small)
    if not sv.has_lora:
        ui.missing(scr, "no LoRa radio role")
        sv.use(scope)
        return
    state = {"radio": None, "pings": 0}

    def radio():
        if state["radio"] is None:
            r = board.lora  # the board keeps one radio; it outlives this app
            r.configure(LORA_MHZ, sf=9, power_dbm=LORA_DBM)
            state["radio"] = r
        return state["radio"]

    def ping():
        try:
            state["pings"] += 1
            ms = radio().send(b"twatch %d" % state["pings"])
            lbl.set_text("%s\nsent #%d, %d ms on air\nat %.1f MHz" % (radio().version, state["pings"], ms, LORA_MHZ))
        except Exception as e:
            lbl.set_text("send failed: %r" % (e,))

    def listen():
        try:
            busy = radio().channel_active()
            lbl.set_text("%s\nchannel %s\nat %.1f MHz" % (radio().version, "busy" if busy else "quiet", LORA_MHZ))
        except Exception as e:
            lbl.set_text("CAD failed: %r" % (e,))

    try:
        lbl.set_text("%s\n%s\ntap Send or Listen" % (board.lora.version, board.lora.status[0]))
        r = ui.row(scr)
        ui.button(r, "Send", ping)
        ui.button(r, "Listen", listen)
    except Exception as e:
        lbl.set_text("radio not answering: %r" % (e,))
    sv.use(scope)
