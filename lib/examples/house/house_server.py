# house_server.py -- the house dashboard alone, without the panel: the sensor
# hub's HTTP + websocket server on the board, fed the SimHouse readings, so a
# phone (or a PC browser) sees the rooms update live and an alert when a
# threshold trips.
#
#   import house.house_server as s; s.run()   # http://<board ip>/
import asyncio
from sensor_hub.hub import Hub
import house_panel   # SimHouse


async def feeder(hub, sim, period=1.0):
    while True:
        sim.step()
        for line in sim.lines():
            hub.ingest(line, "sim")
        await asyncio.sleep(period)


async def main(port=80):
    hub = Hub(name="house", page=house_panel.HERE + "/dashboard.html")
    server = await asyncio.start_server(hub.http, "0.0.0.0", port)
    asyncio.create_task(feeder(hub, house_panel.SimHouse()))
    try:
        import network
        ip = network.WLAN(network.STA_IF).ifconfig()[0]
    except Exception:
        ip = "?"
    print("house hub server on http://%s:%d/" % (ip, port))
    while True:
        await asyncio.sleep(3600)


def run(port=80):
    asyncio.run(main(port))


if __name__ == "__main__":
    run()
