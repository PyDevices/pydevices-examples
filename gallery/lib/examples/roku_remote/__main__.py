"""Entry for ``-m examples.roku_remote`` (MicroPython / CPython).

MicroPython requires this file when using ``-m`` on a package. The launcher
side effect lives in :mod:`roku_remote` (also imported by ``__init__`` for
plain ``import roku_remote`` / gallery). Re-import here is a no-op if
``__init__`` already ran the app to completion.

From ``pydevices-examples/lib`` (swap in ``micropython``, ``circuitpython``, ``python``, …)::

    micropython -m examples.roku_remote
    # relaunch on frontend switch (exit 42); stop on normal SDL quit (0)
    while true; do micropython -m examples.roku_remote; [ $? -eq 42 ] || break; done
    # PowerShell:
    while ($true) { micropython -m examples.roku_remote; if ($LASTEXITCODE -ne 42) { break } }
"""

from . import roku_remote  # noqa: F401
