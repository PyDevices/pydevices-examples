# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
phase_a
====================================================
The silent desktop proof: every tool fires on a matching request, speech
round-trips through files, and a still gets described. Nothing is played
aloud and no key reaches a TV (dry-run or sim).

    python phase_a.py OUTDIR [--image photo.jpg] [--hub HOST[:PORT]] [--model smart|MODEL]

Writes OUTDIR/results.json and the WAV files; prints a transcript.
"""

import json
import os
import sys
import time

from assistant import Assistant
from gemini import CHAT_MODEL, SMART_MODEL, Gemini, wav_bytes
from gemini_key import load_key
from tools import Tools, file_camera

REQUESTS = [
    # (request, the tool that should fire, roku mode)
    ("What's playing on the TV?", "roku_status", "dry-run"),
    ("Turn the TV volume down a little.", "roku_volume", "dry-run"),
    ("Mute the TV.", "roku_volume", "sim"),
    ("Pause the TV.", "roku_press", "sim"),
    ("Turn the TV off.", "roku_power", "sim"),
    ("Open YouTube on the TV.", "roku_launch", "sim"),
    ("What's the temperature in here?", "hub_read", "dry-run"),
    ("How humid is the living room?", "hub_read", "dry-run"),
    ("What can the camera see?", "camera_snapshot", "dry-run"),
]

VOICE_REQUEST = "Turn the TV volume down a little."


def run(outdir, image, model, hub=None):
    os.makedirs(outdir, exist_ok=True)
    g = Gemini(load_key())
    cam = file_camera(image) if image else None
    hub_kw = {"hub_host": hub} if hub else {}
    results = {"model": model, "date": time.strftime("%Y-%m-%d %H:%M"), "tools": [], "speech": {}, "vision": {}}

    # 1. Tools
    for text, want, mode in REQUESTS:
        tools = Tools(gemini=g, roku_mode=mode, camera=cam, **hub_kw)
        a = Assistant(g, tools, model=model, keep_history=False)
        w0 = g.waited
        t0 = time.perf_counter()
        reply, trace = a.ask(text)
        total = time.perf_counter() - t0 - (g.waited - w0)  # net of rate-limit waits
        fired = [c[0] for c in tools.calls]
        row = {
            "request": text,
            "mode": mode,
            "want": want,
            "fired": fired,
            "ok": want in fired,
            "args": [c[1] for c in tools.calls],
            "held_back": list(tools.sent) if mode == "dry-run" else [],
            "sim_sent": [] if mode == "dry-run" else [c[2] for c in tools.calls],
            "reply": reply,
            "trace": trace,
            "total_s": round(total, 2),
        }
        results["tools"].append(row)
        print("%-4s %-50s -> %s %s  %.2fs" % ("ok" if row["ok"] else "MISS", text, fired, row["args"], total))
        print("     " + reply)

    # 2. Speech through files: TTS -> WAV -> STT -> assistant -> TTS -> WAV
    sp = results["speech"]
    pcm, rate = g.tts(VOICE_REQUEST)
    sp["tts_request_s"] = round(g.last_latency, 2)
    req_wav = os.path.join(outdir, "request.wav")
    with open(req_wav, "wb") as f:
        f.write(wav_bytes(pcm, rate))
    sp["request_audio_s"] = round(len(pcm) / 2 / rate, 2)

    with open(req_wav, "rb") as f:
        heard = g.stt(f.read())
    sp["stt_s"] = round(g.last_latency, 2)
    sp["heard"] = heard

    tools = Tools(gemini=g, roku_mode="dry-run", camera=cam, **hub_kw)
    a = Assistant(g, tools, model=model, keep_history=False)
    w0 = g.waited
    t0 = time.perf_counter()
    reply, trace = a.ask(heard)
    sp["assistant_s"] = round(time.perf_counter() - t0 - (g.waited - w0), 2)
    sp["assistant_trace"] = trace
    sp["held_back"] = list(tools.sent)
    sp["reply"] = reply

    pcm, rate = g.tts(reply)
    sp["tts_reply_s"] = round(g.last_latency, 2)
    sp["reply_audio_s"] = round(len(pcm) / 2 / rate, 2)
    with open(os.path.join(outdir, "reply.wav"), "wb") as f:
        f.write(wav_bytes(pcm, rate))
    sp["voice_turn_s"] = round(sp["stt_s"] + sp["assistant_s"] + sp["tts_reply_s"], 2)
    print("speech: heard %r in %.2fs; assistant %.2fs; reply TTS %.2fs; turn %.2fs"
          % (heard, sp["stt_s"], sp["assistant_s"], sp["tts_reply_s"], sp["voice_turn_s"]))
    print("     " + reply)

    # 3. Vision
    if cam:
        jpeg = cam()
        desc = g.describe(jpeg)
        results["vision"] = {"image": os.path.basename(image), "bytes": len(jpeg),
                             "latency_s": round(g.last_latency, 2), "description": desc}
        item = g.describe(jpeg, prompt="You are a shop till. Name the single item for sale in this photo, in three words or fewer.")
        results["vision"]["pos_item"] = item
        results["vision"]["pos_latency_s"] = round(g.last_latency, 2)
        print("vision: %.2fs  %s" % (results["vision"]["latency_s"], desc))
        print("till:   %.2fs  %s" % (results["vision"]["pos_latency_s"], item))

    results["rate_limit_wait_s"] = round(g.waited, 1)
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    return results


if __name__ == "__main__":
    args = sys.argv[1:]
    image = None
    model = CHAT_MODEL
    if "--image" in args:
        i = args.index("--image")
        image = args[i + 1]
        del args[i : i + 2]
    hub = None
    if "--hub" in args:
        i = args.index("--hub")
        hub = args[i + 1]
        del args[i : i + 2]
    if "--model" in args:
        i = args.index("--model")
        model = {"smart": SMART_MODEL}.get(args[i + 1], args[i + 1])
        del args[i : i + 2]
    run(args[0] if args else "phase_a_out", image, model, hub)
