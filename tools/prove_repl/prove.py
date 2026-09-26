#!/usr/bin/env python3
"""Prove the REPL goal: a timer-driven script ends, the prompt comes back,
the timers keep firing, and the program can be inspected at ``>>>``.

Runs each interpreter's ``-i`` on a real pty (so CPython uses readline or
``_pyrepl`` exactly as a person would), types statements after a delay, and
checks that the tick count grew between two reads. Also runs script mode
(keepalive holds the process until the program stops itself) and crash mode
(an uncaught exception exits instead of entering the loop).

usage: prove.py [--pd PATH] [--mp BIN] [--cp BIN] [--python EXE ...]

Exit status is the number of failed checks. Every check is shown able to
fail: ``--planted-fault`` runs the REPL check with ``MULTIMER_SOURCE=none``,
and the input hook off (``MULTIMER_INPUTHOOK=0``), where a bare prompt
cannot deliver, and expects the failure.
"""

import argparse
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
DEFAULT_PD = HERE.parent.parent.parent / "pydevices"


def pty_run(argv, env, settle, statements, gap=0.6, total=15):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(env)
        os.environ["TERM"] = "dumb"
        os.execvp(argv[0], argv)
    out = b""

    def drain(timeout):
        nonlocal out
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    return False
        return True

    drain(settle)
    for s in statements:
        if s is None:
            drain(gap)
            continue
        os.write(fd, (s + "\n").encode())
        drain(gap)
    os.write(fd, b"\x04")
    drain(1.0)
    try:
        os.kill(pid, 9)
    except OSError:
        pass
    os.waitpid(pid, 0)
    return out.decode(errors="replace")


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if not detail else "  -- " + detail))
    return 0 if ok else 1


def repl_goal(label, argv, env, expect_fail=False):
    out = pty_run(
        [*argv, "-i", str(HERE / "demo_timers.py")],
        env,
        1.5,
        [
            "print('COUNT1', len(ticks))",
            None,
            "print('COUNT2', len(ticks), 'SLOW', len(slow))",
            "import multimer; multimer.report()",
        ],
    )
    c = re.findall(r"COUNT1 (\d+)", out)
    d = re.findall(r"COUNT2 (\d+) SLOW (\d+)", out)
    grew = bool(c and d) and int(d[0][0]) > int(c[0]) + 30
    slow_ok = bool(d) and int(d[0][1]) >= 1
    reported = "multimer on" in out and "name='fast'" in out
    if expect_fail:
        return check(
            label + " (planted fault: no wake source)", not grew, "counts %s -> %s" % (c, d)
        )
    fails = check(label + ": ticks grow at the prompt", grew, "counts %s -> %s" % (c, d))
    fails += check(label + ": the 100 ms timer fired too", slow_ok)
    fails += check(label + ": report() answers at the prompt", reported)
    if fails:
        print("---- transcript\n" + out + "\n----")
    return fails


def inloop_repl(label, argv, env):
    """The in-loop line REPL: ticks grow between two reads, report() answers."""
    out = pty_run(
        [*argv, str(HERE / "demo_repl.py")],
        env,
        1.5,
        [
            "print('COUNT1', len(ticks))",
            None,
            "print('COUNT2', len(ticks))",
            "multimer.report()",
        ],
    )
    c = re.findall(r"COUNT1 (\d+)", out)
    d = re.findall(r"COUNT2 (\d+)", out)
    grew = bool(c and d) and int(d[0]) > int(c[0]) + 30
    fails = check(
        label + ": multimer.repl() keeps ticks growing between lines",
        grew,
        "counts %s -> %s" % (c, d),
    )
    fails += check(
        label + ": report() answers inside repl()", "multimer on" in out and "name='fast'" in out
    )
    fails += check(label + ": Ctrl-D returns from repl()", "repl returned" in out)
    if fails:
        print("---- transcript\n" + out + "\n----")
    return fails


def script_mode(label, argv, env):
    t0 = time.time()
    p = subprocess.run(
        [*argv, str(HERE / "demo_keepalive.py")],
        env=dict(os.environ, **env),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    took = time.time() - t0
    out = p.stdout + p.stderr
    ok = "stopping at 15" in out and p.returncode == 0 and took < 5
    return check(
        label + ": keepalive holds the process until the program stops",
        ok,
        "rc=%d %.1fs" % (p.returncode, took),
    )


def crash_mode(label, argv, env):
    t0 = time.time()
    p = subprocess.run(
        [*argv, str(HERE / "demo_crash.py")],
        env=dict(os.environ, **env),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    took = time.time() - t0
    out = p.stdout + p.stderr
    ok = "boom" in out and p.returncode != 0 and took < 5
    return check(
        label + ": a crashing script exits instead of looping",
        ok,
        "rc=%d %.1fs" % (p.returncode, took),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pd", default=str(DEFAULT_PD))
    ap.add_argument("--mp", default=None, help="unix micropython binary")
    ap.add_argument("--cp", default=None, help="unix circuitpython binary")
    ap.add_argument(
        "--python", action="append", default=[], help="CPython executable (repeatable)"
    )
    ap.add_argument("--planted-fault", action="store_true")
    a = ap.parse_args()
    pd = Path(a.pd)
    paths = "%s:%s" % (pd / "lib", pd / "utils")
    env = {"PYTHONPATH": paths, "MICROPYPATH": paths + ":.frozen"}
    fails = 0
    pythons = a.python or [sys.executable]
    for py in pythons:
        label = (
            "CPython %s"
            % subprocess.run(
                [py, "-c", "import sys;print(sys.version.split()[0])"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        )
        fails += repl_goal(label, [py], env)
        if a.planted_fault:
            fails += repl_goal(
                label,
                [py],
                dict(env, MULTIMER_SOURCE="none", MULTIMER_INPUTHOOK="0"),
                expect_fail=True,
            )
        fails += script_mode(label, [py], env)
        fails += crash_mode(label, [py], env)
    if a.mp:
        fails += repl_goal("MicroPython unix", [a.mp], env)
        if a.planted_fault:
            fails += repl_goal(
                "MicroPython unix",
                [a.mp],
                dict(env, MULTIMER_SOURCE="none", MULTIMER_INPUTHOOK="0"),
                expect_fail=True,
            )
        fails += script_mode("MicroPython unix", [a.mp], env)
        fails += crash_mode("MicroPython unix", [a.mp], env)
    if a.cp:
        # CircuitPython has no fall-through REPL: multimer.repl() is the prompt.
        fails += inloop_repl("CircuitPython unix", [a.cp], env)
        fails += script_mode("CircuitPython unix", [a.cp], env)
        fails += crash_mode("CircuitPython unix", [a.cp], env)
    print("failures:", fails)
    return fails


if __name__ == "__main__":
    sys.exit(main())
