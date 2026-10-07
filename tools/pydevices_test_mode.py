"""
Example-matrix test flag (importable on MicroPython and CPython).

example_test_wrapper.py / PyScript harness.html set ENABLED = True before
running bounded examples. On single-threaded hosts the harness cannot inject
quit from another thread; call :func:`install_deadline_hook` so
provider ``timer.sleep_ms`` / ``appdev.App.poll`` cooperatively exit after
``DURATION_S``.

The underlying API is ``multimer.set_deadline_hook`` — development and
troubleshooting only; see https://github.com/PyDevices/pydevices/blob/main/docs/multimer.md.
"""

ENABLED = False
DURATION_S = 5.0

# Internal deadline bookkeeping (set by check_deadline).
_start_s = None
_deadline_fired = False


def check_deadline():
    """If test mode is active and ``DURATION_S`` elapsed, request app quit.

    Returns True when the deadline has fired (possibly just now).
    """
    global _start_s, _deadline_fired
    if not ENABLED:
        return False
    # Keep-alive only: do not arm or fire until ``run`` is on
    # the stack. ``app is None`` must also wait — an early timer tick during
    # import used to start the clock, fire with no app, set
    # ``_deadline_fired``, then never quit once the blocking loop started.
    try:
        import sys

        module = sys.modules.get("display_driver")
        if module is not None and hasattr(module, "app"):
            rt = getattr(module, "app", None)
        else:
            appdev = sys.modules.get("appdev")
            rt = (
                getattr(getattr(appdev, "App", None), "_current", None)
                if appdev is not None
                else None
            )
    except Exception:
        rt = None
    # appdev.App uses ``_blocking_run``; LVGL display_driver.app
    # uses ``_blocking`` for the same "inside run" gate.
    if rt is None or not (getattr(rt, "_blocking_run", False) or getattr(rt, "_blocking", False)):
        return False
    if getattr(rt, "_quit_requested", False):
        _deadline_fired = True
        return True
    import time

    now = time.time()
    if _start_s is None:
        _start_s = now
        return False
    if now - _start_s < float(DURATION_S):
        return False
    try:
        request = getattr(rt, "request_quit", None)
        if callable(request):
            request()
            _deadline_fired = True
        elif not getattr(rt, "quit_requested", False):
            handle = getattr(rt, "_handle_quit", None)
            if callable(handle):
                handle()
                _deadline_fired = True
    except Exception:
        pass
    return True


def _current_apps():
    """Every live app: LVGL's ``display_driver.app`` and ``appdev.App._current``
    (an LVGL example can run both, e.g. drum_machine's ``appdev`` ``app.run()``)."""
    import sys

    apps = []
    module = sys.modules.get("display_driver")
    if module is not None and getattr(module, "app", None) is not None:
        apps.append(module.app)
    appdev = sys.modules.get("appdev")
    current = (
        getattr(getattr(appdev, "App", None), "_current", None) if appdev is not None else None
    )
    if current is not None and current not in apps:
        apps.append(current)
    return apps


def arm_quit_timer():
    """Request every app's quit ``DURATION_S`` from now, from a multimer timer.

    On a host without threads (``micropython.exe``) nothing else can end an
    LVGL example: :func:`check_deadline` is gated on ``_blocking_run`` /
    ``_blocking``, and neither ``appdev.App.run()`` (``multimer.run_until``) nor
    multimer's exit-hook loop (examples that build their UI and end) calls the
    deadline hook from their ``sleep_ms``, so such an example ran until the
    kit's timeout. A multimer one-shot timer is delivered by both loops. When it
    fires before any app exists (slow imports), it tries again in 250 ms.
    Returns True when armed.
    """
    if not ENABLED:
        return False
    try:
        import multimer
    except ImportError:
        return False

    def _fire(_timer):
        global _deadline_fired
        apps = _current_apps()
        if not apps:
            multimer.after(250, _fire, name="test_mode.quit")
            return
        for rt in apps:
            try:
                request = getattr(rt, "request_quit", None)
                if callable(request):
                    request()
                else:
                    handle = getattr(rt, "_handle_quit", None)
                    if callable(handle):
                        handle()
            except Exception:
                pass
        _deadline_fired = True

    multimer.after(int(float(DURATION_S) * 1000), _fire, name="test_mode.quit")
    return True


def install_deadline_hook():
    """Register :func:`check_deadline` with ``multimer.set_deadline_hook``.

    Harness-only. Clear with ``multimer.set_deadline_hook(None)`` when finished
    if the process will keep running.
    """
    try:
        import multimer

        multimer.set_deadline_hook(check_deadline)
    except ImportError:
        pass
