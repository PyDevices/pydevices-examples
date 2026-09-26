# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Shared setup for the hostloop proof scripts.

A headless stand-in display so the proof runs on every interpreter, including
ones with no SDL window and no framebuffer.
"""

from appdev import App

TICK_MS = 20
STOP_AFTER = 15


class Display:
    needs_refresh = False

    def show(self, timer=None):
        pass

    def quit(self):
        print("[app] display released")


def make_app():
    app = App(displays=[Display()], refresh_period=0)
    print("[app] strategy:", app.strategy)
    ticks = []

    @app.every(TICK_MS)
    def _tick(_t):
        ticks.append(1)
        if len(ticks) % 5 == 0:
            print("[tick]", len(ticks))
        if len(ticks) >= STOP_AFTER:
            print("[app] requesting quit at", len(ticks))
            app.request_quit()

    app.ticks = ticks
    return app
