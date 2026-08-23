"""Directory tree matching ``tree -n --charset=ascii``.

No colors, ANSI, or host-only APIs. Portable across CPython, MicroPython,
and CircuitPython (unix, Windows, and MCUs).

Usage::

    from tree import tree
    tree()           # cwd
    tree("/")
    tree(r"U:\\path")
    tree(r"U:\\path\\")
"""

import os
import sys

_DIR = 0x4000
_LNK = 0xA000


def _walk_root(path):
    """Path used for filesystem calls (strip trailing separators except roots)."""
    if path is None or path == "":
        path = "."
    p = path
    while len(p) > 1 and p[-1] in "/\\":
        # Keep Windows drive root: "C:\" / "C:/"
        if len(p) == 3 and p[1] == ":" and p[2] in "/\\":
            break
        p = p[:-1]
    return p


def _join(base, name):
    if base == ".":
        return name
    sep = "\\" if "\\" in base and "/" not in base else "/"
    if base[-1] in "/\\":
        return base + name
    return base + sep + name


def _list_entries(path):
    """Return sorted list of (name, kind) where kind is 'dir', 'file', or 'link'."""
    out = []
    try:
        listing = os.ilistdir(path)
    except AttributeError:
        listing = None
    except OSError:
        return out

    if listing is not None:
        for entry in listing:
            name = entry[0]
            if name in (".", "..") or name[:1] == ".":
                continue
            mode = entry[1] if len(entry) > 1 else 0
            if mode == _LNK or (mode & 0xF000) == _LNK:
                kind = "link"
            elif mode == _DIR or (mode & 0xF000) == _DIR:
                kind = "dir"
            else:
                kind = "file"
            out.append((name, kind))
    else:
        try:
            names = os.listdir(path)
        except OSError:
            return out
        for name in names:
            if name in (".", "..") or name[:1] == ".":
                continue
            full = _join(path, name)
            try:
                mode = os.stat(full)[0]
            except OSError:
                continue
            # Without lstat/readlink, symlinks are classified by their target.
            kind = "dir" if (mode & 0o170000) == 0o040000 else "file"
            out.append((name, kind))

    out.sort(key=lambda x: x[0])
    return out


def tree(path="."):
    """Print an ASCII tree of *path* (default ``"."``). Returns (dirs, files)."""
    display = "." if path is None or path == "" else path
    root = _walk_root(display)
    dirs = 1
    files = 0

    print(display)

    def walk(current, prefix):
        nonlocal dirs, files
        entries = _list_entries(current)
        n = len(entries)
        for i, (name, kind) in enumerate(entries):
            last = i == n - 1
            branch = "`-- " if last else "|-- "
            full = _join(current, name)
            print(prefix + branch + name)
            if kind == "link":
                # Do not recurse into symlinks; count like unix tree.
                try:
                    mode = os.stat(full)[0]
                    if (mode & 0o170000) == 0o040000:
                        dirs += 1
                    else:
                        files += 1
                except OSError:
                    files += 1
                continue
            if kind == "dir":
                dirs += 1
                extension = "    " if last else "|   "
                walk(full, prefix + extension)
            else:
                files += 1

    try:
        os.listdir(root)
    except OSError:
        print(display + " [error opening dir]")
        print("")
        print("0 directories, 0 files")
        return 0, 0

    walk(root, "")
    print("")
    dlabel = "directory" if dirs == 1 else "directories"
    flabel = "file" if files == 1 else "files"
    print("%d %s, %d %s" % (dirs, dlabel, files, flabel))
    return dirs, files


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "."
    tree(arg)
