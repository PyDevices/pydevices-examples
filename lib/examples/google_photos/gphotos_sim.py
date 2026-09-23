# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
gphotos_sim
====================================================
Duck-typed Picker API simulator for gallery / offline demos.

``make_engine()`` returns :class:`GPhotosSimEngine` when:

* ``GPHOTOS_SIM`` is truthy (explicit), or
* PyScript (``emscripten`` / ``webassembly`` / ``import pyscript``), or
* no tokens file with ``client_id`` + ``refresh_token`` exists (see
  ``tools/gphotos_auth.py``), or
* no usable network is detected.

``GPHOTOS_SIM=0`` forces the real :class:`gphotos_engine.GPhotosEngine`.

The sim pretends the user already picked a handful of photos, so the launcher
opens on the list. PICK shows a fake QR code and "picks" again by itself after
a few polls. Thumbnails come from ``assets/sim_NN_<size>.jpg`` when those
files are present (git checkout); the front end paints a placeholder tile
when they are not (MIP / gallery installs carry Python files only).
"""

import sys

from gphotos_engine import GPhotosEngine, credentials_ok, load_tokens, socket as _engine_socket
from gphotos_engine import _env_get, _exists

_PKG = __file__.replace("\\", "/").rsplit("/", 1)[0] if "/" in __file__.replace("\\", "/") else "."
ASSETS_DIR = _PKG + "/assets"

SIM_PICKER_URI = "https://photospicker.google.com/simulator"

# Canned "picked" photos. Even entries are landscape, odd entries portrait.
_SIM_ITEMS = (
    ("IMG_20240503_142211.jpg", "2024-05-03T14:22:11Z", 4032, 3024, "sim_01"),
    ("PXL_20240612_091530.jpg", "2024-06-12T09:15:30Z", 3024, 4032, "sim_02"),
    ("IMG_20240704_203045.jpg", "2024-07-04T20:30:45Z", 4000, 3000, "sim_03"),
    ("PXL_20240815_171012.jpg", "2024-08-15T17:10:12Z", 3000, 4000, "sim_04"),
    ("IMG_20240921_120000.jpg", "2024-09-21T12:00:00Z", 4032, 3024, "sim_05"),
    ("PXL_20241031_183322.jpg", "2024-10-31T18:33:22Z", 3024, 4032, "sim_06"),
    ("IMG_20241225_101500.jpg", "2024-12-25T10:15:00Z", 4032, 3024, "sim_01"),
    ("PXL_20250101_000102.jpg", "2025-01-01T00:01:02Z", 3024, 4032, "sim_02"),
)

# Plaque status when the sim runs because no credentials / network exist.
NO_CREDENTIALS_PLAQUE = "no tokens file - running simulator"
NO_NETWORK_PLAQUE = "no network detected - running simulator"


def _is_pyscript():
    if getattr(sys, "platform", "") in ("emscripten", "webassembly"):
        return True
    try:
        import pyscript  # noqa: F401

        return True
    except ImportError:
        return False


def _network_available():
    """Best-effort: station Wi-Fi up on MCUs, any route on desktop hosts."""
    try:
        import network

        try:
            return bool(network.WLAN(network.STA_IF).isconnected())
        except Exception:
            return True  # a network module without WLAN: assume wired
    except ImportError:
        pass
    try:
        import wifi

        return bool(getattr(wifi.radio, "ipv4_address", None))
    except ImportError:
        pass
    if _engine_socket is None:
        return False
    try:
        s = _engine_socket.socket(_engine_socket.AF_INET, _engine_socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # no packet is sent for UDP connect
            return True
        finally:
            s.close()
    except Exception:
        return False


def sim_reason(tokens=None):
    """Why the sim should run, or ``None`` for the real engine.

    Returns ``"env"``, ``"pyscript"``, ``"no_credentials"``, ``"no_network"``
    or ``None``. Explicit ``GPHOTOS_SIM`` wins.
    """
    raw = _env_get("GPHOTOS_SIM")
    if raw is not None and raw != "":
        return "env" if str(raw).strip().lower() not in ("0", "false", "no", "off") else None
    if _is_pyscript():
        return "pyscript"
    if not credentials_ok(load_tokens() if tokens is None else tokens):
        return "no_credentials"
    if not _network_available():
        return "no_network"
    return None


def want_sim():
    return sim_reason() is not None


def make_engine(**kwargs):
    """Return :class:`GPhotosSimEngine` or :class:`GPhotosEngine` per :func:`sim_reason`."""
    reason = sim_reason(kwargs.get("tokens"))
    if reason:
        return GPhotosSimEngine(reason=reason, **kwargs)
    return GPhotosEngine(**kwargs)


def _sim_items(rotate=0):
    items = []
    n = len(_SIM_ITEMS)
    for i in range(n):
        name, created, w, h, asset = _SIM_ITEMS[(i + rotate) % n]
        items.append(
            {
                "id": "sim-%s" % name,
                "filename": name,
                "createTime": created,
                "type": "PHOTO",
                "mime": "image/jpeg",
                "width": w,
                "height": h,
                "baseUrl": "sim://" + asset,
                "asset": asset,
                "portrait": h > w,
            }
        )
    return items


class GPhotosSimEngine(GPhotosEngine):
    """In-memory Picker stand-in — same surface as :class:`GPhotosEngine`."""

    sim = True

    def __init__(self, reason="env", **kwargs):
        super().__init__(**kwargs)
        self.sim_reason = reason or "env"
        if self.sim_reason == "no_credentials":
            self.sim_notice = NO_CREDENTIALS_PLAQUE
        elif self.sim_reason == "no_network":
            self.sim_notice = NO_NETWORK_PLAQUE
        else:
            self.sim_notice = "simulator"
        self._polls = 0
        self._picks = 0
        self.prefs = {}

    # No network, no files: everything below is in-memory.

    def has_credentials(self):
        return True

    def ensure_token(self, force=False):
        self.access_token = "sim"
        return True

    def _save_prefs(self):
        return True

    def _load_prefs(self):
        if self.prefs is None:
            self.prefs = {}
        return self.prefs

    def create_session(self):
        self._polls = 0
        self.session = {
            "id": "sim-session-%d" % (self._picks + 1),
            "pickerUri": SIM_PICKER_URI,
            "expireTime": "",
            "mediaItemsSet": False,
            "pollInterval": 2.0,
            "timeoutIn": 1800.0,
        }
        self.items = []
        self._urls_at = None
        self.last_error = ""
        return self.session

    def poll_session(self):
        if not self.session:
            self.last_error = "no session"
            return False
        self._polls += 1
        done = self._polls >= 3
        self.session["mediaItemsSet"] = done
        return done

    def delete_session(self):
        self.session = None
        return True

    def list_items(self):
        if not self.session:
            self.last_error = "no session"
            return None
        self._picks += 1
        self.items = _sim_items(rotate=self._picks % len(_SIM_ITEMS))
        self._urls_at = 0
        self.last_error = ""
        return self.items

    def urls_valid(self):
        return bool(self.items)

    def refresh_urls(self):
        return bool(self.items)

    def restore(self):
        self.session = {
            "id": "sim-session-0",
            "pickerUri": SIM_PICKER_URI,
            "expireTime": "",
            "mediaItemsSet": True,
            "pollInterval": 2.0,
            "timeoutIn": 1800.0,
        }
        self.items = _sim_items()
        self._urls_at = 0
        return True

    def forget(self, clear_cache=False):
        self.session = None
        self.items = []

    def asset_path(self, item, w, h, crop=False):
        """Best bundled JPEG for the requested box, or ``""`` when absent."""
        base = item.get("asset") or "sim_01"
        if crop:
            tag = "96" if min(int(w), int(h)) >= 96 else "64"
        else:
            portrait = bool(item.get("portrait"))
            sizes = ((240, 320), (120, 160)) if portrait else ((320, 240), (160, 120))
            tag = None
            for cw, ch in sizes:
                if cw <= int(w) and ch <= int(h):
                    tag = "%dx%d" % (cw, ch)
                    break
            if tag is None:
                cw, ch = sizes[-1]
                tag = "%dx%d" % (cw, ch)
        path = "%s/%s_%s.jpg" % (ASSETS_DIR, base, tag)
        return path if _exists(path) else ""

    def thumbnail_path(self, item, w, h, crop=False):
        if not item or not item.get("id"):
            self.last_error = "no item"
            return ""
        path = self.asset_path(item, w, h, crop)
        if not path:
            self.last_error = "simulator: sample images not installed"
        return path
