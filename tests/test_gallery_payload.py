# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""What the deployed gallery has to carry, read off the generated page.

The cards say what they install; the deploy step copies a *subset* of
``lib/examples`` next to them. When those two disagree the local server hides
it completely -- it serves the whole repo, so every path resolves -- and the
failure appears only on the published site, as a 404 inside the wasm runtime
and an ImportError on the card. That is how ``audiolive_rack`` shipped broken
for twenty minutes (pydevices-examples#129): it declares
``# manifests: audiolive``, and the audiolive package's own header says
``# gallery: skip``, so nothing copied it.

So this reads the hrefs out of the generated index, follows every manifest
they name, and asks whether the files those manifests fetch are files the
deploy actually copies.
"""

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gallery_generator as generator  # noqa: E402

GALLERY_INDEX = ROOT / ".site" / "gallery" / "index.html"
PACKAGES = ROOT / "packages"

#: How a manifest's source URL points back at the example tree. The manifest
#: lives in ``gallery/packages/``, so this is ``gallery/lib/examples/``, which
#: is what ``--copy-examples`` fills.
_FROM_EXAMPLES = "../lib/examples/"

_HREF = re.compile(r'href="micropython\.html\?([^"]+)"')


def cards():
    """(query string) for every card on the generated WebAssembly gallery."""
    return _HREF.findall(GALLERY_INDEX.read_text(encoding="utf-8"))


def query_values(query, key):
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if name == key:
            return [item for item in value.replace("%2C", ",").split(",") if item]
    return []


class TheDeployCarriesWhatTheCardsAskFor(unittest.TestCase):
    def setUp(self):
        self.copied = set(generator.deployed_example_files())

    def test_every_manifest_a_card_installs_is_copied_whole(self):
        missing = {}
        for query in cards():
            for name in query_values(query, "manifests"):
                manifest = PACKAGES / f"{name}.json"
                if not manifest.is_file():
                    self.fail(f"a card installs packages/{name}.json, which does not exist")
                data = json.loads(manifest.read_text(encoding="utf-8"))
                for _destination, source in data["urls"]:
                    if not source.startswith(_FROM_EXAMPLES):
                        continue  # another repo's tree, fetched at runtime
                    relative = source[len(_FROM_EXAMPLES) :]
                    if relative not in self.copied:
                        missing.setdefault(name, []).append(relative)
        self.assertEqual(
            missing,
            {},
            "the deployed site would 404 on these: a card installs them and "
            "nothing copies them next to it",
        )

    def test_every_module_a_card_imports_is_copied(self):
        staged = set(
            json.loads(
                (ROOT / ".site" / "gallery" / "python-files.json").read_text(encoding="utf-8")
            )
        )
        for query in cards():
            for name in query_values(query, "modules"):
                self.assertIn(
                    f"{name}.py",
                    staged,
                    f"the card for {name} imports a module the host never stages",
                )

    def test_a_staged_module_is_a_file_the_deploy_copies(self):
        staged = set(
            json.loads(
                (ROOT / ".site" / "gallery" / "python-files.json").read_text(encoding="utf-8")
            )
        )
        self.assertEqual(
            sorted(
                path
                for path in staged
                if not path.startswith("utils/") and path not in self.copied
            ),
            [],
            "python-files.json stages a file the deploy does not copy",
        )


if __name__ == "__main__":
    unittest.main()
