# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_sim
====================================================
Duck-typed Roku ECP simulator for gallery / offline demos.

``make_engine()`` returns :class:`RokuSimEngine` when:

* ``ROKU_SIM`` is truthy (explicit), or
* PyScript (``emscripten`` / ``webassembly`` / ``import pyscript``), or
* no usable network is detected (no ``socket`` module, or no station IPv4 / Wi‑Fi).

``ROKU_SIM=0`` forces the real :class:`roku_engine.RokuEngine``.

When the sim is chosen because the network is down (including missing
``socket``, e.g. CircuitPython unix), the plaque status line shows
``no network detected, running simulator`` instead of fake playback text.
PyScript / explicit ``ROKU_SIM=1`` keep the normal demo playback labels.
"""

import sys

from roku_engine import RokuEngine, _local_ipv4, socket as _engine_socket

# Demo TVs (Select page + discover).
_SIM_DEVICES = (
    {
        "host": "192.168.1.50",
        "name": "Living Room",
        "serial": "SIMLR0000001",
    },
    {
        "host": "192.168.1.51",
        "name": "Bedroom",
        "serial": "SIMBR0000002",
    },
)

_SIM_APPS_XML = (
    '<?xml version="1.0" encoding="UTF-8" ?>'
    "<apps>"
    '<app id="12" type="appl" version="1.0.0">Netflix</app>'
    '<app id="13" type="appl" version="1.0.0">Prime Video</app>'
    '<app id="151908" type="appl" version="1.0.0">Disney Plus</app>'
    '<app id="2285" type="appl" version="1.0.0">Hulu</app>'
    '<app id="837" type="appl" version="1.0.0">YouTube</app>'
    '<app id="tvinput.dtv" type="tvin" version="1.0.0">Live TV</app>'
    '<app id="tvinput.hdmi1" type="tvin" version="1.0.0">HDMI 1</app>'
    '<app id="tvinput.hdmi2" type="tvin" version="1.0.0">HDMI 2</app>'
    "</apps>"
)

# Plaque status when sim was selected because the host has no network.
_NO_NETWORK_PLAQUE = "no network detected, running simulator"


def _is_pyscript():
    if getattr(sys, "platform", "") in ("emscripten", "webassembly"):
        return True
    try:
        import pyscript  # noqa: F401

        return True
    except ImportError:
        return False


def _network_available():
    """True when sockets exist and a usable station IPv4 is visible."""
    if _engine_socket is None:
        return False
    try:
        return bool(_local_ipv4())
    except Exception:
        return False


def sim_reason():
    """Why the sim should run, or ``None`` for the real engine.

    Returns ``\"env\"``, ``\"pyscript\"``, ``\"no_network\"``, or ``None``.
    Explicit ``ROKU_SIM`` wins; otherwise PyScript, then no-network fallback
    (missing ``socket`` or no station IPv4 / Wi‑Fi).
    """
    try:
        from displaydev import env_bool, env_get
    except ImportError:
        if _is_pyscript():
            return "pyscript"
        if not _network_available():
            return "no_network"
        return None

    raw = env_get("ROKU_SIM", None)
    if raw is not None:
        return "env" if env_bool("ROKU_SIM", False) else None
    if _is_pyscript():
        return "pyscript"
    if not _network_available():
        return "no_network"
    return None


def want_sim():
    """True when the sim engine should be used."""
    return sim_reason() is not None


def make_engine(host=None, port=None, timeout=5.0):
    """Return :class:`RokuSimEngine` or :class:`RokuEngine` per :func:`sim_reason`."""
    reason = sim_reason()
    if reason:
        return RokuSimEngine(
            host=host, port=port, timeout=timeout, reason=reason
        )
    return RokuEngine(host=host, port=port if port is not None else 8060, timeout=timeout)


class RokuSimEngine(RokuEngine):
    """In-memory ECP stand-in — same UI surface as :class:`RokuEngine`."""

    def __init__(self, host=None, port=None, timeout=5.0, reason="env"):
        # Avoid importing ROKU_PORT as default host path; keep empty until select.
        super().__init__(host=host if host is not None else "", port=port or 8060, timeout=timeout)
        self.sim_reason = reason or "env"
        # Only the no-network path advertises itself on the plaque.
        self._sim_notice = _NO_NETWORK_PLAQUE if self.sim_reason == "no_network" else ""
        self._sim_cache = [dict(d) for d in _SIM_DEVICES]
        self._power_on = True
        self._play_state = "play"  # play | pause | ""
        self._position_ms = 125000
        self._duration_ms = 3600000
        self._active_id = "12"
        self._active_name = "Netflix"
        self._by_host = {d["host"]: dict(d) for d in self._sim_cache}

    def playback_app_label(self):
        if self._sim_notice:
            return self._sim_notice
        return super().playback_app_label()

    def playback_state_label(self):
        if self._sim_notice:
            return ""
        return super().playback_state_label()

    def position_label(self):
        if self._sim_notice:
            return ""
        return super().position_label()

    def progress_fraction(self):
        if self._sim_notice:
            return None
        return super().progress_fraction()

    def _device_xml(self, host):
        info = self._by_host.get(host) or {
            "host": host,
            "name": "Sim Roku",
            "serial": "SIM000000000",
        }
        mode = "PowerOn" if self._power_on else "DisplayOff"
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>'
            "<device-info>"
            "<udn>sim-udn-%s</udn>"
            "<serial-number>%s</serial-number>"
            "<device-id>sim-%s</device-id>"
            "<vendor-name>Roku</vendor-name>"
            "<model-name>Simulated Roku</model-name>"
            "<model-number>SIM-1</model-number>"
            "<model-region>US</model-region>"
            "<is-tv>true</is-tv>"
            "<is-stick>false</is-stick>"
            "<user-device-name>%s</user-device-name>"
            "<software-version>1.0.0</software-version>"
            "<software-build>1</software-build>"
            "<power-mode>%s</power-mode>"
            "<network-type>wifi</network-type>"
            "<network-name>sim-wifi</network-name>"
            "<supports-find-remote>false</supports-find-remote>"
            "<supports-audio-volume-control>true</supports-audio-volume-control>"
            "<supports-tv-power-control>true</supports-tv-power-control>"
            "<supports-ethernet>false</supports-ethernet>"
            "<wifi-mac>aa:bb:cc:dd:ee:ff</wifi-mac>"
            "</device-info>"
            % (
                info.get("serial") or "x",
                info.get("serial") or "SIM000000000",
                info.get("serial") or "x",
                info.get("name") or "Sim Roku",
                mode,
            )
        ).encode("utf-8")

    def _active_app_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>'
            "<active-app>"
            '<app id="%s">%s</app>'
            "</active-app>"
            % (self._active_id, self._active_name)
        ).encode("utf-8")

    def _media_xml(self):
        if not self._power_on or not self._play_state:
            return (
                b'<?xml version="1.0" encoding="UTF-8" ?>'
                b'<player error="false" state="stop"></player>'
            )
        pos = self._format_clock(self._position_ms)
        dur = self._format_clock(self._duration_ms)
        return (
            '<?xml version="1.0" encoding="UTF-8" ?>'
            '<player error="false" state="%s">'
            '<plugin id="%s" name="%s"/>'
            '<format audio="aac" captions="none" drm="none" video="mpeg4"/>'
            "<position>%s</position>"
            "<duration>%s</duration>"
            "</player>"
            % (
                self._play_state,
                self._active_id,
                self._active_name,
                pos,
                dur,
            )
        ).encode("utf-8")

    @staticmethod
    def _format_clock(ms):
        total = max(0, int(ms) // 1000)
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        return "%d:%02d:%02d.000" % (h, m, s)

    def _apply_key(self, key):
        key = str(key)
        if key == "Play":
            if self._play_state == "play":
                self._play_state = "pause"
            else:
                self._play_state = "play"
        elif key in ("PowerOn", "Power"):
            self._power_on = True
        elif key == "PowerOff":
            self._power_on = False
        elif key == "Fwd":
            self._position_ms = min(self._duration_ms, self._position_ms + 15000)
        elif key == "Rev":
            self._position_ms = max(0, self._position_ms - 15000)
        elif key == "Home":
            self._active_id = ""
            self._active_name = "Home"
            self._play_state = ""
        # Advance clock a little on any key while playing.
        if self._play_state == "play":
            self._position_ms = min(self._duration_ms, self._position_ms + 1000)

    def _apply_launch(self, app_id):
        app_id = str(app_id)
        names = {
            "12": "Netflix",
            "13": "Prime Video",
            "151908": "Disney Plus",
            "2285": "Hulu",
            "837": "YouTube",
            "tvinput.dtv": "Live TV",
            "tvinput.hdmi1": "HDMI 1",
            "tvinput.hdmi2": "HDMI 2",
        }
        self._active_id = app_id
        self._active_name = names.get(app_id, "App " + app_id)
        self._play_state = "play"
        self._position_ms = 30000
        self._power_on = True

    def _request(self, method, path, data=b""):
        if not self.host:
            self.last_error = "no host"
            return 0, b""
        if self.host not in self._by_host and not path.startswith("/query/"):
            # Still allow queries after set_host to a known sim IP.
            pass
        method = (method or "GET").upper()
        path = path or "/"

        if method == "POST" and path.startswith("/keypress/"):
            self._apply_key(path.split("/", 2)[-1])
            self.connected = True
            self.last_error = ""
            return 200, b""
        if method == "POST" and path.startswith("/keydown/"):
            self.connected = True
            self.last_error = ""
            return 200, b""
        if method == "POST" and path.startswith("/keyup/"):
            self.connected = True
            self.last_error = ""
            return 200, b""
        if method == "POST" and path.startswith("/launch/"):
            app_id = path[len("/launch/") :].split("?")[0]
            self._apply_launch(app_id)
            self.connected = True
            self.last_error = ""
            return 200, b""
        if method == "POST" and path.startswith("/install/"):
            self.connected = True
            self.last_error = ""
            return 200, b""
        if method == "POST" and path.startswith("/input"):
            self.connected = True
            self.last_error = ""
            return 200, b""
        if method == "POST" and path.startswith("/exit-app"):
            self._active_id = ""
            self._active_name = "Home"
            self._play_state = ""
            self.connected = True
            self.last_error = ""
            return 200, b""

        if method == "GET" and path.startswith("/query/device-info"):
            self.connected = True
            self.last_error = ""
            return 200, self._device_xml(self.host)
        if method == "GET" and path.startswith("/query/apps"):
            self.connected = True
            self.last_error = ""
            return 200, _SIM_APPS_XML.encode("utf-8")
        if method == "GET" and path.startswith("/query/active-app"):
            self.connected = True
            self.last_error = ""
            return 200, self._active_app_xml()
        if method == "GET" and path.startswith("/query/media-player"):
            self.connected = True
            self.last_error = ""
            return 200, self._media_xml()
        if method == "GET" and path.startswith("/query/tv-active-channel"):
            return 200, b"<tv-channel><number>7.1</number><name>Sim Network</name></tv-channel>"
        if method == "GET" and path.startswith("/query/tv-channels"):
            return 200, b"<tv-channels><channel><number>7.1</number><name>Sim Network</name></channel></tv-channels>"
        if method == "GET" and path.startswith("/query/chanperf"):
            return 200, b"cpu=12 mem=34"
        if method == "GET" and path.startswith("/query/icon/"):
            return 200, b""
        if method == "GET" and path.startswith("/query/"):
            return 200, b"<ok/>"

        self.last_error = "sim: unhandled %s %s" % (method, path)
        return 404, b""

    def discover(
        self, timeout=1.5, retries=1, scan_fallback=True, ssdp=True, on_device=None
    ):
        found = [dict(d) for d in self._sim_cache]
        for info in found:
            if on_device is not None:
                try:
                    on_device(info)
                except Exception:
                    pass
        self.discovered = found
        self.last_error = "" if found else "no Roku found"
        return self.discovered

    def cached_devices(self):
        return [dict(d) for d in self._sim_cache]

    def remember_devices(self, devices):
        for info in devices or []:
            host = (info.get("host") or "").strip()
            if not host:
                continue
            row = {
                "host": host,
                "name": info.get("name") or info.get("user-device-name") or "",
                "serial": info.get("serial") or info.get("serial-number") or "",
            }
            self._by_host[host] = row
            replaced = False
            for i, old in enumerate(self._sim_cache):
                if old.get("host") == host or (
                    row["serial"] and old.get("serial") == row["serial"]
                ):
                    self._sim_cache[i] = row
                    replaced = True
                    break
            if not replaced:
                self._sim_cache.append(row)
        return True

    def forget_device(self, host):
        host = (host or "").strip()
        before = len(self._sim_cache)
        self._sim_cache = [d for d in self._sim_cache if d.get("host") != host]
        self._by_host.pop(host, None)
        return len(self._sim_cache) < before

    def refresh_cached_names(self):
        return self.cached_devices()

    def resume_last_host(self):
        """Connect the first sim TV so gallery opens on the remote page."""
        devices = self.cached_devices() or self.discover()
        if not devices:
            return False
        self.set_host(devices[0]["host"])
        return self.connect()

    def connect(self, discover_if_empty=True):
        """Ping device-info for the current host (no auto-discover / auto-pick)."""
        del discover_if_empty
        if not self.host:
            self.last_error = "no host"
            self.connected = False
            return False
        info = self.query_device_info()
        self.connected = bool(info)
        if self.connected:
            try:
                self.remember_devices(
                    [
                        {
                            "host": self.host,
                            "name": info.get("user-device-name")
                            or info.get("model-name")
                            or "",
                            "serial": info.get("serial-number") or "",
                        }
                    ]
                )
            except Exception:
                pass
            try:
                self.refresh_playback()
            except Exception:
                pass
            try:
                if not self.apps:
                    self.query_apps()
            except Exception:
                pass
        return self.connected
