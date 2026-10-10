"""
analyzer.py -- the spectrum analyzer as a widget any app can put on its screen.

``spectrum.py`` is the demo that runs it on fake music. This file is the part
an app imports to show its own sound::

    from analyzer import Spectrum, levels_for

    out.play(song)                       # an audiodev AudioOut
    meter = Spectrum(display_drv, levels_for(out))
    meter.start(app)

Importing it opens nothing and starts nothing. ``Spectrum`` takes a display
driver and a source of levels: any object with ``levels(t)`` and ``bands``,
or a factory that builds one for a band count (``FakeMusic`` is one, and so
is what ``levels_for`` returns). It draws on a timer from the app it's
started on, and only the rows that moved reach the panel.

On a board that is usbif's USB sound card, ``levels_for_soundcard()`` takes
the place of ``levels_for(out)``: the meter reads what the computer plays.
"""

from multimer import ticks_diff, ticks_ms
from pygraphics import RGB565, FrameBuffer
from spectrum_view import SpectrumView, band_count_for

try:
    from time import ticks_us
except ImportError:  # CPython

    def ticks_us():
        return ticks_ms() * 1000


FRAME_MS = 16
REPORT_S = 5


def levels_for(audio_out):
    """Levels of whatever an audiodev ``AudioOut`` is playing, for ``Spectrum``.

    Call it after ``play()``. The meter reads the audio pump's tap and does
    its analysis in C, so Python never touches a sample; that needs the
    output to be playing through the pump (``audio_out.pumped``) on a
    firmware with audiodsp's ``audiometer``. An output playing on the
    interpreter thread raises ``ValueError`` instead.
    """
    if not getattr(audio_out, "pumped", False):
        raise ValueError(
            "levels_for() needs an AudioOut playing through the audio pump "
            "(audio_out.pumped is False): play() first, on a firmware with "
            "audiodsp's audiopump and audiometer"
        )
    fmt = audio_out.format

    def tap_levels(bands):
        from pump_levels import TapLevels

        return TapLevels(bands, rate=fmt.rate, channels=fmt.channels)

    return tap_levels


def levels_for_soundcard():
    """Levels of what usbif's USB sound card is playing, for ``Spectrum``.

    The meter reads the sound card's pump and does its analysis in C, as
    ``levels_for`` does for the audio pump. That needs a board whose firmware
    has usbif's sound card and audiodsp's ``audiometer``; anywhere else this
    raises ``ValueError`` (or ``ImportError`` without ``audiometer``).
    """
    import pump_levels

    if not pump_levels.available():
        raise ValueError(
            "levels_for_soundcard() needs a board running usbif's sound card "
            "pump (pump_levels.available() is False)"
        )
    return pump_levels.PumpLevels


class Spectrum:
    """A spectrum analyzer drawn on ``display_drv``, fed by ``source``.

    Every keyword is optional:

    - ``bands``: how many bars. Default: half of what ``band_count_for`` gives
      for the panel's width.
    - ``height``: the meter's height in rows. Default: half the panel.
    - ``y``: the meter's top row. Default: the bottom of the panel.
    - ``style``: ``"smooth"`` or ``"segmented"``.
    - ``report``: print the frame rate and per-part costs every few seconds.

    Halving bands and height trades resolution for frame rate under loud
    music: 18-19 fps full size, 35-45 at half by half on the ESP32-P4.
    """

    def __init__(self, display_drv, source, *, bands=None, height=None, y=None, style="smooth", report=False):
        self.display_drv = display_drv
        W, H = display_drv.width, display_drv.height
        if height is None:
            height = H // 2
        if bands is None:
            bands = band_count_for(W) // 2
        self.y = H - height if y is None else y
        self.view = SpectrumView(W, height, bands=bands, style=style)
        # A class (FakeMusic) or a factory (levels_for) builds the source for
        # this band count; anything else already is one.
        if isinstance(source, type) or not hasattr(source, "levels"):
            source = source(self.view.bands)
        self.source = source
        self.report = report
        self.last_report = ""
        self.timer = None
        # A panel that needs presenting (the P4's DSI panel samples its
        # framebuffer only when told to) gets just the changed rows presented
        # after each frame, rather than appdev's whole-frame refresh every
        # 33 ms, which costs 22 ms a time on the P4.
        self.present_rows = bool(getattr(display_drv, "needs_refresh", False)) and hasattr(
            getattr(display_drv, "_raw_buffer", None), "refresh_rect"
        )
        self._send = self._panel_blit()
        self._dirty = [0, 0]  # rows touched this frame, top and bottom
        self._stats = [0, 0, 0, 0, 0]  # frames, data us, update us, draw us, report start
        self._t0 = self._last = 0

    def _panel_blit(self):
        """How a run of bar rows reaches the panel.

        Where the driver shares a packed framebuffer that has to be presented
        (the P4's DSI panel), rows are copied straight into it with no cache
        sync, and the frame's dirty band is synced and presented once, after
        the bars. The panel's own ``blit`` syncs the cache for every call,
        and a cache sync runs with interrupts off: forty-odd of them a frame
        kept the USB interrupt waiting long enough to lose sound-card
        packets. Otherwise, the driver's ``blit_rect``."""
        d = self.display_drv
        if self.present_rows and getattr(d, "share_framebuffer", False):
            buf, _, n, stride = d.framebuffers()
            w, h = d.width, d.height
            if n == w * h * 2 and stride == w * 2:
                return FrameBuffer(buf, w, h, RGB565).blit_rect
        return d.blit_rect

    def _blit(self, buf, x, y, w, h):
        y += self.y
        self._send(buf, x, y, w, h)
        d = self._dirty
        if y < d[0]:
            d[0] = y
        if y + h > d[1]:
            d[1] = y + h

    def start(self, app, period_ms=FRAME_MS):
        """Paint the meter's background and start drawing from ``app``'s timer."""
        d, view = self.display_drv, self.view
        fill = getattr(d, "fill_rect", None)
        if fill is not None and view.height < d.height:
            fill(0, 0, d.width, d.height, 0)  # clear whatever the panel showed before
        d.blit_rect(view.strip(0, view.height), 0, self.y, view.width, view.height)
        if self.present_rows:
            d.show()
        view._build_bar_columns()  # a second on the P4; not on the first frame
        self._t0 = self._last = ticks_ms()
        self._stats = [0, 0, 0, 0, self._t0]
        self.timer = app.every(self.tick, period=period_ms)
        return self

    def stop(self):
        """Stop drawing; the last frame stays on the panel."""
        if self.timer is not None:
            self.timer.deinit()
            self.timer = None

    def tick(self, _=None):
        """Draw one frame. ``start`` calls this from a timer."""
        now = ticks_ms()
        dt = ticks_diff(now, self._last) / 1000
        self._last = now
        a = ticks_us()
        levels = self.source.levels(ticks_diff(now, self._t0) / 1000)
        b = ticks_us()
        view = self.view
        view.update(levels, min(dt, 0.1))
        c = ticks_us()
        dirty = self._dirty
        dirty[0], dirty[1] = self.y + view.height, 0
        view.render_columns(self._blit)
        if self.present_rows and dirty[1] > dirty[0]:
            self.display_drv.flush_rect(0, dirty[0], view.width, dirty[1] - dirty[0])
        if not self.report:
            return
        d = ticks_us()
        s = self._stats
        s[0] += 1
        s[1] += b - a
        s[2] += c - b
        s[3] += d - c
        span = ticks_diff(now, s[4])
        if span >= REPORT_S * 1000:
            n = s[0]
            self.last_report = "{:.1f} fps; per frame: data {:.2f} ms, update {:.2f} ms, draw+send {:.2f} ms".format(
                n * 1000 / span, s[1] / n / 1000, s[2] / n / 1000, s[3] / n / 1000
            )
            print(self.last_report)
            s[0] = s[1] = s[2] = s[3] = 0
            s[4] = now

    def capture(self, path):
        """Write the meter's rows on screen to ``path`` as raw little-endian
        RGB565: from the panel's own framebuffer when the driver shares it,
        else a rebuild."""
        d, view = self.display_drv, self.view
        frame = None
        fbs = getattr(d, "framebuffers", None)
        if fbs is not None and getattr(d, "share_framebuffer", False):
            buf, _, n, stride = fbs()
            if stride == view.width * 2 and n >= (self.y + view.height) * stride:
                frame = memoryview(buf)[self.y * stride : (self.y + view.height) * stride]
        with open(path, "wb") as f:
            f.write(frame if frame is not None else view.compose())
        return view.width, view.height
