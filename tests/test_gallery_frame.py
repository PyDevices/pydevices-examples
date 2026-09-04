"""Static contracts for the gallery's embedded demo workspace.

The gallery is ``.site/gallery/`` and runs on the direct-WebAssembly host
(``gallery-host.js``). It used to be ``.site/pyscript/`` on PyScript, and the
assertions that described *that* plumbing -- ``micropython.html`` under
``pyscript/``, the inline ``_start()`` autorun, one card carrying two loader
links -- have been restated against the host that replaced it. The Pyodide
loader pages still ship as the gallery's alternative runtime, so what they
still promise is kept. Everything describing what a visitor gets is unchanged.

This is a ``unittest.TestCase`` on purpose: the documented gate
(``python -m unittest discover -s tests``) never collected the module-level
``test_*`` functions this file used to hold, so its failures only ever showed
under pytest.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / ".site" / "gallery"
PYSCRIPT = ROOT / ".site" / "pyscript"

INDEX = GALLERY / "index.html"
LOADER = GALLERY / "micropython.html"
COMPACT_LOADER = GALLERY / "mp.html"
HOST = GALLERY / "gallery-host.js"
PYODIDE_LOADER = PYSCRIPT / "pyodide.html"
PYODIDE_COMPACT_LOADER = PYSCRIPT / "py.html"

# Shared assets the gallery pages load from ../pyscript/.
CSS = PYSCRIPT / "gallery.css"
DEMO_CSS = PYSCRIPT / "demo.css"
THEME = PYSCRIPT / "theme-toggle.js"
INTERPRETER_LAYOUT = PYSCRIPT / "interpreter-layout.js"

NOCHROME_TAG = '<span class="tag">nochrome</span>'


def _read(path):
    return path.read_text(encoding="utf-8")


def _generated_cards(source):
    """Return ``(href, extra_attrs, body)`` for every generated gallery card."""
    generated = source.split("<!-- GEN:demos:start -->", 1)[1].split("<!-- GEN:demos:end -->", 1)[
        0
    ]
    return re.findall(r'<a class="card" href="([^"]+)"([^>]*)>(.*?)</a>', generated, re.DOTALL)


class TestGalleryFrame(unittest.TestCase):
    def test_gallery_has_sidebar_and_single_demo_frame(self):
        source = _read(INDEX)
        assert 'class="gallery-workspace"' in source
        assert 'class="gallery-sidebar"' in source
        assert source.count('id="demo-frame"') == 1
        assert 'class="gallery-preview-bar"' not in source
        assert "Selected demo</span>" not in source

    def test_every_generated_demo_interpreter_can_be_embedded(self):
        """A card that stays inside the gallery must point at a page the frame
        allow-list accepts and that exists beside the gallery, or the click is
        swallowed by ``demoUrl`` / the frame 404s. (This used to grep
        ``<a class="go">``, which no card has carried since the card became the
        link, and passed on an empty set.)"""
        source = _read(INDEX)
        cards = _generated_cards(source)
        assert cards
        embedded = {
            href.split("?", 1)[0] for href, attrs, _ in cards if 'target="_blank"' not in attrs
        }
        assert embedded
        allowed = set(
            re.findall(r"'([^']+\.html)': true", source.split("var allowedPages =", 1)[1])
        )
        assert embedded <= allowed
        for page in embedded:
            assert (GALLERY / page).is_file()

    def test_new_window_cards_keep_the_chrome_unless_nochrome(self):
        """Where a demo opens and what it looks like are separate choices.

        ``# gallery: newwindow`` opens the full ``micropython.html`` page --
        org chrome and all -- in its own tab, for demos too large to read
        beside the cards. ``# gallery: nochrome`` opens the bare ``mp.html``
        shell instead. Everything else embeds ``micropython.html`` in the
        gallery's preview. Each card is one link for the gallery's own runtime;
        the Pyodide pairing lives in the sibling PyScript gallery."""
        cards = _generated_cards(_read(INDEX))
        assert cards
        new_tab = [(href, body) for href, attrs, body in cards if 'target="_blank"' in attrs]
        embedded = [(href, attrs) for href, attrs, _ in cards if 'target="_blank"' not in attrs]
        assert new_tab, "no demo opens in its own tab"
        assert embedded
        for href, body in new_tab:
            expected = "mp.html?" if NOCHROME_TAG in body else "micropython.html?"
            assert href.startswith(expected), f"{href} should start with {expected}"
        for href, attrs in embedded:
            assert href.startswith("micropython.html?")
            assert attrs == ""

    def test_nochrome_links_bypass_embedded_preview(self):
        source = _read(INDEX)
        assert "'mp.html': true" not in source
        assert "'py.html': true" not in source
        assert "if (link.target === '_blank')" in source

    def test_selection_is_bookmarkable_and_preserves_modifier_clicks(self):
        source = _read(INDEX)
        assert "parent.searchParams.set('run', selected.relative)" in source
        assert "window.history.pushState" in source
        assert "window.addEventListener('popstate'" in source
        assert "event.metaKey" in source
        assert "event.ctrlKey" in source

    def test_selected_card_is_kept_inside_list_viewport(self):
        source = _read(INDEX)
        assert "function revealSelectedCard()" in source
        assert "sidebar.querySelector('.card.is-active')" in source
        assert "var sidebarRect = sidebar.getBoundingClientRect();" in source
        assert "var cardRect = card.getBoundingClientRect();" in source
        assert "sidebar.scrollTop = Math.max(" in source
        assert "requestAnimationFrame(revealSelectedCard)" in source

    def test_gallery_layout_keeps_sidebar_beside_preview_until_mobile(self):
        # Bind the assertions to the stylesheet the page actually links.
        assert '<link rel="stylesheet" href="../pyscript/gallery.css">' in _read(INDEX)
        css = _read(CSS)
        assert "grid-template-columns: minmax(300px, 1fr) fit-content(100%);" in css
        assert "grid-template-columns: repeat(auto-fit, minmax(184px, 1fr));" in css
        assert ".gallery-sidebar" in css
        assert ".gallery-preview" in css
        assert "@media (max-width: 760px)" in css

    def test_mobile_gallery_uses_autohiding_app_drawer(self):
        source = _read(INDEX)
        css = _read(CSS)
        assert 'id="gallery-drawer-toggle"' in source
        assert 'id="gallery-drawer-scrim"' in source
        assert "setDrawerOpen(false)" in source
        assert "event.key === 'Escape'" in source
        assert ".gallery-sidebar.is-open" in css
        assert "transform: translateX(-105%);" in css
        assert "<h2>Apps</h2>" in source
        assert "a curated list from <code>lib/examples/</code>" in source
        assert ">Select</button>" in source

    def test_apps_heading_links_to_peter_hinch_collection(self):
        source = _read(INDEX)
        css = _read(CSS)
        assert 'class="gallery-collection-link"' in source
        assert 'href="./peterhinch.html?touch"' in source
        assert "Peter Hinch GUI demos" in source
        assert ".gallery-collection-link" in css

    def test_interpreter_loaders_show_two_cards_and_autorun(self):
        """The loader page shows the device and console cards and runs the demo
        as soon as the runtime is up -- there is no Run button. On the wasm host
        the autorun is ``gallery-host.js`` booting at import and importing the
        entry module; the Pyodide loader still autoruns through its inline
        ``_start()``."""
        for page in (LOADER, PYODIDE_LOADER):
            source = _read(page)
            assert 'class="interpreter-page"' in source
            assert 'id="run-btn"' not in source
            assert 'class="device"' in source
            assert 'class="console-panel"' in source
            assert 'addEventListener("click"' not in source
        assert '<script type="module" src="./gallery-host.js"></script>' in _read(LOADER)
        host = _read(HOST)
        assert "await boot();" in host
        assert "__import__(${pythonLiteral(plan.entry)})" in host
        pyodide = _read(PYODIDE_LOADER)
        assert "def _start():" in pyodide
        assert "            _start()" in pyodide

    def test_interpreter_loaders_set_browser_defaults_without_importing_board(self):
        """No loader page imports ``board_config`` itself -- the app does, once
        the board package is installed. The Pyodide pages take their 320x480
        default from ``ps_loader``; the wasm pages only declare the canvas the
        host attaches to (``WasmDisplay`` raises without it) and leave
        installing ``pydevices-desktop`` to ``gallery-host.js``."""
        loader = _read(ROOT / "lib" / "utils" / "ps_loader.py")
        assert "BOARD_WIDTH = 320" in loader
        assert "BOARD_HEIGHT = 480" in loader
        assert 'env_set("PYDEVICES_WIDTH", BOARD_WIDTH)' in loader
        assert 'env_set("PYDEVICES_HEIGHT", BOARD_HEIGHT)' in loader
        for page in (PYODIDE_LOADER, PYODIDE_COMPACT_LOADER):
            source = _read(page)
            assert "ps_loader.set_board_defaults()" in source
            assert "import board_config" not in source
        for page in (LOADER, COMPACT_LOADER):
            source = _read(page)
            assert '<canvas id="display_canvas"' in source
            assert "board_config" not in source
        host = _read(HOST)
        assert 'mip.install("pydevices-desktop"' in host
        assert "board_config" not in host

    def test_car_cluster_forces_its_browser_resolution(self):
        source = _read(ROOT / "lib" / "examples" / "car_cluster" / "car_cluster.py")
        assert 'env_set("PYDEVICES_WIDTH", "1024")' in source
        assert 'env_set("PYDEVICES_HEIGHT", "512")' in source
        assert 'if env_get("PYDEVICES_WIDTH")' not in source
        assert 'if env_get("PYDEVICES_HEIGHT")' not in source

    def test_pixel_sim_demo_rotates_portrait_displays_before_layout(self):
        source = _read(ROOT / "lib" / "examples" / "pixel_sim_demos.py")
        orientation = source.index(
            "if _host_board.display_drv.width < _host_board.display_drv.height:"
        )
        simulator = source.index("from pixel_sim import display_drv, app")
        grid_size = source.index("GRID_W = display_drv.width")
        assert orientation < simulator < grid_size
        assert (
            "_host_board.display_drv.rotation = (_host_board.display_drv.rotation + 90) % 360"
            in source
        )

    def test_pyscript_loader_silences_installer_file_chatter(self):
        loader = _read(ROOT / "lib" / "utils" / "ps_loader.py")
        assert "def _quiet_install(" in loader
        assert 'had_printer = hasattr(mip_mod, "print")' in loader
        assert "mip_mod.print = lambda *args, **print_kwargs: None" in loader
        assert 'delattr(mip_mod, "print")' in loader
        assert "_quiet_install(mip_mod, module_url(name), target=MANIFEST_MIP_TARGET)" in loader
        assert "_quiet_install(mip_mod, manifest_url(name), **manifest_kw)" in loader

    def test_gallery_uses_local_theme_toggle_and_syncs_the_frame(self):
        source = _read(INDEX)
        theme = _read(THEME)
        assert 'id="pydevices-site-header"' in source
        assert 'id="pydevices-site-footer"' in source
        assert '<script src="../pyscript/site-chrome.js"></script>' in source
        assert '<script src="../pyscript/theme-toggle.js"></script>' in source
        assert 'id="pwa-install-btn"' not in source
        assert 'id="interpreter-toggle"' not in source
        assert "applyThemeToFrames(next)" in theme
        assert 'document.querySelectorAll("iframe")' in theme
        assert "img/logo.svg" in source

    def test_interpreter_frame_and_sidebar_follow_content_height(self):
        source = _read(INDEX)
        layout = _read(INTERPRETER_LAYOUT)
        assert 'scrolling="no"' in source
        assert "frame.style.height = Math.ceil(height) + 'px'" in source
        assert "frame.style.width = width + 'px'" in source
        assert "sidebar.style.height = !mobile && height > 0" in source
        assert 'panel.style.width = width + "px"' in layout
        assert 'panel.style.height = height + "px"' in layout
        assert "width: width" in layout
        assert "Math.ceil(main.getBoundingClientRect().bottom)" in layout

    def test_interpreter_cards_use_compact_outer_padding(self):
        """The bezel keeps 16px above the canvas -- 6px clipped the 22px corner
        radius against it (1f161c9e). The console card and the page's own
        vertical padding stay trimmed."""
        assert '<link rel="stylesheet" href="../pyscript/demo.css">' in _read(LOADER)
        css = _read(DEMO_CSS)
        assert ".interpreter-page .device {\n  padding: 16px 8px 16px;\n}" in css
        assert ".interpreter-page .console-panel {\n  padding: 16px 9px 6px;\n}" in css
        loader_main = css.split(".interpreter-page .loader-main {", 1)[1].split("}", 1)[0]
        assert "padding-top: 0;" in loader_main
        assert "padding-bottom: 0;" in loader_main

    def test_standalone_interpreter_uses_side_by_side_height_tracking(self):
        css = _read(DEMO_CSS)
        layout = _read(INTERPRETER_LAYOUT)
        assert (
            ".interpreter-page.interpreter-standalone.interpreter-with-console .play-area" in css
        )
        assert "grid-template-columns: auto auto;" in css
        assert "var standalone = window.parent === window;" in layout
        assert "if (lastWidth < 0)" in layout
        assert "if (height !== lastHeight)" in layout

    def test_console_is_opt_in_and_gallery_leaves_it_hidden(self):
        index = _read(INDEX)
        layout = _read(INTERPRETER_LAYOUT)
        for page in (LOADER, PYODIDE_LOADER):
            source = _read(page)
            assert 'class="console-toggle"' in source
            assert 'class="device-footer"' in source
            # The toggle is inert unless the page also loads the layout script.
            assert re.search(r'<script src="[^"]*interpreter-layout\.js[^"]*"></script>', source)
        assert 'get("console") === "true"' in layout
        assert 'toggle.textContent = visible ? "Hide console" : "Show console"' in layout
        assert "url.searchParams.set('console', 'true')" not in index
        assert "frame.src = selected.relative" in index


if __name__ == "__main__":
    unittest.main()
