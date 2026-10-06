# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_companion_tts.py
=====================

Demonstrates Text-to-Speech on a Roku TV using the PyDevices Companion app.

The Roku's built-in ``roTextToSpeech`` engine speaks arbitrary text through
the TV speakers — no audio encoding, no proxy server, no external services.
Useful for smart-home alerts, sensor notifications, or accessibility.

Prerequisites
-------------
* The **PyDevices Companion** app sideloaded on the target Roku.
* Roku setting **Control by mobile apps → Enabled**.

Usage (any interpreter — same code everywhere)::

    micropython -c "exec(open('examples/roku_companion_tts.py').read())"
    micropython.exe examples/roku_companion_tts.py
    python examples/roku_companion_tts.py
"""

import time
from utils.roku_companion import RokuCompanion, roku_host

# -- Configuration ----------------------------------------------------------
ROKU_IP = roku_host()
# ---------------------------------------------------------------------------

tv = RokuCompanion(ROKU_IP)

messages = [
    "Hello from PyDevices!",
    "The temperature sensor reads seventy two degrees.",
    "Motion detected at the front door.",
    "Good night. Turning off all lights.",
]

for msg in messages:
    print("Speaking:", msg)
    tv.say(msg)
    time.sleep(5)

print("Done.")
