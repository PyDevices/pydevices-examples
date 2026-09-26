# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The test tools force multimer's wake source through MULTIMER_SOURCE."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import _env

_REPO = Path(__file__).resolve().parent.parent
_TOOLS = _REPO / "tools"
_PRELOAD = _TOOLS / "multimer_source_preload.py"


def _load(name, filename):
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    spec = importlib.util.spec_from_file_location(name, _TOOLS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _child_env():
    env = os.environ.copy()
    env.pop("MULTIMER_SOURCE", None)
    env.pop("MULTIMER_BACKEND", None)
    if _env._HARDWARE_ROOT:
        lib = os.path.join(_env._HARDWARE_ROOT, "lib")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [lib, env.get("PYTHONPATH")]))
    return env


class TestPreload(unittest.TestCase):
    def _run(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "probe.py")
            with open(script, "w") as fh:
                fh.write(
                    "import multimer\nprint('SOURCE_IN_SCRIPT=' + str(multimer.info()['source']))\n"
                )
            return subprocess.run(
                [sys.executable, str(_PRELOAD), source, script],
                cwd=str(_REPO / "lib"),
                env=_child_env(),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

    def test_forced_source_is_the_one_in_use(self):
        for source in ("pending", "none"):
            with self.subTest(source=source):
                proc = self._run(source)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertIn(f"MULTIMER_SOURCE_FORCED={source}", proc.stdout)
                self.assertIn(f"SOURCE_IN_SCRIPT={source}", proc.stdout)

    def test_source_this_host_lacks_is_unavailable(self):
        proc = self._run("wasm")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertIn("MULTIMER_SOURCE_UNAVAILABLE='wasm'", proc.stdout)
        self.assertNotIn("SOURCE_IN_SCRIPT", proc.stdout)


class TestKitAndWrapper(unittest.TestCase):
    def test_kit_forwards_multimer_source(self):
        kit = _load("pydevices_example_test_kit", "example_test_kit.py")
        self.assertEqual(kit.multimer_source_args({}), [])
        self.assertEqual(
            kit.multimer_source_args({"MULTIMER_SOURCE": "signal"}),
            ["--multimer-source", "signal"],
        )

    def test_kit_refuses_retired_multimer_backend(self):
        kit = _load("pydevices_example_test_kit", "example_test_kit.py")
        with self.assertRaises(SystemExit) as ctx:
            kit.multimer_source_args({"MULTIMER_BACKEND": "sdl2"})
        self.assertIn("MULTIMER_SOURCE", str(ctx.exception))

    def test_wrapper_takes_multimer_source(self):
        wrapper = _load("pydevices_example_test_wrapper", "example_test_wrapper.py")
        base = ["wrapper", "demo", "--script", "x.py", "--kind", "loop"]
        args = wrapper._parse_args([*base, "--multimer-source", "pending"])
        self.assertEqual(args["multimer_source"], "pending")
        with self.assertRaises(ValueError):
            wrapper._parse_args([*base, "--multimer-backend", "sdl2"])


if __name__ == "__main__":
    unittest.main()
