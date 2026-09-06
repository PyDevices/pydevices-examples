#!/usr/bin/env python3
"""
gallery_generator.py — refresh the pydevices-examples direct-WASM browser gallery.

Default-includes every example **entry point** under ``lib/examples/``:

  - ``examples/<name>.py`` — single-file module
  - ``examples/<name>/<name>.py`` — package (preferred over ``__init__.py``)
  - ``examples/<name>/__init__.py`` — package when no ``<name>.py`` entry

Optional headers (first 10 lines), one line per namespace::

  # deps: palettes, lvgl          — logical packages → ?deps= via url_maker
  # utils: console, tft_config  — pydevices-examples utils modules (shown as badges)
  # modules: calc_engine          — extra example .py stems (site)
  # manifests: alien              — site-served packages/<name>.json bundles
  # gallery: featured|skip|binaries|nochrome|newwindow  (comma-separated)

MIP manifests for package examples live in ``packages/<name>.json`` (generated
by ``scripts/install_gen_manifests.py``). The direct host loads them from the
deployed gallery tree as ``?manifests=<name>``.

``# gallery: newwindow`` keeps the full ``micropython.html`` / ``pyodide.html``
pages, with the org chrome, but opens them in a new tab instead of the
gallery's embedded preview — for demos too large to read beside the cards.
``# gallery: nochrome`` also opens a new tab but links the minimal ``mp.html``
/ ``py.html`` shells, which carry no chrome at all. The two are separate
choices: new tab is about where the demo opens, chrome is about what it looks
like when it gets there. Values combine, so ``featured, newwindow`` is valid.

Then:

  - Updates gallery cards in ``.site/gallery/index.html`` (``GEN:demos`` markers)
  - Writes ``.site/gallery/python-files.json`` for explicit Python-only staging
  - Enforces shared org chrome mounts via ``ensure_site_chrome``
  - Deletes stale ``.site/gallery/*.html`` from the old per-demo page generator

Each card links direct MicroPython only (the gallery's one supported runtime)
with queries from pydevices' shared private URL policy. Hinch GUIs are not listed in headers — ``fetch_ph_gui``
installs them at runtime via color/hardware/touch setup.

    python scripts/gallery_generator.py
    python scripts/gallery_generator.py --check
    python scripts/gallery_generator.py --copy-examples DIR
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

_scripts = Path(__file__).resolve().parent
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))
from personal_examples import PERSONAL_EXAMPLE_DIRS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
_browser_tools = next(
    path
    for path in (
        REPO_ROOT.parent / "pydevices" / "tools",
        REPO_ROOT / "pydevices" / "tools",
    )
    if (path / "_browser_url.py").is_file()
)
sys.path.insert(0, str(_browser_tools))
from _browser_url import query as browser_query  # noqa: E402

EXAMPLES_DIR = REPO_ROOT / "lib" / "examples"
GALLERY_DIR = REPO_ROOT / ".site" / "gallery"
INDEX = GALLERY_DIR / "index.html"
PYSCRIPT_DIR = REPO_ROOT / ".site" / "pyscript"
PYSCRIPT_INDEX = PYSCRIPT_DIR / "index.html"
THUMBNAILS_DIR = PYSCRIPT_DIR / "thumbnails"
PYTHON_FILES = GALLERY_DIR / "python-files.json"
SCREENSHOT_TOOL = REPO_ROOT / "tools" / "screenshot.py"

KEEP_HTML = frozenset(
    {
        "index",
        "micropython",
        "repl",
        "editor",
        "async",
        "dom",
        "harness",
        "pyodide",
        "mp",
        "py",
        "peterhinch",
    }
)

GENERIC_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>'
)

HEADER_SCAN_LINES = 10
GALLERY_VALUES = frozenset({"featured", "skip", "binaries", "nochrome", "newwindow"})
INSTALLABLE_DEPS = frozenset(
    {"palettes", "pygraphics", "pdwidgets", "audioinstruments", "audioeffects"}
)

LOCAL_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
    re.MULTILINE,
)


class Example:
    """One browser-gallery demo discovered from ``lib/examples/``."""

    def __init__(self, name: str, source_rel: str, kind: str):
        self.name = name
        self.source_rel = source_rel
        self.kind = kind  # "module" | "manifest"
        self.docstring_blurb = ""
        self.extra_modules: list[str] = []
        self.extra_manifests: list[str] = []
        self.deps: list[str] = []
        self.utils: list[str] = []
        self.pyscript_files: list[str] = []
        self.featured = False
        self.nochrome = False
        self.new_window = False
        self.in_gallery = True

    @property
    def title(self) -> str:
        return self.name.replace("_", " ").title()

    @property
    def blurb(self) -> str:
        return (
            self.docstring_blurb
            or f"The <code>{self.name}</code> demo running in the browser via PyScript."
        )

    def _modules_for_query(self) -> tuple[str, ...]:
        if self.kind == "module":
            stems = [Path(path).stem for path in self.pyscript_files]
            # Ensure header extras are present even if discover missed them.
            for stem in self.extra_modules:
                if stem not in stems:
                    stems.append(stem)
            return tuple(stems)
        # Manifest entry: optional extra single-file modules alongside the package.
        return tuple(self.extra_modules)

    def _manifests_for_query(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.kind == "manifest":
            names.append(self.name)
        for name in self.extra_manifests:
            if name not in names:
                names.append(name)
        return tuple(names)

    def loader_queries(self) -> dict[str, str]:
        values = {
            "modules": self._modules_for_query(),
            "manifests": self._manifests_for_query(),
            "deps": self.deps,
        }
        return {
            runtime: browser_query(runtime=runtime, **values) for runtime in ("wasm", "pyodide")
        }

    def loader_hrefs(self) -> dict[str, str]:
        queries = self.loader_queries()
        if self.nochrome:
            return {
                "micropython": f"mp.html{queries['wasm']}",
                "pyodide": f"../pyscript/py.html{queries['pyodide']}",
            }
        return {
            "micropython": f"micropython.html{queries['wasm']}",
            "pyodide": f"../pyscript/pyodide.html{queries['pyodide']}",
        }


def parse_header_list(lines: list[str], prefix: str) -> list[str]:
    """Return comma list for ``# prefix: a, b`` (prefix includes trailing colon sense)."""
    want = prefix if prefix.endswith(":") else prefix + ":"
    for line in lines[:HEADER_SCAN_LINES]:
        s = line.strip()
        if s.startswith(want):
            body = s.split(":", 1)[1].strip()
            return [part.strip() for part in body.split(",") if part.strip()]
    return []


def parse_gallery_values(lines: list[str]) -> set[str]:
    """Return the declared ``# gallery:`` values, or an empty set.

    Comma-separated, because the choices are independent: ``featured`` is
    prominence, ``newwindow`` is where the demo opens, ``nochrome`` is which
    shell it opens. ``featured, newwindow`` is the combination a large hero
    demo wants.
    """
    for line in lines[:HEADER_SCAN_LINES]:
        s = line.strip()
        if not s.startswith("# gallery:"):
            continue
        body = s.split(":", 1)[1].strip().lower()
        if not body:
            return set()
        tokens = {t.strip() for t in body.split(",") if t.strip()}
        unknown = tokens - GALLERY_VALUES
        if unknown:
            raise SystemExit(
                f"invalid # gallery: value(s) {sorted(unknown)!r} "
                f"(want {'|'.join(sorted(GALLERY_VALUES))})"
            )
        return tokens
    return set()


def _py_sort_key(rel: str) -> tuple:
    parts = rel.split("/")
    name = parts[-1]
    init_first = 0 if name == "__init__.py" else 1
    return (parts[:-1], init_first, name)


def discover_package_py_files(name: str) -> list[str]:
    pkg_dir = EXAMPLES_DIR / name
    if not pkg_dir.is_dir():
        raise SystemExit(f"examples/{name}: package directory missing")
    paths: list[str] = []
    for path in sorted(pkg_dir.rglob("*.py")):
        rel = path.relative_to(EXAMPLES_DIR).as_posix()
        paths.append(rel)
    return sorted(paths, key=_py_sort_key)


def discover_local_py_imports(entry_path: Path, text: str) -> list[str]:
    """Same-directory modules and ``examples/<pkg>/`` packages imported by entry."""
    found: list[str] = []
    seen: set[str] = set()
    parent = entry_path.parent

    def add(rel: str) -> None:
        if rel not in seen:
            seen.add(rel)
            found.append(rel)

    for match in LOCAL_IMPORT_RE.finditer(text):
        mod = match.group(1) or match.group(2)
        if not mod or mod.startswith("."):
            continue
        top = mod.split(".")[0]
        same_dir = parent / f"{top}.py"
        if same_dir.is_file():
            add(same_dir.relative_to(EXAMPLES_DIR).as_posix())
            continue
        pkg_init = EXAMPLES_DIR / top / "__init__.py"
        if pkg_init.is_file():
            add(pkg_init.relative_to(EXAMPLES_DIR).as_posix())
    return found


def normalize_py_path(raw: str) -> str:
    return raw if raw.endswith(".py") else f"{raw}.py"


def finalize_py_files(py_files: list[str], entry_rel: str) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    if entry_rel in py_files:
        ordered.append(entry_rel)
        seen.add(entry_rel)
    for rel in sorted(py_files, key=_py_sort_key):
        if rel not in seen:
            ordered.append(rel)
            seen.add(rel)
    return ordered


def resolve_py_files(path: Path, kind: str, name: str, lines: list[str], text: str) -> list[str]:
    extra_modules = parse_header_list(lines, "# modules:")
    entry_rel = path.relative_to(EXAMPLES_DIR).as_posix()

    if kind == "manifest":
        return discover_package_py_files(name)

    py_files = [entry_rel]
    py_files.extend(discover_local_py_imports(path, text))
    for raw in extra_modules:
        rel = normalize_py_path(raw)
        if rel not in py_files:
            py_files.append(rel)
    return finalize_py_files(py_files, entry_rel)


def extract_blurb(text: str, name: str) -> str:
    start = None
    for q in ('"""', "'''"):
        i = text.find(q)
        if i != -1 and (start is None or i < start[0]):
            start = (i, q)
    if not start:
        return ""
    i, q = start
    end = text.find(q, i + 3)
    if end == -1:
        return ""
    doc = text[i + 3 : end]
    skip = {name, f"{name}.py", "=" * len(name)}
    for raw in doc.splitlines():
        line = raw.strip()
        if not line or line in skip or set(line) <= {"=", "-", "~"}:
            continue
        if line.startswith((".. ", ":", "-", "*", "https://", "http://")):
            continue
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return line[:160]
    return ""


def classify_entry(path: Path) -> tuple[str, str] | None:
    """Return ``(name, kind)`` for a gallery entry path, or None if not an entry."""
    try:
        rel = path.relative_to(EXAMPLES_DIR)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) == 1 and parts[0].endswith(".py"):
        return path.stem, "module"
    if len(parts) == 2 and parts[1] == f"{parts[0]}.py":
        return parts[0], "manifest"
    if len(parts) == 2 and parts[1] == "__init__.py":
        return parts[0], "manifest"
    return None


def entry_priority(path: Path) -> int:
    """Lower sorts first: ``<name>.py`` preferred over ``__init__.py`` for packages."""
    if path.name == "__init__.py":
        return 1
    return 0


def parse_example(path: Path) -> Example | None:
    classified = classify_entry(path)
    if classified is None:
        return None
    name, kind = classified

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    rel = path.relative_to(REPO_ROOT).as_posix()
    ex = Example(name, rel, kind)
    gallery = parse_gallery_values(lines)
    ex.in_gallery = not (gallery & {"skip", "binaries"})
    ex.featured = "featured" in gallery
    ex.nochrome = "nochrome" in gallery
    # A bare shell is only reachable in its own tab, so nochrome implies it.
    ex.new_window = "newwindow" in gallery or ex.nochrome
    ex.docstring_blurb = extract_blurb(text, name)
    ex.extra_modules = parse_header_list(lines, "# modules:")
    ex.extra_manifests = parse_header_list(lines, "# manifests:")
    ex.deps = parse_header_list(lines, "# deps:")
    ex.utils = parse_header_list(lines, "# utils:")
    ex.pyscript_files = resolve_py_files(path, kind, name, lines, text)
    for entry in ex.pyscript_files:
        if not (EXAMPLES_DIR / entry).is_file():
            raise SystemExit(f"{rel}: missing pyscript file {entry}")
    return ex


def _is_personal_example(path: Path) -> bool:
    try:
        rel = path.relative_to(EXAMPLES_DIR)
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in PERSONAL_EXAMPLE_DIRS


def example_py_files() -> list[Path]:
    """Candidate entry ``*.py`` under ``lib/examples/``, excluding personal trees."""
    paths: list[Path] = []
    seen: set[str] = set()
    for path in sorted(EXAMPLES_DIR.rglob("*.py")):
        if _is_personal_example(path):
            continue
        if classify_entry(path) is None:
            continue
        paths.append(path)
        seen.add(str(path))
    for child in sorted(EXAMPLES_DIR.iterdir()):
        if child.name in PERSONAL_EXAMPLE_DIRS:
            continue
        if child.is_symlink():
            for path in sorted(child.rglob("*.py")):
                if _is_personal_example(path):
                    continue
                if classify_entry(path) is None:
                    continue
                key = str(path)
                if key not in seen:
                    paths.append(path)
                    seen.add(key)
    return paths


def discover() -> list[Example]:
    """One Example per name; prefer ``<name>.py`` over ``__init__.py``."""
    by_name: dict[str, list[Path]] = {}
    for path in example_py_files():
        classified = classify_entry(path)
        if classified is None:
            continue
        name, _kind = classified
        by_name.setdefault(name, []).append(path)

    found: list[Example] = []
    for name, paths in sorted(by_name.items()):
        named = [p for p in paths if p.name == f"{name}.py"]
        primary = named[0] if named else sorted(paths, key=entry_priority)[0]
        ex = parse_example(primary)
        if ex:
            found.append(ex)
    return found


def imported_top_level_modules(ex: Example) -> set[str]:
    """Return imports from every Python file shipped for an example."""
    imported: set[str] = set()
    for rel in ex.pyscript_files:
        path = EXAMPLES_DIR / rel
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
    return imported


def validate_example_deps(examples: list[Example]) -> None:
    """Reject missing installable deps and warn about unused declarations."""
    errors: list[str] = []
    for ex in examples:
        imported = imported_top_level_modules(ex)
        missing = sorted((imported & INSTALLABLE_DEPS) - set(ex.deps))
        if missing:
            errors.append(f"{ex.source_rel}: missing # deps: {', '.join(missing)}")
        unused = sorted(set(ex.deps) - imported)
        if unused:
            print(
                f"warning: {ex.source_rel}: declared # deps not imported: {', '.join(unused)}",
                file=sys.stderr,
            )
    if errors:
        raise SystemExit("gallery dependency errors:\n  " + "\n  ".join(errors))


# Package deps that are also top-level PyDevices org repos get that repo's
# real ecosystem tier (see .site/pyscript/site-chrome.js ECOSYSTEM_DATA).
# appdev and multimer ship inside pydevices' own lib/, so they take its tier.
_DEP_TIER = {
    "audioif": 2,
    "pygraphics": 2,
    "pdwidgets": 2,
    "palettes": 2,
    "lvgl": 3,
    "appdev": 1,
    "multimer": 1,
}


def _badge_tier(name: str) -> int:
    """A stable tier (1-5) for a badge, reusing the org's tier color palette.

    Deps that map to a real org repo get that repo's tier; everything else
    (utils modules, unknown deps) gets a deterministic pick across the same
    five tier colors so each distinct tag still keeps its own color.
    """
    if name in _DEP_TIER:
        return _DEP_TIER[name]
    return sum(map(ord, name)) % 5 + 1


def _render_badges(ex: Example) -> str:
    """Render deps and utils as colored badge spans next to the card tag."""
    parts: list[str] = []
    for dep in ex.deps:
        parts.append(f'<span class="badge dep tag-tier-{_badge_tier(dep)}">{dep}</span>')
    for util in ex.utils:
        parts.append(f'<span class="badge util tag-tier-{_badge_tier(util)}">{util}</span>')
    if not parts:
        return ""
    return "\n                        " + "\n                        ".join(parts)


def thumbnail_path(ex: Example) -> Path:
    return THUMBNAILS_DIR / f"{ex.name}.png"


def generate_missing_thumbnails(examples: list[Example]) -> tuple[int, int]:
    """Capture missing gallery thumbnails; return ``(created, failed)``."""
    created = 0
    failed = 0
    for ex in examples:
        output = thumbnail_path(ex)
        if not ex.in_gallery or output.exists():
            continue
        command = [
            sys.executable,
            str(SCREENSHOT_TOOL),
            str(REPO_ROOT / ex.source_rel),
            "--delay",
            "2",
            "--resolution",
            "240x320",
            "--scale",
            "0.5",
            "--output",
            str(output),
        ]
        print(f"capturing thumbnail for {ex.name}...")
        try:
            result = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failed += 1
            print(f"warning: thumbnail timed out for {ex.name}", file=sys.stderr)
            continue
        if result.returncode == 0 and output.exists():
            created += 1
            continue
        failed += 1
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit {result.returncode}"
        print(f"warning: thumbnail failed for {ex.name}: {reason}", file=sys.stderr)
    return created, failed


def render_card_icon(ex: Example) -> str:
    if thumbnail_path(ex).exists():
        return f'<img src="../pyscript/thumbnails/{ex.name}.png" alt="" loading="lazy">'
    return GENERIC_ICON


def render_card(ex: Example, *, runtime: str = "micropython") -> str:
    if ex.featured:
        tag = '\n                        <span class="tag featured">featured</span>'
    elif ex.nochrome:
        tag = '\n                        <span class="tag">nochrome</span>'
    elif ex.new_window:
        tag = '\n                        <span class="tag">new window</span>'
    else:
        tag = ""
    badges = _render_badges(ex)
    hrefs = ex.loader_hrefs()
    icon = render_card_icon(ex)
    link_attrs = ' target="_blank" rel="noopener"' if ex.new_window else ""
    return f'''                <a class="card" href="{hrefs[runtime]}"{link_attrs}>
                    <div class="card-top">
                        <span class="card-icon">{icon}</span>
                        <span class="card-badges">{tag}{badges}
                        </span>
                    </div>
                    <h3>{ex.title}</h3>
                    <p>{ex.blurb}</p>
                </a>'''


def render_cards(examples: list[Example], *, runtime: str = "micropython") -> str:
    return "\n".join(render_card(ex, runtime=runtime) for ex in examples if ex.in_gallery)


def replace_block(text: str, key: str, payload: str) -> str:
    start = f"<!-- GEN:{key}:start -->"
    end = f"<!-- GEN:{key}:end -->"
    si = text.find(start)
    ei = text.find(end)
    if si == -1 or ei == -1:
        raise SystemExit(f"{INDEX.name} is missing the {start}/{end} markers")
    return text[: si + len(start)] + "\n" + payload + "\n            " + text[ei:]


def remove_stale_demo_html(stale: list[str], check: bool) -> None:
    for path in GALLERY_DIR.glob("*.html"):
        if path.stem in KEEP_HTML:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        if check:
            stale.append(rel)
            continue
        path.unlink()
        print(f"removed {rel}")


def remove_stale_example_json(stale: list[str], check: bool) -> None:
    """Remove leftover .site/gallery/<example>.json (now generated under packages/)."""
    keep = {"manifest"}  # PWA web app manifest
    for path in GALLERY_DIR.glob("*.json"):
        if path.stem in keep:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        urls = data.get("urls")
        if not isinstance(urls, list) or not urls:
            continue
        first = urls[0]
        # Legacy per-example JSON used ./lib/examples/; ignore other JSON files.
        url = str(first[1])
        if not (
            isinstance(first, list)
            and len(first) >= 2
            and ("/examples/" in url or url.startswith("examples/"))
        ):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        if check:
            stale.append(rel)
            continue
        path.unlink()
        print(f"removed {rel}")


def gallery_example_files() -> list[str]:
    files: set[str] = set()
    for ex in discover():
        if not ex.in_gallery:
            continue
        files.update(ex.pyscript_files)
    return sorted(files)


def tracked_utility_files() -> list[str]:
    """Return committed utility Python paths, excluding generated/ignored caches."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "lib/utils"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    prefix = "lib/"
    return sorted(
        path.removeprefix(prefix)
        for path in result.stdout.decode().split("\0")
        if path.endswith(".py")
    )


def copy_gallery_examples(dest: Path) -> int:
    n = 0
    for rel in gallery_example_files():
        src = EXAMPLES_DIR / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


def ensure_card_interpreter_css(index_text: str) -> str:
    """No-op: card/badge styles live in site.css (kept for backward compat)."""
    return index_text


_HEADER_MOUNT = '<div id="pydevices-site-header"></div>'
_FOOTER_MOUNT = '<div id="pydevices-site-footer"></div>'
_PRODUCT_MARK = (
    '<div class="logo-badge product-mark" style="background: linear-gradient(135deg, var(--tier-1-amber), #d97706); color: #fff;">'
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6M9 12h6M9 15h4"/><circle cx="17" cy="15" r="1.5"/></svg>'
    "</div>"
)
_CHROME_SCRIPTS = (
    '    <script src="../pyscript/site-chrome.js"></script>\n'
    '    <script src="../pyscript/theme-toggle.js"></script>\n'
)


def ensure_site_chrome(index_text: str) -> str:
    """Enforce shared org header/footer mounts + canonical chrome scripts."""
    text = index_text
    # Drop deferred theme script from <head> only (body scripts are managed below).
    head_end = text.find("</head>")
    if head_end != -1:
        head = text[:head_end]
        rest = text[head_end:]
        head = re.sub(
            r'\s*<script src="[./]*theme-toggle\.js"[^>]*></script>\s*',
            "\n",
            head,
        )
        text = head + rest
    text = re.sub(
        r'<header class="site-header">.*?</header>',
        _HEADER_MOUNT,
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'<footer class="site-footer[^"]*">.*?</footer>',
        _FOOTER_MOUNT,
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'<div class="logo-badge product-mark">.*?</div>',
        _PRODUCT_MARK,
        text,
        count=1,
        flags=re.DOTALL,
    )
    # Drop obsolete Install / MP-Py header preference script block.
    text = re.sub(
        r"\n\s*<script>\s*\(function \(\) \{\s*"
        r"var STORAGE_KEY = 'pydevices-gallery-loader';"
        r".*?"
        r"\}\)\(\);\s*</script>",
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    # Normalize trailing chrome scripts to single /assets/chrome/site-chrome.js
    text = re.sub(
        r'\s*<script src="[./a-zA-Z_-]*site-chrome\.js"></script>\s*',
        "\n",
        text,
    )
    text = re.sub(
        r'\s*<script src="[./a-zA-Z_-]*theme-toggle\.js"></script>\s*',
        "\n",
        text,
    )
    text = text.replace("</body>", _CHROME_SCRIPTS + "</body>", 1)
    if 'id="pydevices-site-header"' not in text:
        raise SystemExit("ensure_site_chrome failed to install header mount")
    if 'id="pydevices-site-footer"' not in text:
        raise SystemExit("ensure_site_chrome failed to install footer mount")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="fail if any output is stale")
    parser.add_argument(
        "--copy-examples",
        type=Path,
        metavar="DIR",
        help="copy gallery example .py files into DIR (for GitHub Pages deploy)",
    )
    args = parser.parse_args(argv)

    if args.copy_examples:
        n = copy_gallery_examples(args.copy_examples)
        print(f"copied {n} gallery example file(s) to {args.copy_examples}")

    # featured, then new-window, then A-Z
    discovered = discover()
    validate_example_deps(discovered)
    examples = sorted(
        discovered,
        key=lambda e: (0 if e.featured else 1 if e.new_window else 2, e.title.lower()),
    )
    stale: list[str] = []

    if not args.check:
        created, failed = generate_missing_thumbnails(examples)
        if created or failed:
            print(f"thumbnails: {created} created, {failed} failed")

    def write(path: Path, content: str) -> None:
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old == content:
            return
        if args.check:
            stale.append(str(path.relative_to(REPO_ROOT)))
            return
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")

    remove_stale_example_json(stale, args.check)
    remove_stale_demo_html(stale, args.check)

    def regenerate_index(path: Path, runtime: str) -> None:
        index_text = path.read_text(encoding="utf-8")
        if "<!-- GEN:demos:start -->" not in index_text:
            raise SystemExit(
                f"{path.name} is missing <!-- GEN:demos:start --> "
                "(collapse async/all sections before regenerating)"
            )
        index_text = ensure_card_interpreter_css(index_text)
        index_text = ensure_site_chrome(index_text)
        # Update hint text for new headers.
        index_text = index_text.replace(
            "# pyscript skip: gallery",
            "# gallery: skip",
        )
        index_text = replace_block(index_text, "demos", render_cards(examples, runtime=runtime))
        write(path, index_text)

    regenerate_index(INDEX, "micropython")
    regenerate_index(PYSCRIPT_INDEX, "pyodide")
    python_files = gallery_example_files()
    python_files.extend(tracked_utility_files())
    write(PYTHON_FILES, json.dumps(sorted(set(python_files)), indent=2) + "\n")

    n_module = sum(1 for ex in examples if ex.kind == "module" and ex.in_gallery)
    n_manifest = sum(1 for ex in examples if ex.kind == "manifest" and ex.in_gallery)
    n_featured = sum(1 for ex in examples if ex.featured and ex.in_gallery)
    n_new_window = sum(1 for ex in examples if ex.new_window and ex.in_gallery)
    n_gallery = sum(1 for ex in examples if ex.in_gallery)
    n_local_only = sum(1 for ex in examples if not ex.in_gallery)
    print(
        f"\n{n_gallery} gallery demo(s) "
        f"({n_module} module, {n_manifest} manifest; {n_featured} featured"
        f"; {n_new_window} in a new window)"
        f"; {n_local_only} local-only (gallery: skip/binaries)."
    )

    if args.check and stale:
        print("STALE:\n  " + "\n  ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
