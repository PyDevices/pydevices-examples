#!/usr/bin/env python3
"""Refresh repo-root requirements.txt TestPyPI floors to latest versions.

Used by:
  - Cursor sessionStart hook (when workspace is pydevices-examples)
  - Agent after tagging a TestPyPI-publishing repo (CLI: --force)
  - product release preparation (CLI: --set name=X.Y.Z ...)

Preserves package install order and ``--index-url``. Only rewrites ``name>=ver``
lines for known packages. Fail-open: exits 0 with ``{}`` on any error
(unless ``--force`` / ``--set``).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

# Install order SoT (dependencies before dependents). Keep in sync with the
# Cursor rule. "pydevices" is the whole of pydevices/lib in one distribution --
# appdev, audiodev, displaydev, events, keys, multimer and boarddev -- so the
# per-component entries that used to head this list are gone.
PACKAGE_ORDER = (
    "pydevices",
    "pydevices-audioif",
    "pydevices-pygraphics",
    "pydevices-palettes",
    "pydevices-pdwidgets",
    "pydevices-desktop",
    "pydevices-lvgl",
)

INDEX_URL = "https://test.pypi.org/simple/"
JSON_URL = "https://test.pypi.org/pypi/{}/json"
_FLOOR_RE = re.compile(r"^([A-Za-z0-9_.-]+)>=([0-9][0-9A-Za-z._+]*)\s*$")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REQ = os.path.join(_REPO_ROOT, "requirements.txt")


def _load_stdin():
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _paths_from_payload(payload: dict) -> list[str]:
    paths = []
    for key in ("workspace_roots", "workspaceRoots", "roots"):
        val = payload.get(key)
        if isinstance(val, list):
            paths.extend(str(p) for p in val)
        elif isinstance(val, str):
            paths.append(val)
    for key in ("cwd", "workspace_root", "workspaceRoot", "project_dir", "projectDir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            paths.append(val)
    # Only fall back to process env when the hook payload omitted roots
    # (avoids treating the hook's own PWD as the workspace).
    if not paths:
        env_cwd = os.environ.get("CURSOR_PROJECT_DIR") or os.environ.get("PWD")
        if env_cwd:
            paths.append(env_cwd)
    return paths


def _is_pydevices_examples_workspace(paths: list[str]) -> bool:
    for path in paths:
        norm = os.path.normpath(os.path.expanduser(path))
        base = os.path.basename(norm.rstrip(os.sep))
        if base == "pydevices-examples":
            return True
        if (
            os.path.isfile(os.path.join(norm, "requirements.txt"))
            and os.path.isdir(os.path.join(norm, "lib", "examples"))
            and os.path.isfile(os.path.join(norm, "tools", "example_interpreters.toml"))
        ):
            return True
    return False


def _requirements_path(paths: list[str]) -> str:
    for path in paths:
        norm = os.path.normpath(os.path.expanduser(path))
        candidate = os.path.join(norm, "requirements.txt")
        if os.path.basename(norm.rstrip(os.sep)) == "pydevices-examples" and os.path.isdir(norm):
            return candidate
        if os.path.isfile(os.path.join(norm, "tools", "example_interpreters.toml")):
            return candidate
    return DEFAULT_REQ


def _latest_version(name: str) -> str:
    url = JSON_URL.format(name)
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = json.load(resp)
    return str(data["info"]["version"])


def _read_floors(path: str) -> dict[str, str]:
    floors: dict[str, str] = {}
    if not os.path.isfile(path):
        return floors
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = _FLOOR_RE.match(line.strip())
            if match:
                floors[match.group(1)] = match.group(2)
    return floors


def _write_floors(path: str, versions: dict[str, str]) -> bool:
    """Update floors in place. Return True if the file content changed.

    Rewrites only lines that already carry a ``name>=ver`` floor for a known
    package. Everything else survives verbatim -- ``--extra-index-url``, blank
    lines, comments, unpinned names, and packages outside PACKAGE_ORDER, none of
    which this script is the source of truth for. Regenerating the file from
    PACKAGE_ORDER instead would silently drop them.
    """
    old = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            old = handle.read()

    lines = []
    for line in old.splitlines():
        match = _FLOOR_RE.match(line.strip())
        if match and match.group(1) in versions:
            lines.append(f"{match.group(1)}>={versions[match.group(1)]}")
        else:
            lines.append(line)
    if not old:
        lines = [f"--index-url {INDEX_URL}", ""]
        lines.extend(f"{name}>={versions[name]}" for name in PACKAGE_ORDER)
    text = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    old = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            old = handle.read()
    if old == text:
        return False
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def refresh(path: str) -> dict[str, str]:
    versions = {}
    for name in PACKAGE_ORDER:
        versions[name] = _latest_version(name)
    _write_floors(path, versions)
    return versions


def set_floors(
    path: str, overrides: dict[str, str], *, fetch_missing: bool = True
) -> dict[str, str]:
    """Set specific floors; keep or fetch the rest. Returns the full floor map."""
    unknown = sorted(set(overrides) - set(PACKAGE_ORDER))
    if unknown:
        raise ValueError("unknown package(s): " + ", ".join(unknown))

    versions = _read_floors(path)
    for name, ver in overrides.items():
        versions[name] = ver

    for name in PACKAGE_ORDER:
        if name in versions:
            continue
        if not fetch_missing:
            raise ValueError(f"missing floor for {name!r} and fetch_missing is false")
        versions[name] = _latest_version(name)

    _write_floors(path, versions)
    return {name: versions[name] for name in PACKAGE_ORDER}


def _parse_set_args(argv: list[str]) -> tuple[dict[str, str], str | None]:
    """Parse ``--set a=1 b=2`` and optional ``--path`` from argv."""
    overrides: dict[str, str] = {}
    path = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--set":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                item = argv[i]
                if "=" not in item:
                    raise ValueError(f"--set expected name=version, got: {item}")
                name, ver = item.split("=", 1)
                name = name.strip()
                ver = ver.strip().lstrip("v")
                if not name or not ver:
                    raise ValueError(f"--set expected name=version, got: {item}")
                overrides[name] = ver
                i += 1
            continue
        if arg == "--path":
            i += 1
            if i >= len(argv):
                raise ValueError("--path requires a value")
            path = argv[i]
            i += 1
            continue
        i += 1
    return overrides, path


def main() -> int:
    argv = sys.argv[1:]
    force = "--force" in argv
    try:
        overrides, set_path = _parse_set_args(argv)
    except ValueError as exc:
        print(f"refresh failed: {exc}", file=sys.stderr)
        return 1

    if overrides:
        path = set_path or DEFAULT_REQ
        try:
            versions = set_floors(path, overrides)
        except (urllib.error.URLError, TimeoutError, KeyError, OSError, ValueError) as exc:
            print(f"refresh failed: {exc}", file=sys.stderr)
            return 1
        print(f"Updated {path}", file=sys.stderr)
        for name in PACKAGE_ORDER:
            mark = " *" if name in overrides else ""
            print(f"  {name}>={versions[name]}{mark}", file=sys.stderr)
        print("{}")
        return 0

    payload = _load_stdin() if not force else {}
    paths = _paths_from_payload(payload)

    if not force and not _is_pydevices_examples_workspace(paths):
        print("{}")
        return 0

    path = (
        _requirements_path(paths)
        if not force
        else (argv[argv.index("--path") + 1] if "--path" in argv else DEFAULT_REQ)
    )

    try:
        versions = refresh(path)
    except (urllib.error.URLError, TimeoutError, KeyError, OSError) as exc:
        print("{}")
        if force:
            print(f"refresh failed: {exc}", file=sys.stderr)
            return 1
        return 0

    if force:
        print(f"Updated {path}", file=sys.stderr)
        for name in PACKAGE_ORDER:
            print(f"  {name}>={versions[name]}", file=sys.stderr)
        print("{}")
        return 0

    print(
        json.dumps(
            {
                "additional_context": (
                    "Refreshed pydevices-examples/requirements.txt TestPyPI floors to latest: "
                    + ", ".join(f"{n}>={versions[n]}" for n in PACKAGE_ORDER)
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
