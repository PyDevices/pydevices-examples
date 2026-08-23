"""Build PyScript loader query strings from logical install intents.

Callers pass logical names matching example headers (``# deps:``, ``# modules:``,
``# manifests:``). This module rewrites deps per interpreter, drops builtins for the
active profile, and emits query-only strings
(``?modules=…&manifests=…&deps=…``). Prepend ``micropython.html`` /
``pyodide.html`` (or ``mp.html`` / ``py.html``) yourself.

All shells use the same ``deps=`` key; MicroPython installs via MIP and Pyodide
via micropip.

    from url_maker import urls_from_deps

    urls_from_deps(modules=("hello",), deps=("palettes",), interpreter="micropython")
    # -> '?modules=hello'  (palettes frozen in MP WASM)

    urls_from_deps(modules=("hello",), deps=("palettes",), interpreter="pyodide")
    # -> '?modules=hello&deps=palettes,pygraphics'

    urls_from_deps(modules=("hello",), deps=("palettes",), interpreter=None)
    # -> {'micropython': '?modules=hello',
    #     'pyodide': '?modules=hello&deps=palettes,pygraphics'}
"""

from __future__ import annotations

from typing import Iterable

INTERPRETERS = ("micropython", "pyodide")

# Profiles → logical names already present (frozen/native, or toml-mounted).
# Skip those names when emitting deps for that profile.
PROFILES: dict[str, frozenset[str]] = {
    # Browser MP WASM: PyDevices core (displaydev/appdev/multimer) toml-mounted;
    # sister/ecosystem libs frozen in the pyscript vendor firmware (lvgl,
    # display_driver, pygraphics, palettes, pdwidgets, usdl2 when built in).
    # Do not mip-install those — Pyodide / CPython still get TestPyPI wheels.
    "pyscript-mp": frozenset(
        {
            "pygraphics",
            "displaydev",
            "multimer",
            "appdev",
            "board_config",
            "lvgl",
            "pydevices-lvgl",
            "display_driver",
            "palettes",
            "pdwidgets",
            "usdl2",
            "usdl2-py",
        }
    ),
    # Pyodide: PyDevices core is toml-mounted. Sister packages (pygraphics
    # pyemscripten wasm wheel, usdl2, …) come from TestPyPI via ?deps=.
    "pyscript-pyodide": frozenset(
        {
            "displaydev",
            "multimer",
            "appdev",
            "board_config",
        }
    ),
    # Firmware with sister cmods compiled in — omit those from install lists.
    "firmware-cmods": frozenset(
        {
            "pygraphics",
            "lvgl",
            "pydevices-lvgl",
            "display_driver",
            "palettes",
            "pdwidgets",
            "usdl2",
            "usdl2-py",
        }
    ),
}

# Interpreter-aware rewrites: logical name → install name (or None to omit).
_MIP_REWRITE: dict[str, str | None] = {
    "lvgl": None,  # C-only; no MIP package
    "pydevices-lvgl": None,
    "display_driver": None,  # ships with LVGL firmware / pydevices-lvgl wheel
    "pygraphics": "pygraphics",  # micropython-lib package (pure Python)
    "usdl2-py": "usdl2",  # same import name on MIP (PyDevices/usdl2)
}

_WHEEL_REWRITE: dict[str, str | None] = {
    "lvgl": "pydevices-lvgl",
    "pydeviceslvgl": "pydevices-lvgl",
    "display_driver": "pydevices-lvgl",  # bundled in the wheel
    "pygraphics": "pydevices-pygraphics",
    "palettes": "pydevices-palettes",
    "pdwidgets": "pydevices-pdwidgets",
    "appdev": "pydevices",
    "multimer": "pydevices",
    "displaydev": "pydevices",
    "usdl2-py": "usdl2",  # prefer native TestPyPI wheel when available
}

# Logical deps that need pygraphics at interpreter but often omit it from headers.
_WHEEL_PULLS_PYGRAPHICS = frozenset({"palettes", "pdwidgets"})


def _norm_dep(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _as_tuple(value: Iterable[str] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError("pass a sequence of names, not a bare string")
    return tuple(value)


def _dedupe(names: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def rewrite_mip(name: str) -> str | None:
    """Return MIP install name, or None if this logical name has no MIP."""
    key = name.strip()
    if key in _MIP_REWRITE:
        return _MIP_REWRITE[key]
    return key


def rewrite_wheel(name: str) -> str | None:
    """Return wheel project name, or None if this logical name has no wheel."""
    key = name.strip()
    lowered = key.lower().replace("_", "-")
    if lowered in _WHEEL_REWRITE:
        return _WHEEL_REWRITE[lowered]
    if key in _WHEEL_REWRITE:
        return _WHEEL_REWRITE[key]
    return key


def _apply_channel(
    names: Iterable[str],
    *,
    channel: str,
    profile: str,
) -> list[str]:
    skip = PROFILES.get(profile, frozenset())
    skip_norm = {_norm_dep(s) for s in skip}
    out: list[str] = []
    seen: set[str] = set()
    pull_pygraphics = False
    for raw in names:
        logical = str(raw).strip()
        if not logical:
            continue
        # Already a URL / github: path — pass through.
        if "://" in logical or logical.startswith(("github:", "gitlab:", "codeberg:")):
            if logical not in seen:
                seen.add(logical)
                out.append(logical)
            continue
        if _norm_dep(logical) in _WHEEL_PULLS_PYGRAPHICS:
            pull_pygraphics = True
        if logical in skip or _norm_dep(logical) in skip_norm:
            continue
        if channel == "mip":
            resolved = rewrite_mip(logical)
        elif channel == "wheels":
            resolved = rewrite_wheel(logical)
        else:
            raise ValueError(f"unknown channel {channel!r}")
        if resolved is None:
            if channel == "mip" and logical.lower().startswith("lvgl"):
                continue  # omit silently for mip (C-only)
            continue
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    # palettes / pdwidgets need pygraphics; prefer the native TestPyPI build.
    if channel == "wheels" and pull_pygraphics and "pydevices-pygraphics" not in seen:
        out.append("pydevices-pygraphics")
    return out


def _join_query(parts: list[tuple[str, list[str]]]) -> str:
    chunks: list[str] = []
    for key, values in parts:
        if values:
            chunks.append(f"{key}={','.join(values)}")
    if not chunks:
        return "?"
    return "?" + "&".join(chunks)


def url(
    *,
    modules: Iterable[str] = (),
    manifests: Iterable[str] = (),
    deps: Iterable[str] = (),
    interpreter: str | None = None,
    profile: str | None = None,
    **kwargs: object,
) -> str | dict[str, str]:
    """Emit a loader query string, or both interpreters when ``interpreter`` is None.

    Package installs always use the ``deps=`` query key (MIP on MicroPython,
    micropip on Pyodide). Unknown keyword arguments raise ``TypeError``.
    """
    if kwargs:
        bad = ", ".join(sorted(kwargs))
        raise TypeError(f"url() got unexpected keyword argument(s): {bad}")

    modules_t = _dedupe(_as_tuple(modules))
    manifests_t = _dedupe(_as_tuple(manifests))
    deps_t = _as_tuple(deps)

    if interpreter is not None and interpreter not in INTERPRETERS:
        raise ValueError(
            f"interpreter must be one of {INTERPRETERS!r} or None, got {interpreter!r}"
        )

    def _one(rt: str) -> str:
        if profile is None:
            prof = "pyscript-mp" if rt == "micropython" else "pyscript-pyodide"
        else:
            prof = profile

        channel = "mip" if rt == "micropython" else "wheels"
        parts: list[tuple[str, list[str]]] = [
            ("modules", modules_t),
            ("manifests", manifests_t),
            ("deps", _apply_channel(deps_t, channel=channel, profile=prof)),
        ]
        return _join_query(parts)

    if interpreter is None:
        return {rt: _one(rt) for rt in INTERPRETERS}
    return _one(interpreter)


def urls_from_deps(
    *,
    modules: Iterable[str] = (),
    manifests: Iterable[str] = (),
    deps: Iterable[str] = (),
    interpreter: str | None = None,
    profile: str | None = None,
) -> str | dict[str, str]:
    """Emit loader queries from logical ``deps`` (rewritten per interpreter)."""
    return url(
        modules=modules,
        manifests=manifests,
        deps=deps,
        interpreter=interpreter,
        profile=profile,
    )
