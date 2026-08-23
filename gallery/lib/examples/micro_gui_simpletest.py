# deps: pygraphics
# utils: hardware_setup, gui
"""
micro_gui_simpletest.py - Smoke test for micropython-micro-gui on pydevices-examples.

``hardware_setup`` fetches the GUI and creates ``Display`` with keyboard stand-ins.
This oneshot only verifies the framebuffer path (full widget demos use Screen.change).
``fetch_ph_gui`` (via the matching setup module) installs the GUI on desktop and in the browser.
"""

import board_config
import appdev

app = appdev.App(board_config)
import hardware_setup  # noqa: F401 — fetch + Display
from gui.core.ugui import ssd
from gui.core.colors import RED, BLUE, GREEN

ssd.fill(0)
ssd.line(0, 0, ssd.width - 1, ssd.height - 1, GREEN)
ssd.rect(0, 0, 15, 15, RED)
ssd.rect(ssd.width - 15, ssd.height - 15, 15, 15, BLUE)
ssd.show()