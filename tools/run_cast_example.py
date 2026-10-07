"""run_cast_example.py -- run a real example on a headless cast, and measure it.

    python ../tools/run_cast_example.py roku testris TV [SECONDS]      # from lib/

The first argument is the method's board_config folder in lib/examples
(roku, miracast or roku_hls). The example runs unchanged; after SECONDS
(default 30) one CAST line reports the display's stats(), and it reports
again every SECONDS after that until the example ends or is stopped.

On a board, set CFG, EXAMPLE and SECONDS below and run it with mpftp; the
line also goes to /cast.txt, written once, after the first report.

Any runtime: python, python.exe, micropython, micropython.exe, a board.
"""

import sys
import time

CFG = None  # on a board: "roku", "miracast" or "roku_hls"
EXAMPLE = None  # on a board: the example's module name
TARGET = None  # on a board: the TV's (or laptop's) address
SECONDS = 30

_argv = getattr(sys, "argv", [])[1:]
cfg = _argv[0] if _argv else CFG
example = _argv[1] if len(_argv) > 1 else EXAMPLE
target = _argv[2] if len(_argv) > 2 else TARGET
seconds = int(_argv[3]) if len(_argv) > 3 else SECONDS
board = sys.platform not in ("linux", "win32", "darwin")

base = "/lib/examples" if board else "examples"
if not board and "../tools" not in sys.path:
    sys.path.append("../tools")  # pydevices_test_mode, beside this file
for p in (
    base + "/" + cfg,
    base,
    "." if not board else "/lib",
    "utils" if not board else "/lib/utils",
):
    if p not in sys.path:
        sys.path.insert(0, p) if p.endswith(cfg) else sys.path.append(p)


def now():
    try:
        return time.ticks_ms() / 1000
    except AttributeError:
        return time.monotonic()


_reports = [0]


def report():
    _reports[0] += 1
    try:
        import board_config

        st = board_config.display_drv.stats()
        line = "CAST %s %s %s %s %s" % (
            cfg,
            example,
            sys.implementation.name,
            sys.platform,
            " ".join(
                "%s=%s" % (k, ("%.1f" % v) if isinstance(v, float) else v)
                for k, v in sorted(st.items())
            ),
        )
    except Exception as e:
        line = "CAST %s %s %s %s error %r" % (
            cfg,
            example,
            sys.implementation.name,
            sys.platform,
            e,
        )
    try:
        print(line, flush=True)
    except TypeError:
        print(line)  # MicroPython's print has no flush
    if board and _reports[0] == 1:
        with open("/cast.txt", "w") as f:
            f.write(line + "\n")


def report_loop():
    while True:
        time.sleep(seconds)
        report()


def report_from_show():
    """No threads (micropython.exe): report from inside the display's show()."""
    import board_config

    d = board_config.display_drv
    show = d.show
    due = [now() + seconds]

    def timed_show(*args, **kwargs):
        r = show(*args, **kwargs)
        if now() >= due[0]:
            due[0] += seconds
            report()
        return r

    d.show = timed_show


if board:
    try:
        import wifi

        wifi.connect_from_secrets()
    except Exception as e:
        print("wifi:", e)

# The example-matrix flag: examples skip what waits for a person (testris's
# splash screen). Its deadline is the harness's, not ours: set it past the run.
try:
    import pydevices_test_mode

    pydevices_test_mode.ENABLED = True
    pydevices_test_mode.DURATION_S = 10**6
except ImportError:
    pass

# the example sees no arguments of ours; the address goes where its config looks
if hasattr(sys, "argv"):
    del sys.argv[1:]
# where the picture goes: the board configs read utils.cast_target (the
# Companion's also reads roku_companion.ROKU_IP)
from utils import cast_target  # noqa: E402  (after the paths above)

cast_target.TARGET = target
if cfg == "roku":
    from utils import roku_companion

    roku_companion.ROKU_IP = target
try:
    import threading

    threading.Thread(target=report_loop, daemon=True).start()
except ImportError:
    try:
        import _thread

        _thread.start_new_thread(report_loop, ())
    except ImportError:
        report_from_show()
__import__(example)
