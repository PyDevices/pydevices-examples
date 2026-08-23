# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Tests for the generated pydevices-examples PyScript TOML configurations."""

import os
from pathlib import Path
import unittest

import tomllib

ROOT = Path(__file__).resolve().parents[1]


class TestPyScriptTomlConfigs(unittest.TestCase):
    def test_examples_toml_contains_every_python_source(self):
        toml_path = ROOT / "pydevices-examples.toml"
        self.assertTrue(toml_path.is_file(), "pydevices-examples.toml must exist at repo root")

        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        self.assertIn("files", data)
        destinations = set(data["files"].values())

        expected = set()
        # lib/utils mapped to /utils/ (excluding untracked lib/utils/gui)
        utils_root = ROOT / "lib" / "utils"
        for path in utils_root.rglob("*.py"):
            if "__pycache__" not in path.parts and "gui" not in path.parts:
                expected.add("/utils/" + path.relative_to(utils_root).as_posix())

        # lib/examples mapped to /examples/
        examples_root = ROOT / "lib" / "examples"
        for path in examples_root.rglob("*.py"):
            if "__pycache__" not in path.parts:
                expected.add("/examples/" + path.relative_to(examples_root).as_posix())

        self.assertEqual(expected, destinations)

    def test_pyscript_symlink_resolves_to_root_toml(self):
        link = ROOT / ".site" / "pyscript" / "pydevices-examples.toml"
        self.assertTrue(link.exists(), ".site/pyscript/pydevices-examples.toml must exist")
        self.assertEqual(
            (ROOT / "pydevices-examples.toml").resolve(),
            link.resolve(),
        )

    def test_static_interpreter_headers(self):
        mp = tomllib.loads((ROOT / ".site" / "pyscript" / "micropython.toml").read_text())
        py = tomllib.loads((ROOT / ".site" / "pyscript" / "pyodide.toml").read_text())
        self.assertEqual(mp.get("interpreter"), "/vendor/micropython/micropython.mjs")
        self.assertEqual(py.get("interpreter"), "./vendor/pyodide/pyodide.mjs")

    def test_peterhinch_toml_configs(self):
        for gui in ("nano", "micro", "touch"):
            path = ROOT / ".site" / "pyscript" / f"peterhinch-{gui}.toml"
            self.assertTrue(path.is_file(), f"{path} must exist")
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            self.assertIn("files", data)
            self.assertTrue(len(data["files"]) > 0)
            for dest in data["files"].values():
                self.assertTrue(
                    dest.startswith("/utils/"), f"Destination {dest} must mount to /utils/"
                )


if __name__ == "__main__":
    unittest.main()
