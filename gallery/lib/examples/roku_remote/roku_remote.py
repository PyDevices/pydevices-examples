# deps: lvgl, pygraphics, pdwidgets
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_remote
====================================================
Launcher for the Roku remote stack.

Loads prefs (``frontend``, MRU host/serial, saved TVs), resumes the last TV
when its serial still matches, then starts the chosen front end:

* :mod:`roku_engine`   -- ECP client + discovery + prefs (no UI)
* :mod:`roku_sim`      -- offline / PyScript stand-in (``make_engine``)
* :mod:`roku_lvgl`     -- LVGL front end (default)
* :mod:`roku_widgets`  -- ``pdwidgets`` front end
* :mod:`roku_graphics` -- ``pygraphics.FrameBuffer`` front end

Switching front ends from MORE writes prefs then calls
:func:`roku_engine.restart_app` (MCU ``reset``, else exit ``42`` after clean
teardown). Desktop relaunch is a host shell loop on exit ``42`` only — there
is no in-process ``execv``. PyScript / Jupyter only show ``reload page`` /
``restart kernel``. Soft-reset is not relied on (it does not re-run ``main.py``).

Desktop launch from ``pydevices-examples/lib`` (same for ``micropython``,
``micropython.exe``, ``circuitpython``, ``python``, ``python.exe``)::

    # once
    micropython -m examples.roku_remote

    # relaunch on frontend switch (exit 42); stop on normal SDL quit (0)
    # bash / WSL:
    while true; do micropython -m examples.roku_remote; [ $? -eq 42 ] || break; done
    # PowerShell:
    while ($true) { micropython -m examples.roku_remote; if ($LASTEXITCODE -ne 42) { break } }

Requires Roku **Control by mobile apps -> Enabled**; join WiFi before running
on a microcontroller. Optional fixed target: ``ROKU_HOST`` in :mod:`roku_engine`.

Desktop panel size: edit ``_WIDTH`` / ``_HEIGHT`` / ``_SCALE`` below. Those are
applied via ``displaydev.env_set`` before any front end imports ``board_config``.
Leave ``_SCALE`` as ``None`` to keep the desktop ``AutoDisplay`` default
(autoscale still fits the window).
"""

import sys

_PKG = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from displaydev import env_set

# Local desktop test panel — change these and re-run. Must stay above board_config.
# Match LilyGO T-HMI (ST7789 I80): 240x320. Never apply on MCU boards (panel
# size comes from that board's board_config / display_drv).
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
    env_set("PYDEVICES_WIDTH", _WIDTH)
    env_set("PYDEVICES_HEIGHT", _HEIGHT)
    if _SCALE is not None:
        env_set("PYDEVICES_SCALE", _SCALE)

import roku_engine  # noqa: E402
from roku_engine import (  # noqa: E402
    DEFAULT_FRONTEND,
    get_frontend,
    start_page_for_engine,
)
from roku_sim import make_engine  # noqa: E402


# Front ends that allocate a full-panel Python ``bytearray`` (RGB565).
_PYTHON_FB_FRONTENDS = ("widgets", "pygraphics")


def _import_frontend(name):
    """Import one front-end module by prefs id."""
    if name == "widgets":
        import roku_widgets as mod

        return mod
    if name == "graphics":
        import roku_graphics as mod

        return mod
    import roku_lvgl as mod

    return mod


def _frontend_candidates(preferred):
    """Preferred first, then defaults — session fallbacks never rewrite prefs."""
    ordered = []
    for name in (preferred, DEFAULT_FRONTEND, "lvgl", "pygraphics", "widgets"):
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def _panel_fb_bytes():
    """Bytes for one RGB565 panel buffer at the launcher size."""
    w, h = _WIDTH, _HEIGHT
    if w is None or h is None:
        from board_config import display_drv

        if w is None:
            w = display_drv.width
        if h is None:
            h = display_drv.height
    return int(w) * int(h) * 2


def _can_alloc_panel_fb():
    """True when a contiguous panel-sized ``bytearray`` can be allocated.

    CircuitPython unix often reports megabytes free but refuses ~512KiB+
    contiguous allocs — enough to OOM widgets/graphics at 480x800, while LVGL
    (native buffers) still runs. Probe once before trying those front ends.
    """
    n = _panel_fb_bytes()
    try:
        import gc

        gc.collect()
        buf = bytearray(n)
        del buf
        gc.collect()
        return True
    except MemoryError:
        return False


def main():
    # Suppress front-end auto-start on import; we call ``run()`` below.
    roku_engine._LAUNCHER_OWNS_RUN = True

    engine = make_engine()
    # Probe prefs MRU (last_host / last_serial): online → REMOTE, else SELECT.
    start_page = start_page_for_engine(engine)
    print(
        "roku_remote: start_page=%s host=%s err=%s"
        % (
            start_page,
            getattr(engine, "host", "") or "",
            getattr(engine, "last_error", "") or "",
        )
    )

    preferred = get_frontend()
    fb_ok = None
    last_err = None
    for name in _frontend_candidates(preferred):
        if name in _PYTHON_FB_FRONTENDS:
            if fb_ok is None:
                fb_ok = _can_alloc_panel_fb()
            if not fb_ok:
                print(
                    "roku_remote: %s front end skipped (need %d-byte panel buffer)"
                    % (name, _panel_fb_bytes())
                )
                last_err = MemoryError("panel buffer %d bytes" % _panel_fb_bytes())
                continue
        try:
            mod = _import_frontend(name)
            if name != preferred:
                print(
                    "roku_remote: falling back to %s (prefs=%s)"
                    % (name, preferred)
                )
            mod.run(engine=engine, start_page=start_page)
            return
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception as err:
            # Import/create failure — stay on prefs; try the next candidate.
            print("roku_remote: %s front end unavailable (%s)" % (name, err))
            last_err = err
            # Only a real OOM says anything about the panel buffer. Any other
            # failure (a bad import, a missing binding) is specific to this
            # front end, and must not disable the remaining framebuffer one --
            # doing so skipped the last working fallback and reported the
            # unrelated error as "need N-byte panel buffer".
            if name in _PYTHON_FB_FRONTENDS and isinstance(err, MemoryError):
                fb_ok = False
            try:
                import gc

                gc.collect()
            except Exception:
                pass
    if last_err is not None:
        raise last_err


main()
