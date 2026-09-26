"""Play test material to the Espressif sound card over WASAPI (Windows Python).

    python.exe play_src.py SECONDS SOURCE [GAIN] [excl|shared]

SOURCE: tone | pink | sweep | mix (10 s pink, 10 s log sweep 20 Hz-20 kHz,
alternating) | a path to a 48 kHz wav. Loops. GAIN is linear (default 0.25).
Prints the frame rate the host delivered and underflows, like uac_play_tone.
"""

import sys
import time

import numpy as np
import sounddevice as sd

RATE = 48000
secs = float(sys.argv[1])
src = sys.argv[2]
gain = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25
excl = (sys.argv[4] if len(sys.argv) > 4 else "shared") == "excl"


def pink(n, seed=1):
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(n)
    f = np.fft.rfft(w)
    k = np.arange(len(f))
    k[0] = 1
    f /= np.sqrt(k)
    x = np.fft.irfft(f, n)
    return x / np.max(np.abs(x))


def sweep(n):
    t = np.arange(n) / RATE
    T = n / RATE
    f0, f1 = 20.0, 20000.0
    k = np.log(f1 / f0)
    ph = 2 * np.pi * f0 * T / k * (np.exp(t / T * k) - 1)
    return 0.7 * np.sin(ph)


if src == "tone":
    n = RATE
    mono = 0.7 * np.sin(2 * np.pi * 440 * np.arange(n) / RATE)
    data = np.stack([mono, mono], 1)
elif src == "pink":
    mono = pink(10 * RATE)
    data = np.stack([mono, mono], 1)
elif src == "sweep":
    mono = sweep(10 * RATE)
    data = np.stack([mono, mono], 1)
elif src == "mix":
    mono = np.concatenate([pink(10 * RATE), sweep(10 * RATE)])
    data = np.stack([mono, mono], 1)
else:
    import soundfile as sf

    data, r = sf.read(src, dtype="float64", always_2d=True)
    assert r == RATE, r
    if data.shape[1] == 1:
        data = np.repeat(data, 2, 1)
    data = data[:, :2] / max(1e-9, np.max(np.abs(data)))
pcm = np.clip(data * gain * 32767, -32768, 32767).astype(np.int16)

dev = next(
    i
    for i, d in enumerate(sd.query_devices())
    if "Espressif" in d["name"]
    and d["max_output_channels"]
    and sd.query_hostapis(d["hostapi"])["name"] == "Windows WASAPI"
)
state = {"pos": 0, "frames": 0, "under": 0}


def cb(out, frames, t, status):
    if status.output_underflow:
        state["under"] += 1
    p = state["pos"]
    n = len(pcm)
    idx = (np.arange(frames) + p) % n
    out[:] = pcm[idx]
    state["pos"] = (p + frames) % n
    state["frames"] += frames


with sd.OutputStream(
    device=dev,
    samplerate=RATE,
    channels=2,
    dtype="int16",
    callback=cb,
    extra_settings=sd.WasapiSettings(exclusive=excl),
    latency="high",
):
    t0 = time.perf_counter()
    time.sleep(secs)
    el = time.perf_counter() - t0
print(
    "HOST src=%s gain=%.3f exclusive=%s frames/s=%.1f underflows=%d"
    % (src, gain, excl, state["frames"] / el, state["under"])
)
