"""The hub's Bluetooth door: a GATT service a node or a phone writes readings to.

One service, one writable characteristic. Each write is one reading, in the
same JSON or text form the other doors take (``phone batt=81 tilt=12``). It
takes up to 200 bytes, which fits one write once the link has negotiated a
large MTU (Chrome on Android asks for one; boards answer 247).

The hub advertises the service UUID and its name, so Web Bluetooth can
filter on the service (Chrome on Android never matches a name that only
arrived in the scan response). One central at a time; after it leaves, the
hub advertises again.

Needs ``bledev`` (from pydevices) and ``aioble`` on the board.
"""

import asyncio

import bledev
import bledev.mpble

HUB_SERVICE = bledev.UUID("7d9a0001-5a5e-4c2b-9f0e-8b3c1d2e4f60")
HUB_PUBLISH = bledev.UUID("7d9a0002-5a5e-4c2b-9f0e-8b3c1d2e4f60")


async def serve(hub, name="sensor-hub"):
    ble = bledev.mpble.get()
    service = bledev.Service(HUB_SERVICE)
    publish = bledev.Characteristic(
        service, HUB_PUBLISH, write=True, write_no_response=True, capture=True, max_len=200
    )
    ble.register_services(service)

    async def writes():
        while True:
            _, data = await publish.written()
            hub.ingest(data, "ble")

    asyncio.create_task(writes())
    while True:
        hub.ble_state = "advertising"
        connection = await ble.advertise(name=name[:12], services=[HUB_SERVICE])
        hub.ble_state = "connected"
        await connection.disconnected()
