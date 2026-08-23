#!/usr/bin/env python3
"""
Cross-interpreter example smoke test harness.

From repo root:
    python tools/example_test_kit.py
    python tools/example_test_kit.py --order interpreters
    python tools/example_test_kit.py --only-example calculator --only-interpreter micropython
    python tools/example_test_kit.py --only-interpreter circuitpython python.exe
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from sibling_repos import apply_sibling_env
import tomllib


def _ensure_user_micropy_lib(env: dict) -> None:
    """Preserve MicroPython defaults when ``MICROPYPATH`` is overridden.

    A shell ``MICROPYPATH=.:lib:utils`` *replaces* the interpreter default path,
    which drops both ``.frozen`` (lvgl / ``display_driver``) and
    ``~/.micropython/lib`` (``board_config`` from pydevices-desktop / mip).
    Append those entries when missing so subprocess interpreters still resolve them
    after the working-tree ``lib/`` prefix.
    """
    cur = env.get("MICROPYPATH")
    if not cur:
        return
    parts = cur.split(os.pathsep)
    extras: list[str] = []
    if ".frozen" not in parts:
        extras.append(".frozen")
    user_lib = Path.home() / ".micropython" / "lib"
    if user_lib.is_dir():
        lib = str(user_lib)
        if lib not in parts:
            extras.append(lib)
    if extras:
        env["MICROPYPATH"] = cur + os.pathsep + os.pathsep.join(extras)


REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
SRC = REPO / "lib"
INTERPRETERS_TOML = TOOLS / "example_interpreters.toml"
MANIFEST_TOML = TOOLS / "example_test_manifest.toml"
WRAPPER = TOOLS / "example_test_wrapper.py"
SERVE = TOOLS / "serve.py"
RESULT_RE = re.compile(r"^EXAMPLE_RESULT=(.+)$", re.MULTILINE)
# Android logcat may carry either wrapper EXAMPLE_RESULT or lv_test_timer KIT_RESULT.
ANDROID_RESULT_RE = re.compile(r"^(?:.*\s)?(?:EXAMPLE_RESULT|KIT_RESULT)=(.+)$", re.MULTILINE)
ANDROID_PACKAGE_ID = os.environ.get("PACKAGE_ID", "org.pydevices.launcher")


def _find_android_runner() -> Path:
    """Locate android.py, the host tool that stages a script onto the Runner APK.

    The older android-runner/scripts/android.sh was retired in August
    2026 once android.py covered every one of its flags; ANDROID_SH is still
    honored as an environment override for anyone with it in their shell profile.
    """
    env_runner = os.environ.get("ANDROID_RUNNER") or os.environ.get("ANDROID_SH")
    if env_runner:
        return Path(env_runner)
    which_py = shutil.which("android.py")
    if which_py:
        return Path(which_py)
    return REPO.parent / "pydevices" / "bin" / "android.py"


ANDROID_RUNNER = _find_android_runner()
# Retained alias: this name is used throughout the module and in call sites below.
ANDROID_SH = ANDROID_RUNNER
# Short wall clocks: enough for inject/poll quit; override via --duration-s / --timeout-s.
DEFAULT_DURATION = 2
DEFAULT_TIMEOUT = 15
DEFAULT_ONESHOT_TIMEOUT = 10
# Android emulator paint is slow (splash + first EGL presents). Oneshot hold runs
# in-app after android.py returns; observe window must cover that hold.
ANDROID_ONESHOT_HOLD_S = 20
ANDROID_OBSERVE_S = 20
ANDROID_STAGE_TIMEOUT_S = 120
PYSCRIPT_PORT = 8000
SUBPROCESS_INTERPRETER_KIND = "subprocess"
INTERPRETER_TIMING_KEYS = ("duration_s", "timeout_s", "oneshot_timeout_s")
# Desktop SDL subprocesses — preferred sync matrix (skip async-only hosts).
SYNC_INTERPRETERS = (
    "micropython",
    "micropython.exe",
    "circuitpython",
    "cpython-venv",
    "python.exe",
)
# Full preferred async matrix (includes pyscript + jupyter).
ASYNC_INTERPRETERS = (*SYNC_INTERPRETERS, "pyscript", "jupyter")


def _temp_dir() -> Path:
    return Path(
        os.environ.get("TEMP")
        or os.environ.get("TMPDIR")
        or os.environ.get("TMP")
        or tempfile.gettempdir()
    )


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _split_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    out: list[str] = []
    for item in values:
        for part in item.split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out or None


def load_interpreters() -> dict[str, dict]:
    data = load_toml(INTERPRETERS_TOML)
    return data.get("interpreters", {})


def load_manifest() -> tuple[dict, dict]:
    data = load_toml(MANIFEST_TOML)
    defaults = data.get("defaults", {})
    examples = data.get("examples", {})
    return defaults, examples


def _display_exclusion_label(meta: dict) -> str | None:
    """Label for examples shown in the matrix but not run by default."""
    if meta.get("kind") == "harness":
        return None
    parts: list[str] = []
    if meta.get("matrix") is False:
        parts.append("matrix=false")
    if meta.get("kind") == "legacy" and meta.get("quit") == "pending":
        parts.append("legacy/pending")
    return ", ".join(parts) if parts else None


def matrix_examples(
    examples: dict[str, dict],
    only: list[str] | None,
    *,
    all_except_harness: bool = False,
) -> dict[str, dict]:
    """Examples to execute. Harnesses are always excluded."""
    out = {}
    for name, meta in examples.items():
        if meta.get("kind") == "harness":
            continue
        if only and name not in only:
            continue
        if not all_except_harness and _display_exclusion_label(meta):
            continue
        out[name] = meta
    return out


def display_only_examples(
    examples: dict[str, dict],
    only: list[str] | None,
    *,
    all_except_harness: bool,
) -> dict[str, str]:
    """Examples listed in the matrix output but not executed (default mode only)."""
    if all_except_harness:
        return {}
    out: dict[str, str] = {}
    for name, meta in examples.items():
        if meta.get("kind") == "harness":
            continue
        if only and name not in only:
            continue
        label = _display_exclusion_label(meta)
        if label:
            out[name] = label
    return out


def append_display_rows(
    rows: list[dict],
    display_only: dict[str, str],
    interpreters: dict[str, dict],
    all_examples: dict[str, dict],
) -> list[dict]:
    """Add one row per (example, interpreter) for manifest entries not run by default."""
    for example_id, label in sorted(display_only.items()):
        example_meta = all_examples[example_id]
        for interpreter_id in sorted(interpreters):
            if not example_allowed_on_interpreter(example_meta, interpreter_id):
                continue
            rows.append(
                {
                    "example": example_id,
                    "interpreter": interpreter_id,
                    "summary": label,
                    "display_only": True,
                    "returncode": 0,
                    "timed_out": False,
                    "result": {"status": "display_only", "label": label},
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
    return rows


def _expand_user(path: str) -> str:
    return os.path.expanduser(path)


def resolve_interpreter_exe(interpreter_id: str, meta: dict) -> str | None:
    kind = meta.get("kind", SUBPROCESS_INTERPRETER_KIND)
    if kind != SUBPROCESS_INTERPRETER_KIND:
        return interpreter_id

    command = meta.get("command", [])
    if not command:
        return None

    raw = command[0]
    if raw.startswith("repo:"):
        rel = raw.split(":", 1)[1]
        candidate = REPO / rel
        return str(candidate) if candidate.exists() else None

    if raw == ".venv/bin/python":
        candidate = REPO / ".venv" / "bin" / "python"
        return str(candidate) if candidate.exists() else None

    expanded = _expand_user(raw)
    if Path(expanded).exists():
        return expanded

    for rule in meta.get("resolve", []):
        if rule == "PATH":
            found = shutil.which(Path(raw).name)
            if found:
                return found
        elif rule.startswith("~/"):
            candidate = _expand_user(rule)
            if Path(candidate).exists():
                return candidate
        elif rule.startswith("repo:"):
            candidate = REPO / rule.split(":", 1)[1]
            if candidate.exists():
                return str(candidate)

    return shutil.which(Path(raw).name)


def _pick_adb_bin() -> str | None:
    override = os.environ.get("ADB")
    if override:
        return override
    if shutil.which("adb.exe"):
        return "adb.exe"
    if shutil.which("adb"):
        return "adb"
    return None


def _adb_base_cmd(adb_bin: str) -> list[str]:
    cmd = [adb_bin]
    serial = os.environ.get("ANDROID_SERIAL")
    if serial:
        cmd.extend(["-s", serial])
    return cmd


def android_interpreter_available() -> bool:
    """True when android.py, adb, a device, and the launcher APK are present."""
    if not ANDROID_SH.is_file():
        return False
    adb_bin = _pick_adb_bin()
    if adb_bin is None:
        return False
    try:
        proc = subprocess.run(
            [*_adb_base_cmd(adb_bin), "devices"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    devices = [
        line.split()[0]
        for line in (proc.stdout or "").replace("\r", "").splitlines()[1:]
        if line.strip().endswith("\tdevice")
        or (len(line.split()) >= 2 and line.split()[1] == "device")
    ]
    if not devices:
        return False
    try:
        path_proc = subprocess.run(
            [*_adb_base_cmd(adb_bin), "shell", "pm", "path", ANDROID_PACKAGE_ID],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool((path_proc.stdout or "").strip())


def interpreter_available(interpreter_id: str, meta: dict) -> bool:
    kind = meta.get("kind", SUBPROCESS_INTERPRETER_KIND)
    if kind == SUBPROCESS_INTERPRETER_KIND:
        return resolve_interpreter_exe(interpreter_id, meta) is not None
    if kind == "pyscript":
        return SERVE.exists()
    if kind == "jupyter":
        jupyter = REPO / ".venv" / "bin" / "jupyter"
        return jupyter.exists()
    if kind == "android":
        return android_interpreter_available()
    return False


def example_allowed_on_interpreter(example_meta: dict, interpreter_id: str) -> bool:
    skip = example_meta.get("skip_interpreters", [])
    if interpreter_id in skip:
        return False
    allowed = example_meta.get("interpreters")
    return not (allowed and interpreter_id not in allowed and "*" not in allowed)


def parse_result(stdout: str) -> dict | None:
    for match in RESULT_RE.finditer(stdout):
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    return None


def summarize(result: dict | None, returncode: int, timed_out: bool) -> str:
    if timed_out:
        return "hang"
    if result is None:
        return "no_result" if returncode == 0 else f"exit_{returncode}"
    status = result.get("status", "?")
    if status == "skip":
        return "skip"
    if status == "ok":
        backend = result.get("backend", "?")
        if backend == "headless":
            return "ok"
        return f"{backend}, ok"
    if status == "error":
        err = result.get("error", "error")
        return f"error: {err}"
    return status


def interpreter_timing_defaults(global_defaults: dict, interpreter_meta: dict) -> dict:
    """Merge per-interpreter timing overrides from example_interpreters.toml."""
    merged = dict(global_defaults)
    for key in INTERPRETER_TIMING_KEYS:
        if key in interpreter_meta:
            merged[key] = interpreter_meta[key]
    return merged


def example_timing(
    example_meta: dict, manifest_defaults: dict, interpreter_defaults: dict
) -> tuple[float, float]:
    kind = example_meta.get("kind", "loop")
    duration = float(
        example_meta.get(
            "duration_s",
            interpreter_defaults.get(
                "duration_s",
                manifest_defaults.get("duration_s", DEFAULT_DURATION),
            ),
        )
    )
    if kind == "oneshot":
        timeout = float(
            example_meta.get(
                "oneshot_timeout_s",
                example_meta.get(
                    "timeout_s",
                    interpreter_defaults.get(
                        "oneshot_timeout_s",
                        manifest_defaults.get("oneshot_timeout_s", DEFAULT_ONESHOT_TIMEOUT),
                    ),
                ),
            )
        )
    else:
        timeout = float(
            example_meta.get(
                "timeout_s",
                interpreter_defaults.get(
                    "timeout_s",
                    manifest_defaults.get("timeout_s", DEFAULT_TIMEOUT),
                ),
            )
        )
    return duration, timeout


def run_unit_tests() -> int:
    print("Running unit tests (python -m unittest discover -s tests)...", file=sys.stderr)
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=str(REPO),
        check=False,
    )
    return proc.returncode


def run_subprocess_case(
    interpreter_id: str,
    exe: str,
    example_id: str,
    example_meta: dict,
    duration: float,
    timeout: float,
) -> dict:
    wrapper_rel = os.path.relpath(WRAPPER, SRC)
    script = example_meta.get("script", f"examples/{example_id}.py")
    kind = example_meta.get("kind", "loop")
    quit_mode = example_meta.get("quit", "poll")
    bootstrap = example_meta.get("bootstrap", "full")
    cmd = [exe]
    if interpreter_id == "micropython.exe":
        cmd.extend(["-X", "heapsize=64M"])
    cmd.extend(
        [
            wrapper_rel,
            example_id,
            "--script",
            script,
            "--kind",
            kind,
            "--quit",
            quit_mode,
            "--bootstrap",
            bootstrap,
            "--duration",
            str(duration),
            "--timeout",
            str(timeout),
        ]
    )
    env = os.environ.copy()
    apply_sibling_env(env, repo_root=str(REPO))
    _ensure_user_micropy_lib(env)
    # Windows PE under WSL cannot read Linux-exported env; pass via argv + env_set.
    timer_async = env.get("PYDEVICES_TIMER_ASYNC")
    if timer_async is not None:
        cmd.extend(["--timer-async", str(timer_async)])
    multimer_backend = env.get("MULTIMER_BACKEND")
    if multimer_backend:
        cmd.extend(["--multimer-backend", str(multimer_backend)])
    # Do not forward SDL_* to Windows PE. WSL-exported env is invisible to
    # .exe children (so unix stays headless via the shell export), and PE
    # should keep a real Windows video driver — dummy there hides the brief
    # window that confirms the cell is running.
    #
    # PE also cannot see PYTHONUNBUFFERED from the WSL shell; pass it so
    # CPython .exe flushes EXAMPLE_RESULT / init lines before a timeout kill.
    if interpreter_id.endswith(".exe"):
        cmd.extend(["--env", "PYTHONUNBUFFERED=1"])
    #
    # PE stdout via pipes is often empty after a timeout kill (process was
    # still usable; quit just did not end it). Write PE output to temp files
    # so tails survive TimeoutExpired.
    is_pe = interpreter_id.endswith(".exe")
    out_path = err_path = None
    out_f = err_f = None
    timed_out = False
    returncode = -1
    stdout = ""
    stderr = ""
    try:
        if is_pe:
            with tempfile.NamedTemporaryFile(
                "w+", encoding="utf-8", delete=False, suffix=".stdout"
            ) as out_f, tempfile.NamedTemporaryFile(
                "w+", encoding="utf-8", delete=False, suffix=".stderr"
            ) as err_f:
                out_path, err_path = out_f.name, err_f.name
                try:
                    proc = subprocess.run(
                        cmd,
                        cwd=str(SRC),
                        stdout=out_f,
                        stderr=err_f,
                        timeout=timeout + 5,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        check=False,
                    )
                    timed_out = False
                    returncode = proc.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
                    returncode = -1
            stdout = Path(out_path).read_text(encoding="utf-8", errors="replace")
            stderr = Path(err_path).read_text(encoding="utf-8", errors="replace")
        else:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(SRC),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout + 5,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
                timed_out = False
                returncode = proc.returncode
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                returncode = -1
                stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    finally:
        for path in (out_path, err_path):
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

    result = parse_result(stdout)
    summary = summarize(result, returncode, timed_out)
    return {
        "example": example_id,
        "interpreter": interpreter_id,
        "summary": summary,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration,
        "timeout_s": timeout,
        "result": result,
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else "",
    }


_server_pid: int | None = None


def _server_ready(port: int = PYSCRIPT_PORT) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/.site/pyscript/harness.html", timeout=2
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ConnectionError):
        return False


PACKAGES_DIR = REPO / "packages"


def _pyscript_header_lists(script_path: Path) -> tuple[list[str], list[str], list[str]]:
    """Read ``# modules:`` / ``# manifests:`` / ``# deps:`` from an example (first 10 lines)."""
    modules: list[str] = []
    manifests: list[str] = []
    deps: list[str] = []
    if not script_path.is_file():
        return modules, manifests, deps
    try:
        with open(script_path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= 10:
                    break
                s = line.strip()
                if s.startswith("# modules:"):
                    body = s.split(":", 1)[1].strip()
                    modules = [p.strip() for p in body.split(",") if p.strip()]
                elif s.startswith("# manifests:"):
                    body = s.split(":", 1)[1].strip()
                    manifests = [p.strip() for p in body.split(",") if p.strip()]
                elif s.startswith("# deps:"):
                    body = s.split(":", 1)[1].strip()
                    deps = [p.strip() for p in body.split(",") if p.strip()]
    except OSError:
        pass
    return modules, manifests, deps


def _pyscript_gallery_value(script_path: Path) -> str | None:
    """Return ``featured`` / ``skip`` / ``binaries`` from ``# gallery:``, or None."""
    if not script_path.is_file():
        return None
    try:
        with open(script_path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= 10:
                    break
                s = line.strip()
                if s.startswith("# gallery:"):
                    body = s.split(":", 1)[1].strip().lower()
                    token = body.split(",")[0].strip()
                    return token or None
    except OSError:
        pass
    return None


def pyscript_skips_binaries(example_id: str, example_meta: dict) -> bool:
    """True when the example opts out of PyScript because mip cannot install binaries."""
    script = example_meta.get("script", f"examples/{example_id}.py")
    return _pyscript_gallery_value(SRC / script) == "binaries"


def pyscript_harness_query(example_id: str, example_meta: dict) -> str:
    """Build loader query via ``url_maker`` (modules/manifests/deps) for harness.html."""
    scripts_dir = str(REPO / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from url_maker import urls_from_deps

    script = example_meta.get("script", f"examples/{example_id}.py")
    script_path = SRC / script

    extra_modules, extra_manifests, deps = _pyscript_header_lists(script_path)

    modules: list[str] = []
    manifests: list[str] = []

    if (PACKAGES_DIR / f"{example_id}.json").is_file() and (
        SRC / "examples" / example_id
    ).is_dir():
        manifests = [example_id]
    elif script_path.is_file() and script_path.parent != SRC / "examples":
        pkg = script_path.parent.name
        if (PACKAGES_DIR / f"{pkg}.json").is_file() and (SRC / "examples" / pkg).is_dir():
            manifests = [pkg]
            # Entry must be the example stem (e.g. roku_lvgl), not a sibling
            # listed in ``# modules:`` — those live inside the package and are
            # provided via sys.path after manifest install (see ps_loader).
            if example_id != pkg:
                modules = [example_id]
            # Drop extras that are files inside the package directory.
            extra_modules = [
                m
                for m in extra_modules
                if m != example_id and not (script_path.parent / f"{m}.py").is_file()
            ]
        else:
            modules = [example_id]
    else:
        modules = [example_id] + [m for m in extra_modules if m != example_id]

    for name in extra_modules:
        if name not in modules:
            modules.append(name)
    for name in extra_manifests:
        if name not in manifests:
            manifests.append(name)

    return urls_from_deps(
        modules=modules,
        manifests=manifests,
        deps=deps,
        interpreter="micropython",
    ).lstrip("?")


def _kill_pyscript_port(port: int = PYSCRIPT_PORT) -> None:
    """Free ``port`` when a prior serve.py is wedged (listening but not HTTP-ready)."""
    global _server_pid
    if _server_pid is not None:
        try:
            os.kill(_server_pid, 9)
        except OSError:
            pass
        _server_pid = None
    # Best-effort: anything still bound to the port (stale kit / manual serve).
    subprocess.run(
        ["fuser", "-k", f"{port}/tcp"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.2)


def ensure_pyscript_server(port: int = PYSCRIPT_PORT) -> None:
    global _server_pid
    if _server_ready(port):
        return
    # Port may still be held by a dead/hung serve.py from an earlier case.
    _kill_pyscript_port(port)
    print(f"Starting {SERVE} on port {port}...", file=sys.stderr)
    # Access logs go to stderr; an unread PIPE fills (~64KiB) and deadlocks
    # ThreadingHTTPServer mid-matrix (HTML loads, MicroPython never starts).
    serve_log = _temp_dir() / "pyscript_serve_kit.log"
    serve_log.parent.mkdir(parents=True, exist_ok=True)
    with open(serve_log, "ab") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, str(SERVE), "-p", str(port)],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=log_fh,
        )
    _server_pid = proc.pid
    for _ in range(100):
        if _server_ready(port):
            return
        if proc.poll() is not None:
            try:
                err_tail = serve_log.read_bytes()[-500:].decode("utf-8", "replace")
            except OSError:
                err_tail = ""
            raise RuntimeError(
                f"PyScript server exited before ready on port {port}: {err_tail[-500:]}"
            )
        time.sleep(0.1)
    raise RuntimeError(f"PyScript server did not become ready on port {port}")


def run_pyscript_case(
    example_id: str,
    example_meta: dict,
    duration: float,
    timeout: float,
    port: int = PYSCRIPT_PORT,
) -> dict:
    if pyscript_skips_binaries(example_id, example_meta):
        result = {
            "interpreter": "pyscript",
            "status": "skip",
            "example": example_id,
            "error": "skip: binaries (browser mip cannot install binary assets)",
        }
        return {
            "example": example_id,
            "interpreter": "pyscript",
            "summary": "skip",
            "returncode": 0,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": result,
            "stdout_tail": "EXAMPLE_RESULT=" + json.dumps(result, separators=(",", ":")),
            "stderr_tail": "",
        }

    ensure_pyscript_server(port)
    query = pyscript_harness_query(example_id, example_meta)
    url = (
        f"http://127.0.0.1:{port}/pydevices-examples/pyscript/harness.html?{query}"
        f"&autotest=1&duration={int(duration)}&timeout={int(timeout)}"
    )

    try:
        from pyscript_autotest import run_autotest
    except ImportError:
        tools = str(TOOLS)
        if tools not in sys.path:
            sys.path.insert(0, tools)
        from pyscript_autotest import run_autotest

    try:
        result = run_autotest(url, duration_s=duration, timeout_s=timeout)
    except Exception as exc:
        return {
            "example": example_id,
            "interpreter": "pyscript",
            "summary": f"error: {exc}",
            "returncode": 1,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": {"status": "error", "error": str(exc)},
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }

    if result.get("status") == "skip" or result.get("error", "").startswith(
        "playwright not installed"
    ):
        return {
            "example": example_id,
            "interpreter": "pyscript",
            "summary": "needs_playwright",
            "returncode": -1,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": result,
            "stdout_tail": "",
            "stderr_tail": "",
        }

    summary = summarize(result, 0, False)
    line = "EXAMPLE_RESULT=" + json.dumps(result, separators=(",", ":"))
    return {
        "example": example_id,
        "interpreter": "pyscript",
        "summary": summary,
        "returncode": 0 if result.get("status") == "ok" else 1,
        "timed_out": result.get("smoke") == "js_timeout",
        "duration_s": duration,
        "timeout_s": timeout,
        "result": result,
        "stdout_tail": line[-2000:],
        "stderr_tail": "\n".join((result.get("console_errors") or [])[:5])[-1000:],
    }


def _write_jupyter_notebook(example_id: str, example_meta: dict, duration_s: float) -> Path:
    # Prefer dotted examples imports (cwd=lib, ``.`` on PYTHONPATH). Always
    # ``import utils.path`` so sibling ``utils/`` (keypins, mip, …) matches the
    # subprocess wrapper. Scripts outside ``lib/examples/`` (such as the
    # sibling core timer probe) are loaded by path.
    script = example_meta.get("script", f"examples/{example_id}.py")
    script_path = (SRC / script).resolve()
    try:
        under_examples = script_path.is_relative_to(SRC / "examples")
    except AttributeError:
        under_examples = str(script_path).startswith(str((SRC / "examples").resolve()))
    if under_examples:
        raw_import = example_meta.get("import", example_id)
        if raw_import.startswith("examples."):
            import_line = f"import {raw_import}"
        elif "." in raw_import:
            import_line = f"import examples.{raw_import}"
        else:
            import_line = f"from examples import {raw_import}"
    else:
        import_line = "import runpy\nrunpy.run_path(%r, run_name=__name__)" % (str(script_path),)

    tools_rel = os.path.relpath(TOOLS, SRC)
    test_mode_source = "\n".join(
        [
            "import sys",
            f"sys.path.insert(0, {tools_rel!r})",
            "import utils.path  # noqa: F401",
            "import pydevices_test_mode",
            "pydevices_test_mode.ENABLED = True",
            f"pydevices_test_mode.DURATION_S = {duration_s}",
            "pydevices_test_mode.install_deadline_hook()",
            "",
        ]
    )

    cells = [
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": [test_mode_source],
        },
        {
            "cell_type": "code",
            "metadata": {},
            "execution_count": None,
            "outputs": [],
            "source": [f"{import_line}\n"],
        },
    ]
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }
    # Unique path so concurrent matrix workers (interpreter x timer_async) do not clobber.
    mode = os.environ.get("PYDEVICES_TIMER_ASYNC", "x")
    out = SRC / f"run-{example_id}-async{mode}-{os.getpid()}.ipynb"
    out.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    return out


def run_jupyter_case(
    example_id: str,
    example_meta: dict,
    duration: float,
    timeout: float,
) -> dict:
    venv_python = REPO / ".venv" / "bin" / "python"
    jupyter = REPO / ".venv" / "bin" / "jupyter"
    if not venv_python.exists() or not jupyter.exists():
        return {
            "example": example_id,
            "interpreter": "jupyter",
            "summary": "missing",
            "returncode": -1,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": None,
            "stdout_tail": "",
            "stderr_tail": "Jupyter venv not found",
        }

    nb_path = _write_jupyter_notebook(example_id, example_meta, duration)
    nbconvert_out = nb_path.with_name(f"{nb_path.stem}.nbconvert.ipynb")
    cmd = [
        str(jupyter),
        "nbconvert",
        "--execute",
        "--to",
        "notebook",
        "--ExecutePreprocessor.timeout={}".format(int(timeout)),
        "--ExecutePreprocessor.kernel_name=python3",
        str(nb_path),
    ]
    env = os.environ.copy()
    apply_sibling_env(env, repo_root=str(REPO), prepend_paths=[str(SRC)])
    _ensure_user_micropy_lib(env)

    try:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(SRC),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 30,
                env=env,
                check=False,
            )
            timed_out = False
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
    finally:
        nbconvert_out.unlink(missing_ok=True)
        nb_path.unlink(missing_ok=True)

    ok = returncode == 0 and not timed_out
    result = {
        "example": example_id,
        "status": "ok" if ok else "error",
        "backend": "JNDisplay",
        "duration_s": duration,
    }
    if not ok:
        result["error"] = stderr[-200:] if stderr else f"exit_{returncode}"

    summary = summarize(result, returncode, timed_out)
    return {
        "example": example_id,
        "interpreter": "jupyter",
        "summary": summary,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration,
        "timeout_s": timeout,
        "result": result,
        "stdout_tail": stdout[-2000:] if stdout else "",
        "stderr_tail": stderr[-1000:] if stderr else "",
    }


def parse_android_result(log_text: str) -> dict | None:
    for match in ANDROID_RESULT_RE.finditer(log_text.replace("\r", "")):
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
    return None


def run_android_case(
    example_id: str,
    example_meta: dict,
    duration: float,
    timeout: float,
) -> dict:
    """Stage via pydevices/bin/android.py; collect results from logcat."""
    script = example_meta.get("script", f"examples/{example_id}.py")
    script_path = SRC / script
    if not script_path.is_file():
        return {
            "example": example_id,
            "interpreter": "android",
            "summary": "missing_script",
            "returncode": -1,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": None,
            "stdout_tail": "",
            "stderr_tail": f"not found: {script_path}",
        }
    if not android_interpreter_available():
        return {
            "example": example_id,
            "interpreter": "android",
            "summary": "missing",
            "returncode": -1,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": None,
            "stdout_tail": "",
            "stderr_tail": "android interpreter unavailable (adb/device/APK)",
        }

    adb_bin = _pick_adb_bin()
    assert adb_bin is not None
    adb = _adb_base_cmd(adb_bin)
    # Drop prior examples' Tracebacks / KIT_RESULT lines before relaunch.
    subprocess.run([*adb, "logcat", "-c"], capture_output=True, check=False)

    kind = example_meta.get("kind", "loop")
    cmd = [str(ANDROID_SH), "--no-attach", script]
    if kind == "lvgl" or example_id == "lv_test_timer":
        cmd.append("--kit")
    # Oneshot scripts return immediately; without a hold the Activity tears down
    # (or Android splash covers the single present) and the screen looks blank.
    # Hold runs on-device after android.py returns — observe window must cover it.
    hold_s = 0
    if kind == "oneshot" or example_meta.get("quit") == "native_exit":
        hold_s = max(int(duration), ANDROID_ONESHOT_HOLD_S)
        cmd.extend(["--hold-s", str(hold_s)])
    modules, manifests, deps = _pyscript_header_lists(script_path)
    if modules:
        cmd.extend(["--modules", ",".join(modules)])
    if manifests:
        cmd.extend(["--manifests", ",".join(manifests)])
    if deps:
        cmd.extend(["--deps", ",".join(deps)])

    stage = subprocess.run(
        cmd,
        cwd=str(SRC),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=ANDROID_STAGE_TIMEOUT_S,
        check=False,
    )
    if stage.returncode != 0:
        return {
            "example": example_id,
            "interpreter": "android",
            "summary": f"exit_{stage.returncode}",
            "returncode": stage.returncode,
            "timed_out": False,
            "duration_s": duration,
            "timeout_s": timeout,
            "result": None,
            "stdout_tail": (stage.stdout or "")[-2000:],
            "stderr_tail": (stage.stderr or "")[-1000:],
        }
    wants_kit = kind == "lvgl" or example_id == "lv_test_timer"
    # Leave the Activity up long enough for splash + first presents. Kit examples
    # wait for KIT_RESULT up to timeout_s; others use a paint observe window.
    observe_s = max(
        float(ANDROID_OBSERVE_S),
        duration + 2.0,
        float(hold_s) + 4.0 if hold_s else 0.0,
    )
    deadline = time.time() + (float(timeout) if wants_kit else observe_s)
    paint_until = time.time() + observe_s
    log_chunks: list[str] = []
    result = None
    saw_display = False
    while time.time() < deadline:
        dump = subprocess.run(
            [*adb, "logcat", "-d", "-v", "brief", "python:V", "*:S"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        text = dump.stdout or ""
        log_chunks.append(text)
        if (
            "Application loaded" in text
            or "SDLDisplay: initialized" in text
            or "AndroidSDLDisplay: initialized" in text
            or "Initializing AndroidSDLDisplay" in text
        ):
            saw_display = True
        parsed = parse_android_result(text)
        if parsed is not None:
            result = parsed
        if "Traceback" in text and result is None:
            break
        if result is not None and time.time() >= paint_until:
            break
        if not wants_kit and saw_display and time.time() >= paint_until:
            break
        time.sleep(0.5)

    combined = "\n".join(log_chunks)
    timed_out = result is None and wants_kit
    if result is None and "Traceback" not in combined and saw_display:
        # Duration-quit path when the example has no kit marker.
        result = {"status": "ok", "backend": "android"}
        timed_out = False
    subprocess.run(
        [*adb, "shell", "am", "force-stop", ANDROID_PACKAGE_ID],
        capture_output=True,
        check=False,
    )
    returncode = 0 if result and result.get("status") == "ok" else 1
    summary = summarize(result, returncode, timed_out)
    return {
        "example": example_id,
        "interpreter": "android",
        "summary": summary,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_s": duration,
        "timeout_s": timeout,
        "result": result,
        "stdout_tail": combined[-2000:] if combined else (stage.stdout or "")[-2000:],
        "stderr_tail": (stage.stderr or "")[-1000:],
    }


def run_case(
    example_id: str,
    example_meta: dict,
    interpreter_id: str,
    interpreter_meta: dict,
    manifest_defaults: dict,
    interpreter_defaults: dict,
) -> dict:
    effective_defaults = interpreter_timing_defaults(interpreter_defaults, interpreter_meta)
    duration, timeout = example_timing(example_meta, manifest_defaults, effective_defaults)
    kind = interpreter_meta.get("kind", SUBPROCESS_INTERPRETER_KIND)

    if kind == SUBPROCESS_INTERPRETER_KIND:
        exe = resolve_interpreter_exe(interpreter_id, interpreter_meta)
        if exe is None:
            return {
                "example": example_id,
                "interpreter": interpreter_id,
                "summary": "missing",
                "returncode": -1,
                "timed_out": False,
                "duration_s": duration,
                "timeout_s": timeout,
                "result": None,
                "stdout_tail": "",
                "stderr_tail": "",
            }
        return run_subprocess_case(
            interpreter_id, exe, example_id, example_meta, duration, timeout
        )

    if kind == "pyscript":
        return run_pyscript_case(example_id, example_meta, duration, timeout)

    if kind == "jupyter":
        return run_jupyter_case(example_id, example_meta, duration, timeout)

    if kind == "android":
        return run_android_case(example_id, example_meta, duration, timeout)

    return {
        "example": example_id,
        "interpreter": interpreter_id,
        "summary": "unsupported_interpreter",
        "returncode": -1,
        "timed_out": False,
        "duration_s": duration,
        "timeout_s": timeout,
        "result": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _missing_interpreter_row(example_id: str, interpreter_id: str) -> dict:
    return {
        "example": example_id,
        "interpreter": interpreter_id,
        "summary": "missing",
        "returncode": -1,
        "timed_out": False,
        "result": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _run_example_wave(
    example_id: str,
    example_meta: dict,
    work: list[tuple[str, dict]],
    manifest_defaults: dict,
    interpreter_defaults: dict,
    *,
    jobs: int,
) -> list[dict]:
    """Run one wave of interpreters; preserve ``work`` order in returned rows."""
    if not work:
        return []
    for interpreter_id, _ in work:
        print(f"  start {example_id} @ {interpreter_id}", file=sys.stderr)

    if jobs == 1 or len(work) == 1:
        rows = []
        for interpreter_id, interpreter_meta in work:
            row = run_case(
                example_id,
                example_meta,
                interpreter_id,
                interpreter_meta,
                manifest_defaults,
                interpreter_defaults,
            )
            rows.append(row)
            print(
                f"  done  {example_id} @ {interpreter_id}: {row.get('summary')}",
                file=sys.stderr,
            )
        return rows

    max_workers = len(work) if jobs <= 0 else min(jobs, len(work))
    by_interpreter: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                run_case,
                example_id,
                example_meta,
                interpreter_id,
                interpreter_meta,
                manifest_defaults,
                interpreter_defaults,
            ): interpreter_id
            for interpreter_id, interpreter_meta in work
        }
        for fut in as_completed(futures):
            interpreter_id = futures[fut]
            row = fut.result()
            by_interpreter[interpreter_id] = row
            print(
                f"  done  {example_id} @ {interpreter_id}: {row.get('summary')}",
                file=sys.stderr,
            )
    return [by_interpreter[interpreter_id] for interpreter_id, _ in work]


# The three Peter Hinch GUIs share one lib/utils/gui directory that holds
# exactly one of them, so consecutive GUI examples force a wipe-and-refetch of
# ~70 files. Doing that inside a timed, parallel wave is what broke these cells:
# whichever interpreter won the lock paid the whole download against its own
# timeout (micropython.exe wedged), and CircuitPython cannot download at all --
# this build has no urllib, no socket and no ssl, so mip can never fetch there.
# Seed the tree once, serially, with the venv CPython before the wave starts;
# every interpreter then takes fetch_ph_gui's fast path and installs nothing.
_SHARED_GUI_DEPS = (
    "micropython-nano-gui",
    "micropython-micro-gui",
    "micropython-touch",
)

# Which core each setup module pulls in. Most examples that need the shared
# tree never name it in ``deps`` -- they just import a setup module, which
# calls fetch_ph_gui itself (bmp565_sprite_transparent and displaybuf_simpletest
# both reach nano-gui through color_setup). Seeding only on ``deps`` left those
# to swap the tree inside their own timed cell, which is a ~70 file download
# that micropython.exe does not finish inside its 25s budget.
_SETUP_MODULE_CORES = {
    "color_setup": "micropython-nano-gui",
    "hardware_setup": "micropython-micro-gui",
    "touch_setup": "micropython-touch",
}


def _example_shared_gui_core(example_meta: dict) -> str | None:
    """The Hinch core this example needs, from ``deps`` or its ``# utils:`` header."""
    for dep in example_meta.get("deps", []):
        if dep in _SHARED_GUI_DEPS:
            return dep
    script = example_meta.get("script")
    if not script:
        return None
    path = SRC / script
    try:
        with open(path, encoding="utf-8") as handle:
            for _ in range(10):
                line = handle.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped.startswith("# utils:"):
                    continue
                for name in stripped[len("# utils:") :].split(","):
                    core = _SETUP_MODULE_CORES.get(name.strip())
                    if core:
                        return core
    except OSError:
        return None
    return None


def _preseed_shared_gui(example_meta: dict) -> None:
    """Install this example's Hinch GUI core before any interpreter is timed."""
    core = _example_shared_gui_core(example_meta)
    if not core:
        return
    env = os.environ.copy()
    apply_sibling_env(env, repo_root=str(REPO))
    code = (
        "import sys; sys.path.insert(0, 'utils')\n"
        "import fetch_ph_gui\n"
        # apply_patches=False: each setup module patches for its own interpreter.
        f"ok = fetch_ph_gui.fetch_ph_gui({core!r}, apply_patches=False)\n"
        "print('preseed-ok' if ok else 'preseed-FAILED')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(SRC),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  preseed {core}: {type(exc).__name__}", file=sys.stderr)
        return
    if proc.returncode != 0 or "preseed-FAILED" in proc.stdout:
        # Not fatal: an interpreter that can fetch will still try for itself.
        # Show why -- a silent "failed" here reads as flakiness in the cells it
        # goes on to break.
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "no output"
        print(f"  preseed {core}: failed ({tail[:160]})", file=sys.stderr)
    else:
        print(f"  preseed {core}: ready", file=sys.stderr)


def test_all_examples(
    examples: dict[str, dict],
    interpreters: dict[str, dict],
    manifest_defaults: dict,
    interpreter_defaults: dict,
    *,
    fail_fast: bool = False,
    verbose: bool = False,
    jobs: int = 0,
) -> list[dict]:
    """Run each example across interpreters, then advance to the next example.

    With ``jobs != 1`` (default ``0`` = one worker per interpreter), all eligible
    interpreters for an example run concurrently. An empty PE ``hang`` usually
    means the example stayed alive past ``timeout_s`` (quit did not end it) —
    not that the Windows process failed to start. Fail-fast waits for that
    example's workers to finish, then stops before the next example.
    """
    rows: list[dict] = []
    for example_id, example_meta in examples.items():
        work: list[tuple[str, dict]] = []
        example_rows: list[dict] = []
        for interpreter_id, interpreter_meta in interpreters.items():
            if not example_allowed_on_interpreter(example_meta, interpreter_id):
                continue
            if not interpreter_available(interpreter_id, interpreter_meta):
                if verbose:
                    print(
                        f"Skipping {example_id} @ {interpreter_id} (interpreter missing)",
                        file=sys.stderr,
                    )
                example_rows.append(_missing_interpreter_row(example_id, interpreter_id))
                continue
            work.append((interpreter_id, interpreter_meta))

        if not work:
            rows.extend(example_rows)
            continue

        print(
            f"Running {example_id} @ {len(work)} interpreter(s)"
            + (" in parallel..." if jobs != 1 and len(work) > 1 else "..."),
            file=sys.stderr,
        )
        _preseed_shared_gui(example_meta)
        example_rows.extend(
            _run_example_wave(
                example_id,
                example_meta,
                work,
                manifest_defaults,
                interpreter_defaults,
                jobs=jobs,
            )
        )
        rows.extend(example_rows)
        if fail_fast and any(_row_failed(r) for r in example_rows):
            return rows
    return rows


def _row_failed(row: dict) -> bool:
    if row.get("display_only"):
        return False
    if row["summary"] in ("missing", "skip", "needs_playwright"):
        return False
    if row["timed_out"]:
        return True
    if row["summary"].endswith(", ok"):
        return False
    result = row.get("result") or {}
    return result.get("status") != "ok"


def test_all_interpreters(
    examples: dict[str, dict],
    interpreters: dict[str, dict],
    manifest_defaults: dict,
    interpreter_defaults: dict,
    *,
    fail_fast: bool = False,
    verbose: bool = False,
) -> list[dict]:
    rows = []
    for interpreter_id, interpreter_meta in interpreters.items():
        for example_id, example_meta in examples.items():
            if not example_allowed_on_interpreter(example_meta, interpreter_id):
                continue
            if not interpreter_available(interpreter_id, interpreter_meta):
                if verbose:
                    print(
                        f"Skipping {example_id} @ {interpreter_id} (interpreter missing)",
                        file=sys.stderr,
                    )
                rows.append(
                    {
                        "example": example_id,
                        "interpreter": interpreter_id,
                        "summary": "missing",
                        "returncode": -1,
                        "timed_out": False,
                        "result": None,
                        "stdout_tail": "",
                        "stderr_tail": "",
                    }
                )
                continue
            print(f"Running {example_id} @ {interpreter_id}...", file=sys.stderr)
            row = run_case(
                example_id,
                example_meta,
                interpreter_id,
                interpreter_meta,
                manifest_defaults,
                interpreter_defaults,
            )
            rows.append(row)
            if fail_fast and _row_failed(row):
                return rows
    return rows


def print_table(rows: list[dict], order: str):
    if not rows:
        print("(no runs)")
        return

    if order == "examples":
        examples = sorted({r["example"] for r in rows})
        interpreters = sorted({r["interpreter"] for r in rows})
        ex_w = max(10, max(len(e) for e in examples) + 2)
        rt_w = max(8, max(len(r) for r in interpreters) + 2)
        header = f"{'example':<{ex_w}} |" + "|".join(f"{rt:<{rt_w}}" for rt in interpreters)
        sep = "-" * ex_w + "-+-" + "-+-".join("-" * rt_w for _ in interpreters)
        print(header)
        print(sep)
        by_key = {(r["example"], r["interpreter"]): r["summary"] for r in rows}
        for ex in examples:
            cells = [f"{ex:<{ex_w}}"]
            for rt in interpreters:
                cells.append(f"{by_key.get((ex, rt), '—'):<{rt_w}}")
            print(" |".join(cells))
    else:
        interpreters = sorted({r["interpreter"] for r in rows})
        examples = sorted({r["example"] for r in rows})
        rt_w = max(12, max(len(r) for r in interpreters) + 2)
        ex_w = max(8, max(len(e) for e in examples) + 2)
        header = f"{'interpreter':<{rt_w}} |" + "|".join(f"{ex:<{ex_w}}" for ex in examples)
        sep = "-" * rt_w + "-+-" + "-+-".join("-" * ex_w for _ in examples)
        print(header)
        print(sep)
        by_key = {(r["interpreter"], r["example"]): r["summary"] for r in rows}
        for rt in interpreters:
            cells = [f"{rt:<{rt_w}}"]
            for ex in examples:
                cells.append(f"{by_key.get((rt, ex), '—'):<{ex_w}}")
            print(" |".join(cells))


def compute_exit_code(rows: list[dict]) -> int:
    for row in rows:
        if row.get("display_only"):
            continue
        if row["summary"] in ("missing", "skip", "needs_playwright"):
            continue
        if row["timed_out"]:
            return 1
        if row["summary"].endswith(", ok"):
            continue
        if row.get("result") and row["result"].get("status") == "ok":
            continue
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-interpreter pydevices-examples example smoke tests"
    )
    parser.add_argument(
        "--order",
        choices=("examples", "interpreters"),
        default="examples",
        help="examples: each example on all interpreters first; interpreters: each interpreter on all examples first",
    )
    parser.add_argument(
        "--only-example",
        nargs="+",
        metavar="ID",
        help=(
            "Subset of example ids (space-separated after one flag; "
            "repeating the flag keeps only the last list)"
        ),
    )
    parser.add_argument(
        "--only-interpreter",
        nargs="+",
        metavar="ID",
        help=(
            "Subset of interpreter ids (space-separated after one flag; "
            "repeating the flag keeps only the last list)"
        ),
    )
    parser.add_argument(
        "--curated-only", action="store_true", help="Run only the v1 curated examples"
    )
    parser.add_argument(
        "--all-except-harness",
        action="store_true",
        help="Run every manifest example except kind=harness (includes matrix=false and legacy/pending)",
    )
    parser.add_argument("--no-unit-tests", action="store_true", help="Skip unittest gate")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print full JSON rows to stdout")
    parser.add_argument(
        "--results-json",
        metavar="PATH",
        help="Write full result rows to PATH (default: temp dir/example_test_results.json)",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help=(
            "With --order examples: parallel workers per example "
            "(0=all interpreters concurrently, default; 1=serial)"
        ),
    )
    parser.add_argument(
        "--duration-s",
        type=float,
        metavar="SEC",
        help="Override per-example duration_s (quit inject / test-mode wall clock)",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        metavar="SEC",
        help="Override per-example timeout_s (and oneshot_timeout_s)",
    )
    args = parser.parse_args(argv)

    if not args.no_unit_tests:
        rc = run_unit_tests()
        if rc != 0:
            print("Unit tests failed; aborting example matrix.", file=sys.stderr)
            return rc

    interpreter_data = load_toml(INTERPRETERS_TOML)
    interpreter_defaults = interpreter_data.get("defaults", {})
    if args.duration_s is not None:
        interpreter_defaults["duration_s"] = args.duration_s
    if args.timeout_s is not None:
        interpreter_defaults["timeout_s"] = args.timeout_s
        interpreter_defaults["oneshot_timeout_s"] = args.timeout_s
    interpreters = load_interpreters()
    manifest_defaults, all_examples = load_manifest()

    # CLI timing overrides also win over per-example manifest values.
    if args.duration_s is not None or args.timeout_s is not None:
        for meta in all_examples.values():
            if args.duration_s is not None:
                meta["duration_s"] = args.duration_s
            if args.timeout_s is not None:
                meta["timeout_s"] = args.timeout_s
                meta["oneshot_timeout_s"] = args.timeout_s

    if args.only_interpreter:
        only_rt = _split_list(args.only_interpreter)
        interpreters = {k: v for k, v in interpreters.items() if k in only_rt}

    only_examples = _split_list(args.only_example)
    examples = matrix_examples(
        all_examples, only_examples, all_except_harness=args.all_except_harness
    )
    display_only = display_only_examples(
        all_examples, only_examples, all_except_harness=args.all_except_harness
    )
    if args.curated_only:
        curated = {
            "pydevices_demo",
            "calc_graphics",
            "paint",
            "appdev_simpletest",
            "graphics_simpletest",
            "framebuf_simpletest",
            "color_test",
            "chango",
        }
        examples = {k: v for k, v in examples.items() if k in curated}
        display_only = {k: v for k, v in display_only.items() if k in curated}

    if args.order == "examples":
        rows = test_all_examples(
            examples,
            interpreters,
            manifest_defaults,
            interpreter_defaults,
            fail_fast=args.fail_fast,
            verbose=args.verbose,
            jobs=args.jobs,
        )
    else:
        if args.jobs not in (0, 1):
            print(
                "warning: --jobs only applies to --order examples; ignoring",
                file=sys.stderr,
            )
        rows = test_all_interpreters(
            examples,
            interpreters,
            manifest_defaults,
            interpreter_defaults,
            fail_fast=args.fail_fast,
            verbose=args.verbose,
        )

    rows = append_display_rows(rows, display_only, interpreters, all_examples)

    if args.json:
        print(json.dumps(rows, indent=2))

    print()
    print_table(rows, args.order)

    out_path = (
        Path(args.results_json) if args.results_json else _temp_dir() / "example_test_results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"\nFull results: {out_path}", file=sys.stderr)

    return compute_exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())
