# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
tools
====================================================
The assistant's hands: the functions Gemini may call, and their
declarations.

The Roku tools come in three modes, chosen by ``Tools(roku_mode=...)``:

* ``"dry-run"`` (the default): talks to the real TV, but only ``GET``
  queries leave the machine. Every ``POST`` (a keypress, a launch) is
  printed and recorded instead of sent, at the transport, so no code path
  can slip one through.
* ``"sim"``: the roku_remote simulator; nothing touches the network.
* ``"live"``: keys really go to the TV. Only a harmless set of keys is
  allowed even then.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "roku_remote"))

import roku_engine  # noqa: E402

ROKU_HOST = "192.168.1.129"
HUB_HOST = "192.168.1.137"

# Keys the assistant may press. No input switching, no text entry.
SAFE_KEYS = (
    "Home", "Back", "Select", "Up", "Down", "Left", "Right", "Play", "Rev",
    "Fwd", "InstantReplay", "Info", "VolumeUp", "VolumeDown", "VolumeMute",
    "PowerOn", "PowerOff",
)

# A few well-known ECP channel ids, so "open YouTube" needs no lookup.
KNOWN_APPS = {"youtube": "837", "netflix": "12", "prime video": "13", "hulu": "2285", "disney plus": "151908"}

DECLARATIONS = [
    {
        "name": "roku_status",
        "description": "Read the living-room Roku TV's state: power, the app on screen, and whether something is playing. Read-only.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "roku_press",
        "description": "Press one remote button on the living-room Roku TV.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": list(SAFE_KEYS)},
                "repeat": {"type": "integer", "description": "How many times, 1 to 10. Default 1."},
            },
            "required": ["key"],
        },
    },
    {
        "name": "roku_volume",
        "description": "Turn the living-room TV's volume up or down by a number of steps, or toggle mute.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "mute"]},
                "steps": {"type": "integer", "description": "1 to 10; a small change is 2 or 3. Default 3."},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "roku_power",
        "description": "Turn the living-room TV on or off.",
        "parameters": {
            "type": "object",
            "properties": {"state": {"type": "string", "enum": ["on", "off"]}},
            "required": ["state"],
        },
    },
    {
        "name": "roku_launch",
        "description": "Open an app on the living-room Roku TV, e.g. YouTube or Netflix.",
        "parameters": {
            "type": "object",
            "properties": {"app": {"type": "string", "description": "The app's name."}},
            "required": ["app"],
        },
    },
    {
        "name": "hub_read",
        "description": (
            "Read the latest values from the house sensor hub: every node and its readings "
            "(for example temperature, humidity, a phone's battery, a PC's load). Use it for any "
            "question about temperature, climate or sensors."
        ),
        "parameters": {
            "type": "object",
            "properties": {"node": {"type": "string", "description": "Optional: only this node."}},
        },
    },
    {
        "name": "camera_snapshot",
        "description": "Take a still from the camera and answer a question about what it sees.",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "What to look for or describe."}},
            "required": ["question"],
        },
    },
]


def _dry_transport(log):
    """An ECP transport that lets GETs through and records POSTs."""

    def http(method, url, timeout, data):
        if method.upper() == "GET":
            return roku_engine.http_request("GET", url, timeout=timeout)
        log.append(method.upper() + " " + url)
        print("  [dry-run] would send:", method.upper(), url)
        return 200, b""

    return http


def _sim_transport(engine):
    def http(method, url, timeout, data):
        path = "/" + url.split("/", 3)[3]
        return engine._request(method, path, data)

    return http


class Tools:
    def __init__(self, gemini=None, roku_mode="dry-run", roku_host=ROKU_HOST, hub_host=HUB_HOST, camera=None):
        self.gemini = gemini
        self.roku_mode = roku_mode
        self.hub_host = hub_host
        self.camera = camera  # a callable returning JPEG bytes, or None
        self.sent = []  # the POSTs dry-run held back, or sim/live sent
        self.calls = []  # (name, args, result) for every tool call
        if roku_mode == "sim":
            import roku_sim

            self.roku = roku_sim.RokuSimEngine(host="192.168.1.50", reason="env")
            self.roku._http = _sim_transport(self.roku)
        else:
            self.roku = roku_engine.RokuEngine(host=roku_host, timeout=3.0)
            if roku_mode == "dry-run":
                self.roku._http = _dry_transport(self.sent)
            elif roku_mode != "live":
                raise ValueError("roku_mode: dry-run, sim or live")

    # -- dispatch ----------------------------------------------------------
    def call(self, name, args):
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            result = {"error": "no such tool: " + name}
        else:
            try:
                result = fn(**(args or {}))
            except Exception as e:  # report it to the model, don't crash
                result = {"error": "%s: %s" % (type(e).__name__, e)}
        self.calls.append((name, args, result))
        return result

    # -- Roku --------------------------------------------------------------
    def _press(self, key, n=1):
        if key not in SAFE_KEYS:
            return {"error": "key not allowed: " + key}
        n = max(1, min(10, int(n or 1)))
        ok = all(self.roku.press(key) for _ in range(n))
        return {"ok": ok, "key": key, "times": n, "mode": self.roku_mode}

    def t_roku_status(self):
        info = self.roku.query_device_info() or {}
        app = self.roku.query_active_app() or {}
        self.roku.query_media_player()
        media = self.roku.media_state or {}
        if not info and not app:
            return {"error": "TV did not answer: " + (self.roku.last_error or "no reply")}
        return {
            "name": info.get("user-device-name", ""),
            "power": info.get("power-mode", "on" if self.roku_mode == "sim" else ""),
            "app": app.get("name", ""),
            "screensaver": getattr(self.roku, "active_screensaver", ""),
            "playback": media.get("state", ""),
        }

    def t_roku_press(self, key, repeat=1):
        return self._press(key, repeat)

    def t_roku_volume(self, direction, steps=3):
        if direction == "mute":
            return self._press("VolumeMute")
        return self._press("VolumeUp" if direction == "up" else "VolumeDown", steps)

    def t_roku_power(self, state):
        return self._press("PowerOn" if state == "on" else "PowerOff")

    def t_roku_launch(self, app):
        app_id = KNOWN_APPS.get(app.strip().lower())
        if app_id is None:
            for a in self.roku.query_apps() or []:
                if a.get("name", "").lower() == app.strip().lower():
                    app_id = a.get("id")
                    break
        if app_id is None:
            return {"error": "no app called " + app}
        return {"ok": self.roku.launch(app_id), "app": app, "id": app_id, "mode": self.roku_mode}

    # -- sensor hub --------------------------------------------------------
    def t_hub_read(self, node=None):
        status, body = roku_engine.http_request("GET", "http://%s/api/readings" % self.hub_host, timeout=5.0)
        if status != 200:
            return {"error": "hub at %s did not answer (status %s)" % (self.hub_host, status)}
        data = json.loads(body)
        out = {}
        for name, n in data.get("nodes", {}).items():
            if node and name != node:
                continue
            latest = {k: v[-1] for k, v in n.get("series", {}).items() if v}
            out[name] = {"latest": latest, "age_s": round(n.get("age_ms", 0) / 1000, 1)}
        return {"hub": data.get("hub", ""), "nodes": out}

    # -- camera ------------------------------------------------------------
    def t_camera_snapshot(self, question):
        if self.camera is None:
            return {"error": "no camera connected"}
        if self.gemini is None:
            return {"error": "no vision client"}
        jpeg = self.camera()
        answer = self.gemini.describe(jpeg, prompt=question + " Answer in one or two sentences.")
        return {"answer": answer, "latency_s": round(self.gemini.last_latency, 2), "bytes": len(jpeg)}


def file_camera(path, max_side=640):
    """A stand-in camera: a JPEG from disk, scaled like a board's still."""

    def snap():
        try:
            from PIL import Image
            import io

            im = Image.open(path).convert("RGB")
            im.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            return buf.getvalue()
        except ImportError:
            with open(path, "rb") as f:
                return f.read()

    return snap


def url_camera(url, timeout=10.0):
    """A camera that serves a JPEG over HTTP (the P4's snapshot endpoint)."""

    def snap():
        status, body = roku_engine.http_request("GET", url, timeout=timeout)
        if status != 200:
            raise OSError("camera %s: HTTP %s" % (url, status))
        return body

    return snap
