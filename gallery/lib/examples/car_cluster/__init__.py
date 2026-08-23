import sys

_wd = __file__.replace("\\", "/")
_wd = _wd.rsplit("/", 1)[0] if "/" in _wd else "."
if _wd not in sys.path:
    sys.path.insert(0, _wd)
from . import car_cluster  # noqa: F401 — gallery/kit entry: import car_cluster
from display_driver import app

# Package import is the PyScript/gallery entry (not ``__main__``); keep LVGL alive.
