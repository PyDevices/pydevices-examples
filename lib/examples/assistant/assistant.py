# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
assistant
====================================================
Text in, text out, with Gemini calling the house's tools in between.

    python assistant.py                    # type requests; Roku keys dry-run
    python assistant.py --roku sim         # keys go to the simulator
    python assistant.py "how warm is it"   # one request and exit
"""

import sys

try:
    from time import perf_counter as _now
except ImportError:
    from time import ticks_ms as _tms

    def _now():
        return _tms() / 1000

from gemini import CHAT_MODEL, Gemini
from tools import DECLARATIONS

SYSTEM = (
    "You are the voice assistant for a house full of small devices. "
    "Use the tools to act or to find things out; never invent a reading. "
    "If a tool reports an error or has no such reading, say so plainly. "
    "Reply in one or two short spoken sentences: no markdown, no lists."
)

MAX_ROUNDS = 5


class Assistant:
    def __init__(self, gemini, tools, model=CHAT_MODEL, keep_history=True):
        self.g = gemini
        self.tools = tools
        self.model = model
        self.keep_history = keep_history
        self.history = []

    def ask(self, text):
        """Returns (reply, trace). trace lists each model round and tool call with its time."""
        contents = (self.history if self.keep_history else []) + [{"role": "user", "parts": [{"text": text}]}]
        trace = []
        for _ in range(MAX_ROUNDS):
            content = self.g.chat(contents, tools=DECLARATIONS, system=SYSTEM, model=self.model)
            trace.append(("model", round(self.g.last_latency, 2)))
            contents.append(content)  # verbatim: Gemini 3 needs its thought signatures back
            calls = [p["functionCall"] for p in content.get("parts", []) if "functionCall" in p]
            if not calls:
                reply = "".join(p.get("text", "") for p in content.get("parts", []) if not p.get("thought")).strip()
                if self.keep_history:
                    self.history = contents[-12:]
                return reply, trace
            responses = []
            for c in calls:
                t0 = _now()
                result = self.tools.call(c["name"], c.get("args", {}))
                trace.append(("tool", c["name"], c.get("args", {}), round(_now() - t0, 2)))
                fr = {"name": c["name"], "response": {"result": result}}
                if "id" in c:
                    fr["id"] = c["id"]
                responses.append({"functionResponse": fr})
            contents.append({"role": "user", "parts": responses})
        return "(gave up after %d rounds)" % MAX_ROUNDS, trace


def main(argv):
    from gemini_key import load_key
    from tools import Tools

    mode = "dry-run"
    if "--roku" in argv:
        i = argv.index("--roku")
        mode = argv[i + 1]
        del argv[i : i + 2]
    g = Gemini(load_key())
    a = Assistant(g, Tools(gemini=g, roku_mode=mode))
    if argv:
        reply, trace = a.ask(" ".join(argv))
        print(trace)
        print(reply)
        return
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if text:
            reply, trace = a.ask(text)
            print("  ", trace)
            print(reply)


if __name__ == "__main__":
    main(sys.argv[1:])
