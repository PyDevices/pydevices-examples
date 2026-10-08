# SPDX-License-Identifier: MIT
"""gallery-host.js reports a page whose example died after start as failed.

An example can start cleanly and then raise in its first timer tick. The
interpreter prints the traceback and the page keeps running, so anything that
checks ``document.body.dataset.runtimeState`` must see ``failed`` rather than
``ready``. These tests run the real host script under Node with a stand-in
interpreter, and are skipped where Node isn't installed.
"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / ".site" / "gallery" / "gallery-host.js"
RUNTIME_IMPORT = '"/vendor/micropython/micropython.mjs"'

# The stand-in interpreter: ?command=raise-later prints a traceback the way a
# timer callback's uncaught exception does, a little after start returns.
FAKE_RUNTIME = """
export async function loadMicroPython({stdout}) {
    return {
        FS: {mkdir() {}, writeFile() {}},
        softReset() {},
        async runPythonAsync(source) {
            if (source === "raise-later") {
                setTimeout(() => {
                    stdout("Traceback (most recent call last):");
                    stdout('  File "multimer/_dispatch.py", line 1, in _fire');
                    stdout("ValueError: planted timer fault");
                }, 20);
            }
            if (source === "print-only") {
                setTimeout(() => stdout("hello from a timer"), 20);
            }
        },
    };
}
"""

HARNESS = """
const events = new EventTarget();
globalThis.addEventListener = events.addEventListener.bind(events);
globalThis.dispatchEvent = events.dispatchEvent.bind(events);
globalThis.document = {
    body: {dataset: {}},
    getElementById() { return null; },
    querySelector() { return null; },
    addEventListener() {},
};
globalThis.location = {search: process.argv[2], href: "http://localhost/gallery/micropython.html"};
globalThis.fetch = async () => ({ok: true, json: async () => []});
await import("./host.mjs");
await new Promise((resolve) => setTimeout(resolve, 100));
console.log(JSON.stringify({
    state: document.body.dataset.runtimeState,
    errors: globalThis.__pydevicesHost.errors,
}));
"""


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class TestGalleryHostRuntimeState(unittest.TestCase):
    def _run(self, command):
        source = HOST.read_text(encoding="utf-8")
        self.assertIn(RUNTIME_IMPORT, source)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "host.mjs").write_text(
                source.replace(RUNTIME_IMPORT, '"./fake-runtime.mjs"'), encoding="utf-8"
            )
            (tmp / "fake-runtime.mjs").write_text(FAKE_RUNTIME, encoding="utf-8")
            (tmp / "harness.mjs").write_text(HARNESS, encoding="utf-8")
            result = subprocess.run(
                ["node", str(tmp / "harness.mjs"), f"?command={command}"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_traceback_after_start_marks_the_page_failed(self):
        outcome = self._run("raise-later")
        self.assertEqual(outcome["state"], "failed")
        self.assertIn("ValueError: planted timer fault", outcome["errors"][-1])

    def test_ordinary_output_after_start_stays_ready(self):
        outcome = self._run("print-only")
        self.assertEqual(outcome["state"], "ready")
        self.assertEqual(outcome["errors"], [])


if __name__ == "__main__":
    unittest.main()
