import sys

_wd = __file__.replace("\\", "/")
_wd = _wd.rsplit("/", 1)[0] if "/" in _wd else "."
if _wd not in sys.path:
    sys.path.insert(0, _wd)
from . import noto_fonts
