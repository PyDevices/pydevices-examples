#!/usr/bin/env python3
"""
Subprocess entry point for one cross-interpreter example smoke test.

Invoked from src/ by example_test_kit.py:

    micropython ../tools/example_test_wrapper.py pydevices_demo \\
        --script examples/pydevices_demo.py --kind loop --duration 5

Prints EXAMPLE_RESULT={...} on stdout before exit.
"""

import json
import os
import sys
import time


def _dir_of(path):
    path = path.replace("\\", "/")
    if "/" in path:
        return path.rsplit("/", 1)[0]
    return "."


def _join(*parts):
    if not parts:
        return ""
    out = str(parts[0]).replace("\\", "/")
    for part in parts[1:]:
        if not part:
            continue
        part = str(part).replace("\\", "/").strip("/")
        if not out.endswith("/"):
            out += "/"
        out += part
    return out


def _isdir(path):
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def _isfile(path):
    try:
        with open(path):
            pass
        return True
    except OSError:
        return False


def _env_get(key):
    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            value = environ.get(key)
            if value:
                return value
        except Exception:
            pass
    getenv = getattr(os, "getenv", None)
    if getenv is not None:
        try:
            return getenv(key)
        except Exception:
            pass
    return None


def _env_set(key, value):
    """Set a real process environment value on CPython and small ports."""
    changed = False
    environ = getattr(os, "environ", None)
    if environ is not None:
        try:
            environ[key] = value
            changed = True
        except Exception:
            pass
    putenv = getattr(os, "putenv", None)
    if putenv is not None:
        try:
            putenv(key, value)
            changed = True
        except Exception:
            pass
    if not changed:
        raise ImportError("process environment cannot be changed")


_TOOLS = _dir_of(__file__)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

RESULT_PREFIX = "EXAMPLE_RESULT="
_MULTIMER_TEST_TIMERS = []


def _trace(msg):
    if _env_get("PYDEVICES_TEST_TRACE"):
        print("example_test_wrapper: {}".format(msg), file=sys.stderr)


def _print_result(payload):
    line = RESULT_PREFIX + json.dumps(payload, separators=(",", ":"))
    print(line)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _sleep(seconds):
    time.sleep(seconds)


def _system_exit_code(exc):
    return getattr(exc, "code", None)


def _exec_script(script_path):
    with open(script_path, encoding="utf-8") as f:
        code = f.read()
    namespace = {"__name__": "__main__", "__file__": script_path}
    exec(code, namespace)


def _run_script_in_thread(script_path):
    """Run script_path in a background thread when _thread is available."""
    try:
        import _thread
    except ImportError:
        _thread = None

    state = {"error": None, "done": False}

    def target():
        try:
            _exec_script(script_path)
        except SystemExit as exc:
            code = _system_exit_code(exc)
            if code not in (0, None):
                state["error"] = "exit_{}".format(code)
        except Exception as exc:
            state["error"] = "{}: {}".format(type(exc).__name__, exc)
        finally:
            state["done"] = True

    if _thread is not None:
        _thread.start_new_thread(target, ())
        return state, True

    target()
    return state, False


def _monotonic():
    if hasattr(time, "monotonic"):
        return time.monotonic()
    return time.time()


def _wait_thread(state, threaded, timeout_s):
    if not threaded:
        return state.get("error")

    deadline = _monotonic() + timeout_s
    while _monotonic() < deadline:
        if state.get("done"):
            return state.get("error")
        _sleep(0.05)
    return "thread_timeout"


def _backend_name():
    try:
        import quit_inject

        return quit_inject.display_backend_name()
    except Exception:
        return "?"


def _setup_sibling_paths(src):
    """Ensure top-level palettes/pdwidgets resolve (PYTHONPATH or local discovery)."""
    try:
        import sibling_repos
    except ImportError:
        sibling_repos = None

    if sibling_repos is not None:
        # ``src`` is ``…/pydevices-examples/lib``; repo root is its parent. Do not use
        # ``_dir_of(_join(src, ".."))`` — that leaves a literal ``..`` segment
        # and resolves to ``src`` again. Always Unix paths (not WSL UNC / U:).
        src = sibling_repos.unix_path(src)
        repo_root = _dir_of(src)
        sibling_repos.prepend_sibling_sys_path(repo_root=repo_root)
        return

    for key in ("PYDEVICES_PALETTES_SRC", "PYDEVICES_PDWIDGETS_SRC"):
        path = _env_get(key)
        if path and _isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def _setup_bootstrap(src, mode):
    """Ensure PyDevices packages resolve; prefer env PYTHONPATH/MICROPYPATH.

    Headless uses the sibling core checkout when present, then skips
    display-oriented path setup. When env already seeds product packages /
    ``utils``, skip ``utils.path``. Fall back to ``import utils.path`` only if
    ``displaydev`` is not importable (MCU-style / unset env).
    """
    _setup_sibling_paths(src)
    if mode == "headless":
        repo_root = _dir_of(src)
        workspace_root = _dir_of(repo_root)
        core_lib = _join(workspace_root, "pydevices", "lib")
        if _isdir(core_lib) and core_lib not in sys.path:
            sys.path.insert(0, core_lib)
        return

    # Always apply utils.path: even when displaydev is pip-installed, checkout
    # examples still need sibling ``pydevices/utils`` (keypins, mip, …) and
    # ``utils/`` on sys.path. Import is idempotent about existing entries.
    try:
        import utils.path  # noqa: F401
    except Exception as exc:
        # Fall back only when utils.path is unavailable (MCU flat /lib install).
        try:
            import displaydev  # noqa: F401
        except ImportError:
            raise RuntimeError("utils.path: {}".format(exc)) from exc


def _run_oneshot(script_path, timeout_s):
    try:
        _exec_script(script_path)
        return None
    except SystemExit as exc:
        code = _system_exit_code(exc)
        if code in (0, None):
            return None
        return "exit_{}".format(code)
    except Exception as exc:
        return "{}: {}".format(type(exc).__name__, exc)


def _use_main_thread_for_bounded():
    try:
        name = sys.implementation.name
    except AttributeError:
        return False
    return name in ("cpython", "micropython", "circuitpython")


def _cooperative_lvgl_quit(kind):
    """Skip daemon quit-inject for LVGL; example must self-exit via test mode."""
    if kind != "lvgl":
        return False
    try:
        name = sys.implementation.name
    except AttributeError:
        return False
    # CircuitPython / CPython: daemon inject + LVGL is unsafe (librt deadlock).
    # MicroPython (incl. micropython.exe): no background inject thread; prefer
    # deadline-hook cooperative exit over poll-patch + SDL quit timers.
    return name in ("circuitpython", "cpython", "micropython")


def _touch_delay_s(duration_s):
    return min(duration_s * 0.2, max(0.5, duration_s - 1.0))


def _has_background_inject():
    """True when a daemon thread can sleep then inject quit (not MicroPython)."""
    try:
        import threading

        threading.Thread  # noqa: B018
        return True
    except ImportError:
        pass
    try:
        import _thread  # noqa: F401

        return True
    except ImportError:
        return False


def _install_poll_deadline_quit(duration_s, injected=None):
    """Arm quit via the next ``app.poll()`` when background inject is unavailable.

    MicroPython ``micropython.exe`` has no ``threading`` / ``_thread``; the multimer
    SDL quit timer often never fires when the schedule queue is full. Patching
    ``appdev.App.poll`` avoids a competing timer while keeping quit on the example
    main thread. Does not import ``board_config`` (examples must load it).
    """
    try:
        import appdev
    except Exception:
        return False
    app_cls = appdev.App
    if getattr(app_cls, "_pydevices_poll_deadline_armed", False):
        return True
    deadline = _monotonic() + duration_s
    state = {"fired": False}
    orig_poll = app_cls.poll

    def poll(self):
        if not state["fired"] and _monotonic() >= deadline:
            state["fired"] = True
            try:
                import pydevices_test_mode

                if pydevices_test_mode.ENABLED:
                    self._handle_quit()
                    if injected is not None:
                        injected[0] = True
                    return orig_poll(self)
            except ImportError:
                pass
            import quit_inject

            if (
                quit_inject.inject_quit(broker_poll=False, pump_count=0, deinit=False)
                and injected is not None
            ):
                injected[0] = True
        return orig_poll(self)

    app_cls.poll = poll
    app_cls._pydevices_poll_deadline_armed = True
    return True


def _inject_quit_now(quit_inject, kind, injected, *, pump_count=20):
    lvgl = kind == "lvgl"
    ok = quit_inject.inject_quit(
        broker_poll=False,
        pump_count=pump_count,
        pump_delay=0.02,
        lvgl=lvgl,
    )
    if ok:
        injected[0] = True


def _start_multimer_quit_schedule(duration_s, quit_mode, kind, injected):
    """Schedule delayed quit/touch injection when threads are unavailable."""
    try:
        import quit_inject

        import multimer as timer
    except ImportError:
        return False
    try:
        quit_inject.queue_device()
    except Exception:
        pass

    def on_quit(_timer):
        # Leave Quit on the QUEUE mock; the example's app.poll() delivers it.
        _inject_quit_now(quit_inject, kind, injected, pump_count=0)

    def on_touch(_timer):
        quit_inject.inject_synthetic_touch(broker_poll=False, pump_count=0)

    touch_delay = _touch_delay_s(duration_s)
    if quit_mode == "inject" and touch_delay > 0:
        touch_timer = timer.Timer(-1)
        touch_timer.init(
            mode=timer.Timer.ONE_SHOT,
            period=int(touch_delay * 1000),
            callback=on_touch,
        )
        _MULTIMER_TEST_TIMERS.append(touch_timer)

    quit_timer = timer.Timer(-1)
    quit_timer.init(
        mode=timer.Timer.ONE_SHOT,
        period=int(duration_s * 1000),
        callback=on_quit,
    )
    _MULTIMER_TEST_TIMERS.append(quit_timer)
    return True


def _run_bounded_main_thread(script_path, kind, duration_s, timeout_s, quit_mode):
    injected = [False]
    cooperative = _cooperative_lvgl_quit(kind)
    use_poll_deadline = not cooperative and not _has_background_inject()

    if use_poll_deadline:
        # No background thread (e.g. micropython.exe): patch poll + deadline hook.
        _install_poll_deadline_quit(duration_s, injected)
    elif quit_mode == "inject" and not cooperative:
        # Daemon inject is only for quit=inject. quit=poll must not start it:
        # on CPython sync/librt, inject_quit from a worker wedges the main
        # thread so neither Quit delivery nor the deadline hook can run.
        import quit_inject

        def delayed_inject():
            touch_delay = _touch_delay_s(duration_s)
            if touch_delay > 0:
                _sleep(touch_delay)
                quit_inject.inject_synthetic_touch(broker_poll=False)
            _sleep(max(0, duration_s - touch_delay))
            _inject_quit_now(quit_inject, kind, injected)

        try:
            import threading

            threading.Thread(target=delayed_inject, daemon=True).start()
        except ImportError:
            daemon_started = _start_daemon(delayed_inject)
            if not daemon_started and not _start_multimer_quit_schedule(
                duration_s, quit_mode, kind, injected
            ):
                delayed_inject()
    else:
        # quit=poll (or cooperative LVGL): deadline hook installed in main().
        try:
            import pydevices_test_mode

            pydevices_test_mode.ENABLED = True
            pydevices_test_mode.DURATION_S = duration_s
            pydevices_test_mode.install_deadline_hook()
        except ImportError:
            pass

    try:
        _exec_script(script_path)
        if cooperative:
            return None, True
        return None, injected[0]
    except SystemExit as exc:
        code = _system_exit_code(exc)
        if code in (0, None):
            return None, injected[0]
        return "exit_{}".format(code), injected[0]
    except Exception as exc:
        return "{}: {}".format(type(exc).__name__, exc), injected[0]


def _start_daemon(target):
    try:
        import threading

        threading.Thread(target=target, daemon=True).start()
        return True
    except ImportError:
        pass
    try:
        import _thread

        _thread.start_new_thread(target, ())
        return True
    except ImportError:
        return False


def _run_interactive(script_path, duration_s, example, kind):
    """Run on main thread (SDL); pass after duration_s even if script blocks in help()/REPL."""

    def finisher():
        _sleep(duration_s)
        backend = _backend_name()
        _print_result(
            {
                "example": example,
                "status": "ok",
                "kind": kind,
                "backend": backend,
                "duration_s": duration_s,
                "quit_injected": False,
            }
        )
        _subprocess_hard_exit(0)

    if not _start_daemon(finisher):
        return "interactive_requires_thread"

    try:
        _exec_script(script_path)
        return None
    except SystemExit as exc:
        code = _system_exit_code(exc)
        if code in (0, None):
            return None
        return "exit_{}".format(code)
    except Exception as exc:
        return "{}: {}".format(type(exc).__name__, exc)


def _run_bounded(script_path, kind, duration_s, timeout_s, quit_mode):
    if _use_main_thread_for_bounded():
        return _run_bounded_main_thread(script_path, kind, duration_s, timeout_s, quit_mode)

    import quit_inject

    state, threaded = _run_script_in_thread(script_path)
    if not threaded:
        err = state.get("error")
        if err:
            return err, False
        return "hang_no_thread", False

    _trace("running {}s before quit injection".format(duration_s))
    touch_delay = min(duration_s * 0.2, max(0.5, duration_s - 1.0))
    if quit_mode == "inject" and touch_delay > 0:
        _sleep(touch_delay)
        quit_inject.inject_synthetic_touch(broker_poll=False)
    _sleep(max(0, duration_s - touch_delay))

    lvgl = kind == "lvgl"
    injected = quit_inject.inject_quit(
        broker_poll=False,
        pump_count=20,
        pump_delay=0.02,
        lvgl=lvgl,
    )
    if not injected:
        return "no_queue_device", False

    err = _wait_thread(state, threaded, timeout_s=min(10, timeout_s))
    if err:
        return err, True
    if not state.get("done"):
        return "quit_not_handled", True
    return None, True


def _parse_args(argv):
    if len(argv) < 2:
        raise ValueError("usage: example_test_wrapper.py EXAMPLE --script PATH --kind KIND")
    out = {
        "example": argv[1],
        "script": None,
        "kind": None,
        "quit": "poll",
        "bootstrap": "full",
        "duration": 5.0,
        "timeout": 30.0,
        "timer_async": None,
        "multimer_source": None,
        "env": [],
    }
    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--script" and i + 1 < len(argv):
            out["script"] = argv[i + 1]
            i += 2
        elif arg == "--kind" and i + 1 < len(argv):
            out["kind"] = argv[i + 1]
            i += 2
        elif arg == "--quit" and i + 1 < len(argv):
            out["quit"] = argv[i + 1]
            i += 2
        elif arg == "--bootstrap" and i + 1 < len(argv):
            out["bootstrap"] = argv[i + 1]
            i += 2
        elif arg == "--duration" and i + 1 < len(argv):
            out["duration"] = float(argv[i + 1])
            i += 2
        elif arg == "--timeout" and i + 1 < len(argv):
            out["timeout"] = float(argv[i + 1])
            i += 2
        elif arg == "--timer-async" and i + 1 < len(argv):
            out["timer_async"] = argv[i + 1]
            i += 2
        elif arg == "--multimer-source" and i + 1 < len(argv):
            out["multimer_source"] = argv[i + 1]
            i += 2
        elif arg == "--env" and i + 1 < len(argv):
            out["env"].append(argv[i + 1])
            i += 2
        else:
            raise ValueError("unknown argument: {}".format(arg))
    if not out["script"] or not out["kind"]:
        raise ValueError("--script and --kind are required")
    return out


def _force_multimer_source(name):
    """Make multimer select wake source ``name`` now, or raise.

    Same check as ``multimer_source_preload.force_source``.
    """
    _env_set("MULTIMER_SOURCE", name)
    import multimer
    from multimer import _dispatch

    _dispatch._ensure_source()
    info = multimer.info()
    active = info.get("source")
    if active != name:
        raise RuntimeError(
            "multimer chose {!r}: {}".format(active, info.get("source_error", "already selected"))
        )
    return active


def _subprocess_hard_exit(code, *, headless=False):
    """Exit past SDL teardown, which can block normal interpreter shutdown.

    CPython only: ``os._exit`` is the only way to skip that teardown, and no
    other supported interpreter has it — MicroPython and CircuitPython must return
    and let shutdown take its course. Returns False when it could not exit;
    otherwise it does not return.
    """
    if not hasattr(os, "_exit"):
        return False
    if headless:
        os._exit(code)
    try:
        import pydevices_test_mode

        if pydevices_test_mode.ENABLED:
            os._exit(code)
    except ImportError:
        pass
    # Reached only when pydevices_test_mode is unavailable, i.e. not under this
    # harness: let the display release SDL before the process disappears.
    try:
        from board_config import display_drv

        display_drv.quit(code, force=True)
    except SystemExit:
        raise
    except Exception:
        pass
    os._exit(code)


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    tools = _dir_of(__file__)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        args = _parse_args(argv)
    except ValueError as exc:
        print("example_test_wrapper: {}".format(exc), file=sys.stderr)
        return 2

    src = os.getcwd()
    try:
        import sibling_repos as _sibling_repos

        src = _sibling_repos.unix_path(src)
    except ImportError:
        src = src.replace("\\", "/")
    if src not in sys.path:
        sys.path.insert(0, src)
    if not _isdir(_join(src, "examples")):
        print("example_test_wrapper: cwd must be pydevices-examples/lib", file=sys.stderr)
        return 2

    script_path = args["script"]
    if not script_path.startswith("/"):
        script_path = _join(src, script_path)
    try:
        import sibling_repos as _sibling_repos

        script_path = _sibling_repos.unix_path(script_path)
    except ImportError:
        script_path = script_path.replace("\\", "/")
    if not _isfile(script_path):
        payload = {
            "example": args["example"],
            "status": "error",
            "error": "script not found: {}".format(args["script"]),
            "backend": "?",
        }
        _print_result(payload)
        return 1

    try:
        import pydevices_test_mode

        pydevices_test_mode.ENABLED = True
        pydevices_test_mode.DURATION_S = args["duration"]
    except Exception:
        pass

    headless = args["bootstrap"] == "headless"
    try:
        _setup_bootstrap(src, args["bootstrap"])
    except Exception as exc:
        payload = {
            "example": args["example"],
            "status": "error",
            "error": str(exc),
            "backend": "headless" if headless else "?",
        }
        _print_result(payload)
        return 1

    # Windows PE under WSL does not see Linux-exported env vars via getenv.
    # Apply --env / --timer-async via env_set before board_config / SDL init
    # (deadline hook and the example both import board_config).
    try:
        from displaydev import env_set
    except Exception:
        env_set = None
    if env_set is not None:
        for item in args.get("env") or []:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            if key:
                env_set(key, value)
        # --timer-async is accepted and ignored: multimer has one timer model
        # on every host, and board configs no longer export timer_async.

    # Install the deadline hook AFTER bootstrap: it imports multimer, which is
    # only on sys.path once _setup_bootstrap has run. The hook drives quit for
    # the canonical no-loop idiom (app auto-service / App.run).
    try:
        import pydevices_test_mode

        pydevices_test_mode.install_deadline_hook()
    except Exception:
        pass

    # MULTIMER_SOURCE is multimer's one override. Set it inside the child
    # because Windows PE launched from WSL cannot see the parent's exported
    # environment, and select the source now: a forced source that cannot start
    # falls back to "none" silently. A source this host cannot supply is a
    # skip, not a failure: sweeps ask every interpreter for every source.
    if args.get("multimer_source") is not None:
        try:
            _force_multimer_source(args["multimer_source"])
        except (ImportError, RuntimeError, ValueError) as exc:
            _print_result(
                {
                    "example": args["example"],
                    "status": "skip",
                    "error": "multimer source {!r} unavailable: {}".format(
                        args["multimer_source"], exc
                    ),
                    "backend": "headless" if headless else "?",
                }
            )
            return 0

    backend = "headless" if headless else "?"
    quit_injected = False
    error = None

    if args["kind"] == "oneshot":
        error = _run_oneshot(script_path, args["timeout"])
    elif args["kind"] == "interactive":
        error = _run_interactive(script_path, args["duration"], args["example"], args["kind"])
    elif args["kind"] in ("loop", "async", "lvgl", "pdwidgets", "legacy"):
        error, quit_injected = _run_bounded(
            script_path, args["kind"], args["duration"], args["timeout"], args["quit"]
        )
    else:
        error = "unknown kind {}".format(args["kind"])

    if not headless:
        backend = _backend_name()

    status = "ok" if error is None else "error"
    payload = {
        "example": args["example"],
        "status": status,
        "kind": args["kind"],
        "backend": backend,
        "duration_s": args["duration"],
        "quit_injected": quit_injected,
    }
    if error:
        payload["error"] = error

    _print_result(payload)
    code = 0 if status == "ok" else 1
    _subprocess_hard_exit(code, headless=headless)
    return code


if __name__ == "__main__":
    sys.exit(main())
