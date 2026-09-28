"""Run the hub: ``micropython -m examples.sensor_hub [--port 8080] [--udp-port 5005] [--no-ble]``.

On a board, ``main.py`` joins Wi-Fi first (see README.md), then calls
``sensor_hub.hub.run()``. ``--plant drop_feed`` starts a hub whose feed is
dead on purpose, for proving ``check_hub.py`` can fail.
"""

import sys

from . import hub

args = sys.argv[1:]
opts = {}
while args:
    a = args.pop(0)
    if a == "--port":
        opts["port"] = int(args.pop(0))
    elif a == "--udp-port":
        opts["udp_port"] = int(args.pop(0))
    elif a == "--no-ble":
        opts["ble"] = False
    elif a == "--name":
        opts["name"] = args.pop(0)
    elif a == "--plant":
        opts["plant"] = args.pop(0)
hub.run(**opts)
