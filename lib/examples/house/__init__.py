# gallery: skip
# The house appliance's modules import each other and the cast example by name
# (house_panel, roku_cast, castfast), and the sensor hub as a package, so
# importing this package puts its own directory, the cast example's and their
# parent on the path. Needs the ESP32-P4 firmware with castif to cast.
import sys

_wd = __file__.replace("\\", "/")
_wd = _wd.rsplit("/", 1)[0] if "/" in _wd else "."
_parent = _wd.rsplit("/", 1)[0] if "/" in _wd else ".."
for _p in (_wd, _parent + "/cast", _parent):
    if _p not in sys.path:
        sys.path.append(_p)
