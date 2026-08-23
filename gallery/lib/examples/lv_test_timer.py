# deps: lvgl
"""
lv_test_timer.py

LVGL timer smoke test. Uses whatever timer mode ``board_config`` / ``app``
already has.

Shows interpreter, OS, display, timer backend, and LVGL version; a seconds counter
and spinning arc prove LVGL timers fire; a tap button exercises input.

Interactive (default): build the UI and let the app run itself — no trailing
``app.run()``. At a REPL the prompt comes back for introspection while LVGL
keeps ticking. Kit mode (``kit`` argv) still uses a short sync/async wait for
click injection because LVGL owns the host queue.

Parent may set before launch:

* ``PYDEVICES_TIMER_ASYNC`` — desktop sync/async timers (``board_config``)
* ``PYDEVICES_LV_ROTATION`` — ``0``/``90``/``180``/``270`` applied to
  ``display_drv.rotation`` before ``display_driver`` import
"""

import sys

_file = __file__.replace("\\", "/").split("/")
if len(_file) >= 2 and _file[-2] == "examples":
    _src = "/".join(_file[:-2]) or "."
else:
    _src = "."
if _src not in sys.path:
    sys.path.insert(0, _src)
_tools = _src + "/../tools"
if _tools not in sys.path:
    sys.path.insert(0, _tools)

import json
import time

from board_config import display_drv
from displaydev import env_get
from multimer import auto as timer

# Optional logical orientation for LVGL (hw MADCTL/SDL/PG or software rotate).
_lv_rot = env_get("PYDEVICES_LV_ROTATION")
if _lv_rot is not None and str(_lv_rot).strip() != "":
    try:
        display_drv.rotation = int(str(_lv_rot).strip())
    except (TypeError, ValueError):
        pass

import display_driver
import lvgl as lv
from display_driver import app

_seconds = 0
_taps = 0
_arc_angle = 0

_DURATION_S = 4
_RESULT_PREFIX = "KIT_RESULT="


def _mode_label():
    return "async" if getattr(app, "timer_async", False) else "sync"


def get_state():
    return {"seconds": _seconds, "taps": _taps}


def reset_taps():
    global _taps
    _taps = 0


def _format_timer_type(timer_cls):
    if timer_cls is None:
        return "?"
    # MicroPython's machine.Timer often has no __module__; still label it.
    try:
        import machine

        if timer_cls is getattr(machine, "Timer", None):
            return "machine"
    except ImportError:
        pass
    mod = getattr(timer_cls, "__module__", None) or "?"
    name = getattr(timer_cls, "__name__", "?")
    part = mod.rsplit(".", 1)[-1]
    if part == "aio":
        return "aio"
    if part.startswith("_"):
        return part
    if mod in ("machine", "multimer"):
        return name if mod == "multimer" else mod
    return part if part == name else f"{part}.{name}"


def _interpreter_label():
    impl = getattr(sys, "implementation", None)
    if impl is None:
        return "python"
    name = getattr(impl, "name", "python")
    ver = getattr(impl, "version", None)
    if ver and isinstance(ver, (tuple, list)) and ver:
        if len(ver) >= 2:
            return f"{name} {ver[0]}.{ver[1]}"
        return f"{name} {ver[0]}"
    return name


def _lvgl_label():
    try:
        return f"{lv.version_major()}.{lv.version_minor()}"
    except AttributeError:
        pass
    try:
        info = lv.version_info()
        if info and len(info) >= 2:
            return f"{info[0]}.{info[1]}"
    except (AttributeError, TypeError):
        pass
    return "?"


def _timer_type():
    # Deliberately not named ``timer``: that would shadow the module-level
    # ``multimer.auto`` import this function falls back to, and the fallback
    # then reads None on any provider that has not armed yet.
    armed = getattr(app, "_timer", None)
    if armed is not None:
        return _format_timer_type(type(armed))
    try:
        from multimer import AsyncTimer

        return _format_timer_type(AsyncTimer if app.timer_async else timer.Timer)
    except ImportError:
        return "?"


def get_platform_info():
    w = int(getattr(display_drv, "width", 0) or 0)
    h = int(getattr(display_drv, "height", 0) or 0)
    return {
        "interpreter": _interpreter_label(),
        "os": sys.platform,
        "display": type(display_drv).__name__,
        "resolution": f"{w}x{h}",
        "timer": _timer_type(),
        "lvgl": _lvgl_label(),
        "mode": _mode_label(),
        "rotation": int(getattr(display_drv, "rotation", 0) or 0),
    }


def timer_backend_name():
    return get_platform_info()["timer"]


def _add_info_labels(scr, info, y_start=26, line_h=16):
    lines = (
        f"Mode: {info['mode']}",
        f"Interpreter: {info['interpreter']}",
        f"OS: {info['os']}",
        f"Display: {info['display']} {info.get('resolution', '?')}",
        f"Timer: {info['timer']}",
        f"LVGL: {info['lvgl']}",
        f"Rotation: {info.get('rotation', 0)}",
    )
    y = y_start
    for text in lines:
        lbl = lv.label(scr)
        lbl.set_text(text)
        lbl.align(lv.ALIGN.TOP_MID, 0, y)
        y += line_h


def build_ui():
    """Build the timer test screen. Returns the tap button."""
    global _seconds, _taps, _arc_angle
    _seconds = 0
    _taps = 0
    _arc_angle = 0

    # Pause shared LVGL task_handler while constructing widgets (not re-entrant).
    import display_driver

    inst = display_driver.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        scr = lv.screen_active()
        info = get_platform_info()

        title = lv.label(scr)
        title.set_text("LVGL Timer Test")
        title.align(lv.ALIGN.TOP_MID, 0, 8)
        _add_info_labels(scr, info)

        btn = lv.button(scr)
        btn.set_size(120, 50)
        btn.align(lv.ALIGN.BOTTOM_MID, 0, -30)
        btn_lbl = lv.label(btn)
        btn_lbl.set_text("Tap me (0)")
        btn_lbl.center()

        arc = lv.arc(scr)
        arc.set_size(80, 80)
        arc.align_to(btn, lv.ALIGN.OUT_TOP_MID, 0, -8)
        arc.set_bg_angles(0, 360)
        arc.set_angles(0, 0)
        arc.remove_style(None, lv.PART.KNOB)
        arc.remove_flag(lv.obj.FLAG.CLICKABLE)

        seconds_lbl = lv.label(scr)
        seconds_lbl.set_text("Seconds: 0")
        seconds_lbl.align_to(arc, lv.ALIGN.OUT_TOP_MID, 0, -4)

        def on_seconds_timer(_t):
            global _seconds
            _seconds += 1
            seconds_lbl.set_text(f"Seconds: {_seconds}")

        def on_arc_timer(_t):
            global _arc_angle
            _arc_angle = (_arc_angle + 10) % 360
            arc.set_angles(0, _arc_angle)

        def on_click(_e):
            global _taps
            _taps += 1
            btn_lbl.set_text(f"Tap me ({_taps})")

        lv.timer_create(on_seconds_timer, 1000, None)
        lv.timer_create(on_arc_timer, 50, None)
        btn.add_event_cb(on_click, lv.EVENT.CLICKED, None)
        return btn
    finally:
        if inst is not None:
            inst.enable()


def _setup():
    """Import display_driver (LVGL) then build UI. Call from sync/async entry."""
    import display_driver  # noqa: F401

    return build_ui()


# --- kit / automated path (tools/lv_timer_test_kit.py) ---


def _button_center(btn):
    from board_config import display_drv

    try:
        area = lv.area_t()
        btn.get_coords(area)
        return (area.x1 + area.x2) // 2, (area.y1 + area.y2) // 2
    except Exception:
        return display_drv.width // 2, display_drv.height - 55


def _inject_click(cx, cy):
    import quit_inject
    import events

    reset_taps()
    queue_dev = quit_inject.queue_device()
    if queue_dev is None:
        return 0

    # LVGL coords are display space; the queue device expects host-window pixels.
    at = quit_inject.host_point(cx, cy)
    pending = [
        events.Button(events.MOUSEBUTTONDOWN, at, 1, False, None),
        events.Button(events.MOUSEBUTTONUP, at, 1, False, None),
    ]
    orig_read = queue_dev._read

    def mock_read():
        return [pending.pop(0)] if pending else None

    queue_dev._read = mock_read
    try:
        deadline = time.time() + 1.5
        while (pending or get_state()["taps"] < 1) and time.time() < deadline:
            # Pump: the host queue is drained from the app tick, which
            # pump-based backends only deliver while the main thread sleeps here.
            timer.sleep_ms(10)
    finally:
        queue_dev._read = orig_read
    return get_state()["taps"]


async def _inject_click_async(cx, cy):
    import quit_inject
    import events
    from multimer import asyncio

    reset_taps()
    queue_dev = quit_inject.queue_device()
    if queue_dev is None:
        return 0

    at = quit_inject.host_point(cx, cy)
    pending = [
        events.Button(events.MOUSEBUTTONDOWN, at, 1, False, None),
        events.Button(events.MOUSEBUTTONUP, at, 1, False, None),
    ]
    orig_read = queue_dev._read

    def mock_read():
        return [pending.pop(0)] if pending else None

    queue_dev._read = mock_read
    try:
        deadline = time.time() + 1.5
        while (pending or get_state()["taps"] < 1) and time.time() < deadline:
            await asyncio.sleep(0.01)
    finally:
        queue_dev._read = orig_read
    return get_state()["taps"]


def _emit_result(state, taps):
    mode = _mode_label()
    seconds = state["seconds"]
    if seconds < 2:
        click, status = "no timers", "fail"
    elif taps >= 1:
        click, status = "ok", "ok"
    else:
        click, status = "no clicks", "fail"
    payload = {
        "mode": mode,
        "status": status,
        "click_status": click,
        "backend": timer_backend_name(),
        "seconds": seconds,
        "taps": taps,
    }
    print(_RESULT_PREFIX + json.dumps(payload, separators=(",", ":")))
    sys.stdout.flush()
    return payload


def _quit_and_exit(code=0):
    try:
        app.stop_timer()
    except Exception:
        pass
    try:
        display_drv.force_quit(code)
    except SystemExit:
        raise
    except Exception:
        pass
    raise SystemExit(code)


def _run_kit_sync():
    btn = _setup()
    deadline = time.time() + _DURATION_S
    clicked_taps = None
    while time.time() < deadline:
        # timer.sleep_ms, not time.sleep: pump-based backends (threading on
        # CircuitPython / Windows CPython, SDL2) deliver callbacks only
        # while the main thread pumps. For librt this resolves to a plain sleep.
        timer.sleep_ms(10)
        if clicked_taps is None and get_state()["seconds"] >= 2:
            cx, cy = _button_center(btn)
            clicked_taps = _inject_click(cx, cy)

    state = get_state()
    taps = clicked_taps if clicked_taps is not None else state["taps"]
    payload = _emit_result(state, taps)
    _quit_and_exit(0 if payload["status"] == "ok" else 1)


async def _run_kit_async():
    btn = _setup()
    from multimer import asyncio

    deadline = time.time() + _DURATION_S
    clicked_taps = None
    while time.time() < deadline:
        # Do not app.poll() while LVGL owns the host queue (indev reads it).
        await asyncio.sleep(0.01)
        if clicked_taps is None and get_state()["seconds"] >= 2:
            cx, cy = _button_center(btn)
            clicked_taps = await _inject_click_async(cx, cy)

    state = get_state()
    taps = clicked_taps if clicked_taps is not None else state["taps"]
    return _emit_result(state, taps)


def run_kit():
    """Automated timer + click check.

    Interactive apps need no explicit loop at all. The kit still needs a
    small sync/async wait flavor because LVGL click injection must pump either
    ``time.sleep`` (sync timer) or ``asyncio.sleep`` (async timer) — not
    ``app.poll()`` while LVGL owns the host queue.
    """
    try:
        if app.timer_async:
            payload = app.run_async(_run_kit_async)
            if payload is not None and hasattr(payload, "done"):
                _quit_and_exit(1)
            _quit_and_exit(0 if payload and payload.get("status") == "ok" else 1)
        else:
            _run_kit_sync()
    except SystemExit:
        raise
    except Exception as exc:
        print(
            _RESULT_PREFIX
            + json.dumps(
                {
                    "mode": _mode_label(),
                    "status": "error",
                    "backend": timer_backend_name(),
                    "error": repr(exc),
                },
                separators=(",", ":"),
            )
        )
        raise


def _wants_kit():
    # Scan the whole command line: under a runner (e.g.
    # tools/multimer_backend_preload.py) the token is not at a fixed index, and
    # CircuitPython cannot rewrite sys.argv to move it.
    return any(arg in ("kit", "harness") for arg in sys.argv[1:])


if _wants_kit():
    run_kit()
else:
    # Canonical interactive entry — no app loop here. display_driver wires LVGL
    # into the shared app at import, and the app keeps itself alive past the
    # end of this script.
    import display_driver  # noqa: F401

    build_ui()
