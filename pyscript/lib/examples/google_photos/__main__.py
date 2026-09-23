"""Entry for ``-m examples.google_photos`` (MicroPython / CPython).

MicroPython requires this file when using ``-m`` on a package. The launcher
side effect lives in :mod:`google_photos` (also imported by ``__init__`` for
plain ``import google_photos`` / gallery). Re-import here is a no-op if
``__init__`` already ran the app to completion.

From ``pydevices-examples/lib`` (swap in ``micropython``, ``python``, …)::

    micropython -m examples.google_photos
"""

from . import google_photos  # noqa: F401
