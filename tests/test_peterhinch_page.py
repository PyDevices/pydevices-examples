"""Static contract tests for the dynamic Peter Hinch demo browser.

The page runs on the direct-WebAssembly host (``gallery-host.js``). It used to
run on PyScript, and the assertions that described *that* plumbing — the ``mpy``
interpreter type, ``dataset.configs``, the modular ``.toml`` config chain — have
been restated against the host that replaced it. Everything describing what a
visitor gets is unchanged.
"""

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / ".site" / "gallery"
PAGE = GALLERY / "peterhinch.html"


def _source():
    return PAGE.read_text(encoding="utf-8")


def _excluded(gui):
    source = _source()
    match = re.search(
        rf'    "{gui}": \{{(?P<body>.*?)\n    \}},',
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    return set(re.findall(r'^\s+"([^"]+)",', match.group("body"), flags=re.MULTILINE))


class TestPeterHinchPage(unittest.TestCase):
    def test_page_declares_its_gui_specific_plan_before_the_host_loads(self):
        """The host reads ``?manifests=…&command=…`` from the address bar, but this
        page's address bar carries the demo browser's own state (``?touch&demo=…``),
        so it hands the host a GUI-specific plan directly — before the host loads."""
        source = _source()
        interpreter = source.index('<script id="hinch-interpreter" type="text/plain"')
        manifest_map = source.index("nano: 'micropython-nano-gui'")
        plan = source.index("globalThis.__pydevicesPlan = new URLSearchParams({")
        command = source.index("command: document.getElementById('hinch-interpreter').textContent")
        loader = source.index('<script type="module" src="./gallery-host.js"></script>')
        assert interpreter < manifest_map < plan < command < loader
        assert "manifests: manifests[gui]" in source
        # The retired PyScript plumbing must not come back with it.
        assert "interpreter.type = 'mpy'" not in source
        assert "dataset.configs" not in source
        assert ".toml" not in source
        assert "pyscript-config.js" not in source
        assert "pyodide" not in source.lower()

    def test_page_loads_the_shared_gallery_chrome_and_styles(self):
        """The COI shim the PyScript page carried is obsolete here: the direct host
        runs MicroPython on the page's own main thread and never needs
        SharedArrayBuffer. What survives is that the page wears the same chrome and
        stylesheets as its sibling runtime page rather than forking them."""
        source = _source()
        sibling = (GALLERY / "micropython.html").read_text(encoding="utf-8")
        for link in (
            '<link rel="stylesheet" href="/assets/chrome/site.css">',
            '<link rel="stylesheet" href="../pyscript/site-extra.css">',
            '<link rel="stylesheet" href="../pyscript/demo.css">',
        ):
            assert link in source
            assert link in sibling
        assert "mini-coi" not in source
        assert "mini-coi" not in sibling
        assert '<script src="../pyscript/site-chrome.js"></script>' in source
        assert '<script src="../pyscript/theme-toggle.js"></script>' in source
        assert 'id="pydevices-site-header"' in source
        assert 'id="pydevices-site-footer"' in source

    def test_bare_url_defaults_to_touch_gui(self):
        source = _source()
        assert "Bare URL (or only ?demo=…): same as ?touch" in source
        assert "gui = 'touch';" in source
        assert "selectors.length === 0 && unknownBare.length === 0" in source

    def test_gui_files_come_from_per_gui_mip_manifests(self):
        """Each GUI's files come from its own manifest, sourced straight from
        peterhinch's upstream repository — and nothing shared rides along in it.
        ``pydevices-desktop`` (board_config, displaydev) is the host's job."""
        source = _source()
        packages = {
            "nano": "micropython-nano-gui",
            "micro": "micropython-micro-gui",
            "touch": "micropython-touch",
        }
        for gui, package in packages.items():
            assert f"{gui}: '{package}'" in source
            manifest = json.loads((ROOT / "packages" / f"{package}.json").read_text())
            destinations = {destination for destination, _ in manifest["urls"]}
            assert destinations
            assert not any(name.endswith("board_config.py") for name in destinations)
            assert all(name.startswith("gui/") for name in destinations)
            assert any(name.startswith("gui/demos/") for name in destinations)
            for destination, origin in manifest["urls"]:
                assert origin == f"github:peterhinch/{package}/{destination}"

    def test_gallery_pages_share_one_direct_wasm_host(self):
        """The modular ``.toml`` config chain retired with PyScript. The gallery's
        loader pages now compose by sharing one host module instead."""
        for filename in ("micropython.html", "mp.html", "peterhinch.html"):
            source = (GALLERY / filename).read_text(encoding="utf-8")
            assert '<script type="module" src="./gallery-host.js"></script>' in source
            assert ".toml" not in source
            assert "pyscript-config.js" not in source
        host = (GALLERY / "gallery-host.js").read_text(encoding="utf-8")
        assert "globalThis.__pydevicesPlan ?? location.search" in host
        assert 'command: params.get("command")' in host
        assert "`./packages/${manifest}.json`" in host

    def test_dynamic_discovery_is_sorted_and_excludes_init(self):
        source = _source()
        assert 'os.listdir("/utils/gui/demos")' in source
        assert 'filename != "__init__.py"' in source
        assert "names.sort()" in source

    def test_demo_list_is_reused_across_fresh_interpreter_reloads(self):
        source = _source()
        assert "'peterhinch-demos-' + gui" in source
        assert "window.sessionStorage.getItem(cacheKey)" in source
        assert 'window.sessionStorage.setItem("peterhinch-demos-" + gui, signature)' in source
        assert 'if _gui_value("__hinchDemoSignature") != "\\n".join(names):' in source

    def test_display_size_is_overridden_before_setup_import(self):
        source = _source()
        width = source.index('env_set("PYDEVICES_WIDTH", 320)')
        height = source.index('env_set("PYDEVICES_HEIGHT", 240)')
        setup_import = source.index("__import__(setup)")
        assert width < setup_import
        assert height < setup_import

    def test_micro_gui_has_visible_keyboard_hint(self):
        source = _source()
        assert "Use the arrow keys to navigate and adjust. Press Space to select." in source
        assert "document.getElementById('control-hint').hidden = gui !== 'micro';" in source

    def test_gui_name_links_to_its_upstream_repository(self):
        source = _source()
        assert 'id="package-link"' in source
        assert "https://github.com/peterhinch/micropython-nano-gui" in source
        assert "https://github.com/peterhinch/micropython-micro-gui" in source
        assert "https://github.com/peterhinch/micropython-touch" in source
        assert "packageLink.textContent = labels[gui];" in source
        assert "packageLink.href = repositories[gui];" in source

    def test_gui_picker_is_ordered_touch_micro_nano(self):
        source = _source()
        touch = source.index('data-gui="touch"')
        micro = source.index('data-gui="micro"')
        nano = source.index('data-gui="nano"')
        assert touch < micro < nano

    def test_console_stacks_below_canvas_and_cards_are_synchronized(self):
        source = _source()
        assert "grid-template-columns: max-content max-content;" in source
        assert "justify-content: center;" in source
        assert ".hinch-stage .play-area > .console-panel" in source
        assert "grid-row: 3;" in source
        assert "stage.style.width = width;" in source
        assert "panel.style.width = width;" in source
        assert "demoPanel.style.width = width;" in source
        assert "demoPanel.style.maxWidth = width;" in source
        assert "panel.style.height = rect.height + 'px';" in source
        assert "demoPanel.style.height = consoleBottom - demoTop + 'px';" in source

    def test_console_output_is_the_hosts_and_is_not_written_twice(self):
        """PyScript needed the page to rebind ``print`` to reach the console panel.
        ``gallery-host.js`` already pipes stdout and stderr into ``#log``, so a
        second writer would double every line."""
        source = _source()
        assert '<pre id="log" class="log"' in source
        assert "builtins.print" not in source
        host = (GALLERY / "gallery-host.js").read_text(encoding="utf-8")
        assert 'const logElement = () => document.getElementById("log");' in host
        assert 'log(line, "stdout")' in host
        assert 'log(line, "stderr")' in host

    def test_known_incompatible_demos_are_filtered(self):
        assert _excluded("nano") == {
            "aclock",
            "aclock_large",
            "aclock_ttgo",
            "alevel",
            "asnano",
            "asnano_sync",
            "clock_batt",
            "clocktest",
            "color15",
            "color96",
            "fpt",
            "mono_test",
            "sharptest",
        }
        assert _excluded("micro") == {"audio", "bitmap", "date", "qrcode"}
        assert _excluded("touch") == {"audio", "bitmap", "date", "qrcode"}

    def test_selected_demo_must_be_discovered_and_supported(self):
        source = _source()
        assert 'if not selected:\n            _set_status("Discovering demos…")' in source
        assert "'Starting ' + demo + '…'" in source
        assert "if selected not in names:" in source
        assert "if selected in discovered:" in source
        assert "Demo is not compatible with the browser interpreter:" in source
        assert '__import__("gui.demos." + selected)' in source

    def test_valid_demo_scrolls_panel_below_sticky_header(self):
        source = _source()
        validation = source.index("if selected not in names:")
        scroll = source.index("_scroll_to_demo_panel()", validation)
        demo_import = source.index('__import__("gui.demos." + selected)')
        assert validation < scroll < demo_import
        assert 'document.querySelector(".demo-panel")' in source
        assert 'document.querySelector(".site-header")' in source
        assert "window.scrollTo(0, max(0, int(target)))" in source

    def test_gallery_regeneration_preserves_page(self):
        generator = (ROOT / "scripts" / "gallery_generator.py").read_text(encoding="utf-8")
        keep_html = generator.split("KEEP_HTML =", 1)[1].split("ARROW =", 1)[0]
        assert '"peterhinch"' in keep_html


if __name__ == "__main__":
    unittest.main()
