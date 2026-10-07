# deps: lvgl
"""
lv_dynamic_fonts.py

Fonts your LVGL build left out, fetched from GitHub when you ask for them.

Step through the list with the arrow buttons, a keyboard's or TV remote's
left and right arrows, or Tab and Enter. Each font is downloaded once from
lvgl-bindings' ``fonts/`` folder, kept in a cache folder, and loaded with
``fs_driver`` and ``lv.binfont_create``, so the second time round it works
with no network at all. The status line says which happened. A download runs
a slice at a time on an LVGL timer (in a browser, as the browser's own
fetch), so the screen stays live, and stepping away from a font cancels it.

Connect to a network before you start this; it never turns Wi-Fi on itself.
On a board::

    import wifi
    wifi.connect_from_secrets()
    import lv_dynamic_fonts

The ``.bin`` format follows LVGL's version, and lvgl-bindings regenerates its
fonts whenever its LVGL pin moves. So the download comes from the
lvgl-bindings tag in ``FONT_REFS`` for the running LVGL's major.minor, never
from ``main``. An LVGL that isn't in the map gets a message, not a guess.

Our LVGL builds turn ``LV_USE_BIDI`` off, so the Hebrew sample is reversed
into display order here before LVGL sees it.
"""

import sys

_file = __file__.replace("\\", "/").split("/")
if len(_file) >= 2 and _file[-2] == "examples":  # noqa: SIM108
    _src = "/".join(_file[:-2]) or "."
else:
    _src = "."
if _src not in sys.path:
    sys.path.insert(0, _src)

import os  # noqa: E402

import display_driver  # noqa: E402, F401
import fs_driver  # noqa: E402
import lvgl as lv  # noqa: E402
import multimer  # noqa: E402

# The lvgl-bindings tag whose fonts each LVGL major.minor can read.
FONT_REFS = {(9, 5): "v9.5.22"}
URL = "https://raw.githubusercontent.com/PyDevices/lvgl-bindings/%s/fonts/%s.bin"
DRIVE = "S"


def _rtl(text):
    """Right-to-left text in display order, for an LVGL without BIDI."""
    return "".join(reversed(list(text)))


_PANGRAM = "The quick brown fox jumps over the lazy dog"
_SYMBOLS = " ".join(
    (lv.SYMBOL.WIFI, lv.SYMBOL.BLUETOOTH, lv.SYMBOL.BATTERY_FULL, lv.SYMBOL.HOME, lv.SYMBOL.SETTINGS)
)

# file name, family, size in px, sample text. The Montserrat sizes are ones
# lvgl-bindings' lv_conf.h doesn't compile in, and each sample fits on a
# 240x240 screen.
FONTS = (
    ("montserrat_12", "Montserrat", 12, _PANGRAM + "\n0123456789 " + _SYMBOLS),
    ("montserrat_20", "Montserrat", 20, "The quick brown fox\n" + _SYMBOLS),
    ("montserrat_28", "Montserrat", 28, "Black quartz\n" + _SYMBOLS),
    ("montserrat_48", "Montserrat", 48, "Ag " + lv.SYMBOL.WIFI + " " + lv.SYMBOL.SETTINGS),
    ("unscii_16", "unscii", 16, "UNSCII 16\n[0123456789]\n<{(*#@%&)}>"),
    (
        "dejavu_16_persian_hebrew",
        "DejaVu Sans",
        16,
        _rtl("שלום עולם") + "\nHello, world\n" + _rtl("אבגדהוזחטיכלמנסעפצקרשת"),
    ),
    (
        "source_han_sans_sc_16_cjk",
        "Source Han Sans",
        16,
        "你好，世界。\n中文字体\n日本語も少し",
    ),
)

# A board says how to connect; a computer or a browser has its own way.
if sys.platform in ("linux", "darwin", "win32", "webassembly", "emscripten"):
    _CONNECT_HINT = "connect, then step back to this font"
else:
    _CONNECT_HINT = "connect first, for example with wifi.connect_from_secrets()"


def lvgl_version():
    return lv.version_major(), lv.version_minor()


def font_ref():
    """The lvgl-bindings tag for the running LVGL, or None if it isn't pinned."""
    return FONT_REFS.get(lvgl_version())


# --- the cache --------------------------------------------------------------


def _cache_root():
    """A per-user cache folder on a desktop, ``/lvgl_fonts`` on a board or in
    a browser (there it lasts as long as the page)."""
    getenv = getattr(os, "getenv", None)
    base = None
    if getenv is not None:
        base = getenv("LOCALAPPDATA") or getenv("XDG_CACHE_HOME")
        if not base and getenv("HOME") and sys.platform != "webassembly":
            base = getenv("HOME") + "/.cache"
    return (base.replace("\\", "/") if base else "") + "/lvgl_fonts"


def cache_dir(ref):
    # The tag is part of the path, so moving the pin never reuses old files.
    return _cache_root() + "/" + ref


def cache_path(name, ref):
    return cache_dir(ref) + "/" + name + ".bin"


def _size(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return None


def _makedirs(path):
    so_far = ""
    for part in path.split("/"):
        if not part:
            so_far = so_far or "/"
            continue
        so_far = (so_far.rstrip("/") + "/" + part) if so_far else part
        if part.endswith(":"):  # a Windows drive
            continue
        try:
            os.mkdir(so_far)
        except OSError:
            pass  # already there


# --- the network ------------------------------------------------------------


class FetchError(Exception):
    """The download failed. ``offline`` is True when the network was the reason."""

    def __init__(self, message, offline=False):
        super().__init__(message)
        self.offline = offline


def board_offline():
    """True on a board whose Wi-Fi station isn't connected.

    Only looks: never turns the radio on or joins a network. False where
    there's no station to ask (a desktop, a browser), so the fetch itself
    is the test there.
    """
    try:
        import wifi

        return not wifi.radio.connected
    except (ImportError, AttributeError):
        pass
    try:
        import network

        return not network.WLAN(network.STA_IF).isconnected()
    except (ImportError, AttributeError, OSError, ValueError):
        return False


def _open(url):
    """Start the request. Returns ``(read, close, total bytes or None)``.

    CPython has ``urllib``; MicroPython has ``requests``, on a board and on a
    desktop.
    """
    try:
        from urllib.error import HTTPError
        from urllib.request import urlopen
    except ImportError:
        urlopen = None
    if urlopen is not None:
        try:
            r = urlopen(url, timeout=20)
        except HTTPError as e:
            raise FetchError("HTTP %d" % e.code)
        except OSError as e:  # URLError, a timeout, no route
            raise FetchError(str(getattr(e, "reason", e)), offline=True)
        return r.read, r.close, _length(r.headers.items())
    try:
        import requests
    except ImportError:
        raise FetchError("no HTTP client here (MicroPython's requests is missing)")
    try:
        r = requests.get(url)
    except OSError as e:
        raise FetchError("%s %s" % (type(e).__name__, e), offline=True)
    if r.status_code != 200:
        r.close()
        raise FetchError("HTTP %d" % r.status_code)
    return r.raw.read, r.close, _length((r.headers or {}).items())


def _length(headers):
    for key, value in headers:  # MicroPython's headers are a plain dict
        if key.lower() == "content-length":
            return int(value)
    return None


def _commit(tmp, path):
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp, path)


def fetch(url, path, chunk=2048):
    """Download ``url`` into ``path`` a chunk at a time, yielding
    ``(bytes so far, total or None)`` after each one, so a caller can do
    other work in between. Raises ``FetchError``.

    It writes to ``path + ".part"`` and renames that only once it's whole,
    so a download that stops halfway never looks cached.
    """
    tmp = path + ".part"
    read, close, total = _open(url)
    got = 0
    try:
        with open(tmp, "wb") as f:
            while True:
                try:
                    data = read(chunk)
                except OSError as e:
                    raise FetchError("the connection dropped (%s)" % e)
                if not data:
                    break
                f.write(data)
                got += len(data)
                yield got, total
    finally:
        close()
    if total and got != total:
        raise FetchError("got %d of %d bytes" % (got, total))
    _commit(tmp, path)


async def fetch_async(url, path):
    """The browser's ``fetch``: there, a download is asynchronous anyway."""
    import js

    try:
        r = await js.fetch(url)
    except Exception as e:  # the browser's TypeError: Failed to fetch
        # MicroPython's JsException carries (error, name, message)
        raise FetchError(str(e.args[-1] if e.args else e), offline=True)
    if not r.ok:
        raise FetchError("HTTP %d" % r.status)
    data = bytes(js.Uint8Array.new(await r.arrayBuffer()))
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    _commit(tmp, path)


# --- the screen -------------------------------------------------------------

_UI_SIZES = (14, 16, 24, 32, 40)


def _font_for(short_side):
    """The largest built-in Montserrat at or below a twentieth of the short side."""
    best = None
    for size in _UI_SIZES:
        font = getattr(lv, "font_montserrat_%d" % size, None)
        if font is not None and (best is None or size <= short_side // 20):
            best = font
    return best


class FontBrowser:
    def __init__(self):
        self.index = 0
        self.font = None  # the loaded font on show, destroyed when replaced
        self.loaded = None  # its file name
        self.state = "starting"  # fetching, downloaded, cached, offline, error, unpinned
        self._job = None  # (index, path, the fetch generator) while downloading
        self._timer = None
        self._said = 0  # when the progress was last shown
        self.ref = font_ref()
        if self.ref is not None:
            fs_driver.register(DRIVE)
            _makedirs(cache_dir(self.ref))
        self._build()
        self.show(0)

    # -- layout

    def _build(self):
        scr = lv.screen_active()
        w, h = scr.get_width(), scr.get_height()
        short = min(w, h)
        font = self.ui_font = _font_for(short)
        pad = max(4, short // 40)
        try:
            th = lv.theme_default_init(
                lv.display_get_default(),
                lv.palette_main(lv.PALETTE.BLUE),
                lv.palette_main(lv.PALETTE.TEAL),
                True,
                font,
            )
            lv.display_get_default().set_theme(th)
        except AttributeError:
            pass
        scr.set_style_text_font(font, 0)
        scr.set_style_pad_all(pad, 0)
        scr.set_style_pad_gap(pad, 0)
        scr.remove_flag(lv.obj.FLAG.SCROLLABLE)
        scr.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        muted = lv.palette_main(lv.PALETTE.GREY)

        title = lv.label(scr)
        title.set_text("Fonts from GitHub")
        title.set_style_text_color(lv.palette_main(lv.PALETTE.BLUE), 0)

        card = lv.obj(scr)
        card.set_width(lv.pct(100))
        card.set_flex_grow(1)
        card.set_style_pad_all(pad, 0)
        card.set_style_pad_gap(pad // 2, 0)
        card.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        top = lv.obj(card)
        top.remove_style_all()
        top.set_size(lv.pct(100), lv.SIZE_CONTENT)
        top.set_flex_flow(lv.FLEX_FLOW.ROW)
        top.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        top.set_style_pad_column(pad, 0)
        self.name = lv.label(top)
        self.kb = lv.label(top)
        self.kb.set_style_text_color(muted, 0)
        self.meta = lv.label(card)  # the file name
        # one line, cut short with dots: DOTS needs a fixed height
        self.meta.set_size(lv.pct(100), font.get_line_height())
        self.meta.set_long_mode(lv.label.LONG_MODE.DOTS)
        self.meta.set_style_text_color(muted, 0)
        self.sample = lv.label(card)
        self.sample.set_width(lv.pct(100))
        self.sample.set_long_mode(lv.label.LONG_MODE.WRAP)
        self.sample.set_style_pad_top(pad, 0)

        row = lv.obj(scr)
        row.remove_style_all()
        row.set_size(lv.pct(100), lv.SIZE_CONTENT)
        row.set_flex_flow(lv.FLEX_FLOW.ROW)
        row.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.prev_btn = self._button(row, lv.SYMBOL.LEFT + " Prev", -1, pad)
        self.counter = lv.label(row)
        self.next_btn = self._button(row, "Next " + lv.SYMBOL.RIGHT, 1, pad)

        self.status = lv.label(scr)
        self.status.set_width(lv.pct(100))
        self.status.set_long_mode(lv.label.LONG_MODE.WRAP)
        self.status.set_style_text_color(muted, 0)

    def _button(self, parent, text, step, pad):
        btn = lv.button(parent)
        btn.set_style_pad_hor(pad * 2, 0)
        btn.set_style_pad_ver(pad, 0)
        lbl = lv.label(btn)
        lbl.set_text(text)
        lbl.center()
        btn.add_event_cb(lambda _e: self.step(step), lv.EVENT.CLICKED, None)
        # Arrow keys reach whichever button has the focus, as LV_EVENT_KEY.
        btn.add_event_cb(self._on_key, lv.EVENT.KEY, None)
        return btn

    def _on_key(self, e):
        key = e.get_key()
        if key in (lv.KEY.LEFT, lv.KEY.UP):
            self.step(-1)
        elif key in (lv.KEY.RIGHT, lv.KEY.DOWN):
            self.step(1)

    def _say(self, state, text, color=None):
        self.state = state
        self.status.set_text(text)
        self.status.set_style_text_color(color or lv.palette_main(lv.PALETTE.GREY), 0)

    # -- stepping

    def step(self, delta):
        self.show((self.index + delta) % len(FONTS))

    def show(self, index):
        self._cancel()
        self.index = index
        name, family, size, _sample = FONTS[index]
        self.counter.set_text("%d / %d" % (index + 1, len(FONTS)))
        self.name.set_text("%s %d" % (family, size))
        self.meta.set_text(name + ".bin")
        self.kb.set_text("")
        if self.ref is None:
            major, minor = lvgl_version()
            self._unload()
            self._say(
                "unpinned",
                "LVGL %d.%d has no font set pinned in FONT_REFS, so nothing is fetched."
                % (major, minor),
                lv.palette_main(lv.PALETTE.ORANGE),
            )
            return
        path = cache_path(name, self.ref)
        if _size(path):
            if self._apply(index, path):
                self._say("cached", "Loaded from the cache")
            return
        self._unload()
        if board_offline():
            self._say("offline", "No network: " + _CONNECT_HINT, lv.palette_main(lv.PALETTE.ORANGE))
            return
        url = URL % (self.ref, name)
        self._say("fetching", "Fetching from GitHub...")
        if sys.platform in ("webassembly", "emscripten"):  # a browser
            import asyncio

            start = getattr(asyncio, "ensure_future", None) or asyncio.create_task
            start(self._fetch_async(index, url, path))
        else:
            # A board or a computer downloads on an LVGL timer, 40 ms at a
            # time, so the screen keeps drawing and the buttons keep working.
            # Connecting still holds things up for a moment, so the first
            # tick waits for a frame with the status on it.
            self._job = (index, path, fetch(url, path))
            self._said = multimer.ticks_ms()
            self._timer = lv.timer_create(self._pump, 50, None)

    def _pump(self, timer):
        timer.set_period(10)  # then as often as LVGL runs its timers
        index, path, job = self._job
        t0 = multimer.ticks_ms()
        try:
            while multimer.ticks_diff(multimer.ticks_ms(), t0) < 40:
                got, total = next(job)
        except StopIteration:
            self._stop_timer()
            self._job = None
            self._fetched(index, path)
            return
        except Exception as e:  # on the screen, not a traceback in a timer
            self._cancel()
            self._failed(e if isinstance(e, FetchError) else FetchError("%s %s" % (type(e).__name__, e)))
            return
        # Twice a second is plenty: redrawing the status every tick halved
        # the download speed on an ESP32-S3 with an 800x480 panel.
        if total and multimer.ticks_diff(t0, self._said) >= 500:
            self._said = t0
            self._say("fetching", "Fetching from GitHub: %d of %d KB" % (got // 1024, total // 1024))

    def _stop_timer(self):
        if self._timer is not None:
            self._timer.delete()
            self._timer = None

    def _cancel(self):
        """Stop a download in progress: stepping away from a font does."""
        self._stop_timer()
        if self._job is not None:
            _index, path, job = self._job
            self._job = None
            job.close()
            try:
                os.remove(path + ".part")
            except OSError:
                pass

    async def _fetch_async(self, index, url, path):
        try:
            await fetch_async(url, path)
        except FetchError as e:
            self._failed(e)
            return
        except Exception as e:
            self._failed(FetchError("%s %s" % (type(e).__name__, e)))
            return
        self._fetched(index, path)

    def _fetched(self, index, path):
        if index != self.index:
            return  # stepped away while the browser fetched; it's cached now
        if self._apply(index, path):
            self._say("downloaded", "Downloaded and cached")

    def _failed(self, e):
        orange = lv.palette_main(lv.PALETTE.ORANGE)
        if e.offline:
            self._say("offline", "No network (%s): %s" % (e, _CONNECT_HINT), orange)
        else:
            self._say("error", "Couldn't fetch it: %s" % e, lv.palette_main(lv.PALETTE.RED))

    def _apply(self, index, path):
        """Load the font at ``path`` and put it on the sample. False if LVGL
        couldn't read it."""
        name, family, size, sample = FONTS[index]
        font = lv.binfont_create(DRIVE + ":" + path)
        if not font:
            # Not a truncated download (those never leave their .part file)
            # nor another LVGL's (the tag is in the path): most likely memory.
            self._unload()
            self._say(
                "error",
                "LVGL couldn't load %s (out of memory?)" % path,
                lv.palette_main(lv.PALETTE.RED),
            )
            return False
        self.kb.set_text("%.1f KB" % ((_size(path) or 0) / 1024))
        self.sample.set_style_text_font(font, 0)
        self.sample.set_text(sample)
        self._replace(font, name)
        return True

    def _unload(self):
        """Back to the screen's own font, with nothing loaded."""
        self.sample.set_style_text_font(self.ui_font, 0)
        self.sample.set_text("")
        self._replace(None, None)

    def _replace(self, font, name):
        old, self.font, self.loaded = self.font, font, name
        if old is not None:
            lv.binfont_destroy(old)  # the sample has let go of it


def build_ui():
    inst = display_driver.event_loop.current_instance()
    if inst is not None:
        inst.disable()
    try:
        return FontBrowser()
    finally:
        if inst is not None:
            inst.enable()


# Canonical interactive entry: no app loop here. display_driver wires LVGL
# into the shared app at import, and the app keeps itself alive past the end
# of this script. ``browser`` is the running screen, for a REPL to poke at.
browser = build_ui()
