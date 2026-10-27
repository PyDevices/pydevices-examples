"""When the Roku displays close: after multimer's keep-alive loop, and never twice over.

A timer-driven app's script body ends while the app is still running, and
multimer keeps it alive from its own exit hook. The displays used to close
from ``atexit``, which runs the most recently registered hook first, so the
channel closed while the app was still drawing. While ``close()`` waited on
the TV, a timer could also run ``show()`` inside it and relaunch the channel.

Run with: python tests/test_roku_close.py
"""

from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import _env  # noqa: F401

_LIB = Path(__file__).resolve().parent.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


class _Fake:
    def __init__(self, *args, **kwargs):
        pass


def _import_roku():
    stub = None
    try:
        import framebuf  # noqa: F401
    except ImportError:
        stub = types.ModuleType("framebuf")
        stub.RGB565 = 1
        stub.FrameBuffer = _Fake
        sys.modules["framebuf"] = stub
    try:
        from utils import roku_companion
    finally:
        if stub is not None:
            sys.modules.pop("framebuf", None)
    return roku_companion


roku_companion = _import_roku()


class _Encoder:
    def encode(self, buf, w, h):
        return b"png"


_log = []


class _Server:
    def __init__(self, host="", port=0):
        self.closed = False
        _log.append("bind")

    def update_frame(self, png):
        pass

    def close(self):
        self.closed = True


class _Inner:
    width = 4
    height = 2
    buffer = bytearray(16)

    def show(self):
        pass


class _TV:
    """Records ECP calls; ``during_close`` runs inside close_channel(), as a
    timer would while the request blocks."""

    host = "127.0.0.1"

    def __init__(self):
        self.during_close = None

    def frames(self, url):
        _log.append("launch")

    def close_channel(self):
        _log.append("quit")
        if self.during_close is not None:
            self.during_close()


class TestRokuClose(unittest.TestCase):
    def setUp(self):
        del _log[:]
        patches = (
            mock.patch.object(roku_companion, "_png_encoder", _Encoder),
            mock.patch.object(roku_companion, "_FrameServer", _Server),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _wrapper(self):
        tv = _TV()
        return roku_companion.RokuDisplayWrapper(_Inner(), tv, my_ip="127.0.0.1"), tv

    def test_close_waits_for_multimer_keep_alive_loop(self):
        from multimer import _hostloop

        with mock.patch.object(_hostloop, "strategy", return_value="exit_hook"), mock.patch.object(
            _hostloop, "on_stop"
        ) as on_stop, mock.patch("atexit.register") as register:
            display, _tv = self._wrapper()
            display.show()
        on_stop.assert_called_once_with(display.close)
        register.assert_not_called()

    def test_close_falls_back_to_atexit_without_a_keep_alive_loop(self):
        from multimer import _hostloop

        with mock.patch.object(_hostloop, "strategy", return_value=None), mock.patch.object(
            _hostloop, "on_stop"
        ) as on_stop, mock.patch("atexit.register") as register:
            display, _tv = self._wrapper()
            display.show()
        register.assert_called_once_with(display.close)
        on_stop.assert_not_called()

    def test_show_inside_close_does_not_relaunch(self):
        with mock.patch("atexit.register"):
            display, tv = self._wrapper()
            display.show()
            tv.during_close = display.show
            display.close()
            # Once closed, the next frame binds a new server and launches the
            # channel at it, the way the first frame did.
            tv.during_close = None
            display.show()
        self.assertEqual(_log, ["bind", "launch", "quit", "bind", "launch"])


if __name__ == "__main__":
    unittest.main()
