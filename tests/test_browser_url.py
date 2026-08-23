"""The gallery consumes pydevices' one browser-URL policy module."""

from pathlib import Path
import sys
import unittest

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = next(
    path
    for path in (_ROOT.parent / "pydevices" / "tools", _ROOT / "pydevices" / "tools")
    if (path / "_browser_url.py").is_file()
)
sys.path.insert(0, str(_TOOLS))

from _browser_url import query, resolve_dependencies  # noqa: E402


class BrowserUrlTests(unittest.TestCase):
    def test_direct_skips_compiled_packages(self):
        self.assertEqual(
            query(runtime="wasm", modules=("hello",), deps=("palettes",)),
            "?modules=hello",
        )

    def test_pyodide_maps_sister_wheels(self):
        self.assertEqual(
            query(runtime="pyodide", modules=("hello",), deps=("palettes",)),
            "?modules=hello&deps=pydevices-palettes%2Cpydevices-pygraphics",
        )

    def test_manifest_and_mip_passthrough(self):
        self.assertEqual(
            query(
                runtime="wasm",
                manifests=("alien",),
                deps=("github:PyDevices/example/package.json",),
            ),
            "?manifests=alien&deps=github%3APyDevices%2Fexample%2Fpackage.json",
        )

    def test_unknown_runtime_fails(self):
        with self.assertRaises(ValueError):
            resolve_dependencies((), "unknown")


if __name__ == "__main__":
    unittest.main()
