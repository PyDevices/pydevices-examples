#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Generate MicroPython MIP package manifests (packages/*.json) for pydevices-examples.

Filesystem TOML mappings (pydevices-examples.toml) are generated via
dotgithub/scripts/generate_pyscript_filesystem_toml.py.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from gallery_personal import PERSONAL_EXAMPLE_DIRS
except ImportError:
    PERSONAL_EXAMPLE_DIRS = ()

parser = argparse.ArgumentParser(
    description="Generate MicroPython package manifests for pydevices-examples."
)
args = parser.parse_args()

repo_dir = ""
src_dir = "lib/"
package_ver = "0.0.1"
repo_url = "github:PyDevices/pydevices-examples/lib/"
output_dir = repo_dir
packages_dir = "packages/"

# List of package directories, dependencies, and extra files in that package.
packages = [
    ["utils", [], []],
    ["examples", [], []],
]

SKIP_DIR_NAMES = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache"}
# MicroPython mip only fetches .py / .mpy / .json (see micropython-lib mip).
MIP_FILE_SUFFIXES = {".py", ".mpy", ".json"}
# Local upstream checkouts (gitignored) — never list in mip manifests.
PACKAGE_SKIP_DIRS = {
    "utils": {"gui"},
    "examples": set(PERSONAL_EXAMPLE_DIRS),
}


def should_include_file(filename: str) -> bool:
    """Keep only mip-safe source extensions (skip .bmp/.png/.sh/… uniformly)."""
    return Path(filename).suffix.lower() in MIP_FILE_SUFFIXES


def is_gitignored(path: str) -> bool:
    """Skip generated/local-only files."""
    try:
        return (
            subprocess.run(
                ["git", "-C", repo_dir or ".", "check-ignore", "-q", "--", path],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
    except OSError:
        return False


package_dicts = {}

# Iterate over the packages and create the package files
for package_path, deps, extra_files in packages:
    package_name = package_path.split("/")[-1]
    full_path = os.path.join(repo_dir, src_dir, package_path)
    package_sub_dir = "" if package_name == package_path else package_name + "/"
    package_dicts[package_name] = {"urls": [], "deps": deps, "version": package_ver}

    for extra_file in sorted(extra_files):
        full_file_path = os.path.join(full_path.split(package_name)[0], extra_file)
        src_file = repo_url + os.path.relpath(full_file_path, repo_dir)
        package_dicts[package_name]["urls"].append([extra_file, src_file])

    package_skip = PACKAGE_SKIP_DIRS.get(package_name, set())

    for root, dirs, files in os.walk(full_path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES and d not in package_skip)
        for f in sorted(files):
            if not should_include_file(f):
                continue
            full_file_path = os.path.join(root, f)
            if is_gitignored(full_file_path):
                continue
            dest_file = package_sub_dir + os.path.relpath(full_file_path, full_path)
            src_file = repo_url + os.path.relpath(full_file_path, repo_dir)
            package_dicts[package_name]["urls"].append([dest_file, src_file])

# Write the package .json files (GitHub MIP only).
manual_package_stems = {
    "micropython-micro-gui",
    "micropython-nano-gui",
    "micropython-touch",
}
reserved_package_names = set(package_dicts) | manual_package_stems | {"appdev", "multimer"}
for package_name, contents in package_dicts.items():
    package_file = os.path.join(output_dir, packages_dir, package_name + ".json")
    with open(package_file, "w") as f:
        json.dump(contents, f, indent=2)
        f.write("\n")

# One MIP manifest per examples/<subdir>/ (for PyScript ?manifests= and GitHub mip).
examples_root = os.path.join(repo_dir, src_dir, "examples")
example_package_names = []
for entry in sorted(os.listdir(examples_root)):
    example_dir = os.path.join(examples_root, entry)
    if not os.path.isdir(example_dir):
        continue
    if entry in SKIP_DIR_NAMES or entry in PERSONAL_EXAMPLE_DIRS:
        continue
    if entry in reserved_package_names:
        print(f"skip examples/{entry}: name conflicts with packages/{entry}.json")
        continue
    urls = []
    for root, dirs, files in os.walk(example_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
        for f in sorted(files):
            if not should_include_file(f):
                continue
            full_file_path = os.path.join(root, f)
            if is_gitignored(full_file_path):
                continue
            rel_from_examples = os.path.relpath(full_file_path, examples_root).replace("\\", "/")
            src_file = "../lib/examples/" + rel_from_examples
            urls.append([rel_from_examples, src_file])
    package_file = os.path.join(output_dir, packages_dir, entry + ".json")
    if not urls:
        if os.path.isfile(package_file) and entry not in reserved_package_names:
            os.remove(package_file)
            print(f"removed packages/{entry}.json (no mip-safe files)")
        continue
    with open(package_file, "w") as f:
        json.dump({"urls": urls, "version": package_ver}, f, indent=2)
        f.write("\n")
    example_package_names.append(entry)

# Ensure symlinks in .site/pyscript/
pyscript_lib_link = os.path.join(output_dir, ".site", "pyscript", "lib")
lib_abs = os.path.join(output_dir, "lib")
if os.path.islink(pyscript_lib_link) or os.path.exists(pyscript_lib_link):
    if not os.path.islink(pyscript_lib_link):
        raise SystemExit(f"{pyscript_lib_link} exists and is not a symlink")
    if os.readlink(pyscript_lib_link) not in ("../../lib", lib_abs):
        os.remove(pyscript_lib_link)
        os.symlink("../../lib", pyscript_lib_link)
else:
    os.symlink("../../lib", pyscript_lib_link)

pyscript_packages_link = os.path.join(output_dir, ".site", "pyscript", "packages")
packages_abs = os.path.join(output_dir, packages_dir.rstrip("/"))
if os.path.islink(pyscript_packages_link) or os.path.exists(pyscript_packages_link):
    if not os.path.islink(pyscript_packages_link):
        raise SystemExit(f"{pyscript_packages_link} exists and is not a symlink")
    if os.readlink(pyscript_packages_link) not in ("../../packages", packages_abs):
        os.remove(pyscript_packages_link)
        os.symlink("../../packages", pyscript_packages_link)
else:
    os.symlink("../../packages", pyscript_packages_link)

pyscript_toml_link = os.path.join(output_dir, ".site", "pyscript", "pydevices-examples.toml")
toml_abs = os.path.join(output_dir, "pydevices-examples.toml")
if os.path.islink(pyscript_toml_link) or os.path.exists(pyscript_toml_link):
    if os.path.islink(pyscript_toml_link) and os.readlink(pyscript_toml_link) not in (
        "../../pydevices-examples.toml",
        toml_abs,
    ):
        os.remove(pyscript_toml_link)
        os.symlink("../../pydevices-examples.toml", pyscript_toml_link)
elif not os.path.exists(pyscript_toml_link):
    os.symlink("../../pydevices-examples.toml", pyscript_toml_link)

print(
    f"{__file__.split('/')[-1]} finished "
    f"({len(package_dicts)} lib packages, {len(example_package_names)} example packages)\n"
)
