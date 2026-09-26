#!/usr/bin/env python3
"""Prove the notebook case: timers armed in one cell keep firing between cells.

Starts an IPython kernel with jupyter_client (no browser), runs a cell that
arms two multimer timers and ends, waits, then reads the counts from a second
cell and calls multimer.report() from a third. The kernel's asyncio loop is
the wake source, so the cells return while the timers run.

usage: prove_jupyter.py [--pd PATH]
Exit status is the number of failed checks.
"""

import argparse
import os
import queue
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PD = HERE.parent.parent.parent / "pydevices"

CELL_ARM = """
import multimer
ticks = []
slow = []
fast = multimer.every(10, lambda t: ticks.append(multimer.ticks_ms()), name="fast")
slower = multimer.every(100, lambda t: slow.append(1), name="slower")
print("SOURCE", multimer.info()["source"], "STRATEGY", multimer.strategy())
"""
CELL_COUNT1 = "print('COUNT1', len(ticks), len(slow))"
CELL_COUNT2 = "print('COUNT2', len(ticks), len(slow))"
CELL_REPORT = "multimer.report()"
CELL_APP = """
import board_config, appdev
app = appdev.App(board_config)
shows = []
app.every(50, lambda t: shows.append(1), name="app.tick")
print("APP", app.strategy, type(app.primary).__name__)
"""
CELL_APP_COUNT = "print('APPCOUNT', len(shows), app.primary.frame_clock.period_ms)"


def run_cell(kc, code, timeout=30):
    msg_id = kc.execute(code)
    out = ""
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=timeout)
        except queue.Empty:
            break
        t = msg["header"]["msg_type"]
        c = msg["content"]
        if t == "stream":
            out += c["text"]
        elif t == "error":
            out += "\n".join(c["traceback"])
        elif t == "status" and c["execution_state"] == "idle" and msg["parent_header"].get("msg_id") == msg_id:
            break
    return out


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if not detail else "  -- " + detail))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pd", default=str(DEFAULT_PD))
    a = ap.parse_args()
    pd = Path(a.pd)
    from jupyter_client import KernelManager

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(pd / "lib"), str(pd / "utils"), str(pd / "board_configs" / "jndisplay")])
    km = KernelManager(kernel_name="python3")
    km.start_kernel(env=env)
    kc = km.client()
    kc.start_channels()
    kc.wait_for_ready(timeout=60)
    fails = 0
    try:
        out = run_cell(kc, CELL_ARM)
        src = re.findall(r"SOURCE (\S+) STRATEGY (\S+)", out)
        fails += check("cell 1 arms timers on the kernel's loop", bool(src) and src[0][0] == "asyncio" and src[0][1] == "ambient", out.strip())
        time.sleep(1.0)
        c1 = re.findall(r"COUNT1 (\d+) (\d+)", run_cell(kc, CELL_COUNT1))
        time.sleep(1.0)
        c2 = re.findall(r"COUNT2 (\d+) (\d+)", run_cell(kc, CELL_COUNT2))
        grew = bool(c1 and c2) and int(c2[0][0]) > int(c1[0][0]) + 50 and int(c2[0][1]) > int(c1[0][1])
        fails += check("timers keep firing between cells", grew, "counts %s -> %s" % (c1, c2))
        rep = run_cell(kc, CELL_REPORT)
        fails += check("report() answers from a cell", "source=asyncio" in rep and "name='fast'" in rep, rep.strip()[:200])
        out = run_cell(kc, CELL_APP)
        app_ok = "APP ambient JNDisplay" in out
        fails += check("an App on JNDisplay arms in a notebook", app_ok, out.strip()[-300:])
        if app_ok:
            time.sleep(0.6)
            ac = re.findall(r"APPCOUNT (\d+) (\d+)", run_cell(kc, CELL_APP_COUNT))
            fails += check("the App's timers ran between cells", bool(ac) and int(ac[0][0]) >= 5, str(ac))
    finally:
        kc.stop_channels()
        km.shutdown_kernel(now=True)
    print("failures:", fails)
    return fails


if __name__ == "__main__":
    sys.exit(main())
