"""Prove a windowed app stays alive at the Windows REPL prompt.

``python.exe -i -m examples.<app>`` opens its window (WinDisplay or SDL) and
then sits at ``>>>``. With no ``app.run()``, the timers are all that pump the
window's message queue, so if nothing delivers at the prompt Windows marks the
window hung after a few seconds (``IsHungAppWindow``) and it stops repainting.
This runs the app under a Windows pseudo console (the child sees a real
console handle, so ``_pyrepl`` waits exactly as it does for a person), finds
the child's window, samples ``IsHungAppWindow`` for a while, captures it with
``PrintWindow`` (which a hung window cannot answer), and types into the REPL.

Run it with Windows Python from the examples ``lib`` directory::

    python.exe ..\\tools\\prove_repl\\win_window_alive.py -m examples.roku_remote

Pass ``--pythonpath`` to test a checkout instead of the installed packages.
Exit status is the number of failed checks: the window must never be hung once
it is up, both captures must have content, and the REPL must answer.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from prove_windows import ConPty  # noqa: E402

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
u32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.IsWindowVisible.argtypes = [wt.HWND]
u32.IsHungAppWindow.argtypes = [wt.HWND]
u32.IsHungAppWindow.restype = wt.BOOL
u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.GetWindowDC.argtypes = [wt.HWND]
u32.GetWindowDC.restype = wt.HDC
u32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
u32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
u32.PrintWindow.restype = wt.BOOL
g32.CreateCompatibleDC.argtypes = [wt.HDC]
g32.CreateCompatibleDC.restype = wt.HDC
g32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
g32.CreateCompatibleBitmap.restype = wt.HBITMAP
g32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
g32.SelectObject.restype = wt.HGDIOBJ
g32.GetDIBits.argtypes = [
    wt.HDC,
    wt.HBITMAP,
    wt.UINT,
    wt.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wt.UINT,
]
g32.DeleteObject.argtypes = [wt.HGDIOBJ]
g32.DeleteDC.argtypes = [wt.HDC]
_ENUM = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
PW_RENDERFULLCONTENT = 0x00000002


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


def windows_of(pid):
    found = []

    @_ENUM
    def cb(hwnd, _):
        wpid = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            found.append((hwnd, buf.value))
        return True

    u32.EnumWindows(cb, 0)
    # The console host's own window (if any) is not ours: prefer a titled one.
    found.sort(key=lambda t: (t[1] == "", t[1]))
    return found


def capture(hwnd, path):
    """PrintWindow into a bitmap; save PNG; return (ok, non_background_pixels)."""
    rc = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        return False, 0
    hdc = u32.GetWindowDC(hwnd)
    mdc = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    old = g32.SelectObject(mdc, bmp)
    ok = bool(u32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT))
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = w, -h, 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    g32.SelectObject(mdc, old)
    g32.DeleteObject(bmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, hdc)
    raw = buf.raw
    # Count pixels that are neither black nor white (a blank window is one of those).
    px = memoryview(raw).cast("I")
    content = sum(1 for v in px if (v & 0xFFFFFF) not in (0, 0xFFFFFF))
    try:
        from PIL import Image

        Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1).save(path)
    except Exception as exc:  # PIL missing: keep the numbers, skip the file
        print("capture: no PNG written (%s)" % exc)
    return ok, content


def check(label, ok, detail=""):
    print(
        ("PASS " if ok else "FAIL ") + label + ("" if not detail else "  -- " + detail), flush=True
    )
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", dest="module", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--pythonpath", default="")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument(
        "--settle", type=float, default=8.0, help="seconds for the app to open its window"
    )
    ap.add_argument("--watch", type=float, default=12.0, help="seconds to sample IsHungAppWindow")
    ap.add_argument("--out", default=str(Path(os.environ.get("TEMP", ".")) / "win_window_alive"))
    ap.add_argument("--env", action="append", default=[], help="NAME=VALUE for the child")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    env = {"PYTHONDONTWRITEBYTECODE": "1"}
    if args.pythonpath:
        env["PYTHONPATH"] = args.pythonpath
    for kv in args.env:
        k, _, v = kv.partition("=")
        env[k] = v
    child = ConPty(
        [args.python, "-i", "-m", args.module], cwd=args.cwd, env=env, cols=140, rows=50
    )
    print(
        "child pid",
        child.pid,
        "cwd",
        args.cwd,
        "PYTHONPATH",
        env.get("PYTHONPATH", "(installed)"),
        flush=True,
    )
    fails = 0
    deadline = time.time() + args.settle
    wins = []
    while time.time() < deadline and not wins:
        time.sleep(0.5)
        wins = windows_of(child.pid)
    fails += check("the app opened a window", bool(wins), repr(wins))
    if not wins:
        child.write("raise SystemExit\r\n")
        child.close()
        print(child.text()[-2000:])
        sys.exit(fails + 1)
    hwnd, title = wins[0]
    samples = []
    t0 = time.time()
    cap1 = cap2 = None
    while time.time() - t0 < args.watch:
        time.sleep(1.0)
        hung = bool(u32.IsHungAppWindow(hwnd))
        samples.append(hung)
        el = time.time() - t0
        if cap1 is None and el >= args.watch / 2 and not hung:
            cap1 = capture(hwnd, str(out / "capture1.png"))
    if not samples[-1]:
        cap2 = capture(hwnd, str(out / "capture2.png"))
    fails += check(
        "the window is never hung while the REPL sits at the prompt (%d samples over %.0f s)"
        % (len(samples), args.watch),
        not any(samples),
        "hung samples: " + "".join("H" if s else "." for s in samples) + "  title=%r" % title,
    )
    fails += check(
        "PrintWindow captures content (a hung window cannot answer it)",
        bool(cap1 and cap1[0] and cap1[1] > 100 and cap2 and cap2[0] and cap2[1] > 100),
        "cap1=%r cap2=%r (ok, content pixels) -> %s" % (cap1, cap2, out),
    )
    # The REPL answers while the window lives.
    child.write("import multimer; print('REPL-OK', 21 * 2)\r\n")
    time.sleep(1.0)
    child.write("multimer.report()\r\n")
    time.sleep(1.5)
    txt = child.text()
    fails += check("the REPL answers with the window up", "REPL-OK 42" in txt)
    still = bool(u32.IsHungAppWindow(hwnd))
    fails += check("the window is still not hung after the REPL statements", not still)
    src = re.search(r"source=(\S+) delivery=(\S+)", txt)
    print("report:", src.group(0) if src else "(no report line)")
    for line in txt.splitlines():
        if line.strip().startswith("Timer("):
            print("  " + line.strip())
    child.write("raise SystemExit\r\n")
    child.wait(5.0)
    child.close()
    print("failed checks:", fails)
    sys.exit(fails)


if __name__ == "__main__":
    main()
