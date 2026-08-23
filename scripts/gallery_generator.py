#!/usr/bin/env python3
"""
gallery_generator.py — refresh the pydevices-examples PyScript browser gallery.

Default-includes every example **entry point** under ``lib/examples/``:

  - ``examples/<name>.py`` — single-file module
  - ``examples/<name>/<name>.py`` — package (preferred over ``__init__.py``)
  - ``examples/<name>/__init__.py`` — package when no ``<name>.py`` entry

Optional headers (first 10 lines), one line per namespace::

  # deps: palettes, lvgl          — logical packages → ?deps= via url_maker
  # utils: console, tft_config  — pydevices-examples utils modules (shown as badges)
  # modules: calc_engine          — extra example .py stems (site)
  # manifests: alien              — site-served packages/<name>.json bundles
  # gallery: featured|skip|binaries|nochrome

MIP manifests for package examples live in ``packages/<name>.json`` (generated
by ``scripts/install_gen_manifests.py``). PyScript loads them via the
``.site/pyscript/packages`` symlink as ``?manifests=<name>``.

``# gallery: nochrome`` keeps the demo in the gallery but links the minimal
``mp.html`` / ``py.html`` shells (no gallery chrome) — useful for
large landscape demos.

Then:

  - Updates gallery cards in ``.site/pyscript/index.html`` (``GEN:demos`` markers)
  - Enforces shared org chrome mounts via ``ensure_site_chrome``
  - Deletes stale ``.site/pyscript/*.html`` from the old per-demo page generator

Each card links both interpreters (MicroPython + Pyodide) with filtered queries
from ``url_maker``. Hinch GUIs are not listed in headers — ``fetch_ph_gui``
installs them at runtime via color/hardware/touch setup.

    python scripts/gallery_generator.py
    python scripts/gallery_generator.py --check
    python scripts/gallery_generator.py --copy-examples DIR
"""

from __future__ import annotations

import argparse
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
from url_maker import urls_from_deps  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "lib" / "examples"
PYSCRIPT_DIR = REPO_ROOT / ".site" / "pyscript"
INDEX = PYSCRIPT_DIR / "index.html"
THUMBNAILS_DIR = PYSCRIPT_DIR / "thumbnails"
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

ARROW = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
)

GENERIC_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>'
)

HEADER_SCAN_LINES = 10
GALLERY_VALUES = frozenset({"featured", "skip", "binaries", "nochrome"})

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
        return urls_from_deps(
            modules=self._modules_for_query(),
            manifests=self._manifests_for_query(),
            deps=self.deps,
            interpreter=None,
        )

    def loader_hrefs(self) -> dict[str, str]:
        queries = self.loader_queries()
        if self.nochrome:
            return {
                "micropython": f"mp.html{queries['micropython']}",
                "pyodide": f"py.html{queries['pyodide']}",
            }
        return {
            "micropython": f"micropython.html{queries['micropython']}",
            "pyodide": f"pyodide.html{queries['pyodide']}",
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


def parse_gallery_value(lines: list[str]) -> str | None:
    """Return featured|skip|binaries|nochrome or None. Exactly one value when present."""
    for line in lines[:HEADER_SCAN_LINES]:
        s = line.strip()
        if not s.startswith("# gallery:"):
            continue
        body = s.split(":", 1)[1].strip().lower()
        if not body:
            return None
        # Allow a single token only.
        token = body.split(",")[0].strip()
        if token in GALLERY_VALUES:
            return token
        raise SystemExit(
            f"invalid # gallery: value {body!r} (want featured|skip|binaries|nochrome)"
        )
    return None


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
    gallery = parse_gallery_value(lines)
    ex.in_gallery = gallery not in ("skip", "binaries")
    ex.featured = gallery == "featured"
    ex.nochrome = gallery == "nochrome"
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


def _render_badges(ex: Example) -> str:
    """Render deps and utils as colored badge spans next to the card tag."""
    parts: list[str] = []
    for dep in ex.deps:
        parts.append(f'<span class="badge dep">{dep}</span>')
    for ao in ex.utils:
        parts.append(f'<span class="badge add-on">{ao}</span>')
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
        return f'<img src="thumbnails/{ex.name}.png" alt="" loading="lazy">'
    return GENERIC_ICON


def render_card(ex: Example) -> str:
    if ex.featured:
        tag = '\n                        <span class="tag featured">featured</span>'
    elif ex.nochrome:
        tag = '\n                        <span class="tag">nochrome</span>'
    else:
        tag = ""
    badges = _render_badges(ex)
    hrefs = ex.loader_hrefs()
    icon = render_card_icon(ex)
    link_attrs = ' target="_blank" rel="noopener"' if ex.nochrome else ""
    return f'''                <article class="card">
                    <div class="card-top">
                        <span class="card-icon">{icon}</span>
                        <span class="card-badges">{tag}{badges}
                        </span>
                    </div>
                    <h3>{ex.title}</h3>
                    <p>{ex.blurb}</p>
                    <div class="card-interpreters">
                        <a class="go" href="{hrefs["micropython"]}"{link_attrs}>MicroPython {ARROW}</a>
                        <a class="go" href="{hrefs["pyodide"]}"{link_attrs}>Pyodide {ARROW}</a>
                    </div>
                </article>'''


def render_cards(examples: list[Example]) -> str:
    return "\n".join(render_card(ex) for ex in examples if ex.in_gallery)


def replace_block(text: str, key: str, payload: str) -> str:
    start = f"<!-- GEN:{key}:start -->"
    end = f"<!-- GEN:{key}:end -->"
    si = text.find(start)
    ei = text.find(end)
    if si == -1 or ei == -1:
        raise SystemExit(f"{INDEX.name} is missing the {start}/{end} markers")
    return text[: si + len(start)] + "\n" + payload + "\n            " + text[ei:]


def remove_stale_demo_html(stale: list[str], check: bool) -> None:
    for path in PYSCRIPT_DIR.glob("*.html"):
        if path.stem in KEEP_HTML:
            continue
        rel = str(path.relative_to(REPO_ROOT))
        if check:
            stale.append(rel)
            continue
        path.unlink()
        print(f"removed {rel}")


def remove_stale_example_json(stale: list[str], check: bool) -> None:
    """Remove leftover .site/pyscript/<example>.json (now generated under packages/)."""
    keep = {"manifest"}  # PWA web app manifest
    for path in PYSCRIPT_DIR.glob("*.json"):
        if path.stem in keep:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        urls = data.get("urls")
        if not isinstance(urls, list) or not urls:
            continue
        first = urls[0]
        # Legacy .site/pyscript/<example>.json used ./lib/examples/; ignore others.
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
_PRODUCT_MARK = "https://pydevices.github.io/assets/img/logo.svg"
_CHROME_SCRIPTS = (
    '    <script src="./site-chrome.js"></script>\n    <script src="./theme-toggle.js"></script>\n'
)


def ensure_site_chrome(index_text: str) -> str:
    """Enforce shared org header/footer mounts + local chrome scripts."""
    text = index_text
    # Drop deferred theme script from <head> only (body scripts are managed below).
    head_end = text.find("</head>")
    if head_end != -1:
        head = text[:head_end]
        rest = text[head_end:]
        head = re.sub(
            r'\s*<script src="\./theme-toggle\.js"[^>]*></script>\s*',
            "\n",
            head,
            count=1,
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
        r'(<div class="logo-badge product-mark"><img src=")[^"]+(")',
        rf"\1{_PRODUCT_MARK}\2",
        text,
        count=1,
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
    # Normalize trailing chrome scripts to a single ordered pair.
    text = re.sub(
        r'\s*<script src="\./site-chrome\.js"></script>\s*',
        "\n",
        text,
    )
    text = re.sub(
        r'\s*<script src="\./theme-toggle\.js"></script>\s*',
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

    # featured, then nochrome, then A-Z
    examples = sorted(
        discover(),
        key=lambda e: (0 if e.featured else 1 if e.nochrome else 2, e.title.lower()),
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

    index_text = INDEX.read_text(encoding="utf-8")
    if "<!-- GEN:demos:start -->" not in index_text:
        raise SystemExit(
            f"{INDEX.name} is missing <!-- GEN:demos:start --> "
            "(collapse async/all sections before regenerating)"
        )
    index_text = ensure_card_interpreter_css(index_text)
    index_text = ensure_site_chrome(index_text)
    # Update hint text for new headers.
    index_text = index_text.replace(
        "# pyscript skip: gallery",
        "# gallery: skip",
    )
    index_text = replace_block(index_text, "demos", render_cards(examples))
    write(INDEX, index_text)

    n_module = sum(1 for ex in examples if ex.kind == "module" and ex.in_gallery)
    n_manifest = sum(1 for ex in examples if ex.kind == "manifest" and ex.in_gallery)
    n_featured = sum(1 for ex in examples if ex.featured and ex.in_gallery)
    n_nochrome = sum(1 for ex in examples if ex.nochrome and ex.in_gallery)
    n_gallery = sum(1 for ex in examples if ex.in_gallery)
    n_local_only = sum(1 for ex in examples if not ex.in_gallery)
    print(
        f"\n{n_gallery} gallery demo(s) "
        f"({n_module} module, {n_manifest} manifest; {n_featured} featured"
        f"; {n_nochrome} nochrome)"
        f"; {n_local_only} local-only (gallery: skip/binaries)."
    )

    if args.check and stale:
        print("STALE:\n  " + "\n  ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
