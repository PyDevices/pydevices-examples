"""``main.py`` for a board that hosts the hub. Copy it to the board as ``/main.py``.

It joins Wi-Fi from the board's ``secrets.py`` (pydevices' ``wifi.py``, as in
board bring-up), then serves the hub on port 80, UDP 5005 and Bluetooth.
Name the hub after the board. Bluetooth shows ``ble_name``, 8 characters at most.
"""

import wifi

wifi.connect_from_secrets()

import sensor_hub.hub  # noqa: E402

sensor_hub.hub.run(name="T-Embed hub", ble_name="T-Embed")
