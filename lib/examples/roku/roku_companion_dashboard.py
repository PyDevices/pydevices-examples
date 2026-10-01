# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_companion_dashboard.py
============================

Demonstrates using a Roku TV as a large sensor dashboard with the
PyDevices Companion app.

Sends periodic status updates to the TV screen — sensor readings, system
status, or any text you want displayed.  The Roku acts as a big, bright,
always-on monitor that any PyDevice on the network can write to.

Prerequisites
-------------
* The **PyDevices Companion** app sideloaded on the target Roku.
* Roku setting **Control by mobile apps → Enabled**.

Usage::

    micropython examples/roku_companion_dashboard.py
    python examples/roku_companion_dashboard.py
"""

import time
from utils.roku_companion import RokuCompanion

# -- Configuration ----------------------------------------------------------
ROKU_IP = "192.168.1.129"
UPDATE_INTERVAL = 4   # seconds between dashboard refreshes
# ---------------------------------------------------------------------------

tv = RokuCompanion(ROKU_IP)

# Simulate sensor readings cycling through a few states.
readings = [
    "Kitchen  72°F  45% RH\nGarage   68°F  52% RH\nOutdoor  81°F  38% RH",
    "Kitchen  72°F  45% RH\nGarage   67°F  53% RH\nOutdoor  80°F  39% RH\n\n⚠ Garage door OPEN",
    "Kitchen  73°F  44% RH\nGarage   67°F  53% RH\nOutdoor  79°F  40% RH\n\n✓ Garage door CLOSED",
    "Kitchen  73°F  44% RH\nGarage   68°F  52% RH\nOutdoor  78°F  41% RH\n\nAll systems nominal.",
]

print("Sending dashboard updates to Roku at", ROKU_IP)
for i, text in enumerate(readings):
    print("Update %d/%d" % (i + 1, len(readings)))
    tv.dashboard(text)
    if i < len(readings) - 1:
        time.sleep(UPDATE_INTERVAL)

print("Done.")
