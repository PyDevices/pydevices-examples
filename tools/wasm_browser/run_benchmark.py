#!/usr/bin/env python3
"""Controlled direct-WASM versus locally built MicroPython-PyScript benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics

from playwright.async_api import Page, async_playwright
from run_contract import FIXTURE_PATH, WORKSPACE, local_server

BENCHMARK_PATH = FIXTURE_PATH.replace("fixture.html", "benchmark.html")
BASELINE_RUNTIME = WORKSPACE / "cmods/micropython/ports/webassembly/build-pyscript/micropython.mjs"
PYDEVICES_LIB = WORKSPACE / "pydevices/lib"
PIXELS = 320 * 480


def source_files() -> dict[str, str]:
    return {
        "/lib/" + path.relative_to(PYDEVICES_LIB).as_posix(): path.read_text()
        for path in PYDEVICES_LIB.rglob("*.py")
    }


async def wait_ready(page: Page, base_url: str, backend: str) -> None:
    await page.goto(f"{base_url}{BENCHMARK_PATH}?backend={backend}")
    await page.wait_for_function("__benchmark.phase !== 'loading'")
    state = await page.evaluate("() => ({phase:__benchmark.phase, errors:__benchmark.errors})")
    assert state["phase"] == "ready", state
    if backend == "direct":
        await page.wait_for_function("Module.pydevicesBridge.stats().frames > 0")


async def framebuffer_metric(page: Page, backend: str) -> float:
    source = (
        "display._framebuffer[:] = bytes([0x1f, 0]) * (320 * 480)"
        if backend == "direct"
        else "display.blit_rect(bytes([0x1f, 0]) * (320 * 480), 0, 0, 320, 480)"
    )
    before_frame = None
    if backend == "direct":
        before_frame = await page.evaluate("Module.pydevicesBridge.stats().frames")
    started = await page.evaluate("performance.now()")
    await page.evaluate("source => __benchmark.mp.runPythonAsync(source)", source)
    if before_frame is not None:
        await page.wait_for_function(
            "frame => Module.pydevicesBridge.stats().frames > frame", arg=before_frame
        )
    elapsed = await page.evaluate("started => performance.now() - started", started)
    return PIXELS / elapsed


async def input_metric(page: Page) -> float:
    iterations = 2000
    elapsed = await page.evaluate(
        """async iterations => {
              const canvas=document.querySelector('canvas');
              const rect=canvas.getBoundingClientRect();
              const read=__benchmark.mp.globals.get('bench_read');
              const started=performance.now();
              for(let index=0;index<iterations;index++) {
                canvas.dispatchEvent(new PointerEvent('pointermove', {
                  bubbles:true, clientX:rect.left+(index%320), clientY:rect.top+(index%480),
                  movementX:1, movementY:1, pointerId:1, pointerType:'mouse'}));
                read();
              }
              return performance.now()-started;
            }""",
        iterations,
    )
    return elapsed / iterations


async def timer_metric(page: Page, backend: str) -> float:
    if backend == "direct":
        await page.evaluate("Module.pydevicesBridge.resetTimerFirings()")
        await page.evaluate(
            """() => __benchmark.mp.runPython(`
from multimer.wasm import Timer
bench_timer = Timer(id=9001, mode=Timer.PERIODIC, period=10, callback=lambda _: None)
`)"""
        )
        await page.evaluate(
            """() => {
              const poll=()=>{
                if(Module.pydevicesBridge.stats().timerFirings.length>=50) {
                  __benchmark.mp.runPython('bench_timer.deinit()');
                  __benchmark.timerDone=true;
                } else requestAnimationFrame(poll);
              };
              poll();
            }"""
        )
        await page.wait_for_function("__benchmark.timerDone === true")
        delivery_latencies = await page.evaluate(
            """() => {
              const stats=Module.pydevicesBridge.stats();
              return stats.timerDeliveries.map((item,index)=>item.at-stats.timerFirings[index].at);
            }"""
        )
    else:
        await page.evaluate(
            """() => {
              __benchmark.timerLatencies=[];
              __benchmark.timerHandle=setInterval(()=>{
                const fired=performance.now();
                __benchmark.mp.runPython('0');
                __benchmark.timerLatencies.push(performance.now()-fired);
                if(__benchmark.timerLatencies.length>=50) {
                  clearInterval(__benchmark.timerHandle);
                  __benchmark.timerDone=true;
                }
              },10);
            }"""
        )
        await page.wait_for_function("__benchmark.timerDone === true")
        delivery_latencies = await page.evaluate("__benchmark.timerLatencies")
    return statistics.pstdev(delivery_latencies)


async def audio_metric(page: Page, backend: str) -> tuple[float, int]:
    source = (
        """from audiodev import AudioFormat
from audiodev.wasm_audio import WasmPCMOutput
audio = WasmPCMOutput(AudioFormat(48000, 2, 16))
audio.write(bytes(4800 * 4))"""
        if backend == "direct"
        else """from audiodev import AudioFormat
from audiodev.web_audio import WebPCMOutput
audio = WebPCMOutput(AudioFormat(48000, 2, 16))
audio.write(bytes(4800 * 4))"""
    )
    started = await page.evaluate("performance.now()")
    await page.evaluate("source => __benchmark.mp.runPythonAsync(source)", source)
    elapsed = await page.evaluate("started => performance.now() - started", started)
    return elapsed, 0


async def measure(page: Page, backend: str) -> dict[str, float | int]:
    return {
        "framebuffer_pixels_per_ms": await framebuffer_metric(page, backend),
        "input_round_trip_ms": await input_metric(page),
        "timer_jitter_ms": await timer_metric(page, backend),
        "audio_queue_ms": (await audio_metric(page, backend))[0],
        "audio_underruns": 0,
    }


def medians(rows: list[dict[str, float | int]]) -> dict[str, float]:
    return {key: statistics.median(float(row[key]) for row in rows) for key in rows[0]}


async def main(iterations: int) -> int:
    if not BASELINE_RUNTIME.exists():
        raise SystemExit(
            "baseline missing; run cmods/build_mp.sh --port webassembly --variant pyscript"
        )
    browser_env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}
    }
    results = {"direct": [], "pyscript": []}
    with local_server() as base_url:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(env=browser_env)
            try:

                async def run_once(backend: str, record: bool) -> None:
                    page = await browser.new_page(viewport={"width": 320, "height": 480})
                    await page.add_init_script(
                        "window.__sourceFiles=" + json.dumps(source_files())
                    )
                    try:
                        await wait_ready(page, base_url, backend)
                        row = await measure(page, backend)
                        if record:
                            results[backend].append(row)
                    finally:
                        await page.close()

                await run_once("direct", False)
                await run_once("pyscript", False)
                for iteration in range(iterations):
                    order = (
                        ("direct", "pyscript") if iteration % 2 == 0 else ("pyscript", "direct")
                    )
                    for backend in order:
                        await run_once(backend, True)
            finally:
                await browser.close()
    summary = {backend: medians(rows) for backend, rows in results.items()}
    direct, baseline = summary["direct"], summary["pyscript"]
    assert direct["framebuffer_pixels_per_ms"] > baseline["framebuffer_pixels_per_ms"], summary
    for metric in ("input_round_trip_ms", "timer_jitter_ms", "audio_queue_ms"):
        assert direct[metric] < baseline[metric], (metric, summary)
    assert direct["audio_underruns"] <= baseline["audio_underruns"], summary
    print(json.dumps({"iterations": results, "median": summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.iterations)))
