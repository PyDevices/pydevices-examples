# SPDX-License-Identifier: MIT
"""Gallery thumbnail generation and card rendering."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import _env  # noqa: F401

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import gallery_generator as gallery  # noqa: E402


class TestGalleryScreenshots(unittest.TestCase):
    def test_direct_stage_excludes_generated_gui_cache_and_validates_dependencies(self):
        utilities = gallery.tracked_utility_files()
        self.assertIn("utils/tft_config.py", utilities)
        self.assertFalse(any(path.startswith("utils/gui/") for path in utilities))

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            gallery, "EXAMPLES_DIR", Path(tmp)
        ):
            package = Path(tmp) / "demo"
            package.mkdir()
            (package / "demo.py").write_text("import palettes\nfrom pygraphics import Area\n")
            (package / "helper.py").write_text("from pdwidgets.button import Button\n")
            example = gallery.Example("demo", "lib/examples/demo/demo.py", "manifest")
            example.pyscript_files = ["demo/demo.py", "demo/helper.py"]
            example.deps = ["palettes", "pygraphics", "pdwidgets", "audioif"]

            with mock.patch("sys.stderr") as stderr:
                gallery.validate_example_deps([example])
            warning = "".join(call.args[0] for call in stderr.write.call_args_list)
            self.assertIn("declared # deps not imported: audioif", warning)

            example.deps.remove("pdwidgets")
            with mock.patch("sys.stderr"), self.assertRaisesRegex(
                SystemExit, r"missing # deps: pdwidgets"
            ):
                gallery.validate_example_deps([example])

    def test_card_uses_existing_thumbnail(self):
        example = gallery.Example("demo", "demo.py", "module")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            gallery, "THUMBNAILS_DIR", Path(tmp)
        ):
            (Path(tmp) / "demo.png").write_bytes(b"png")
            icon = gallery.render_card_icon(example)
        self.assertIn('src="../pyscript/thumbnails/demo.png"', icon)
        self.assertIn("<img ", icon)

    def test_card_falls_back_when_thumbnail_is_missing(self):
        example = gallery.Example("missing", "missing.py", "module")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            gallery, "THUMBNAILS_DIR", Path(tmp)
        ):
            self.assertEqual(gallery.render_card_icon(example), gallery.GENERIC_ICON)

    def test_existing_thumbnail_is_not_regenerated(self):
        example = gallery.Example("demo", "demo.py", "module")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            gallery, "THUMBNAILS_DIR", Path(tmp)
        ), mock.patch.object(gallery.subprocess, "run") as run:
            (Path(tmp) / "demo.png").write_bytes(b"png")
            self.assertEqual(gallery.generate_missing_thumbnails([example]), (0, 0))
            run.assert_not_called()

    def test_capture_uses_repository_relative_source_path(self):
        example = gallery.Example("demo", "lib/examples/demo.py", "module")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            gallery, "THUMBNAILS_DIR", Path(tmp)
        ), mock.patch.object(gallery.subprocess, "run") as run:

            def create_thumbnail(*_args, **_kwargs):
                (Path(tmp) / "demo.png").write_bytes(b"png")
                return mock.Mock(returncode=0, stderr="", stdout="")

            run.side_effect = create_thumbnail
            gallery.generate_missing_thumbnails([example])
        command = run.call_args.args[0]
        self.assertEqual(Path(command[2]), gallery.REPO_ROOT / example.source_rel)


if __name__ == "__main__":
    unittest.main()
