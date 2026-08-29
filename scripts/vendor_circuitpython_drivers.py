#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2024 Brad Barnett
# SPDX-License-Identifier: MIT
"""Vendor Adafruit CircuitPython display/touch drivers into pydevices-examples."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

DISPLAY_DRIVERS = {
    "sh1106": "Adafruit_CircuitPython_DisplayIO_SH1106",
    "sh1107": "Adafruit_CircuitPython_DisplayIO_SH1107",
    "ssd1305": "Adafruit_CircuitPython_DisplayIO_SSD1305",
    "ssd1306": "Adafruit_CircuitPython_DisplayIO_SSD1306",
    "ssd1322": "Adafruit_CircuitPython_SSD1322",
    "ssd1325": "Adafruit_CircuitPython_SSD1325",
    "ssd1327": "Adafruit_CircuitPython_SSD1327",
    "ssd1331": "Adafruit_CircuitPython_SSD1331",
    "ssd1351": "Adafruit_CircuitPython_SSD1351",
    "ra8875": "Adafruit_CircuitPython_RA8875",
    "pcd8544": "Adafruit_CircuitPython_PCD8544",
}

TOUCH_DRIVERS = {
    "ft5336": "Adafruit_CircuitPython_FT5336",
    "tsc2007": "Adafruit_CircuitPython_TSC2007",
    "tt21100": "Adafruit_CircuitPython_TT21100",
    "stmpe610": "Adafruit_CircuitPython_STMPE610",
    "touchscreen": "Adafruit_CircuitPython_Touchscreen",
}

COMMUNITY_DISPLAY = {
    "community/st7565": ("mateusznowakdev/CircuitPython_DisplayIO_ST7565", "displayio_st7565.py"),
}

BUSDISPLAY_IMPORT = """from displaydev.busdisplay import BusDisplay
"""


def clone_repo(repo: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(
        ["git", "clone", "--depth", "1", f"https://github.com/adafruit/{repo}.git", str(dest)],
        check=True,
        capture_output=True,
    )


def clone_repo_url(url: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(
        ["git", "clone", "--depth", "1", f"https://github.com/{url}.git", str(dest)],
        check=True,
        capture_output=True,
    )


def find_module_py(repo_dir: Path, stem: str) -> Path:
    for path in repo_dir.glob("adafruit_*.py"):
        return path
    pkg = repo_dir / f"adafruit_{stem}"
    if pkg.is_dir():
        candidate = pkg / f"{stem}.py"
        if candidate.exists():
            return candidate
    matches = list(repo_dir.glob(f"*{stem}*.py"))
    if not matches:
        raise FileNotFoundError(f"No module in {repo_dir} for {stem}")
    return matches[0]


def patch_busdisplay(content: str) -> str:
    content = re.sub(r"^from busdisplay import BusDisplay\s*$", "", content, flags=re.M)
    content = re.sub(
        r"^try:\s*\n\s*from displaydev\.busdisplay import BusDisplay.*?\nexcept ImportError:.*?\n\s*from busdisplay import BusDisplay\s*\n",
        "",
        content,
        flags=re.M | re.S,
    )
    content = re.sub(
        r"^try:\s*\n\s*from displaysys\.busdisplay import BusDisplay.*?\nexcept ImportError:.*?\n\s*from busdisplay import BusDisplay\s*\n",
        "",
        content,
        flags=re.M | re.S,
    )
    if "from displaydev.busdisplay import BusDisplay" not in content:
        content = BUSDISPLAY_IMPORT + "\n" + content
    content = re.sub(r"^__version__ = .*$", "", content, flags=re.M)
    content = re.sub(r"^__repo__ = .*$", "", content, flags=re.M)
    return content


def vendor_adafruit(name: str, repo: str, out_dir: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / repo
        clone_repo(repo, repo_dir)
        src = find_module_py(repo_dir, name.replace("_", ""))
        content = patch_busdisplay(src.read_text(encoding="utf-8"))
        dest = out_dir / f"{name}.py"
        dest.write_text(content, encoding="utf-8")
        print(f"vendored {dest.relative_to(ROOT)}")


def vendor_touch(name: str, repo: str, out_dir: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / repo
        clone_repo(repo, repo_dir)
        src = find_module_py(repo_dir, name)
        dest = out_dir / "circuitpython" / f"adafruit_{name}.py"
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")
        content = re.sub(r"^__version__ = .*$", "", content, flags=re.M)
        content = re.sub(r"^__repo__ = .*$", "", content, flags=re.M)
        dest.write_text(content, encoding="utf-8")
        print(f"vendored {dest.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--touch", action="store_true")
    parser.add_argument("--community", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    run_all = args.all or not (args.display or args.touch or args.community)

    display_dir = ROOT / "drivers" / "display"
    touch_dir = ROOT / "drivers" / "touch"

    if run_all or args.display:
        for name, repo in DISPLAY_DRIVERS.items():
            try:
                vendor_adafruit(name, repo, display_dir)
            except Exception as exc:  # noqa: BLE001
                print(f"skip {name}: {exc}", file=sys.stderr)

    if run_all or args.touch:
        for name, repo in TOUCH_DRIVERS.items():
            try:
                vendor_touch(name, repo, touch_dir)
            except Exception as exc:  # noqa: BLE001
                print(f"skip touch {name}: {exc}", file=sys.stderr)

    if run_all or args.community:
        for out_name, (repo_url, module_file) in COMMUNITY_DISPLAY.items():
            with tempfile.TemporaryDirectory() as tmp:
                repo_dir = Path(tmp) / "repo"
                clone_repo_url(repo_url, repo_dir)
                src = repo_dir / module_file
                content = patch_busdisplay(src.read_text(encoding="utf-8"))
                dest = display_dir / f"{out_name}.py"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                print(f"vendored {dest.relative_to(ROOT)}")

    # Promote WIP OLED color drivers if vendored successfully
    for wip in ("ssd1331", "ssd1351"):
        src = display_dir / f"{wip}.py"
        wip_src = display_dir / "work_in_progress" / f"{wip}.py"
        if src.exists() and wip_src.exists():
            wip_src.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
