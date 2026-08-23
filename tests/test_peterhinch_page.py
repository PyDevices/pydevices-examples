"""Static contract tests for the dynamic Peter Hinch demo browser."""

import json
from pathlib import Path
import re

import tomllib

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / ".site" / "pyscript" / "peterhinch.html"


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


def test_page_selects_a_gui_specific_micropython_config_before_core_loads():
    source = _source()
    interpreter = source.index('<script id="hinch-interpreter" type="text/plain"')
    interpreter_config = source.index("'./micropython.toml'")
    desktop_config = source.index(
        "'https://raw.githubusercontent.com/PyDevices/pydevices/main/pydevices-desktop.toml'"
    )
    shared_config = source.index("'./pydevices-examples.toml'")
    gui_config = source.index("'./peterhinch-' + gui + '.toml'")
    loader = source.index('<script type="module" src="./pyscript-config.js"></script>')
    assert interpreter < interpreter_config < desktop_config < shared_config < gui_config < loader
    assert "interpreter.type = 'mpy';" in source
    assert "interpreter.dataset.configs" in source
    assert "pyodide" not in source.lower()


def test_page_loads_coi_shim_and_styles():
    source = _source()
    assert '<script src="./mini-coi-fd.js"></script>' in source
    assert '<link rel="stylesheet" href="./site.css">' in source


def test_bare_url_defaults_to_touch_gui():
    source = _source()
    assert "Bare URL (or only ?demo=…): same as ?touch" in source
    assert "gui = 'touch';" in source
    assert "selectors.length === 0 && unknownBare.length === 0" in source


def test_generated_configs_split_shared_files_from_gui_manifests():
    micropython = tomllib.loads((ROOT / ".site" / "pyscript" / "micropython.toml").read_text())
    pyodide = tomllib.loads((ROOT / ".site" / "pyscript" / "pyodide.toml").read_text())
    assert micropython == {"interpreter": "./vendor/micropython/micropython.mjs"}
    assert pyodide == {"interpreter": "./vendor/pyodide/pyodide.mjs"}

    packages = {
        "nano": "micropython-nano-gui",
        "micro": "micropython-micro-gui",
        "touch": "micropython-touch",
    }
    for gui, package in packages.items():
        config = tomllib.loads(
            (ROOT / ".site" / "pyscript" / f"peterhinch-{gui}.toml").read_text()
        )
        manifest = json.loads((ROOT / "packages" / f"{package}.json").read_text())
        assert set(config) == {"files"}
        assert "./lib/board_config.py" not in config["files"]
        for destination, source in manifest["urls"]:
            github_path = source.removeprefix("github:")
            owner, repository, path = github_path.split("/", 2)
            raw_source = f"https://raw.githubusercontent.com/{owner}/{repository}/master/{path}"
            assert config["files"][raw_source] == f"/utils/{destination}"


def test_gallery_pages_compose_modular_toml_configs():
    pages = {
        "repl.html": "micropython",
        "harness.html": "micropython",
        "editor.html": "micropython",
        "micropython.html": "micropython",
        "async.html": "micropython",
        "dom.html": "micropython",
        "mp.html": "micropython",
        "py.html": "pyodide",
        "pyodide.html": "pyodide",
    }
    for filename, interpreter in pages.items():
        source = (ROOT / ".site" / "pyscript" / filename).read_text()
        assert (
            f'data-configs="./{interpreter}.toml https://raw.githubusercontent.com/PyDevices/pydevices/main/pydevices-desktop.toml ./pydevices-examples.toml"'
            in source
        )
        assert '<script type="module" src="./pyscript-config.js"></script>' in source
        assert ".json" not in source.split("data-configs=")[1].split(">")[0]


def test_dynamic_discovery_is_sorted_and_excludes_init():
    source = _source()
    assert 'os.listdir("/utils/gui/demos")' in source
    assert 'filename != "__init__.py"' in source
    assert "names.sort()" in source


def test_demo_list_is_reused_across_fresh_interpreter_reloads():
    source = _source()
    assert "'peterhinch-demos-' + gui" in source
    assert "window.sessionStorage.getItem(cacheKey)" in source
    assert 'window.sessionStorage.setItem("peterhinch-demos-" + gui, signature)' in source
    assert 'if _gui_value("__hinchDemoSignature") != "\\n".join(names):' in source


def test_display_size_is_overridden_before_setup_import():
    source = _source()
    width = source.index('env_set("PYDEVICES_WIDTH", 320)')
    height = source.index('env_set("PYDEVICES_HEIGHT", 240)')
    setup_import = source.index("__import__(setup)")
    assert width < setup_import
    assert height < setup_import


def test_micro_gui_has_visible_keyboard_hint():
    source = _source()
    assert "Use the arrow keys to navigate and adjust. Press Space to select." in source
    assert "document.getElementById('control-hint').hidden = gui !== 'micro';" in source


def test_gui_name_links_to_its_upstream_repository():
    source = _source()
    assert 'id="package-link"' in source
    assert "https://github.com/peterhinch/micropython-nano-gui" in source
    assert "https://github.com/peterhinch/micropython-micro-gui" in source
    assert "https://github.com/peterhinch/micropython-touch" in source
    assert "packageLink.textContent = labels[gui];" in source
    assert "packageLink.href = repositories[gui];" in source


def test_gui_picker_is_ordered_touch_micro_nano():
    source = _source()
    touch = source.index('data-gui="touch"')
    micro = source.index('data-gui="micro"')
    nano = source.index('data-gui="nano"')
    assert touch < micro < nano


def test_console_stacks_below_canvas_and_cards_are_synchronized():
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


def test_known_incompatible_demos_are_filtered():
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


def test_selected_demo_must_be_discovered_and_supported():
    source = _source()
    assert 'if not selected:\n            _set_status("Discovering demos…")' in source
    assert "'Starting ' + demo + '…'" in source
    assert "if selected not in names:" in source
    assert "if selected in discovered:" in source
    assert "Demo is not compatible with the browser interpreter:" in source
    assert '__import__("gui.demos." + selected)' in source


def test_valid_demo_scrolls_panel_below_sticky_header():
    source = _source()
    validation = source.index("if selected not in names:")
    scroll = source.index("_scroll_to_demo_panel()", validation)
    demo_import = source.index('__import__("gui.demos." + selected)')
    assert validation < scroll < demo_import
    assert 'document.querySelector(".demo-panel")' in source
    assert 'document.querySelector(".site-header")' in source
    assert "window.scrollTo(0, max(0, int(target)))" in source


def test_gallery_regeneration_preserves_page():
    generator = (ROOT / "scripts" / "gallery_generator.py").read_text(encoding="utf-8")
    keep_html = generator.split("KEEP_HTML =", 1)[1].split("ARROW =", 1)[0]
    assert '"peterhinch"' in keep_html
