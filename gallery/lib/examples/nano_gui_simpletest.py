# deps: pygraphics
# utils: color_setup, gui
"""
nano_gui_simpletest.py - Copied from:
https://github.com/peterhinch/micropython-nano-gui/tree/master?tab=readme-ov-file#23-verifying-hardware-configuration

``color_setup`` fetches micropython-nano-gui into utils/gui/ when needed.
``fetch_ph_gui`` (via the matching setup module) installs the GUI on desktop and in the browser.
"""

import board_config
import appdev

app = appdev.App(board_config)
from color_setup import ssd  # Create a display instance
from gui.core.colors import RED, BLUE, GREEN
from gui.core.nanogui import refresh

refresh(ssd, True)  # Initialise and clear display.
ssd.fill(0)
ssd.line(0, 0, ssd.width - 1, ssd.height - 1, GREEN)  # Green diagonal corner-to-corner
ssd.rect(0, 0, 15, 15, RED)  # Red square at top left
ssd.rect(ssd.width - 15, ssd.height - 15, 15, 15, BLUE)  # Blue square at bottom right
ssd.show()