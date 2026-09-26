# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Unit tests for ``lib/examples/roku_remote/roku_knob`` -- the knob front end.

No window and no TV: ``appdev`` and ``board_config`` are stand-ins, and the
engine's HTTP goes through its ``_http`` test hook, which records every
request and answers from canned ECP replies.
"""

import os
import sys
import tempfile
import time
import types
import unittest

import _env  # noqa: F401

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PKG = os.path.join(_REPO, "lib", "examples", "roku_remote")
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

# connect() writes the remote's prefs under $HOME; keep them out of yours.
os.environ["HOME"] = tempfile.mkdtemp(prefix="roku_knob_test_")

import events  # noqa: E402
import keys  # noqa: E402


class _Display:
    width = 170
    height = 320

    def __init__(self):
        self.blits = 0

    def blit_rect(self, buf, x, y, w, h):
        self.blits += 1


class _App:
    events = events

    def __init__(self, board_config=None):
        self.handlers = {}
        self.quit = False

    def on(self, kind, fn):
        self.handlers.setdefault(kind, []).append(fn)

    def every(self, ms, fn):
        return None

    def request_quit(self, code=None):
        self.quit = True


_board = types.ModuleType("board_config")
_board.display_drv = _Display()
_appdev = types.ModuleType("appdev")
_appdev.App = _App
sys.modules["board_config"] = _board
sys.modules["appdev"] = _appdev

os.environ.pop("ROKU_SENDS", None)
import roku_engine  # noqa: E402

# Read before any test touches it: a fresh import must come up locked.
_LOCKED_AT_IMPORT = not roku_engine.sends_enabled()
roku_engine._LAUNCHER_OWNS_RUN = True
import roku_knob  # noqa: E402

_DEVICE = (
    b"<device-info><serial-number>X1</serial-number><is-tv>true</is-tv>"
    b"<user-device-name>Test TV</user-device-name><power-mode>PowerOn</power-mode>"
    b"</device-info>"
)
_ACTIVE = b'<active-app><app id="837" type="appl">YouTube</app></active-app>'
_MEDIA = (
    b'<player state="play" error="false"><plugin id="837" name="YouTube" />'
    b"<position>5042605 ms</position></player>"
)


class _Fake:
    def __init__(self):
        self.posts = []
        self.gets = []

    def __call__(self, method, url, timeout, data):
        path = url.split(":8060", 1)[1]
        if method == "POST":
            self.posts.append(path)
            return 200, b""
        self.gets.append(path)
        body = {
            "/query/device-info": _DEVICE,
            "/query/active-app": _ACTIVE,
            "/query/media-player": _MEDIA,
            "/query/apps": b'<apps><app id="837">YouTube</app></apps>',
        }.get(path, b"")
        return (200, body) if body else (404, b"")


def _remote():
    eng = roku_engine.RokuEngine(host="10.0.0.9")
    fake = _Fake()
    eng._http = fake
    eng.query_device_info()
    k = roku_knob.KnobRemote(engine=eng, start_page="remote")
    return k, fake


def _pump(k, n=12):
    for _ in range(n):
        k._tick_body()


def _key(code):
    return types.SimpleNamespace(key=code)


class KnobTests(unittest.TestCase):
    def test_turning_sends_one_volume_key_per_detent(self):
        k, fake = _remote()
        k.turn(3)
        k.turn(-1)
        _pump(k)
        self.assertEqual(fake.posts, ["/keypress/VolumeUp"] * 2)
        self.assertEqual(k.vol_recent, 2)

    def test_press_opens_menu_and_hold_is_play(self):
        k, fake = _remote()
        k.button(True)
        k.button(False)
        self.assertEqual(k.page, "menu")
        self.assertEqual(fake.posts, [])
        k.button(True)
        k.down_at -= roku_knob.HOLD_MS + 50  # held long enough
        _pump(k, 2)
        k.button(False)
        self.assertEqual(fake.posts, ["/keypress/Play"])
        self.assertEqual(k.page, "menu")  # a hold does not also press

    def test_navigate_hands_the_knob_to_the_tv(self):
        k, fake = _remote()
        k._open_menu()
        k._nav(roku_knob._NAV_LR)
        k.turn(-2)
        k.press()
        _pump(k)
        self.assertEqual(fake.posts, ["/keypress/Left", "/keypress/Left", "/keypress/Select"])
        k.last_input -= roku_knob.NAV_IDLE_MS + 1
        _pump(k, 1)
        self.assertEqual(k.page, "now")

    def test_arrow_keys_and_enter_stand_in_for_the_knob(self):
        k, fake = _remote()
        k._on_key(_key(keys.K_UP))
        k._on_key(_key(keys.K_UP))
        _pump(k)
        self.assertEqual(fake.posts, ["/keypress/VolumeUp"] * 2)
        k._on_key(_key(keys.K_RETURN))
        k._on_key(_key(keys.K_RETURN))  # key repeat is ignored
        k._on_keyup(_key(keys.K_RETURN))
        self.assertEqual(k.page, "menu")
        k._on_key(_key(keys.K_ESCAPE))
        self.assertTrue(roku_knob.app.quit)

    def test_now_playing_reads_ecp(self):
        k, _ = _remote()
        k._refresh()
        self.assertEqual(k.engine.playback_app_label(), "YouTube")
        self.assertEqual(k.engine.playback_state_label(), "play")
        before = _board.display_drv.blits
        k.draw()
        self.assertEqual(_board.display_drv.blits, before + 1)

    def test_manual_address_connects(self):
        k, fake = _remote()
        k._open_ip()
        k.ip = [10, 0, 0, 8]
        k.ip_part = 3
        k.turn(1)
        k.press()
        _pump(k, 3)
        self.assertEqual(k.engine.host, "10.0.0.9")
        self.assertEqual(k.page, "now")
        self.assertEqual(fake.posts, [])

    def test_hold_cancels_the_address_editor(self):
        k, fake = _remote()
        k._open_tvs()
        k.jobs.clear()  # skip the LAN search
        k._open_ip()
        k.button(True)
        k.down_at -= roku_knob.HOLD_MS + 50
        _pump(k, 1)
        k.button(False)
        self.assertEqual(k.page, "tvs")
        self.assertEqual(fake.posts, [])


class _Recorder:
    """A local HTTP server that records the request line of every request."""

    def __init__(self):
        import socket
        import threading

        self.lines = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            conn.settimeout(2)
            try:
                data = conn.recv(4096)
                if data:
                    self.lines.append(data.split(b"\r\n", 1)[0].decode())
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 13\r\n"
                        b"Connection: close\r\n\r\n<device-info>"
                    )
            except OSError:
                pass
            finally:
                conn.close()

    def close(self):
        self.stop = True
        self.sock.close()


class SendLockTests(unittest.TestCase):
    """No ECP POST reaches the network until sends are enabled."""

    def setUp(self):
        roku_engine.enable_sends(False)
        self.srv = _Recorder()
        self.eng = roku_engine.RokuEngine(host="127.0.0.1", port=self.srv.port)

    def tearDown(self):
        roku_engine.enable_sends(False)
        self.srv.close()

    def _settle(self):
        time.sleep(0.2)

    def test_locked_by_default_on_every_path(self):
        self.assertTrue(_LOCKED_AT_IMPORT)
        self.assertFalse(self.eng.press("VolumeUp"))
        self.assertIn("locked", self.eng.last_error)
        self.assertFalse(self.eng.press("VolumeUp", wait=False))
        self.assertFalse(self.eng.launch("837"))
        self.assertFalse(self.eng.keydown("Up"))
        with self.assertRaises(roku_engine.SendsLocked):
            roku_engine.http_request("POST", "http://127.0.0.1:%d/x" % self.srv.port)
        # A query still goes out.
        self.eng.query_device_info()
        self._settle()
        self.assertEqual(
            [ln.rsplit(" ", 1)[0] for ln in self.srv.lines], ["GET /query/device-info"]
        )

    def test_knob_shows_the_lock(self):
        k = roku_knob.KnobRemote(engine=self.eng, start_page="remote")
        k.turn(1)
        _pump(k, 2)
        self._settle()
        self.assertFalse(any(ln.startswith("POST") for ln in self.srv.lines))
        self.assertIn("locked", k.message[0])

    def test_enabled_sends_reach_the_tv(self):
        roku_engine.enable_sends()
        self.assertTrue(self.eng.press("VolumeUp"))
        self._settle()
        self.assertIn("POST /keypress/VolumeUp", [ln.rsplit(" ", 1)[0] for ln in self.srv.lines])


class LauncherTests(unittest.TestCase):
    def test_knob_board_detection(self):
        # Import the launcher's helpers without running it.
        with open(os.path.join(_PKG, "roku_remote.py")) as f:
            src = f.read()
        src = src[: src.rindex("\nmain()")]
        ns = {"__file__": os.path.join(_PKG, "roku_remote.py"), "__name__": "x"}
        exec(compile(src, "roku_remote.py", "exec"), ns)
        _board.encoder_read = lambda: 0
        try:
            self.assertTrue(ns["_knob_board"]())
            _board.touch_read = lambda: None
            self.assertFalse(ns["_knob_board"]())
        finally:
            del _board.encoder_read
            if hasattr(_board, "touch_read"):
                del _board.touch_read
        self.assertFalse(ns["_knob_board"]())


if __name__ == "__main__":
    unittest.main()
