# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
server
====================================================
The assistant as a small HTTP service, so a board can use it without
holding the API key: the board POSTs what it heard or saw, the PC talks
to Gemini and drives the tools, and the board gets back audio to play.

    python server.py [--port 8770] [--roku dry-run|sim|live] [--image test.jpg]

| Request | Body | Reply |
|---|---|---|
| ``POST /voice`` | a WAV of the request | a WAV of the answer; the text in ``X-Heard`` / ``X-Reply`` headers |
| ``POST /ask`` | the request as text | JSON: reply, tool calls, timings |
| ``POST /see`` | a JPEG (``?q=question``) | JSON: the description |
| ``POST /tts`` | text | a WAV |
| ``GET /health`` | | ``ok`` |

Every reply carries ``X-Timing``: seconds per stage.
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from assistant import Assistant
from gemini import Gemini, wav_bytes
from gemini_key import load_key
from tools import Tools, file_camera, url_camera


def _ascii(text):
    return text.encode("ascii", "replace").decode().replace("\n", " ")[:900]


def make_handler(assistant, g):
    class Handler(BaseHTTPRequestHandler):
        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(n) if n else b""

        def _send(self, code, body, ctype, headers=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, b"ok", "text/plain")
            self._send(404, b"", "text/plain")

        def do_POST(self):
            url = urlparse(self.path)
            q = parse_qs(url.query)
            body = self._body()
            try:
                if url.path == "/ask":
                    t0 = time.perf_counter()
                    reply, trace = assistant.ask(body.decode())
                    return self._json({"reply": reply, "trace": trace, "total_s": round(time.perf_counter() - t0, 2)})
                if url.path == "/tts":
                    pcm, rate = g.tts(body.decode())
                    return self._send(200, wav_bytes(pcm, rate), "audio/wav", {"X-Timing": "tts=%.2f" % g.last_latency})
                if url.path == "/see":
                    question = q.get("q", ["Describe what you see in two sentences."])[0]
                    text = g.describe(body, prompt=question)
                    return self._json({"answer": text, "latency_s": round(g.last_latency, 2)})
                if url.path == "/voice":
                    heard = g.stt(body)
                    t_stt = g.last_latency
                    t0 = time.perf_counter()
                    reply, trace = assistant.ask(heard) if heard else ("I didn't catch that.", [])
                    t_llm = time.perf_counter() - t0
                    pcm, rate = g.tts(reply)
                    timing = "stt=%.2f assistant=%.2f tts=%.2f" % (t_stt, t_llm, g.last_latency)
                    return self._send(200, wav_bytes(pcm, rate), "audio/wav",
                                      {"X-Heard": _ascii(heard), "X-Reply": _ascii(reply), "X-Timing": timing})
            except Exception as e:
                return self._json({"error": "%s: %s" % (type(e).__name__, str(e)[:500])}, 502)
            self._send(404, b"", "text/plain")

        def log_message(self, fmt, *args):
            sys.stderr.write("assistant: " + (fmt % args) + "\n")

    return Handler


def main(argv):
    port, mode, camera = 8770, "dry-run", None
    while argv:
        a = argv.pop(0)
        if a == "--port":
            port = int(argv.pop(0))
        elif a == "--roku":
            mode = argv.pop(0)
        elif a == "--image":
            camera = file_camera(argv.pop(0))
        elif a == "--camera-url":
            camera = url_camera(argv.pop(0))
    g = Gemini(load_key())
    assistant = Assistant(g, Tools(gemini=g, roku_mode=mode, camera=camera))
    srv = ThreadingHTTPServer(("0.0.0.0", port), make_handler(assistant, g))
    print("assistant: listening on :%d (roku %s)" % (port, mode))
    srv.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
