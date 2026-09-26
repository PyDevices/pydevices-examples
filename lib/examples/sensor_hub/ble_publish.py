"""Publish readings to the hub over Bluetooth, from a PC (or a board acting as central).

    python ble_publish.py                      # find the hub by its service, send once a second
    python ble_publish.py --node desk-ble --count 30

The hub's Bluetooth door is one writable characteristic (see ``blefeed.py``);
each write is one reading in the hub's text form, ``node key=value ...``.
It uses ``bledev`` from pydevices, so the same code runs on a laptop
(``bledev.bleak``, needs bleak) and on a board (``bledev.mpble``). On WSL run
it with the Windows Python, which owns the radio.
"""

import asyncio
import sys
import time

import bledev.auto

HUB_SERVICE = "7d9a0001-5a5e-4c2b-9f0e-8b3c1d2e4f60"
HUB_PUBLISH = "7d9a0002-5a5e-4c2b-9f0e-8b3c1d2e4f60"


async def publish(node="pc-ble", count=0, every=1.0):
    ble = bledev.auto.adapter()
    print("looking for the hub ...")
    device = await ble.find(service=HUB_SERVICE, timeout_ms=20000)
    async with await device.connect() as connection:
        service = await connection.service(HUB_SERVICE)
        publish = await service.characteristic(HUB_PUBLISH)
        print("connected to", device)
        t0 = time.time()
        n = 0
        while not count or n < count:
            n += 1
            line = "{} n={} secs={}".format(node, n, int(time.time() - t0))
            await publish.write(line.encode())
            print(line)
            await asyncio.sleep(every)


def main(argv):
    import argparse

    ap = argparse.ArgumentParser(description="Publish readings to the sensor hub over Bluetooth.")
    ap.add_argument("--node", default="pc-ble")
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--every", type=float, default=1.0)
    a = ap.parse_args(argv)
    asyncio.run(publish(a.node, a.count, a.every))


if __name__ == "__main__":
    main(sys.argv[1:])
