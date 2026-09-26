"""Prove the REPL goal on Windows, in a real console (ConPTY).

``prove.py`` forks a pty, which Windows has not got. This runs the same
checks under a Windows pseudo console: the child sees a genuine console
handle on stdin, so ``python.exe`` uses ``_pyrepl`` (or readline-less
``input()``) exactly as a person at a terminal would, and ``micropython.exe``
takes its ``ReadConsoleInput`` path with the console wait of overlay patch
0015. Typed statements go in through the console's input pipe; what the
program prints comes back through its output pipe, with the VT escapes
stripped.

Run it with Windows Python (from WSL, ``python.exe`` by its full path)::

    python.exe prove_windows.py --pd \\\\wsl.localhost\\...\\pydevices ^
        --python python.exe --mp C:\\...\\micropython.exe

Checks, each shown able to fail (``--planted-fault`` runs the REPL check
with no wake source and the input hook off, and expects the count to stand
still):

* the REPL goal: ``-i demo_timers.py`` keeps delivering at the prompt
  (``len(ticks)`` grows by about 100 a second) and ``report()`` answers;
* keepalive: ``demo_keepalive.py`` prints ``stopping at 15`` and exits 0;
* crash: ``demo_crash.py`` exits nonzero with ``boom`` on its stderr, and
  never enters the loop.

Exit status is the number of failed checks.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
STARTF_USESTDHANDLES = 0x00000100
_VT = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[=>]|\r")


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


def _prototypes():
    """Exact argument widths: SIZE_T and HANDLE are 64-bit, a bare int is not."""
    k32.CreatePipe.argtypes = [
        ctypes.POINTER(wt.HANDLE),
        ctypes.POINTER(wt.HANDLE),
        ctypes.c_void_p,
        wt.DWORD,
    ]
    k32.CreatePseudoConsole.argtypes = [
        COORD,
        wt.HANDLE,
        wt.HANDLE,
        wt.DWORD,
        ctypes.POINTER(wt.HANDLE),
    ]
    k32.CreatePseudoConsole.restype = ctypes.c_long
    k32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p,
        wt.DWORD,
        wt.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    k32.CreateProcessW.argtypes = [
        wt.LPCWSTR,
        wt.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.BOOL,
        wt.DWORD,
        ctypes.c_void_p,
        wt.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_INFORMATION),
    ]
    k32.ReadFile.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
        ctypes.c_void_p,
    ]
    k32.WriteFile.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
        ctypes.c_void_p,
    ]
    k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    k32.ClosePseudoConsole.argtypes = [wt.HANDLE]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]


def _check(ok, what):
    if not ok:
        raise OSError("%s failed: %s" % (what, ctypes.FormatError(ctypes.get_last_error())))


class ConPty:
    """A child process on a Windows pseudo console."""

    def __init__(self, argv, cwd=None, env=None, cols=120, rows=40):
        self.out = b""
        self._lock = threading.Lock()
        _prototypes()
        in_r, in_w = wt.HANDLE(), wt.HANDLE()
        out_r, out_w = wt.HANDLE(), wt.HANDLE()
        _check(k32.CreatePipe(ctypes.byref(in_r), ctypes.byref(in_w), None, 0), "CreatePipe")
        _check(k32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), None, 0), "CreatePipe")
        self._hpc = wt.HANDLE()
        rc = k32.CreatePseudoConsole(COORD(cols, rows), in_r, out_w, 0, ctypes.byref(self._hpc))
        if rc != 0:
            raise OSError("CreatePseudoConsole failed: 0x%08x" % (rc & 0xFFFFFFFF))
        k32.CloseHandle(in_r)
        k32.CloseHandle(out_w)
        self._in_w, self._out_r = in_w, out_r

        size = ctypes.c_size_t(0)
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attrs = ctypes.create_string_buffer(size.value)
        _check(
            k32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)),
            "InitializeProcThreadAttributeList",
        )
        _check(
            k32.UpdateProcThreadAttribute(
                attrs,
                0,
                PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                self._hpc.value,
                ctypes.sizeof(wt.HANDLE),
                None,
                None,
            ),
            "UpdateProcThreadAttribute",
        )
        six = STARTUPINFOEXW()
        six.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        six.lpAttributeList = ctypes.addressof(attrs)
        # Our own std handles are pipes (this runs from a WSL shell or a CI
        # runner). Without this flag CreateProcess duplicates them into the
        # child, which then never sees the console; with it and null handles
        # the child takes the pseudo console's, as node-pty does.
        six.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        pi = PROCESS_INFORMATION()
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        full = dict(os.environ)
        if env:
            full.update(env)
        block = "".join("%s=%s\0" % kv for kv in sorted(full.items())) + "\0"
        envbuf = ctypes.create_unicode_buffer(block, len(block))
        _check(
            k32.CreateProcessW(
                None,
                cmdline,
                None,
                None,
                False,
                EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
                envbuf,
                cwd,
                ctypes.byref(six),
                ctypes.byref(pi),
            ),
            "CreateProcessW",
        )
        self.pid = pi.dwProcessId
        self._hproc = pi.hProcess
        k32.CloseHandle(pi.hThread)
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self):
        buf = ctypes.create_string_buffer(65536)
        n = wt.DWORD()
        while True:
            if not k32.ReadFile(self._out_r, buf, 65536, ctypes.byref(n), None):
                return
            with self._lock:
                self.out += buf.raw[: n.value]

    def write(self, text):
        data = text.encode()
        n = wt.DWORD()
        _check(k32.WriteFile(self._in_w, data, len(data), ctypes.byref(n), None), "WriteFile")

    def text(self):
        with self._lock:
            raw = self.out
        return _VT.sub("", raw.decode("utf-8", "replace"))

    def wait(self, timeout_s):
        """Exit code, or None if still running. Everything printed is in text() after."""
        rc = k32.WaitForSingleObject(self._hproc, int(timeout_s * 1000))
        if rc != 0:
            return None
        code = wt.DWORD()
        k32.GetExitCodeProcess(self._hproc, ctypes.byref(code))
        # The console keeps the last lines in its own pipe until it closes:
        # close it now and drain, or a program's final output is lost.
        self._close_console()
        return code.value

    def _close_console(self):
        if self._hpc is None:
            return
        k32.ClosePseudoConsole(self._hpc)
        self._hpc = None
        self._reader.join(3.0)

    def close(self):
        self._close_console()
        if k32.WaitForSingleObject(self._hproc, 1000) != 0:
            k32.TerminateProcess(self._hproc, 9)
        k32.CloseHandle(self._hproc)
        k32.CloseHandle(self._in_w)
        k32.CloseHandle(self._out_r)


def check(label, ok, detail=""):
    print(
        ("PASS " if ok else "FAIL ") + label + ("" if not detail else "  -- " + detail), flush=True
    )
    return 0 if ok else 1


def repl_goal(label, argv, cwd, env, expect_fail=False, settle=2.0):
    child = ConPty([*argv, "-i", str(HERE / "demo_timers.py")], cwd=cwd, env=env)
    time.sleep(settle)
    child.write("print('N1', len(ticks))\r\n")
    time.sleep(1.0)
    child.write("print('N2', len(ticks))\r\n")
    time.sleep(0.6)
    child.write("import multimer; multimer.report()\r\n")
    time.sleep(0.8)
    child.write("raise SystemExit\r\n")
    child.wait(2.0)
    out = child.text()
    child.close()
    nums = re.findall(r"^N([12]) (\d+)", out, re.M)
    got = {k: int(v) for k, v in nums}
    grew = "1" in got and "2" in got and got["2"] - got["1"] >= 40
    source = re.search(r"source=(\S+)", out)
    detail = "N1=%s N2=%s source=%s" % (
        got.get("1"),
        got.get("2"),
        source.group(1) if source else None,
    )
    ok = (not grew) if expect_fail else (grew and source is not None)
    rc = check(label, ok, detail)
    if not ok:
        print("---- transcript\n" + out + "\n----")
    return rc


def script_mode(label, argv, cwd, env):
    child = ConPty([*argv, str(HERE / "demo_keepalive.py")], cwd=cwd, env=env)
    code = child.wait(10.0)
    out = child.text()
    child.close()
    ok = code == 0 and "stopping at 15" in out
    rc = check(label, ok, "exit=%s" % code)
    if not ok:
        print("---- transcript\n" + out + "\n----")
    return rc


def crash_mode(label, argv, cwd, env):
    child = ConPty([*argv, str(HERE / "demo_crash.py")], cwd=cwd, env=env)
    code = child.wait(10.0)
    out = child.text()
    child.close()
    ok = code not in (None, 0) and "boom" in out
    rc = check(label, ok, "exit=%s" % code)
    if not ok:
        print("---- transcript\n" + out + "\n----")
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pd", required=True, help="pydevices checkout (Windows or UNC path)")
    ap.add_argument("--python", action="append", default=[], help="a python.exe to test")
    ap.add_argument("--mp", action="append", default=[], help="a micropython.exe to test")
    ap.add_argument("--planted-fault", action="store_true")
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()
    pd = Path(args.pd)
    cwd = str(HERE)
    fails = 0
    for exe in args.python:
        env = {
            "PYTHONPATH": os.pathsep.join([str(pd / "lib"), str(pd / "utils")]),
            "PYTHON_BASIC_REPL": "",
        }
        env.pop("PYTHON_BASIC_REPL")
        fails += repl_goal(
            "CPython -i %s: ticks grow at the prompt" % exe, [exe], cwd, env, settle=args.settle
        )
        if args.planted_fault:
            bad = dict(env, MULTIMER_SOURCE="none", MULTIMER_INPUTHOOK="0")
            fails += repl_goal(
                "CPython planted fault (no source, hook off): stands still",
                [exe],
                cwd,
                bad,
                expect_fail=True,
                settle=args.settle,
            )
        fails += script_mode("CPython script mode: keepalive then exit 0", [exe], cwd, env)
        fails += crash_mode("CPython crash mode: exits nonzero", [exe], cwd, env)
    for exe in args.mp:
        env = {"MICROPYPATH": os.pathsep.join([str(pd / "lib"), str(pd / "utils"), ".frozen"])}
        fails += repl_goal(
            "MicroPython -i %s: ticks grow at the prompt" % exe,
            [exe],
            cwd,
            env,
            settle=args.settle,
        )
        if args.planted_fault:
            bad = dict(env, MULTIMER_SOURCE="none")
            fails += repl_goal(
                "MicroPython planted fault (no source): stands still",
                [exe],
                cwd,
                bad,
                expect_fail=True,
                settle=args.settle,
            )
        fails += script_mode("MicroPython script mode: keepalive then exit 0", [exe], cwd, env)
        fails += crash_mode("MicroPython crash mode: exits nonzero", [exe], cwd, env)
    print("failed checks:", fails)
    sys.exit(fails)


if __name__ == "__main__":
    main()
