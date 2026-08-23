"""Desktop secrets from environment variables.

On microcontrollers, delete/replace this file with plain assignments::

    WIFI_SSID = "your-ssid"
    WIFI_PASSWORD = "your-passphrase"
    GEMINI_API_KEY = "your-key"
"""

import sys

from displaydev import env_get

_DESKTOP = frozenset(("linux", "darwin", "win32", "unix", "webassembly", "emscripten"))


def _is_mcu_host(impl=None, platform=None):
    """True when this ``secrets.py`` must not run (real MCU board)."""
    if impl is None:
        impl = sys.implementation.name
    if platform is None:
        platform = sys.platform
    return impl in ("micropython", "circuitpython") and platform not in _DESKTOP


if _is_mcu_host():
    raise RuntimeError(
        "This utils/secrets.py is for desktop/browser hosts only.\n"
        "On a microcontroller, replace secrets.py with:\n"
        "\n"
        'WIFI_SSID = "your-ssid"\n'
        'WIFI_PASSWORD = "your-passphrase"\n'
        'GEMINI_API_KEY = "your-key"\n'
    )


def get(name, default=None):
    """Return secret ``name`` from the environment (or ``default``)."""
    return env_get(name, default)


WIFI_SSID = get("WIFI_SSID")
WIFI_PASSWORD = get("WIFI_PASSWORD")
GEMINI_API_KEY = get("GEMINI_API_KEY")
DEEPGRAM_TOKEN = get("DEEPGRAM_TOKEN")
GROQ_API_KEY = get("GROQ_API_KEY")
