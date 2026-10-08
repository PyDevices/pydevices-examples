# deps: lvgl
"""
lv_test_timer.py

LVGL timer smoke test. Uses whatever timer mode ``board_config`` / ``app``
already has.

Two cards. One says what this run is: the interpreter and OS, the display
driver, the screen (size, rotation and, on a desktop, the window's scale), the
timer's wake source, and LVGL's version. The other holds every moving part, so
the dirty areas stay together: an arc that turns once a second, stepping
every frame at the display's refresh period, with the seconds counted in its
middle (if the two timers drift apart, it shows), the display's frame rate (``display_drv.measure_fps``), and a tap
button for input. The frame rate is also in kit mode's ``KIT_RESULT`` line as
``fps``.

The layout fits any screen from 240x240 to 1280x720 with two rules: the cards
sit side by side only when the screen is more than 1.5 times wider than tall,
and the font is the largest built-in size at or below a twentieth of the
screen's short side.

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
from boarddev import env_get
import multimer

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

# A displaydev older than measure_fps has no meter: the label says so.
_measure = getattr(display_drv, "measure_fps", None)
if _measure is not None:
    _measure(True)


def get_fps():
    """The display's frame-rate dict, or None without a meter."""
    fps = getattr(display_drv, "fps", None)
    return fps() if fps is not None else None


def _mode_label():
    return multimer.info().get("source") or "sync"


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
    """multimer's wake source on this host (machine, native, signal, pending,
    asyncio, wasm or none). Callbacks run between bytecodes almost everywhere,
    so the delivery is shown only when it's the other kind, ``idle``, where
    they run only when the program yields to its loop (asyncio, a browser)."""
    info = multimer.info()
    source = info.get("source")
    return source if info.get("delivery") != "idle" else "%s, idle" % source


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
        # a desktop window's scale (after fitting the desktop); boards have none
        "scale": getattr(display_drv, "scale", None) or getattr(display_drv, "_scale", None),
    }


def timer_backend_name():
    return get_platform_info()["timer"]


_FONT_SIZES = (14, 16, 24, 32, 40)


def _font_for(short_side):
    """The largest built-in Montserrat at or below a twentieth of the short side."""
    best = None
    for size in _FONT_SIZES:
        font = getattr(lv, "font_montserrat_%d" % size, None)
        if font is not None and (best is None or size <= short_side // 20):
            best = font
    return best


def _fps_short(split=False):
    """The frame rate, the time each present takes, and the share of time
    spent presenting; on two lines when it sits beside the arc."""
    s = get_fps()
    if s is None:
        return "fps n/a"
    return "%.1f fps%s%.1f ms, %d%% busy" % (
        s["fps"],
        "\n" if split else ", ",
        s["present_ms"],
        round(s["busy"] * 100),
    )


def _card(parent, flow, pad):
    c = lv.obj(parent)
    c.set_style_pad_all(pad, 0)
    c.set_style_pad_gap(pad // 2, 0)
    c.set_flex_flow(flow)
    c.remove_flag(lv.obj.FLAG.SCROLLABLE)
    c.set_flex_grow(1)
    return c


def build_ui():
    """Build the timer test screen. Returns the tap button."""
    global _seconds, _taps, _arc_angle
    _seconds = 0
    _taps = 0
    _arc_angle = 0

    import display_driver

    inst = display_driver.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        scr = lv.screen_active()
        w = scr.get_width()
        h = scr.get_height()
        short = min(w, h)
        font = _font_for(short)
        big = _font_for(short * 2) or font
        pad = max(4, short // 40)
        try:
            th = lv.theme_default_init(
                lv.display_get_default(),
                lv.palette_main(lv.PALETTE.BLUE),
                lv.palette_main(lv.PALETTE.TEAL),
                True,
                font,
            )
            lv.display_get_default().set_theme(th)
        except AttributeError:
            pass
        scr.set_style_text_font(font, 0)
        scr.set_style_pad_all(pad, 0)
        scr.set_style_pad_gap(pad, 0)
        scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
        landscape = (
            w * 2 > h * 3
        )  # side by side only when the screen is more than 1.5 times wider than tall
        scr.set_flex_flow(lv.FLEX_FLOW.ROW if landscape else lv.FLEX_FLOW.COLUMN)

        info = get_platform_info()
        # The info card: what this run is, read once.
        card = _card(scr, lv.FLEX_FLOW.COLUMN, pad)
        if landscape:
            card.set_height(lv.pct(100))
        else:
            card.set_width(lv.pct(100))
        title = lv.label(card)
        title.set_text("LVGL timer test")
        title.set_style_text_color(lv.palette_main(lv.PALETTE.BLUE), 0)
        rows = (
            ("Python", "%s, %s" % (info["interpreter"], info["os"])),
            ("Display", info["display"]),
            (
                "Screen",
                "%s, rot %d%s"
                % (
                    info["resolution"],
                    info["rotation"],
                    ", x%.3g" % info["scale"] if info["scale"] and info["scale"] != 1 else "",
                ),
            ),
            ("Timer", info["timer"]),
            ("LVGL", info["lvgl"]),
        )
        muted = lv.palette_main(lv.PALETTE.GREY)
        for key, value in rows:
            row = lv.obj(card)
            row.remove_style_all()
            row.set_size(lv.pct(100), lv.SIZE_CONTENT)
            row.set_flex_flow(lv.FLEX_FLOW.ROW)
            row.set_flex_align(
                lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
            )
            row.set_style_pad_column(pad, 0)  # a key never runs into its value
            k = lv.label(row)
            k.set_text(key)
            k.set_style_text_color(muted, 0)
            v = lv.label(row)
            v.set_text(value)
            v.set_long_mode(lv.label.LONG_MODE.DOTS)
            v.set_style_max_width(lv.pct(72), 0)

        if landscape:
            card.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.START)
        else:
            card.set_flex_grow(0)
            card.set_height(lv.SIZE_CONTENT)
        # The live card lays out along its own long side: down when it's tall
        # (beside the info card, or under it on a portrait screen), across when
        # it's wide (under the info card on a square or landscape screen).
        across = not landscape and w * 10 >= h * 9

        # The live card: every moving part, so the dirty areas stay together.
        live = _card(scr, lv.FLEX_FLOW.ROW if across else lv.FLEX_FLOW.COLUMN, pad)
        live.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        if landscape:
            live.set_height(lv.pct(100))
        else:
            live.set_width(lv.pct(100))

        arc_d = short // 3 if across else short * 2 // 5
        arc = lv.arc(live)
        arc.set_size(arc_d, arc_d)
        arc.set_bg_angles(0, 360)
        arc.set_rotation(270)
        arc.set_angles(0, 0)
        arc.set_style_arc_width(max(4, arc_d // 12), lv.PART.MAIN)
        arc.set_style_arc_width(max(4, arc_d // 12), lv.PART.INDICATOR)
        arc.remove_style(None, lv.PART.KNOB)
        arc.remove_flag(lv.obj.FLAG.CLICKABLE)
        seconds_lbl = lv.label(arc)
        seconds_lbl.set_style_text_font(big, 0)
        seconds_lbl.set_text("0")
        seconds_lbl.center()

        side = live
        if across:
            # beside the arc: the frame rate over the button
            side = lv.obj(live)
            side.remove_style_all()
            side.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
            side.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            side.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
            side.set_style_pad_gap(pad, 0)
        fps_lbl = lv.label(side)
        fps_lbl.set_style_text_color(muted, 0)
        fps_lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        fps_lbl.set_text(_fps_short(across))

        btn = lv.button(side)
        btn.set_style_pad_hor(pad * 2, 0)
        btn.set_style_pad_ver(pad, 0)
        btn_lbl = lv.label(btn)
        btn_lbl.set_text("Tap  0")
        btn_lbl.center()

        def on_seconds_timer(_t):
            global _seconds
            _seconds += 1
            seconds_lbl.set_text(str(_seconds))
            fps_lbl.set_text(_fps_short(across))

        # The arc steps at the display's refresh period (33 ms unless the
        # display or PYDEVICES_REFRESH_MS says otherwise), so it changes every
        # frame and the frame rate shown is the display's, not this app's pace.
        # Its angle comes from the clock: one turn a second at any period, in
        # step with the seconds counter, which shows if the two timers drift.
        frame_ms = int(getattr(display_drv, "refresh_period_ms", 0) or 33)
        t0 = multimer.ticks_ms()

        def on_arc_timer(_t):
            global _arc_angle
            ms = multimer.ticks_diff(multimer.ticks_ms(), t0) % 1000
            _arc_angle = ms * 360 // 1000
            arc.set_angles(0, _arc_angle)

        def on_click(_e):
            global _taps
            _taps += 1
            btn_lbl.set_text("Tap  %d" % _taps)

        lv.timer_create(on_seconds_timer, 1000, None)
        lv.timer_create(on_arc_timer, frame_ms, None)
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
            # multimer.sleep_ms delivers on every host while this thread waits.
            multimer.sleep_ms(10)
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
        "fps": get_fps(),
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
        # multimer.sleep_ms, not time.sleep: a host with no wake source
        # (CircuitPython) delivers only while this thread waits here.
        multimer.sleep_ms(10)
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
        if multimer.loop_running():
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
    # tools/multimer_source_preload.py) the token is not at a fixed index, and
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
