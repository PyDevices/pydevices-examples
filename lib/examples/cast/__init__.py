# gallery: skip
# The modules in this example import each other by name (micecast, castfast,
# roku_cast, ...), so importing the package puts its directory on the path.
# Run a demo with `import cast.tv_cast` (or laptop_input, drum_cast).
import sys

_wd = __file__.replace("\\", "/")
_wd = _wd.rsplit("/", 1)[0] if "/" in _wd else "."
if _wd not in sys.path:
    sys.path.insert(0, _wd)
