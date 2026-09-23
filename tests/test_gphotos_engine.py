# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Unit tests for ``lib/examples/google_photos`` (engine, simulator) and
``tools/gphotos_auth.py`` -- all network traffic is faked."""

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request

import _env  # noqa: F401

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PKG = os.path.join(_REPO, "lib", "examples", "google_photos")
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)
_TOOLS = os.path.join(_REPO, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import gphotos_auth  # noqa: E402
import gphotos_engine as ge  # noqa: E402
import gphotos_sim as gs  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
TOKENS = {"client_id": "cid", "client_secret": "sec", "refresh_token": "rt"}


def _picked(i, base="https://lh3.example/photo%d"):
    return {
        "id": "item-%d" % i,
        "createTime": "2024-05-%02dT14:22:11Z" % (i + 1),
        "type": "PHOTO",
        "mediaFile": {
            "baseUrl": base % i,
            "mimeType": "image/jpeg",
            "filename": "IMG_%d.jpg" % i,
            "mediaFileMetadata": {"width": "4032", "height": "3024"},
        },
    }


class FakeTransport:
    """Stands in for ``gphotos_engine._transport``; routes by (method, url prefix)."""

    def __init__(self):
        self.calls = []
        self.routes = []  # (method, url_prefix, handler)

    def route(self, method, prefix, handler):
        self.routes.append((method, prefix, handler))

    def __call__(self, method, url, headers, body, timeout, sink=None):
        self.calls.append((method, url, dict(headers or {}), body))
        for m, prefix, handler in self.routes:
            if m == method and url.startswith(prefix):
                status, payload = handler(url, headers or {}, body)
                if isinstance(payload, (dict, list)):
                    payload = json.dumps(payload).encode("utf-8")
                if sink is not None:
                    sink(payload)
                    return status, len(payload)
                return status, payload
        raise AssertionError("unexpected %s %s" % (method, url))


def token_ok(url, headers, body):
    return 200, {"access_token": "AT1", "expires_in": 3600, "token_type": "Bearer"}


class HelperTests(unittest.TestCase):
    def test_quote_and_form(self):
        self.assertEqual(ge.quote("a b/c~d"), "a%20b%2Fc~d")
        self.assertEqual(ge.form_encode([("a", "1 2"), ("b", "x&y")]), "a=1%202&b=x%26y")

    def test_labels_and_durations(self):
        self.assertEqual(ge.parse_duration_s("5s"), 5.0)
        self.assertEqual(ge.parse_duration_s("1.5s"), 1.5)
        self.assertEqual(ge.parse_duration_s(None, 7.0), 7.0)
        self.assertEqual(ge.parse_duration_s("junk", 3.0), 3.0)
        self.assertEqual(ge.date_label("2024-05-03T14:22:11Z"), "2024-05-03")
        self.assertEqual(ge.time_label("2024-05-03T14:22:11Z"), "14:22")
        self.assertEqual(ge.time_label("2024-05-03"), "")
        self.assertEqual(len(ge.item_hash("anything")), 8)
        self.assertNotEqual(ge.item_hash("a"), ge.item_hash("b"))

    def test_thumb_url_and_sniff(self):
        self.assertEqual(ge.thumb_url("https://x/y", 64, 64, True), "https://x/y=w64-h64-c")
        self.assertEqual(ge.thumb_url("https://x/y", 320, 400), "https://x/y=w320-h400")
        self.assertEqual(ge.thumb_url("", 1, 1), "")
        self.assertEqual(ge.sniff_ext(JPEG), ".jpg")
        self.assertEqual(ge.sniff_ext(PNG), ".png")
        self.assertEqual(ge.sniff_ext(b"<html>"), "")

    def test_normalize_item(self):
        item = ge.normalize_item(_picked(3))
        self.assertEqual(item["id"], "item-3")
        self.assertEqual(item["filename"], "IMG_3.jpg")
        self.assertEqual(item["width"], 4032)
        self.assertEqual(item["baseUrl"], "https://lh3.example/photo3")
        self.assertEqual(ge.normalize_item("nope"), {})

    def test_path_overrides(self):
        with mock.patch.dict(
            os.environ, {"GPHOTOS_TOKENS": "/tmp/t.json", "GPHOTOS_CACHE": "/tmp/c"}
        ):
            self.assertEqual(ge.tokens_path(), "/tmp/t.json")
            self.assertEqual(ge.cache_dir(), "/tmp/c")
        with mock.patch.dict(os.environ, {"HOME": "/home/x"}, clear=False):
            os.environ.pop("GPHOTOS_PREFS", None)
            self.assertEqual(ge.prefs_path(), "/home/x/.gphotos_prefs")


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.transport = FakeTransport()
        patcher = mock.patch.object(ge, "_transport", self.transport)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, tokens=TOKENS, **kw):
        return ge.GPhotosEngine(
            tokens=dict(tokens),
            prefs_file=os.path.join(self.tmp.name, "prefs"),
            cache_path=os.path.join(self.tmp.name, "cache"),
            **kw,
        )


class TokenTests(EngineTestCase):
    def test_missing_credentials(self):
        eng = self.make(tokens={})
        self.assertFalse(eng.has_credentials())
        self.assertFalse(eng.ensure_token())
        self.assertIn("gphotos_auth", eng.last_error)
        self.assertEqual(self.transport.calls, [])

    def test_refresh_then_cache_then_force(self):
        self.transport.route("POST", ge.TOKEN_URL, token_ok)
        eng = self.make()
        self.assertTrue(eng.ensure_token())
        self.assertEqual(eng.access_token, "AT1")
        _method, _url, headers, body = self.transport.calls[0]
        self.assertEqual(headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertIn(b"grant_type=refresh_token", body)
        self.assertIn(b"refresh_token=rt", body)
        self.assertIn(b"client_secret=sec", body)
        self.assertTrue(eng.ensure_token())
        self.assertEqual(len(self.transport.calls), 1)
        self.assertTrue(eng.ensure_token(force=True))
        self.assertEqual(len(self.transport.calls), 2)

    def test_refresh_failure_reports_google_error(self):
        self.transport.route(
            "POST",
            ge.TOKEN_URL,
            lambda u, h, b: (
                400,
                {"error": "invalid_grant", "error_description": "Token has been expired"},
            ),
        )
        eng = self.make()
        self.assertFalse(eng.ensure_token())
        self.assertEqual(
            eng.last_error, "token refresh: HTTP 400 invalid_grant: Token has been expired"
        )

    def test_network_failure(self):
        def boom(*a, **k):
            raise ge.GPhotosError("dns")

        with mock.patch.object(ge, "_transport", boom):
            eng = self.make()
            self.assertFalse(eng.ensure_token())
            self.assertIn("dns", eng.last_error)


class SessionTests(EngineTestCase):
    def setUp(self):
        super().setUp()
        self.transport.route("POST", ge.TOKEN_URL, token_ok)
        self.session = {
            "id": "sess/1",
            "pickerUri": "https://photospicker.google.com/s/1",
            "pollingConfig": {"pollInterval": "3s", "timeoutIn": "1800s"},
            "expireTime": "2030-01-01T00:00:00Z",
            "mediaItemsSet": False,
        }
        self.polls = 0

        def create(url, headers, body):
            self.assertEqual(headers["Authorization"], "Bearer AT1")
            self.assertEqual(body, b"{}")
            return 200, self.session

        def poll(url, headers, body):
            self.polls += 1
            data = dict(self.session)
            data["mediaItemsSet"] = self.polls >= 2
            return 200, data

        def listing(url, headers, body):
            if "pageToken=" in url:
                return 200, {"mediaItems": [_picked(2)]}
            return 200, {"mediaItems": [_picked(0), _picked(1)], "nextPageToken": "p2"}

        self.transport.route("POST", ge.PICKER_BASE + "/sessions", create)
        self.transport.route("GET", ge.PICKER_BASE + "/sessions/", poll)
        self.transport.route("GET", ge.PICKER_BASE + "/mediaItems?", listing)
        self.transport.route("GET", "https://lh3.example/photo", lambda u, h, b: (200, JPEG))

    def test_full_flow_and_prefs_roundtrip(self):
        eng = self.make()
        s = eng.create_session()
        self.assertEqual(s["id"], "sess/1")
        self.assertEqual(s["pollInterval"], 3.0)
        self.assertEqual(eng.poll_interval_s(), 3.0)
        self.assertFalse(eng.poll_session())
        self.assertTrue(eng.poll_session())
        items = eng.list_items()
        self.assertEqual([i["id"] for i in items], ["item-0", "item-1", "item-2"])
        self.assertTrue(eng.urls_valid())
        list_calls = [c for c in self.transport.calls if "/mediaItems?" in c[1]]
        self.assertEqual(len(list_calls), 2)
        self.assertIn("sessionId=sess%2F1", list_calls[0][1])

        # prefs: session + items persisted, urls not
        with open(eng.prefs_file) as f:
            prefs = json.load(f)
        self.assertEqual(prefs["session"]["id"], "sess/1")
        self.assertEqual(len(prefs["items"]), 3)
        self.assertNotIn("baseUrl", prefs["items"][0])

        other = self.make()
        self.assertTrue(other.restore())
        self.assertEqual(other.session["pickerUri"], "https://photospicker.google.com/s/1")
        self.assertEqual(len(other.items), 3)
        self.assertFalse(other.urls_valid())
        self.assertEqual(other.count_label(), "3 photos")

    def test_thumbnail_download_cache_and_refresh(self):
        eng = self.make()
        eng.create_session()
        eng.list_items()
        item = eng.items[1]
        path = eng.thumbnail_path(item, 64, 64, crop=True)
        self.assertTrue(path.endswith("_64x64c.jpg"), path)
        self.assertTrue(os.path.isfile(path))
        dl = [c for c in self.transport.calls if c[1].startswith("https://lh3.example")]
        self.assertEqual(dl[-1][1], "https://lh3.example/photo1=w64-h64-c")
        self.assertEqual(dl[-1][2]["Authorization"], "Bearer AT1")
        n = len(self.transport.calls)
        self.assertEqual(eng.thumbnail_path(item, 64, 64, crop=True), path)
        self.assertEqual(len(self.transport.calls), n)  # served from cache

        # restored engine has no urls: thumbnail fetch re-lists first
        other = self.make()
        other.restore()
        before = len(self.transport.calls)
        view = other.thumbnail_path(other.items[2], 320, 400)
        self.assertTrue(view.endswith("_320x400.jpg"))
        urls = [c[1] for c in self.transport.calls[before:]]
        self.assertTrue(any("/mediaItems?" in u for u in urls))
        self.assertIn("https://lh3.example/photo2=w320-h400", urls)

    def test_png_and_bad_downloads(self):
        self.transport.routes = [
            r for r in self.transport.routes if not r[1].startswith("https://lh3")
        ]
        self.transport.route("GET", "https://lh3.example/photo0", lambda u, h, b: (200, PNG))
        self.transport.route("GET", "https://lh3.example/photo1", lambda u, h, b: (403, b"denied"))
        self.transport.route("GET", "https://lh3.example/photo2", lambda u, h, b: (200, b"<html>"))
        eng = self.make()
        eng.create_session()
        eng.list_items()
        self.assertTrue(eng.thumbnail_path(eng.items[0], 96, 96, True).endswith(".png"))
        self.assertEqual(eng.thumbnail_path(eng.items[1], 96, 96, True), "")
        self.assertIn("403", eng.last_error)
        self.assertEqual(eng.thumbnail_path(eng.items[2], 96, 96, True), "")
        self.assertIn("not an image", eng.last_error)
        leftovers = [n for n in os.listdir(eng.cache_path) if not n.endswith(".png")]
        self.assertEqual(leftovers, [])

    def test_401_refreshes_token_once(self):
        seen = {"n": 0}

        def flaky(url, headers, body):
            seen["n"] += 1
            if seen["n"] == 1:
                return 401, {"error": {"message": "expired"}}
            return 200, self.session

        self.transport.routes = [
            r for r in self.transport.routes if not r[1].endswith("/sessions")
        ]
        self.transport.route("POST", ge.PICKER_BASE + "/sessions", flaky)
        eng = self.make()
        self.assertIsNotNone(eng.create_session())
        tokens = [c for c in self.transport.calls if c[1] == ge.TOKEN_URL]
        self.assertEqual(len(tokens), 2)

    def test_session_gone(self):
        eng = self.make()
        eng.create_session()
        self.transport.routes = [
            r for r in self.transport.routes if not r[1].endswith("/sessions/")
        ]
        self.transport.route(
            "GET",
            ge.PICKER_BASE + "/sessions/",
            lambda u, h, b: (404, {"error": {"status": "NOT_FOUND", "message": "gone"}}),
        )
        self.assertFalse(eng.poll_session())
        self.assertIsNone(eng.session)
        self.assertIn("expired", eng.last_error)
        self.assertIsNone(eng.list_items())
        self.assertEqual(eng.last_error, "no session")

    def test_api_error_message(self):
        self.transport.routes = [
            r for r in self.transport.routes if not r[1].endswith("/sessions")
        ]
        self.transport.route(
            "POST",
            ge.PICKER_BASE + "/sessions",
            lambda u, h, b: (
                403,
                {"error": {"status": "PERMISSION_DENIED", "message": "API disabled"}},
            ),
        )
        eng = self.make()
        self.assertIsNone(eng.create_session())
        self.assertEqual(eng.last_error, "create session: HTTP 403 API disabled")

    def test_max_items_and_eviction(self):
        eng = self.make(max_items=2, cache_max=2)
        eng.create_session()
        self.assertEqual(len(eng.list_items()), 2)
        for w in (32, 48, 64):
            eng.thumbnail_path(eng.items[0], w, w, True)
        self.assertLessEqual(len(os.listdir(eng.cache_path)), 2)
        eng.forget(clear_cache=True)
        self.assertEqual(os.listdir(eng.cache_path), [])
        self.assertEqual(eng.items, [])
        self.assertFalse(self.make().restore())

    def test_delete_session(self):
        self.transport.route("DELETE", ge.PICKER_BASE + "/sessions/", lambda u, h, b: (200, {}))
        eng = self.make()
        eng.create_session()
        self.assertTrue(eng.delete_session())
        self.assertIsNone(eng.session)
        self.assertEqual(self.transport.calls[-1][0], "DELETE")


class FakeSocketModule:
    """Enough of ``socket`` for ``_socket_request`` (plain HTTP only)."""

    AF_INET = 2
    SOCK_STREAM = 1

    def __init__(self, response):
        self.response = response
        self.sent = b""
        self.closed = False

    def getaddrinfo(self, host, port, family, socktype):
        return [(self.AF_INET, socktype, 6, "", (host, port))]

    def socket(self, family, socktype, proto):
        return self

    def settimeout(self, t):
        pass

    def connect(self, addr):
        self.addr = addr

    def sendall(self, data):
        self.sent += bytes(data)

    def recv(self, n):
        chunk, self.response = self.response[:n], self.response[n:]
        return chunk

    def close(self):
        self.closed = True


class SocketFallbackTests(unittest.TestCase):
    def test_plain_http_roundtrip(self):
        body = b'{"ok": true}'
        raw = (
            b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
            % len(body)
            + body
        )
        fake = FakeSocketModule(raw)
        with mock.patch.object(ge, "socket", fake):
            status, out = ge._socket_request(
                "POST", "http://api.test:8080/v1/x?y=1", {"Authorization": "Bearer t"}, b"{}", 5.0
            )
        self.assertEqual((status, out), (200, body))
        self.assertEqual(fake.addr, ("api.test", 8080))
        head = fake.sent.split(b"\r\n\r\n", 1)[0]
        self.assertTrue(head.startswith(b"POST /v1/x?y=1 HTTP/1.0\r\nHost: api.test"))
        self.assertIn(b"Authorization: Bearer t", head)
        self.assertIn(b"Content-Length: 2", head)
        self.assertTrue(fake.sent.endswith(b"{}"))
        self.assertTrue(fake.closed)

    def test_streaming_sink_without_content_length(self):
        raw = b"HTTP/1.0 200 OK\r\n\r\n" + JPEG
        fake = FakeSocketModule(raw)
        chunks = []
        with mock.patch.object(ge, "socket", fake):
            status, n = ge._socket_request("GET", "http://h/p", {}, None, 5.0, sink=chunks.append)
        self.assertEqual((status, n), (200, len(JPEG)))
        self.assertEqual(b"".join(chunks), JPEG)


class RequestsBackendTests(unittest.TestCase):
    """The MicroPython ``requests`` path (urllib disabled)."""

    class Resp:
        def __init__(self, status, data):
            self.status_code = status
            self.content = data
            self.raw = io.BytesIO(data)
            self.closed = False

        def close(self):
            self.closed = True

    def test_request_and_stream(self):
        calls = []
        resp = [None]

        class Requests:
            @staticmethod
            def request(method, url, data=None, headers=None, stream=None, timeout=None):
                calls.append((method, url, data, headers, stream, timeout))
                resp[0] = RequestsBackendTests.Resp(200, JPEG)
                return resp[0]

        with mock.patch.object(ge, "_urllib", lambda: None), mock.patch.object(
            ge, "_find_requests", lambda: Requests
        ):
            self.assertEqual(
                ge.http_request("GET", "https://h/x", headers={"A": "b"}), (200, JPEG)
            )
            self.assertEqual(calls[-1][3], {"A": "b"})
            self.assertEqual(calls[-1][4], False)
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "f.bin")
                self.assertEqual(ge.http_download("https://h/x", path), (200, len(JPEG)))
                with open(path, "rb") as f:
                    self.assertEqual(f.read(), JPEG)
            self.assertEqual(calls[-1][4], True)
        self.assertTrue(resp[0].closed)


class SimTests(unittest.TestCase):
    def test_sim_reason(self):
        with mock.patch.dict(os.environ, {"GPHOTOS_SIM": "1"}):
            self.assertEqual(gs.sim_reason(TOKENS), "env")
        with mock.patch.dict(os.environ, {"GPHOTOS_SIM": "0"}):
            self.assertIsNone(gs.sim_reason(TOKENS))
        with mock.patch.dict(os.environ, {"GPHOTOS_SIM": ""}):
            os.environ.pop("GPHOTOS_SIM")
            self.assertEqual(gs.sim_reason({}), "no_credentials")
            with mock.patch.object(gs, "_network_available", lambda: False):
                self.assertEqual(gs.sim_reason(TOKENS), "no_network")
            with mock.patch.object(gs, "_network_available", lambda: True):
                self.assertIsNone(gs.sim_reason(TOKENS))

    def test_sim_flow(self):
        with mock.patch.dict(os.environ, {"GPHOTOS_SIM": "1"}):
            eng = gs.make_engine(tokens={})
        self.assertTrue(eng.sim)
        self.assertTrue(eng.restore())
        first = eng.items[0]["id"]
        self.assertTrue(eng.ensure_token())
        s = eng.create_session()
        self.assertEqual(eng.items, [])
        self.assertEqual(s["pickerUri"], gs.SIM_PICKER_URI)
        self.assertFalse(eng.poll_session())
        self.assertFalse(eng.poll_session())
        self.assertTrue(eng.poll_session())
        items = eng.list_items()
        self.assertEqual(len(items), len(gs._SIM_ITEMS))
        self.assertNotEqual(items[0]["id"], first)
        self.assertTrue(eng.urls_valid())
        # bundled assets (git checkout) resolve by size class
        tile = eng.thumbnail_path(items[0], 56, 56, crop=True)
        self.assertTrue(tile.endswith("_64.jpg"))
        self.assertTrue(eng.thumbnail_path(items[0], 120, 120, crop=True).endswith("_96.jpg"))
        landscape = next(i for i in items if not i["portrait"])
        portrait = next(i for i in items if i["portrait"])
        self.assertTrue(eng.thumbnail_path(landscape, 320, 400).endswith("_320x240.jpg"))
        self.assertTrue(eng.thumbnail_path(landscape, 200, 150).endswith("_160x120.jpg"))
        self.assertTrue(eng.thumbnail_path(portrait, 240, 320).endswith("_240x320.jpg"))
        self.assertTrue(eng.thumbnail_path(portrait, 100, 100).endswith("_120x160.jpg"))
        for path in (tile,):
            self.assertTrue(os.path.isfile(path))
        eng.delete_session()
        self.assertIsNone(eng.session)


class AuthToolTests(unittest.TestCase):
    def test_pkce(self):
        verifier, challenge = gphotos_auth.pkce_pair()
        self.assertGreaterEqual(len(verifier), 43)
        expect = gphotos_auth.base64url(hashlib.sha256(verifier.encode()).digest())
        self.assertEqual(challenge, expect)
        self.assertNotIn("=", challenge)

    def test_client_secrets_and_tokens_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "client.json")
            with open(path, "w") as f:
                json.dump({"installed": {"client_id": "cid.apps", "client_secret": "s"}}, f)
            self.assertEqual(gphotos_auth.load_client_secrets(path), ("cid.apps", "s"))
            with open(path, "w") as f:
                json.dump({"client_id": "flat"}, f)
            self.assertEqual(gphotos_auth.load_client_secrets(path), ("flat", ""))
            with open(path, "w") as f:
                json.dump({"web": {}}, f)
            with self.assertRaises(gphotos_auth.AuthError):
                gphotos_auth.load_client_secrets(path)
            out = gphotos_auth.write_tokens(os.path.join(d, "sub", "t.json"), TOKENS)
            self.assertEqual(gphotos_auth.read_tokens(out)["refresh_token"], "rt")
            if os.name != "nt":
                self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)
            # the engine reads what the tool writes
            self.assertTrue(ge.credentials_ok(ge.load_tokens(out)))

    def test_auth_url(self):
        url = gphotos_auth.build_auth_url("cid", "http://127.0.0.1:4321/", "chal", "st")
        self.assertTrue(url.startswith(gphotos_auth.AUTH_URL + "?"))
        query = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        self.assertEqual(query["redirect_uri"], "http://127.0.0.1:4321/")
        self.assertEqual(query["scope"], gphotos_auth.SCOPE)
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertEqual(query["access_type"], "offline")
        self.assertEqual(query["prompt"], "consent")
        self.assertEqual(query["state"], "st")

    def test_loopback_callback(self):
        server = gphotos_auth.start_callback_server(0)
        port = server.server_address[1]
        result = {}

        def serve():
            result.update(gphotos_auth.wait_for_callback(server, timeout=10))

        t = threading.Thread(target=serve)
        t.start()
        with urllib.request.urlopen(
            "http://127.0.0.1:%d/?code=abc&state=xyz" % port, timeout=5
        ) as r:
            self.assertIn(b"Signed in", r.read())
        t.join(5)
        server.server_close()
        self.assertEqual(result, {"code": "abc", "state": "xyz"})

    def test_login_exchanges_code(self):
        calls = []

        def fake_post(url, fields, timeout=30.0):
            calls.append((url, fields))
            return 200, {"access_token": "a", "refresh_token": "r", "scope": gphotos_auth.SCOPE}

        def fake_wait(server, timeout):
            # base64url is patched below, so the tool's state is "fixedstate"
            return {"code": "the-code", "state": "fixedstate"}

        with mock.patch.object(gphotos_auth, "_post_form", fake_post), mock.patch.object(
            gphotos_auth, "wait_for_callback", fake_wait
        ), mock.patch.object(gphotos_auth, "base64url", lambda b: "fixedstate"):
            data = gphotos_auth.login("cid", "sec", open_browser=False, out=io.StringIO())
        self.assertEqual(data["refresh_token"], "r")
        url, fields = calls[-1]
        self.assertEqual(url, gphotos_auth.TOKEN_URL)
        self.assertEqual(fields["grant_type"], "authorization_code")
        self.assertEqual(fields["code"], "the-code")
        self.assertEqual(fields["code_verifier"], "fixedstate")
        self.assertTrue(fields["redirect_uri"].startswith("http://127.0.0.1:"))


if __name__ == "__main__":
    unittest.main()
