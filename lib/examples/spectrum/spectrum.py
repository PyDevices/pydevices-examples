# deps: pygraphics
"""
spectrum.py -- an audio spectrum analyzer.

Log-spaced bars from 20 Hz to 20 kHz in a cool gradient, with peak-hold caps,
a reflection under the baseline, and frequency labels at their true log
positions. Drawn with ``pygraphics``: the static art once, then each bar as
its own packed column, so a frame copies and sends only the rows that moved.

The layout comes from the display's size, so the same file runs on a desktop
window, the ESP32-P4 panel (800x480) and the T-Embed (320x170). On desktop it
opens at 800x480 unless ``PYDEVICES_WIDTH``/``PYDEVICES_HEIGHT`` say otherwise.
Set ``SPECTRUM_STYLE=segmented`` for LED-style bars.

The levels come from the sound card's C pump when the firmware has one
(``pump_levels.PumpLevels``: run this beside usbif's ``soundcard.py``), from
what the computer is playing on a CPython desktop with numpy and
``soundcard`` installed (``loopback_levels.LoopbackLevels``), and from
``fake_music.FakeMusic`` otherwise. ``SPECTRUM_SOURCE=fake|pump|loopback``
forces one. Either only has to hand ``SpectrumView.update`` one 0..1 level per band.

This file is the app: importing it (the gallery does) or running it starts
the meter. An app that wants the meter on its own sound imports
``analyzer.Spectrum`` instead; ``mp3_from_sd.py`` beside this folder does.

``capture(path)`` writes the frame on screen to a file as raw RGB565, for a
screenshot of a real panel.
"""

import sys

from boarddev import env_get, env_set

# A desktop board_config reads these; a real board's display ignores them.
if env_get("PYDEVICES_WIDTH") is None:
    env_set("PYDEVICES_WIDTH", 800)
    env_set("PYDEVICES_HEIGHT", 480)
if env_get("PYDEVICES_SCALE") is None:
    env_set("PYDEVICES_SCALE", 1.0)

_here = __file__.replace("\\", "/").rsplit("/", 1)[0] if "/" in __file__ else "."
if _here not in sys.path:
    sys.path.insert(0, _here)

import board_config  # noqa: E402
import appdev  # noqa: E402
from board_config import display_drv  # noqa: E402
from analyzer import Spectrum  # noqa: E402
from fake_music import FakeMusic  # noqa: E402

app = None
meter = None
view = None
music = None
timer = None


def _source(bands):
    """The sound card's C pump on a board, what the computer is playing on a
    desktop (``loopback_levels``), else the fake. ``SPECTRUM_SOURCE`` forces
    one: ``fake``, ``pump`` or ``loopback``."""
    want = env_get("SPECTRUM_SOURCE")
    if want != "fake":
        if want in (None, "pump"):
            try:
                import pump_levels

                if pump_levels.available():
                    return pump_levels.PumpLevels(bands)
            except ImportError:
                pass
        if want in (None, "loopback"):
            try:
                import loopback_levels

                if loopback_levels.available():
                    return loopback_levels.LoopbackLevels(bands)
            except Exception as error:  # no loopback device, no audio stack
                print("spectrum: no loopback source (%r)" % (error,))
    return FakeMusic(bands)


def capture(path):
    """Write the meter's rows on screen to ``path`` as raw RGB565."""
    return meter.capture(path)


def start(bands=None, height=None, y=None, style=None):
    """Start the meter, once; a second call returns the running one. Every
    argument is optional (see ``analyzer.Spectrum``); ``style`` defaults to
    ``SPECTRUM_STYLE`` or smooth."""
    global app, meter, view, music, timer
    if meter is not None:
        return view
    app = appdev.App(board_config, refresh_period=0 if _present_rows() else None)
    meter = Spectrum(
        display_drv,
        _source,
        bands=bands,
        height=height,
        y=y,
        style=style or env_get("SPECTRUM_STYLE") or "smooth",
        report=True,
    )
    view, music = meter.view, meter.source
    timer = meter.start(app).timer
    return view


def _present_rows():
    # The DSI panel presents just the rows the meter changed, so appdev's
    # whole-frame refresh is turned off (see analyzer.Spectrum).
    return bool(getattr(display_drv, "needs_refresh", False)) and hasattr(
        getattr(display_drv, "_raw_buffer", None), "refresh_rect"
    )


start()
