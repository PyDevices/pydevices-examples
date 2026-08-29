#!/usr/bin/env python3
"""Keep repo-root requirements.txt's package list in sync with PACKAGE_ORDER.

Used by:
  - Cursor sessionStart hook (when workspace is pydevices-examples)
  - CI / local check: ``--check`` exits nonzero if requirements.txt is stale

Since 51ff2a27 ("chore: refresh dependencies and WebAssembly runtime"),
requirements.txt lists bare, unpinned package names -- pip always resolves the
latest release from the configured indexes, so there is no per-package
version floor for this script to maintain any more. Its only remaining job is
to keep the package list itself in sync with PACKAGE_ORDER: add names that
belong and are missing, drop names that no longer belong, in PACKAGE_ORDER's
order. Everything else in the file (``--index-url``, ``--extra-index-url``,
blank lines, comments) survives verbatim. Running it when the file already
matches PACKAGE_ORDER is a no-op.
"""

from __future__ import annotations

import json
import os
import sys

# Install order SoT (dependencies before dependents). Keep in sync with the
# Cursor rule. "pydevices" is the whole of pydevices/lib in one distribution --
# appdev, audiodev, displaydev, events, keys, multimer and boarddev -- so the
# per-component entries that used to head this list are gone.
PACKAGE_ORDER = (
    "pydevices",
    "pydevices-audioif",
    "pydevices-desktop",
    "pydevices-lvgl",
    "pydevices-palettes",
    "pydevices-pdwidgets",
    "pydevices-pygraphics",
)

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


def desired_text(path: str) -> str:
    """Return what ``path`` should contain: existing non-package lines
    verbatim, followed by PACKAGE_ORDER as bare names.

    A "package line" is a non-blank, non-comment line that doesn't start with
    ``--`` (an index/option flag). Those are the only lines this function
    touches.
    """
    old = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            old = handle.read()

    header: list[str] = []
    for line in old.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--") and not stripped.startswith("#"):
            continue  # a package line -- dropped; regenerated below
        header.append(line)
    while header and header[-1] == "":
        header.pop()

    if not old:
        header = ["--index-url https://test.pypi.org/simple/", ""]

    lines = (
        [*header, "", *PACKAGE_ORDER] if header and header[-1] != "" else [*header, *PACKAGE_ORDER]
    )
    return "\n".join(lines) + "\n"


def refresh(path: str) -> bool:
    """Write ``path`` if it doesn't already match PACKAGE_ORDER. Return True
    if the file changed."""
    text = desired_text(path)
    old = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            old = handle.read()
    if old == text:
        return False
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def main() -> int:
    argv = sys.argv[1:]
    force = "--force" in argv
    check = "--check" in argv

    path = argv[argv.index("--path") + 1] if "--path" in argv else None

    if check:
        path = path or DEFAULT_REQ
        changed_text = desired_text(path)
        old = ""
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                old = handle.read()
        if old == changed_text:
            print(f"{path} is current.")
            return 0
        print(f"{path} is stale; run scripts/refresh-requirements.py --force", file=sys.stderr)
        return 1

    if force:
        path = path or DEFAULT_REQ
        changed = refresh(path)
        print(f"{'Updated' if changed else 'Already current'}: {path}", file=sys.stderr)
        print("{}")
        return 0

    payload = _load_stdin()
    paths = _paths_from_payload(payload)

    if not _is_pydevices_examples_workspace(paths):
        print("{}")
        return 0

    path = _requirements_path(paths)
    changed = refresh(path)
    if not changed:
        print("{}")
        return 0

    print(
        json.dumps(
            {
                "additional_context": (
                    "Synced pydevices-examples/requirements.txt package list to "
                    "PACKAGE_ORDER: " + ", ".join(PACKAGE_ORDER)
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
