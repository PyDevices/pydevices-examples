"""Static contracts for the gallery's embedded demo workspace."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / ".site" / "pyscript" / "index.html"
CSS = ROOT / ".site" / "pyscript" / "site-extra.css"
DEMO_CSS = ROOT / ".site" / "pyscript" / "demo.css"
THEME = ROOT / ".site" / "pyscript" / "theme-toggle.js"
INTERPRETER_LAYOUT = ROOT / ".site" / "pyscript" / "interpreter-layout.js"


def test_gallery_has_sidebar_and_single_demo_frame():
    source = INDEX.read_text(encoding="utf-8")
    assert 'class="gallery-workspace"' in source
    assert 'class="gallery-sidebar"' in source
    assert source.count('id="demo-frame"') == 1
    assert 'class="gallery-preview-bar"' not in source
    assert "Selected demo</span>" not in source


def test_every_generated_demo_interpreter_can_be_embedded():
    source = INDEX.read_text(encoding="utf-8")
    generated = source.split("<!-- GEN:demos:start -->", 1)[1].split("<!-- GEN:demos:end -->", 1)[
        0
    ]
    loader_pages = {
        href.split("?", 1)[0]
        for href in re.findall(r'<a class="go" href="([^"]+)"(?! target="_blank")', generated)
    }
    allowed = set(re.findall(r"'([^']+\.html)': true", source.split("var allowedPages =", 1)[1]))
    assert loader_pages <= allowed


def test_every_nochrome_card_uses_compact_interpreter_pages():
    source = INDEX.read_text(encoding="utf-8")
    generated = source.split("<!-- GEN:demos:start -->", 1)[1].split("<!-- GEN:demos:end -->", 1)[
        0
    ]
    cards = re.findall(r'<article class="card">(.*?)</article>', generated, re.DOTALL)
    nochrome_cards = [card for card in cards if '<span class="tag">nochrome</span>' in card]
    assert nochrome_cards
    for card in nochrome_cards:
        hrefs = re.findall(r'<a class="go" href="([^"]+)"', card)
        assert len(hrefs) == 2
        assert hrefs[0].startswith("mp.html?")
        assert hrefs[1].startswith("py.html?")
        assert not any(href.startswith(("micropython.html?", "pyodide.html?")) for href in hrefs)
        assert card.count('target="_blank" rel="noopener"') == 2


def test_nochrome_links_bypass_embedded_preview():
    source = INDEX.read_text(encoding="utf-8")
    assert "'mp.html': true" not in source
    assert "'py.html': true" not in source
    assert "if (link.target === '_blank')" in source


def test_selection_is_bookmarkable_and_preserves_modifier_clicks():
    source = INDEX.read_text(encoding="utf-8")
    assert "parent.searchParams.set('run', selected.relative)" in source
    assert "window.history.pushState" in source
    assert "window.addEventListener('popstate'" in source
    assert "event.metaKey" in source
    assert "event.ctrlKey" in source


def test_selected_card_is_kept_inside_list_viewport():
    source = INDEX.read_text(encoding="utf-8")
    assert "function revealSelectedCard()" in source
    assert "sidebar.querySelector('.card.is-active')" in source
    assert "var sidebarRect = sidebar.getBoundingClientRect();" in source
    assert "var cardRect = card.getBoundingClientRect();" in source
    assert "sidebar.scrollTop = Math.max(" in source
    assert "requestAnimationFrame(revealSelectedCard)" in source


def test_gallery_layout_keeps_sidebar_beside_preview_until_mobile():
    css = CSS.read_text(encoding="utf-8")
    assert "grid-template-columns: minmax(300px, 1fr) fit-content(100%);" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(184px, 1fr));" in css
    assert ".gallery-sidebar" in css
    assert ".gallery-preview" in css
    assert "@media (max-width: 760px)" in css


def test_mobile_gallery_uses_autohiding_app_drawer():
    source = INDEX.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'id="gallery-drawer-toggle"' in source
    assert 'id="gallery-drawer-scrim"' in source
    assert "setDrawerOpen(false)" in source
    assert "event.key === 'Escape'" in source
    assert ".gallery-sidebar.is-open" in css
    assert "transform: translateX(-105%);" in css
    assert "<h2>Apps</h2>" in source
    assert "a curated list from <code>lib/examples/</code>" in source
    assert ">Select</button>" in source


def test_apps_heading_links_to_peter_hinch_collection():
    source = INDEX.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert 'class="gallery-collection-link"' in source
    assert 'href="./peterhinch.html?touch"' in source
    assert "Peter Hinch GUI demos" in source
    assert ".gallery-collection-link" in css


def test_interpreter_loaders_show_two_cards_and_autorun():
    for name in ("micropython.html", "pyodide.html"):
        source = (ROOT / ".site" / "pyscript" / name).read_text(encoding="utf-8")
        assert 'class="interpreter-page"' in source
        assert 'id="run-btn"' not in source
        assert 'class="device"' in source
        assert 'class="console-panel"' in source
        assert "def _start():" in source
        assert "            _start()" in source
        assert 'addEventListener("click"' not in source


def test_interpreter_loaders_set_browser_defaults_without_importing_board():
    loader = (ROOT / "lib" / "utils" / "ps_loader.py").read_text(encoding="utf-8")
    assert "BOARD_WIDTH = 320" in loader
    assert "BOARD_HEIGHT = 480" in loader
    assert 'env_set("PYDEVICES_WIDTH", BOARD_WIDTH)' in loader
    assert 'env_set("PYDEVICES_HEIGHT", BOARD_HEIGHT)' in loader
    for name in ("micropython.html", "pyodide.html", "mp.html", "py.html"):
        source = (ROOT / ".site" / "pyscript" / name).read_text(encoding="utf-8")
        assert "ps_loader.set_board_defaults()" in source
        assert "import board_config" not in source


def test_car_cluster_forces_its_browser_resolution():
    source = (ROOT / "lib" / "examples" / "car_cluster" / "car_cluster.py").read_text(
        encoding="utf-8"
    )
    assert 'env_set("PYDEVICES_WIDTH", "1024")' in source
    assert 'env_set("PYDEVICES_HEIGHT", "512")' in source
    assert 'if env_get("PYDEVICES_WIDTH")' not in source
    assert 'if env_get("PYDEVICES_HEIGHT")' not in source


def test_pixel_sim_demo_rotates_portrait_displays_before_layout():
    source = (ROOT / "lib" / "examples" / "pixel_sim_demos.py").read_text(encoding="utf-8")
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


def test_pyscript_loader_silences_installer_file_chatter():
    loader = (ROOT / "lib" / "utils" / "ps_loader.py").read_text(encoding="utf-8")
    assert "def _quiet_install(" in loader
    assert 'had_printer = hasattr(mip_mod, "print")' in loader
    assert "mip_mod.print = lambda *args, **print_kwargs: None" in loader
    assert 'delattr(mip_mod, "print")' in loader
    assert "_quiet_install(mip_mod, module_url(name), target=MANIFEST_MIP_TARGET)" in loader
    assert "_quiet_install(mip_mod, manifest_url(name), **manifest_kw)" in loader


def test_gallery_uses_local_theme_toggle_and_syncs_the_frame():
    source = INDEX.read_text(encoding="utf-8")
    theme = THEME.read_text(encoding="utf-8")
    assert 'id="pydevices-site-header"' in source
    assert 'id="pydevices-site-footer"' in source
    assert '<script src="./site-chrome.js"></script>' in source
    assert '<script src="./theme-toggle.js"></script>' in source
    assert 'id="pwa-install-btn"' not in source
    assert 'id="interpreter-toggle"' not in source
    assert "applyThemeToFrames(next)" in theme
    assert 'document.querySelectorAll("iframe")' in theme
    assert "img/logo.svg" in source


def test_interpreter_frame_and_sidebar_follow_content_height():
    source = INDEX.read_text(encoding="utf-8")
    layout = INTERPRETER_LAYOUT.read_text(encoding="utf-8")
    assert 'scrolling="no"' in source
    assert "frame.style.height = Math.ceil(height) + 'px'" in source
    assert "frame.style.width = width + 'px'" in source
    assert "sidebar.style.height = !mobile && height > 0" in source
    assert 'panel.style.width = width + "px"' in layout
    assert 'panel.style.height = height + "px"' in layout
    assert "width: width" in layout
    assert "Math.ceil(main.getBoundingClientRect().bottom)" in layout


def test_interpreter_cards_use_compact_outer_padding():
    css = DEMO_CSS.read_text(encoding="utf-8")
    assert "padding: 6px 8px 16px;" in css
    assert "padding: 16px 9px 6px;" in css
    assert "padding-top: 0;" in css
    assert "padding-bottom: 0;" in css


def test_standalone_interpreter_uses_side_by_side_height_tracking():
    css = DEMO_CSS.read_text(encoding="utf-8")
    layout = INTERPRETER_LAYOUT.read_text(encoding="utf-8")
    assert ".interpreter-page.interpreter-standalone.interpreter-with-console .play-area" in css
    assert "grid-template-columns: auto auto;" in css
    assert "var standalone = window.parent === window;" in layout
    assert "if (lastWidth < 0)" in layout
    assert "if (height !== lastHeight)" in layout


def test_console_is_opt_in_and_gallery_leaves_it_hidden():
    index = INDEX.read_text(encoding="utf-8")
    layout = INTERPRETER_LAYOUT.read_text(encoding="utf-8")
    for name in ("micropython.html", "pyodide.html"):
        source = (ROOT / ".site" / "pyscript" / name).read_text(encoding="utf-8")
        assert 'class="console-toggle"' in source
        assert 'class="device-footer"' in source
    assert 'get("console") === "true"' in layout
    assert 'toggle.textContent = visible ? "Hide console" : "Show console"' in layout
    assert "url.searchParams.set('console', 'true')" not in index
    assert "frame.src = selected.relative" in index
