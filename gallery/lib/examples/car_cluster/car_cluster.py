# gallery: nochrome
# deps: lvgl
# SPDX-License-Identifier: MIT
"""
car_cluster
====================================================
Flagship LVGL automobile instrument cluster.

Landscape 1024×512 cluster with Material accents, nested chrome, four side
gauges, dual steering-wheel style menu rails, and eight live center screens.

Controls:
  Left/Right — switch focus group (left rail / center / right rail)
  Up/Down    — previous/next control within the active group
  Enter      — activate focused control

Vehicle speed, gear, RPM, and oil pressure follow an automatic drive cycle
(speed ≈ 10× gear). Fuel and coolant stay fixed.
"""

import sys
import time

_file = __file__.replace("\\", "/")
_PKG = _file.rsplit("/", 1)[0]
_parts = _file.split("/")
# src/ is the parent of examples/ (package lives in examples/car_cluster/).
if "examples" in _parts:
    _idx = _parts.index("examples")
    _src = "/".join(_parts[:_idx]) if _idx else "."
else:
    _src = "."
if not _src:
    _src = "."
if _src not in sys.path:
    sys.path.insert(0, _src)
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import input_map  # noqa: E402 — capture hook must run before display_driver

input_map.capture_virtual_devices()

from displaydev import env_bool, env_get, env_set

env_set("PYDEVICES_WIDTH", "1024")
env_set("PYDEVICES_HEIGHT", "512")
if env_get("PYDEVICES_SCALE") is None:
    env_set("PYDEVICES_SCALE", "1")

import display_driver  # noqa: E402 — wires LVGL into the shared app
import lvgl as lv  # noqa: E402
from board_config import display_drv  # noqa: E402
from display_driver import app  # noqa: E402

import focus_nav  # noqa: E402
import input_map  # noqa: E402
import layout  # noqa: E402
from vehicle import Vehicle  # noqa: E402

_ui = None
_vehicle = None
_last_ms = None
_timer = None


def _now_ms():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.time() * 1000)


def _dt_s(now):
    global _last_ms
    if _last_ms is None:
        _last_ms = now
        return 0.05
    try:
        dt = time.ticks_diff(now, _last_ms) / 1000.0
    except AttributeError:
        dt = (now - _last_ms) / 1000.0
    _last_ms = now
    if dt < 0:
        dt = 0.05
    if dt > 0.25:
        dt = 0.25
    return dt


# Design / interactive freeze: set CAR_CLUSTER_FREEZE=1 (or truthy) to hold
# gauges/screens at static values so layout can be tweaked from the REPL.
_FREEZE = env_bool("CAR_CLUSTER_FREEZE", False)


def _on_tick(timer):
    global _ui, _vehicle
    if _ui is None or _vehicle is None:
        return
    if _FREEZE:
        return
    dt = _dt_s(_now_ms())
    _vehicle.tick(dt)
    _ui.update()


def freeze(static=True):
    """Hold or resume vehicle/gauge animation (interactive design helper)."""
    global _FREEZE
    _FREEZE = bool(static)
    if _FREEZE and _ui is not None and _vehicle is not None:
        # Snap once to a readable static scene.
        _vehicle.rpm = 3200
        _vehicle.speed_mph = 48
        _vehicle.fuel_frac = 0.62
        _vehicle.coolant_f = 195
        _vehicle.oil_psi = 42
        _ui.update()
    return _FREEZE


def build_ui():
    global _ui, _vehicle, _timer, _last_ms

    inst = display_driver.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        _vehicle = Vehicle()
        nav = focus_nav.FocusNav()

        bridge = input_map.InputBridge(app, _vehicle, focus_nav=nav)
        bridge.install()

        _ui = layout.ClusterUI(_vehicle, focus_nav=nav)
        # Groups are populated by layout; start focus on the left rail.
        nav.set_active(focus_nav.FocusNav.LEFT)
        _last_ms = _now_ms()
        _timer = lv.timer_create(_on_tick, 40, None)

        # Apply deferred rail→tabview changes outside LVGL task_handler.
        def _drain_rails(_t):
            if _ui is not None and _ui.rails is not None:
                _ui.rails.drain_pending()

        app.on_tick(_drain_rails, period=30, async_=False)
        _ui.rails.drain_pending()
        if _FREEZE:
            freeze(True)
    finally:
        if inst is not None:
            inst.enable()


build_ui()

# The app keeps itself alive past the end of this script, and stays live under
# a REPL ``import`` (design session) on signal-driven backends too.
