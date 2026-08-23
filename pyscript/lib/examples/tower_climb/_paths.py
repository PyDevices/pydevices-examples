"""Package paths for a self-contained tower_climb example tree."""

import os


def _norm(path):
    return str(path).replace("\\", "/")


def _dirname(path):
    path = _norm(path).rstrip("/")
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


def _join(*parts):
    out = ""
    for part in parts:
        if not part:
            continue
        part = _norm(part)
        if not out:
            out = part.rstrip("/")
        else:
            out = out.rstrip("/") + "/" + part.lstrip("/")
    return out


def ensure_parent_dir(path):
    parent = _dirname(path)
    if not parent:
        return
    try:
        os.mkdir(parent)
    except OSError:
        pass


PKG_DIR = _dirname(_norm(__file__))
ASSETS_DIR = _join(PKG_DIR, "assets")
TOOLS_DIR = _join(PKG_DIR, "tools")
TRACE_DIR = _join(PKG_DIR, "trace")
SRC_DIR = _dirname(_dirname(PKG_DIR))
REPO_ROOT = _dirname(SRC_DIR)
GAME_SCRIPT = _join(PKG_DIR, "tower_climb.py")


def asset_path(name):
    return _join(ASSETS_DIR, name)
