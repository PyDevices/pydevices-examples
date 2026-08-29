#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Audit MicroPython / CircuitPython board_config sibling pairs.

Board configs export hardware capabilities only. Application-level traffic
controllers such as ``appdev.App`` must be constructed by the app.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
# Board configs live in sibling pydevices (fallback: local stub).
BOARD_ROOT = ROOT.parent / "pydevices" / "board_configs"
if not BOARD_ROOT.is_dir():
    BOARD_ROOT = ROOT / "board_configs"


def _pairs(root: Path) -> list[tuple[Path, Path]]:
    """MP configs stay under ``board_configs/<bus>/…``; CP siblings live under
    ``board_configs/cp/<bus>/…/<name>/`` (same relative path, no ``cp_`` prefix).
    """
    pairs: list[tuple[Path, Path]] = []
    cp_root = root / "cp"
    for mp_config in sorted(root.rglob("board_config.py")):
        mp_dir = mp_config.parent
        try:
            rel = mp_dir.relative_to(root)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] == "cp":
            continue
        cp_dir = cp_root / rel
        cp_config = cp_dir / "board_config.py"
        if cp_config.is_file():
            pairs.append((mp_config, cp_config))
    return pairs


def _owns_event_app(text: str) -> bool:
    return bool(
        re.search(r"^\s*(?:import\s+appdev\b|from\s+appdev\b)", text, re.MULTILINE)
        or re.search(r"^\s*(?:app|broker)\s*=", text, re.MULTILINE)
        or re.search(r"\bappdev\.(?:App|Broker)\b|\bbroker\.create\b", text)
    )


def _touch_kind(text: str) -> str:
    if "touch_read=" in text or re.search(r"\btouch\s*=", text):
        return "touch"
    if "add_keypad" in text:
        return "keypad"
    return "none"


def _display_dims(text: str) -> tuple[int | None, int | None, int | None]:
    width = re.search(r"\bwidth=(\d+)", text)
    height = re.search(r"\bheight=(\d+)", text)
    depth = re.search(r"\bcolor_depth=(\d+)", text)
    return (
        int(width.group(1)) if width else None,
        int(height.group(1)) if height else None,
        int(depth.group(1)) if depth else None,
    )


def _dims_issues(rel: Path, mp_dims, cp_dims) -> list[str]:
    issues: list[str] = []
    mp_w, mp_h, mp_d = mp_dims
    cp_w, cp_h, cp_d = cp_dims
    if mp_w is None and cp_w is None:
        return issues
    if mp_w is None or cp_w is None:
        issues.append(f"{rel}: missing width on {'MP' if mp_w is None else 'CP'}")
    elif mp_w != cp_w:
        issues.append(f"{rel}: width mismatch MP={mp_w} CP={cp_w}")
    if mp_h is None and cp_h is None:
        pass
    elif mp_h is None or cp_h is None:
        issues.append(f"{rel}: missing height on {'MP' if mp_h is None else 'CP'}")
    elif mp_h != cp_h:
        issues.append(f"{rel}: height mismatch MP={mp_h} CP={cp_h}")
    if mp_d is not None and cp_d is not None and mp_d != cp_d:
        issues.append(f"{rel}: color_depth mismatch MP={mp_d} CP={cp_d}")
    return issues


def audit_pair(mp_path: Path, cp_path: Path) -> list[str]:
    issues: list[str] = []
    rel = mp_path.parent.relative_to(BOARD_ROOT)
    mp_text = mp_path.read_text(encoding="utf-8")
    cp_text = cp_path.read_text(encoding="utf-8")

    for label, text in (("MP", mp_text), ("CP", cp_text)):
        if _owns_event_app(text):
            issues.append(f"{rel}: {label} owns an application-level appdev.App")

    mp_touch = _touch_kind(mp_text)
    cp_touch = _touch_kind(cp_text)
    if mp_touch != cp_touch:
        issues.append(f"{rel}: input mismatch (MP={mp_touch}, CP={cp_touch})")

    mp_dims = _display_dims(mp_text)
    cp_dims = _display_dims(cp_text)
    issues.extend(_dims_issues(rel, mp_dims, cp_dims))

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        help="board_configs subtree to scan (default: busdisplay, fbdisplay)",
    )
    args = parser.parse_args()
    subtrees = args.root or ["busdisplay", "fbdisplay"]

    all_issues: list[str] = []
    pair_count = 0
    for mp_path, cp_path in _pairs(BOARD_ROOT):
        rel = mp_path.parent.relative_to(BOARD_ROOT)
        if rel.parts[0] not in subtrees:
            continue
        pair_count += 1
        all_issues.extend(audit_pair(mp_path, cp_path))

    if all_issues:
        for issue in all_issues:
            print(issue, file=sys.stderr)
        print(f"\n{len(all_issues)} issue(s) in {pair_count} pair(s)", file=sys.stderr)
        return 1

    print(f"OK ({pair_count} CP/MP pair(s) audited)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
