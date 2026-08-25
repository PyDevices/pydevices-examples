#!/usr/bin/env python3
"""Isolated direct-WASM browser contract tests; intentionally not a site crawler."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

from playwright.async_api import Browser, Page, async_playwright

WORKSPACE = Path(__file__).resolve().parents[3]
FIXTURE_PATH = "/pydevices-examples/tools/wasm_browser/fixture.html"
AUDIO_SILENCE_THRESHOLD = 0.01


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass


@contextlib.contextmanager
def local_server():
    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(WORKSPACE), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


async def python_json(page: Page, source: str):
    await page.evaluate("source => window.__wasmContract.mp.runPythonAsync(source)", source)
    text = await page.evaluate("window.__wasmContract.mp.globals.get('__contract_result')")
    return json.loads(text)


async def wait_ready(page: Page, base_url: str) -> None:
    await page.goto(base_url + FIXTURE_PATH)
    await page.wait_for_function("window.__wasmContract.phase !== 'loading'")
    state = await page.evaluate(
        "() => ({phase: __wasmContract.phase, errors: __wasmContract.errors, stderr: __wasmContract.stderr})"
    )
    assert state["phase"] == "ready", state
    await page.wait_for_function("Module.pydevicesBridge.stats().frames >= 1")


async def check_framebuffer(page: Page) -> dict:
    pixels = await page.evaluate(
        """() => Array.from(document.querySelector('canvas').getContext('2d')
            .getImageData(0, 0, 4, 2).data)"""
    )
    expected = [
        255,
        0,
        0,
        255,
        0,
        255,
        0,
        255,
        0,
        0,
        255,
        255,
        255,
        255,
        255,
        255,
        0,
        0,
        0,
        255,
        132,
        130,
        132,
        255,
        123,
        125,
        123,
        255,
        255,
        0,
        0,
        255,
    ]
    assert pixels == expected, pixels
    return {"frames": await page.evaluate("Module.pydevicesBridge.stats().frames")}


async def check_soft_reset(page: Page) -> dict:
    await page.evaluate(
        "source => window.__wasmContract.mp.runPythonAsync(source)",
        "from multimer.wasm import Timer\n_reset_timer = Timer(mode=Timer.PERIODIC, period=100, callback=lambda _: None)",
    )
    await page.wait_for_function("Module.pydevicesBridge.stats().timers === 1")
    await page.evaluate("window.__wasmContract.mp.softReset()")
    result = await python_json(
        page,
        """import json
import _wasm_bridge
from displaydev.wasmdisplay import WasmDisplay
display = WasmDisplay(4, 2, quiet=True)
display.init()
display._framebuffer[:] = bytes((
    0x00, 0xf8, 0xe0, 0x07, 0x1f, 0x00, 0xff, 0xff,
    0x00, 0x00, 0x10, 0x84, 0xef, 0x7b, 0x00, 0xf8,
))
__contract_result = json.dumps({'bridge': _wasm_bridge.__name__})""",
    )
    assert result["bridge"] == "_wasm_bridge", result
    assert await page.evaluate("Module.pydevicesBridge.stats().timers") == 0
    before = await page.evaluate("Module.pydevicesBridge.stats().frames")
    await page.wait_for_function(
        "before => Module.pydevicesBridge.stats().frames > before", arg=before
    )
    return result


async def check_input(page: Page) -> dict:
    await page.evaluate(
        """() => {
          const c = document.querySelector('canvas');
          const rect = c.getBoundingClientRect();
          const pointer = (type, init) => c.dispatchEvent(new PointerEvent(type, {
            bubbles:true, cancelable:true, clientX:rect.left+20, clientY:rect.top+10, pointerId:7,
            pointerType:'mouse', isPrimary:true, ...init}));
          pointer('pointerdown', {button:0, buttons:1, ctrlKey:true});
          pointer('pointermove', {clientX:rect.left+40, clientY:rect.top+20, movementX:1, movementY:1, buttons:1});
          pointer('pointerup', {button:0, buttons:0});
          pointer('pointerdown', {pointerId:8, pointerType:'touch', pressure:.5, button:0, buttons:1});
          pointer('pointerup', {pointerId:8, pointerType:'touch', button:0, buttons:0});
          pointer('pointerdown', {pointerId:9, pointerType:'pen', pressure:.75, button:0, buttons:1});
          pointer('pointerup', {pointerId:9, pointerType:'pen', button:0, buttons:0});
          pointer('pointerdown', {pointerId:10, pointerType:'touch', pressure:.5, button:0, buttons:1});
          pointer('pointercancel', {pointerId:10, pointerType:'touch', button:0, buttons:0});
          c.dispatchEvent(new WheelEvent('wheel', {bubbles:true, cancelable:true, clientX:rect.left+20, clientY:rect.top+10, deltaX:2, deltaY:-3}));
          c.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, cancelable:true, key:'A', code:'KeyA', shiftKey:true}));
          c.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, cancelable:true, key:'A', code:'KeyA', shiftKey:true}));
          c.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, cancelable:true, key:'Escape', code:'Escape'}));
          c.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, cancelable:true, key:'BrowserBack', code:'BrowserBack'}));
          window.__gamepads = [{index:0, connected:true, axes:[.5], buttons:[{pressed:true, touched:true, value:1}]}];
        }"""
    )
    before = await page.evaluate("Module.pydevicesBridge.stats().frames")
    await page.wait_for_function(
        "before => Module.pydevicesBridge.stats().frames > before", arg=before
    )
    result = await python_json(
        page,
        """import json
items = display.get_events() or []
__contract_result = json.dumps({
    'classes': [type(item).__name__ for item in items],
    'positions': [item.pos for item in items if hasattr(item, 'pos')],
    'keys': [item.name for item in items if hasattr(item, 'name')],
    'quit_chord': display.quit_chord,
})""",
    )
    classes = set(result["classes"])
    assert {
        "Button",
        "Motion",
        "Finger",
        "Wheel",
        "Key",
        "JoyAxisMotion",
        "JoyButtonDown",
    } <= classes, result
    assert [1, 1] in result["positions"] and [2, 1] in result["positions"], result
    assert {"Escape", "BrowserBack"} <= set(result["keys"]), result
    assert len(result["quit_chord"]) == 2, result
    return result


async def check_timers(page: Page) -> dict:
    await page.evaluate("Module.pydevicesBridge.resetTimerFirings()")
    result = await python_json(
        page,
        """import json
from time import ticks_diff, ticks_ms
from multimer.wasm import Timer, sleep_ms
times = []
start = ticks_ms()
t = Timer(mode=Timer.PERIODIC, period=10, callback=lambda _: times.append(ticks_diff(ticks_ms(), start)))
sleep_ms(38)
t.deinit()
count_after_cancel = len(times)
sleep_ms(20)
one = []
Timer(mode=Timer.ONE_SHOT, period=5, callback=lambda timer: (one.append(1), timer.deinit()))
sleep_ms(12)
__contract_result = json.dumps({'periodic': times, 'after_cancel': len(times), 'count_after_cancel': count_after_cancel, 'oneshot': len(one)})""",
    )
    firings = await page.evaluate("Module.pydevicesBridge.stats().timerFirings")
    by_id = {}
    for firing in firings:
        by_id.setdefault(firing["id"], []).append(firing["at"])
    periodic = max(by_id.values(), key=len)
    intervals = [right - left for left, right in zip(periodic, periodic[1:], strict=False)]
    assert result["periodic"] and result["after_cancel"] == result["count_after_cancel"], result
    assert result["oneshot"] == 1, result
    assert intervals and max(abs(value - 10) for value in intervals) < 15, (result, firings)
    result["host_intervals_ms"] = intervals
    return result


async def check_audio(page: Page) -> dict:
    await page.evaluate("Module.pydevicesBridge.enableAudio(false)")
    result = await python_json(
        page,
        """import json
from audiodev import AudioFormat
from audiodev.wasm_audio import WasmPCMOutput
cases = []
for bits in (8, 16, 32):
    for signed in (False, True):
        for order in ('little', 'big'):
            for channels in (1, 2):
                fmt = AudioFormat(8000, channels, bits, signed=signed, byteorder=order)
                midpoint = 0 if signed else 1 << (bits - 1)
                sample = int(midpoint).to_bytes(bits // 8, order)
                payload = sample * channels * 2
                out = WasmPCMOutput(fmt)
                cases.append((bits, signed, order, channels, out.write(payload)))
queued_before = __import__('_wasm_bridge').audio_queued_size(False)
__contract_result = json.dumps({'cases': cases, 'queued_before': queued_before})""",
    )
    starts = await page.evaluate(
        """() => __audioContext.starts.map(item => ({
          channels:item.buffer.numberOfChannels, rate:item.buffer.sampleRate,
          samples:item.buffer.data.map(channel => Array.from(channel))
        }))"""
    )
    assert len(result["cases"]) == 24 and len(starts) == 24, (result, starts)
    assert all(
        abs(sample) <= 1 for item in starts for channel in item["samples"] for sample in channel
    )
    await page.wait_for_function("Module.pydevicesBridge.stats().queuedAudioBytes === 0")
    await page.evaluate("Module.pydevicesBridge.injectMicrophone([[0, .5, -1]], 8000)")
    captured = await python_json(
        page,
        """import json
from audiodev import AudioFormat
from audiodev.wasm_audio import WasmPCMInput
buf = bytearray(6)
count = WasmPCMInput(AudioFormat(8000, 1, 16, signed=True, byteorder='little')).readinto(buf)
samples = [int.from_bytes(buf[i:i+2], 'little') for i in range(0, count, 2)]
samples = [value - 65536 if value & 0x8000 else value for value in samples]
__contract_result = json.dumps({'count': count, 'samples': samples})""",
    )
    assert (
        captured["count"] == 6 and captured["samples"][0] == 0 and captured["samples"][2] < -32000
    ), captured
    return {"formats": len(starts), "capture": captured}


async def check_audio_out(page: Page) -> dict:
    """A real synthio.Synthesizer, played through audiodev.sample_out.AudioOut
    over the wasm_audio transport -- the same CircuitPython-shaped
    play()/service() contract every host backend speaks (see
    pydevices/docs/audio.md). Confirms the whole pull-the-graph/push-the-bytes
    chain (synthio -> AudioOut -> WasmPCMOutput -> Web Audio) actually
    produces real, non-silent PCM in a browser, not just that the DSP usermod
    imports.
    """
    await page.evaluate("Module.pydevicesBridge.enableAudio(false)")
    # __audioContext.starts accumulates across the whole page session (e.g.
    # check_audio()'s 24 format cases already ran on this same page) -- mark
    # where this check's own buffers begin so it only asserts on those.
    start_index = await page.evaluate("__audioContext.starts.length")
    result = await python_json(
        page,
        """import json
import synthio
from audiodev import AudioFormat
from audiodev.sample_out import AudioOut
from audiodev.wasm_audio import WasmPCMOutput
import audiodev.sample_out as sample_out

# Deterministic, manually-advanced clock: AudioOut schedules by wall time
# (see sample_out.py), which a browser test should not depend on for a
# stable number of pulled chunks -- same technique
# audio_playback_golden_probe.py uses in the pydevices test suite.
class _FakeClock:
    def __init__(self):
        self.now = 0
    def ms(self):
        return self.now
    def diff(self, a, b):
        return a - b
    def advance(self, ms):
        self.now += ms

clock = _FakeClock()
sample_out.ticks_ms = clock.ms
sample_out.ticks_diff = clock.diff

fmt = AudioFormat(8000, 1, 16, signed=True, byteorder='little')
transport = WasmPCMOutput(fmt)
out = AudioOut(transport, chunk_ms=40)
synth = synthio.Synthesizer(sample_rate=fmt.rate, channel_count=fmt.channels)
out.play(synth)
note = synthio.Note(440.0)
synth.press(note)
for _ in range(6):
    clock.advance(10)
    out.service()
synth.release(note)
for _ in range(4):
    clock.advance(10)
    out.service()
out.close()
__contract_result = json.dumps({'ok': True})""",
    )
    assert result["ok"], result
    starts = await page.evaluate(
        """(startIndex) => __audioContext.starts.slice(startIndex).map(item => ({
          channels:item.buffer.numberOfChannels, rate:item.buffer.sampleRate,
          samples: Array.from(item.buffer.data[0])
        }))""",
        start_index,
    )
    assert len(starts) > 0, "AudioOut never scheduled any AudioBufferSource"
    assert all(item["rate"] == 8000 and item["channels"] == 1 for item in starts), starts
    # A pressed synthio.Note must produce real, non-silent, non-clipped PCM --
    # not just call createBufferSource() with empty/silent data.
    all_samples = [s for item in starts for s in item["samples"]]
    assert any(abs(s) > AUDIO_SILENCE_THRESHOLD for s in all_samples), "AudioOut PCM was silent"
    assert all(abs(s) <= 1.0 for s in all_samples), "AudioOut PCM exceeded full scale"
    return {"buffers": len(starts), "frames": len(all_samples)}


async def check_fetch_retry(page: Page, base_url: str) -> dict:
    result = await python_json(
        page,
        f"""import json
import requests
response = requests.get({json.dumps(base_url + "/retry-fixture")})
__contract_result = json.dumps({{'status': response.status_code, 'content': response.content.decode()}})""",
    )
    attempts = await page.evaluate("window.__retryFetchAttempts")
    assert result == {"status": 200, "content": "retry"} and attempts == 3, (
        result,
        attempts,
    )
    return {**result, "attempts": attempts}


async def run_browser(browser_name: str, browser: Browser, base_url: str) -> dict:
    page = await browser.new_page(viewport={"width": 320, "height": 480})
    browser_errors = []
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on(
        "console",
        lambda message: (
            browser_errors.append(f"console {message.type}: {message.text}")
            if message.type == "error"
            else None
        ),
    )
    try:
        await wait_ready(page, base_url)
        return {
            "framebuffer": await check_framebuffer(page),
            "soft_reset": await check_soft_reset(page),
            "input": await check_input(page),
            "timers": await check_timers(page),
            "fetch_retry": await check_fetch_retry(page, base_url),
            "audio": await check_audio(page),
            "audio_out": await check_audio_out(page),
        }
    except Exception as error:
        diagnostics = {"url": page.url, "browser_errors": browser_errors}
        with contextlib.suppress(Exception):
            diagnostics["contract"] = await page.evaluate(
                "() => globalThis.__wasmContract ? ({errors: __wasmContract.errors, stderr: __wasmContract.stderr, stdout: __wasmContract.stdout}) : null"
            )
        raise AssertionError(f"{browser_name} diagnostics: {diagnostics}") from error
    finally:
        await page.close()


async def main(selected: list[str]) -> int:
    with local_server() as base_url:
        async with async_playwright() as playwright:
            results = {}
            for name in selected:
                browser_type = getattr(playwright, name)
                browser_env = {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
                }
                browser = await browser_type.launch(env=browser_env)
                try:
                    results[name] = await run_browser(name, browser, base_url)
                finally:
                    await browser.close()
            print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="append", choices=("chromium", "firefox", "webkit"))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.browser or ["chromium", "firefox", "webkit"])))
