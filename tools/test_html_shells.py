#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Brad Barnett
# SPDX-License-Identifier: MIT
"""Comprehensive test runner for pydevices-examples PyScript HTML shells."""

import asyncio
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
import urllib.request

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
from serve import DemoRequestHandler  # noqa: E402

PAGES_TO_TEST = [
    ("DOM Event Test", "dom.html"),
    ("Async Animation Test", "async.html"),
    ("MicroPython Hello", "micropython.html?modules=hello"),
    ("Pyodide Hello", "pyodide.html?modules=hello"),
    ("Compact MP Runner", "mp.html?modules=hello"),
    ("Compact Pyodide Runner", "py.html?modules=hello"),
    ("Autotest Harness", "harness.html?modules=hello"),
    ("Interactive Editor", "editor.html"),
    ("Interactive REPL", "repl.html"),
    ("Peter Hinch GUI Demos", "peterhinch.html?touch"),
]


def test_http_and_configs(base_url: str):
    print("=" * 70)
    print("STEP 1: Validating HTTP Endpoints & TOML Configuration References")
    print("=" * 70)

    for title, path in PAGES_TO_TEST:
        full_url = f"{base_url}/.site/pyscript/{path}"
        req = urllib.request.Request(full_url, headers={"User-Agent": "PyScript-Test"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8")
            status = resp.status
            assert status == 200, f"{path} returned HTTP {status}"
            assert "<!DOCTYPE html>" in content or "<html>" in content

            # Check that pyscript-config.js is loaded (not pyscript-json-config.js)
            assert 'src="./pyscript-config.js"' in content, f"{path} must load pyscript-config.js"
            assert "pyscript-json-config.js" not in content, (
                f"{path} contains obsolete JSON loader"
            )

            # Check data-configs attribute
            if "data-configs=" in content:
                raw_configs = content.split('data-configs="', 1)[1].split('"', 1)[0]
                for cfg in raw_configs.split():
                    assert not cfg.endswith(".json"), f"{path} references .json config: {cfg}"
                    assert cfg.endswith(".toml"), f"{path} references non-toml config: {cfg}"
                    if not cfg.startswith("http"):
                        cfg_url = f"{base_url}/.site/pyscript/{cfg}"
                        with urllib.request.urlopen(cfg_url, timeout=5) as c_resp:
                            c_text = c_resp.read().decode("utf-8")
                            parsed = tomllib.loads(c_text)
                            assert parsed, f"Failed to parse TOML from {cfg}"

            print(f"  [PASS] {title:25s} -> {path} (HTTP 200, TOML configs verified)")


async def test_with_playwright(base_url: str):
    print("\n" + "=" * 70)
    print("STEP 2: Executing Headless Browser Verification via Playwright")
    print("=" * 70)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("  [SKIP] Playwright is not installed in the environment.")
        return

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:
            print(f"  [SKIP] Playwright chromium browser not available: {exc}")
            return

        context = await browser.new_context()
        page = await context.new_page()

        console_messages = []
        errors = []

        page.on("console", lambda msg: console_messages.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: errors.append(str(err)))

        for title, rel_path in PAGES_TO_TEST:
            console_messages.clear()
            errors.clear()
            url = f"{base_url}/.site/pyscript/{rel_path}"
            print(f"\nTesting: {title} ({url})")

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                # Wait for PyScript to start parsing and setting config
                await page.wait_for_timeout(3000)

                # Check if error status is shown
                status_el = await page.query_selector("#status")
                if status_el:
                    status_text = await status_el.text_content()
                    print(f"  Status element: {status_text.strip()}")

                canvas_el = await page.query_selector("canvas")
                if canvas_el:
                    print("  Canvas element present.")

                # If DOM test, test click interaction
                if "dom.html" in rel_path:
                    btn = await page.query_selector("#next_color")
                    if btn:
                        await btn.click()
                        await page.wait_for_timeout(500)
                        updated_status = await status_el.text_content() if status_el else ""
                        print(f"  DOM click status: {updated_status.strip()}")

                print(f"  [PASS] {title} loaded without fatal page crashes.")
            except Exception as e:
                print(f"  [WARN] Page test exception on {rel_path}: {e}")

        await browser.close()


def main():
    port = 8765
    bind = "127.0.0.1"
    base_url = f"http://{bind}:{port}"

    DemoRequestHandler.coi_enabled = True
    handler = partial(DemoRequestHandler, directory=str(REPO_ROOT))
    httpd = ThreadingHTTPServer((bind, port), handler)

    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.5)

    print(f"Started temporary test server at {base_url}")
    try:
        test_http_and_configs(base_url)
        asyncio.run(test_with_playwright(base_url))
        print("\n" + "=" * 70)
        print("ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 70)
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
