#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""One-time Google sign-in for ``lib/examples/google_photos`` (CPython, stdlib only).

A microcontroller cannot complete Google's login by itself: the TV
"enter this code on your phone" flow refuses the Photos Picker scope, and a
LAN address cannot be registered as an OAuth redirect. So the browser login
runs here, once, and the resulting *refresh token* is copied to the device.
From then on the device only trades that refresh token for short-lived
access tokens.

Usage::

    python tools/gphotos_auth.py --client-secrets ~/Downloads/client_secret_XXX.json
    python tools/gphotos_auth.py --client-id ID --client-secret SECRET
    python tools/gphotos_auth.py --verify            # re-check an existing tokens file

Then copy the file to the board::

    mpremote cp ~/.gphotos_tokens.json :/gphotos_tokens.json

Google Cloud setup (details in ``lib/examples/google_photos/README.md``):

1. APIs & Services -> Library -> enable **Google Photos Picker API**.
2. OAuth consent screen: user type External. Either publish the app to
   *Production* (unverified is fine for personal use) or keep it in *Testing*
   and add your account as a test user -- but Testing refresh tokens expire
   after 7 days, so you would repeat this login weekly.
3. Credentials -> Create credentials -> OAuth client ID -> **Desktop app**;
   download the JSON.

The login uses PKCE and a loopback redirect (``http://127.0.0.1:<port>/``),
the flow Google recommends for installed apps. ``--no-browser`` prints the
URL instead of opening a browser (copy it to any browser on this machine).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
PICKER_SESSIONS_URL = "https://photospicker.googleapis.com/v1/sessions"
SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
DEFAULT_OUTPUT = "~/.gphotos_tokens.json"
LOGIN_TIMEOUT_S = 300

_DONE_HTML = (
    "<!doctype html><html><body style='font-family:sans-serif;margin:3em'>"
    "<h2>{title}</h2><p>{body}</p></body></html>"
)


class AuthError(Exception):
    """Login could not be completed."""


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """PKCE ``(code_verifier, code_challenge)`` using S256."""
    verifier = base64url(os.urandom(48))
    challenge = base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def load_client_secrets(path: str) -> tuple[str, str]:
    """``client_id, client_secret`` from a Google Cloud client JSON download."""
    with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("installed", "web"):
        if isinstance(data.get(key), dict):
            data = data[key]
            break
    client_id = data.get("client_id") or ""
    client_secret = data.get("client_secret") or ""
    if not client_id:
        raise AuthError(f"{path}: no client_id found")
    return client_id, client_secret


def build_auth_url(client_id: str, redirect_uri: str, challenge: str, state: str) -> str:
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(query)


def _post_form(url: str, fields: dict, timeout: float = 30.0) -> tuple[int, dict]:
    body = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _json(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, _json(err.read())
    except urllib.error.URLError as err:
        raise AuthError(f"network error: {err.reason}") from err


def _json(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _describe(status: int, data: dict) -> str:
    err = data.get("error")
    if isinstance(err, dict):
        return f"HTTP {status} {err.get('status', '')} {err.get('message', '')}".strip()
    desc = data.get("error_description") or ""
    return f"HTTP {status} {err or ''} {desc}".strip()


def exchange_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str, verifier: str
) -> dict:
    status, data = _post_form(
        TOKEN_URL,
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
    )
    if status != 200 or not data.get("access_token"):
        raise AuthError("token exchange failed: " + _describe(status, data))
    return data


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    status, data = _post_form(
        TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if status != 200 or not data.get("access_token"):
        raise AuthError("token refresh failed: " + _describe(status, data))
    return data


def picker_probe(access_token: str, timeout: float = 30.0) -> str:
    """Create and delete one picker session; returns a human-readable verdict."""
    headers = {
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(PICKER_SESSIONS_URL, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            session = _json(resp.read())
    except urllib.error.HTTPError as err:
        raise AuthError(
            "Picker API check failed: " + _describe(err.code, _json(err.read()))
        ) from err
    except urllib.error.URLError as err:
        raise AuthError(f"network error: {err.reason}") from err
    sid = session.get("id") or ""
    if sid:
        req = urllib.request.Request(
            PICKER_SESSIONS_URL + "/" + urllib.parse.quote(sid, safe=""),
            headers={"Authorization": "Bearer " + access_token},
            method="DELETE",
        )
        try:
            urllib.request.urlopen(req, timeout=timeout).close()
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass
    return "Picker API OK (session created and deleted)"


def write_tokens(path: str, data: dict) -> str:
    """Write the tokens JSON with owner-only permissions; returns the path."""
    path = os.path.expanduser(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def read_tokens(path: str) -> dict:
    with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("refresh_token"):
        raise AuthError(f"{path}: not a tokens file (no refresh_token)")
    return data


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures ``?code=…&state=…`` from Google's loopback redirect."""

    result: dict = {}

    def do_GET(self):  # noqa: N802 - http.server API
        query = urllib.parse.urlparse(self.path).query
        params = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        if "code" in params or "error" in params:
            type(self).result = params
        if "error" in params:
            title, body = "Sign-in failed", params.get("error", "")
        elif "code" in params:
            title, body = "Signed in", "You can close this tab and return to the terminal."
        else:
            title, body = "Waiting", "This page only answers Google's redirect."
        payload = _DONE_HTML.format(title=title, body=body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence the default stderr access log
        pass


def start_callback_server(port: int = 0) -> http.server.HTTPServer:
    _CallbackHandler.result = {}
    return http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)


def wait_for_callback(server: http.server.HTTPServer, timeout: float) -> dict:
    """Serve until a code (or error) arrives, or ``timeout`` seconds pass."""
    server.timeout = 1.0
    deadline = _now() + timeout
    while not _CallbackHandler.result and _now() < deadline:
        server.handle_request()
    return dict(_CallbackHandler.result)


def _now() -> float:
    import time

    return time.monotonic()


def login(
    client_id: str,
    client_secret: str,
    port: int = 0,
    open_browser: bool = True,
    timeout: float = LOGIN_TIMEOUT_S,
    out=sys.stdout,
) -> dict:
    """Run the browser login; returns Google's token response."""
    verifier, challenge = pkce_pair()
    state = base64url(os.urandom(16))
    server = start_callback_server(port)
    try:
        redirect_uri = "http://127.0.0.1:%d/" % server.server_address[1]
        url = build_auth_url(client_id, redirect_uri, challenge, state)
        print("Sign in with the Google account whose photos you want to show.", file=out)
        if open_browser:
            print("Opening your browser (or copy this URL into one):", file=out)
        else:
            print("Open this URL in a browser on this machine:", file=out)
        print("\n" + url + "\n", file=out)
        if open_browser:
            thread = threading.Thread(target=webbrowser.open, args=(url,), daemon=True)
            thread.start()
        params = wait_for_callback(server, timeout)
    finally:
        server.server_close()
    if not params:
        raise AuthError("timed out waiting for the browser redirect")
    if params.get("error"):
        raise AuthError("Google refused the sign-in: " + params["error"])
    if params.get("state") != state:
        raise AuthError("state mismatch on the redirect (stale tab?) - try again")
    return exchange_code(client_id, client_secret, params["code"], redirect_uri, verifier)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--client-secrets", help="client_secret_*.json downloaded from Google Cloud"
    )
    parser.add_argument("--client-id")
    parser.add_argument("--client-secret", default="")
    parser.add_argument(
        "--output", default=DEFAULT_OUTPUT, help=f"tokens file (default {DEFAULT_OUTPUT})"
    )
    parser.add_argument(
        "--port", type=int, default=0, help="loopback port (default: any free port)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="print the URL instead of opening a browser"
    )
    parser.add_argument(
        "--timeout", type=float, default=LOGIN_TIMEOUT_S, help="seconds to wait for the redirect"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="after login (or alone) refresh the token and check the Picker API",
    )
    args = parser.parse_args(argv)

    try:
        if args.client_secrets or args.client_id:
            if args.client_secrets:
                client_id, client_secret = load_client_secrets(args.client_secrets)
                if args.client_secret:
                    client_secret = args.client_secret
            else:
                client_id, client_secret = args.client_id, args.client_secret
            response = login(
                client_id,
                client_secret,
                port=args.port,
                open_browser=not args.no_browser,
                timeout=args.timeout,
            )
            refresh_token = response.get("refresh_token")
            if not refresh_token:
                raise AuthError(
                    "Google returned no refresh token. Remove the app at "
                    "https://myaccount.google.com/permissions and run this again."
                )
            tokens = {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "scope": response.get("scope", SCOPE),
                "token_type": response.get("token_type", "Bearer"),
            }
            path = write_tokens(args.output, tokens)
            print(f"Wrote {path}")
            print("Copy it to the board, e.g.:")
            print(f"  mpremote cp {path} :/gphotos_tokens.json")
            print("Desktop runs read it from that same path (override: GPHOTOS_TOKENS=...).")
        elif args.verify:
            tokens = read_tokens(args.output)
        else:
            parser.error("give --client-secrets FILE or --client-id ID (or --verify)")
            return 2

        if args.verify:
            data = refresh_access_token(
                tokens["client_id"], tokens.get("client_secret", ""), tokens["refresh_token"]
            )
            print("Token refresh OK (expires in %s s)" % data.get("expires_in", "?"))
            print(picker_probe(data["access_token"]))
    except AuthError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
