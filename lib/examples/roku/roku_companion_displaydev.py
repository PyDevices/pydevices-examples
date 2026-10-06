#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_companion_displaydev.py
============================

Demonstrates rendering to a Roku TV using PyDevices `displaydev` via:
1. `RokuDisplay` — subclass of `FBDisplay`
2. `RokuDisplayWrapper` — wrapper around an existing `FBDisplay` instance

Both use `pygraphics.encode_png` to turn the in-memory RGB565 framebuffer
into PNG frames and push them live to the PyDevices Companion app on the TV.

Usage::

    python roku_companion_displaydev.py [ROKU_IP]
"""

import sys
import time


from utils.roku_companion import RokuCompanion, RokuDisplay, RokuDisplayWrapper, roku_host
try:
    from displaydev.fbdisplay import FBDisplay
except ImportError:
    FBDisplay = None

ROKU_IP = roku_host()
WIDTH = 480
HEIGHT = 270

# RGB565 color constants
BLACK = 0x0000
BLUE = 0x001F
RED = 0xF800
GREEN = 0x07E0
CYAN = 0x07FF
MAGENTA = 0xF81F
YELLOW = 0xFFE0
WHITE = 0xFFFF


def demo_subclass(tv):
    print("--- 1. Testing RokuDisplay (FBDisplay subclass) ---")
    disp = RokuDisplay(tv, width=WIDTH, height=HEIGHT, port=8090)

    try:
        # Draw background and a title card
        disp.fill_rect(0, 0, WIDTH, HEIGHT, 0x18C3)  # Dark slate blue
        disp.fill_rect(20, 20, WIDTH - 40, 50, 0x0000)  # Header bar
        disp.fill_rect(24, 24, WIDTH - 48, 42, 0x2124)  # Inner bar

        # Draw colorful test swatches
        swatches = [RED, GREEN, BLUE, YELLOW, CYAN, MAGENTA]
        sw_w = (WIDTH - 60) // len(swatches)
        for i, color in enumerate(swatches):
            disp.fill_rect(30 + i * sw_w, 90, sw_w - 4, 60, color)

        # Border
        disp.fill_rect(0, 0, WIDTH, 4, WHITE)
        disp.fill_rect(0, HEIGHT - 4, WIDTH, 4, WHITE)
        disp.fill_rect(0, 0, 4, HEIGHT, WHITE)
        disp.fill_rect(WIDTH - 4, 0, 4, HEIGHT, WHITE)

        print("Presenting frame via disp.show()...")
        disp.show()
        print("Waiting 5 seconds for Roku to display frame...")
        time.sleep(5.0)

        # Animate a bouncing box
        print("Animating across display...")
        box_x = 30
        step = (WIDTH - 90) // 15  # ends 30 px from the right edge
        for _ in range(15):
            disp.fill_rect(box_x, 170, 30, 30, 0x18C3)  # Erase
            box_x += step
            disp.fill_rect(box_x, 170, 30, 30, YELLOW)  # Draw
            disp.show()
            time.sleep(0.15)

        time.sleep(2.0)

    finally:
        disp.close()


def demo_wrapper(tv):
    print("\n--- 2. Testing RokuDisplayWrapper (FBDisplay decorator) ---")
    if FBDisplay is None:
        print("Skipping: displaydev.fbdisplay not available")
        return

    buf = bytearray(WIDTH * HEIGHT * 2)
    base_display = FBDisplay(buf, width=WIDTH, height=HEIGHT)
    disp = RokuDisplayWrapper(base_display, tv, port=8090)

    try:
        # Fill bright background
        disp.fill_rect(0, 0, WIDTH, HEIGHT, 0x0210)  # Deep purple
        disp.fill_rect(40, 40, WIDTH - 80, HEIGHT - 80, 0xFC00)  # Orange center
        disp.fill_rect(60, 60, WIDTH - 120, HEIGHT - 120, WHITE)  # White box
        disp.fill_rect(80, 80, WIDTH - 160, HEIGHT - 160, GREEN)  # Green core

        print("Presenting wrapped display frame via disp.show()...")
        disp.show()
        print("Waiting 5 seconds for Roku to display frame...")
        time.sleep(5.0)

    finally:
        disp.close()


def main():
    print("Connecting to Roku TV at %s..." % ROKU_IP)
    tv = RokuCompanion(ROKU_IP)

    # 1. Test subclass
    demo_subclass(tv)

    time.sleep(1.0)

    # 2. Test wrapper
    demo_wrapper(tv)

    print("\nBoth FBDisplay implementations completed successfully!")


if __name__ == "__main__":
    main()
