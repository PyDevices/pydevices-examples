# house_app.py -- the smart-home appliance the P4 boots into.
#
# One program: the house panel on the P4's own display, the sensor hub's
# dashboard served at http://<board ip>/ for a phone, and a SHOW-TV touch button
# that casts the panel (video + audio) to the TV. All on one asyncio loop. Real
# nodes (a FunHouse posting to /api/publish) take the first cards; a simulated
# house fills the rest.
#
#   import house.house_app; house_app.run()   # or copy main.py to /main.py
import sys, asyncio, time

from sensor_hub.hub import Hub
import house_panel as hp
from board_config import fb, touch_read


async def feeder(hub, sim):
    while True:
        sim.step()
        for line in sim.lines():
            hub.ingest(line, "sim")
        await asyncio.sleep(1)


async def painter(hub, audio, state):
    prev = set()
    while True:
        try:
            prev = _paint_once(hub, audio, state, prev)
        except Exception as e:
            # a painter that dies takes the panel with it while the hub keeps
            # answering, which looks like a frozen screen: log it and go on
            # (console only: a flash write can stall a running cast)
            sys.print_exception(e)
        # a full redraw holds the GIL ~0.2 s; yield generously so the hub server stays responsive
        await asyncio.sleep(0.8)


def _paint_once(hub, audio, state, prev):
    if True:
        snap = hub.snapshot()
        items = []
        panel_rooms, all_rooms = hp.room_list(snap)   # real nodes (the FunHouse) take the first cards
        for name in all_rooms:
            node = snap["nodes"].get(name)
            cur = hp.latest(node["series"]) if node else {}
            items += hp.alerts_for(name, cur)
        keys = set(k for k, _ in items)
        if keys - prev:
            audio.chime_now(feeding=state["casting"])
        prev = keys
        hp.draw_panel(snap, [t for _, t in items], state["casting"], "house", panel_rooms)
        # SHOW-TV touch button toggles the cast (the RokuScreen is made on first use)
        try:
            pts = touch_read()
        except Exception:
            pts = None
        if pts and time.ticks_diff(time.ticks_ms(), state["touch"]) > 700:
            p = pts[0]
            px = p[0] if isinstance(p, (tuple, list)) else getattr(p, "x", 0)
            py = p[1] if isinstance(p, (tuple, list)) else getattr(p, "y", 0)
            if hp.in_rect(px, py, hp.CAST_BTN):
                state["touch"] = time.ticks_ms()
                tv = state["tv"]
                if tv is None:
                    from roku_cast import RokuScreen
                    tv = state["tv"] = RokuScreen(hp.TV, name="PyDevices House", log=lambda *a: None)
                    tv.on()
                if state["casting"]:
                    tv.stop_cast()
                    state["casting"] = False
                else:
                    # the castif C task streams (core 0); the audio feed shares the chime's speaker stream
                    state["casting"] = bool(tv.start_cast(fb, audio=audio.cast_feed(), seconds=3600))
        return prev


async def main(port=80):
    hub = Hub(name="house", page=hp.HERE + "/dashboard.html")
    audio = hp.HouseAudio(log=lambda *a: None)
    state = {"casting": False, "touch": -10000, "tv": None}
    server = await asyncio.start_server(hub.http, "0.0.0.0", port)
    asyncio.create_task(feeder(hub, hp.SimHouse()))
    asyncio.create_task(painter(hub, audio, state))
    try:
        import network
        ip = network.WLAN(network.STA_IF).ifconfig()[0]
    except Exception:
        ip = "?"
    print("house app: panel up, dashboard on http://%s:%d/" % (ip, port))
    while True:
        await asyncio.sleep(3600)


def run(port=80):
    asyncio.run(main(port))


if __name__ == "__main__":
    run()
