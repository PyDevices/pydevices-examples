# gallery: skip
"""Load the Gemini API key without ever displaying it.

The key lives in ~/.pydevices/secrets/gemini.key on the desktop, or
/gemini.key on a board. Callers pass the returned string straight to the
client; nothing here prints or logs it.
"""

import os

_PATHS = ("~/.pydevices/secrets/gemini.key", "/gemini.key")


def load_key():
    env = os.environ.get("GEMINI_API_KEY") if hasattr(os, "environ") else None
    if env:
        return env.strip()
    for p in _PATHS:
        try:
            p = os.path.expanduser(p)
        except AttributeError:
            pass
        try:
            with open(p) as f:
                k = f.read().strip()
            if k:
                return k
        except OSError:
            continue
    raise RuntimeError("no Gemini key found (looked in ~/.pydevices/secrets/gemini.key, /gemini.key)")
