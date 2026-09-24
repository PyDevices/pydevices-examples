# deps: lvgl
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
google_photos
====================================================
Pick Google Photos on your phone; the board lists, views, and slideshows them.

Google Photos on a PyDevices display: pick photos from your phone, browse
the list with thumbnails, view them full screen, or run a slideshow.

Launcher for the Google Photos stack:

* :mod:`gphotos_engine` -- Picker API client, token refresh, prefs, thumbnail
  cache (no UI)
* :mod:`gphotos_sim`    -- offline / PyScript stand-in (``make_engine``)
* :mod:`gphotos_lvgl`   -- LVGL front end (list, view, slideshow, QR pairing)

How picking works: the device creates a Picker API *session* and shows its
link as a QR code. Scan it with your phone, choose photos in Google Photos,
tap Done, and the device lists what you picked. Google only hands out
photos the user explicitly picked -- since March 2025 third-party apps can
no longer browse a whole library -- so this is the official, self-serve path.

Setup (one time, on a PC; see ``README.md`` beside this file): create a
Google Cloud OAuth *Desktop app* client with the Picker API enabled, run
``tools/gphotos_auth.py`` to sign in, then copy the resulting
``gphotos_tokens.json`` to the board (``mpremote cp … :/gphotos_tokens.json``).
Without that file, or without a network, the launcher runs the simulator
with sample photos so the UI can be explored anywhere (PyScript gallery too).

Desktop launch from ``pydevices-examples/lib`` (same for ``micropython``,
``python``, ``python.exe``)::

    micropython -m examples.google_photos

Join Wi-Fi before running on a microcontroller. Optional desktop panel size:
edit ``_WIDTH`` / ``_HEIGHT`` / ``_SCALE`` below (applied via
``displaydev.env_set`` before ``board_config`` is imported; never on MCUs).
"""

import sys

_PKG = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from displaydev import env_set

# Local desktop test panel -- change these and re-run. Must stay above board_config.
_WIDTH = None
_HEIGHT = None
_SCALE = None  # e.g. 1 or 2; None = AutoDisplay default + autoscale
_MCU_PLATFORMS = (
    "esp32",
    "esp8266",
    "rp2",
    "samd",
    "nrf",
    "mimxrt",
    "renesas-ra",
    "stm32",
    "zephyr",
)
if getattr(sys, "platform", "") not in _MCU_PLATFORMS:
    # None leaves the environment alone, so PYDEVICES_WIDTH / _HEIGHT set by
    # the caller (or tools/screenshot.py --resolution) still apply.
    for _name, _value in (
        ("PYDEVICES_WIDTH", _WIDTH),
        ("PYDEVICES_HEIGHT", _HEIGHT),
        ("PYDEVICES_SCALE", _SCALE),
    ):
        if _value is not None:
            env_set(_name, _value)

import gphotos_engine  # noqa: E402
from gphotos_sim import make_engine  # noqa: E402


def main():
    # Suppress front-end auto-start on import; we call ``run()`` below.
    gphotos_engine._LAUNCHER_OWNS_RUN = True

    engine = make_engine()
    has_items = engine.restore()
    start_page = "list" if has_items else "connect"
    notice = getattr(engine, "sim_notice", "") or ""
    print(
        "google_photos: engine=%s start_page=%s items=%d%s"
        % (
            "sim" if engine.sim else "picker",
            start_page,
            len(engine.items),
            (" (" + notice + ")") if notice else "",
        )
    )

    import gphotos_lvgl

    gphotos_lvgl.run(engine=engine, start_page=start_page)
    _block_if_batch()


def _block_if_batch():
    """Keep ``python -m examples.google_photos`` alive.

    The shared app host-loop decides its strategy once, when ``display_driver``
    builds the ``App`` -- here that happens while the package ``__init__`` is
    still being imported by ``runpy``, before ``__main__.__file__`` exists, so
    a ``-m`` launch looks like a REPL ("ambient") or a tool run ("none") and
    the process would return to the prompt with the UI half-built. Decide from
    the command line instead: under ``-m`` / ``-c`` without ``-i`` on a
    desktop host, block here until the app quits. Every other host (script
    path, MCU REPL, PyScript, the example kit) keeps the app alive by itself.
    """
    try:
        from appdev import _hostloop
        from display_driver import app

        if not _launched_with_m(_hostloop) or _hostloop.ambient():
            return
        if getattr(getattr(sys, "flags", None), "interactive", 0):
            return
    except Exception:
        return
    if app.strategy != _hostloop.AMBIENT or app.timer_async:
        app.run()  # "none": blocking service loop (async timers: asyncio.run)
        return
    # "ambient" was chosen at import time; the timer already drives the app,
    # so just hold the main thread until the window closes. Hold it with the
    # timer backend's own sleep, never time.sleep: on Windows the timer fires
    # only while this thread is in an alertable wait (SleepEx), and a plain
    # time.sleep starves it -- the window then never repaints and Windows
    # marks it "Not Responding".
    from multimer import auto as timer

    while not app.quit_requested:
        timer.sleep_ms(50)


def _launched_with_m(_hostloop):
    """``-m`` / ``-c`` launch, even where the OS command line is unreadable.

    ``_hostloop.batch()`` reads the real command line. On micropython.exe that
    read fails (pydevices <= 0.5.0 decodes it with a UTF-16 codec MicroPython
    doesn't have), so a ``-m`` launch looked like a script run and the process
    returned after ~2 s (#142). MicroPython's own tell is ``sys.argv``: ``-m
    pkg`` leaves ``["pkg"]``, a script leaves its ``.py`` path, a REPL ``[]``
    or ``[""]``.
    """
    if _hostloop.batch():
        return True
    if getattr(sys.implementation, "name", "") != "micropython":
        return False
    argv = getattr(sys, "argv", None) or [""]
    first = argv[0] or ""
    return bool(first) and not first.endswith(".py") and not first.endswith(".mpy")


main()
