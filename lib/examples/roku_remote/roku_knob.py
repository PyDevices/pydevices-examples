# deps: pygraphics
# modules: roku_engine
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_knob
====================================================
A Roku remote you drive with one rotary knob and its push button.

The fourth front end on :class:`roku_engine.RokuEngine`, for a board with an
encoder and a small screen and no touch (the LilyGO T-Embed S3, 170x320).
``roku_remote`` picks it on its own on a board like that; anywhere else, set
``ROKU_FRONTEND=knob``.

What the knob does
------------------
On the now-playing page (where it starts):

    turn          volume up or down, one ECP step per detent
    press         open the menu
    hold (0.6 s)  play / pause

In the menu, turning moves the highlight, a press picks the row, and a hold
is still play / pause. ``Navigate`` hands the knob to the TV's own menus:
turning sends Up / Down (or Left / Right), a press sends OK. The knob comes
back to volume after a few idle seconds, and the screen says when.

``Pick TV`` searches the LAN (SSDP ``roku:ecp``, plus the TVs you picked
before) and lists what answered. ``Type an address`` is the fallback for a TV
that won't answer multicast: turn to set each part of the address and press
to move to the next.

On the desktop the arrow keys stand in for the knob, Enter or Space for its
button (hold it for play / pause), and Escape quits. A mouse wheel turns it
too.

The now-playing page shows what ECP gives: the app in front, and for the
apps that report it, play / pause and the position. ECP has no volume read,
so the volume bar shows the steps you just sent rather than a level.

Nothing reaches the TV until you unlock it
------------------------------------------
``roku_engine`` starts with its send lock closed: it reads the TV but sends
no key until ``roku_engine.enable_sends()`` runs (on a desktop,
``ROKU_SENDS=1`` does the same). While it's locked, a turn or a press shows
``sends locked`` at the bottom of the screen. Unlock it in ``main.py`` when
you want the knob to drive the TV.

Run it on the LilyGO T-Embed S3
-------------------------------
Its ``board_config`` and ``wifi.py`` with ``secrets.py`` go on first, as in
board bring-up. Then put ``roku_engine``, ``roku_sim``, ``roku_knob`` and
``roku_remote`` in ``/lib`` (``mpy-cross -march=xtensawin`` makes them load
faster) and use this as ``/main.py``::

    import wifi

    wifi.connect_from_secrets()

    import roku_engine

    roku_engine.enable_sends()  # leave this out and the knob only watches
    import roku_remote  # picks this front end on a knob-only board

It starts on the TV you used last, or on ``Pick TV`` the first time.
"""

import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

from board_config import display_drv  # noqa: E402
import board_config  # noqa: E402
import appdev  # noqa: E402

app = appdev.App(board_config)

import keys  # noqa: E402
from multimer import ticks_diff, ticks_ms  # noqa: E402
from pygraphics import RGB565, FrameBuffer  # noqa: E402
from roku_engine import app_label, ascii_label  # noqa: E402
from roku_sim import make_engine  # noqa: E402

# --- feel ---------------------------------------------------------------
HOLD_MS = 600  # a press held this long is play / pause
NAV_IDLE_MS = 8000  # Navigate hands the knob back to volume after this
MENU_IDLE_MS = 20000  # an untouched menu goes back to now playing
REFRESH_MS = 2500  # now-playing poll while the knob is at rest
QUIET_AFTER_MS = 800  # no polling this soon after a turn: keys go first
VOL_SHOW_MS = 2500  # how long the volume bar stays after a turn
KNOB_DIR = 1  # -1 if clockwise reads backwards on your encoder
FOOT_H = 32  # the hint strip at the bottom

# --- colours (RGB565) ---------------------------------------------------
BG = 0x0000
PANEL = 0x18E3
INK = 0xFFFF
DIM = 0x8410
ACCENT = 0x901F  # Roku violet
PLAY = 0x07E0
WARN = 0xFC00


# Menu rows: (label, action). Built per visit so Power reads the TV's state.
_NAV_UD = "nav_ud"
_NAV_LR = "nav_lr"


def _clip(text, chars):
    text = ascii_label(text or "")
    return text if len(text) <= chars else text[: max(0, chars - 1)] + "~"


class KnobRemote:
    """State machine: pages ``now``, ``menu``, ``nav``, ``apps``, ``tvs``, ``ip``."""

    def __init__(self, engine=None, start_page="devices"):
        self.engine = engine if engine is not None else make_engine()
        self.w = display_drv.width
        self.h = display_drv.height
        self.cols = max(8, self.w // 8)
        self.buf = bytearray(self.w * self.h * 2)
        self.fb = FrameBuffer(self.buf, self.w, self.h, RGB565)

        self.page = "now"
        self.sel = 0
        self.top = 0
        self.rows = []  # (label, action, arg)
        self.nav_axis = _NAV_UD
        self.message = ""
        self.message_until = 0

        self.jobs = []  # work for the engine's sender, handed over one at a time
        self.vol_pending = 0  # detents not yet sent
        self.vol_recent = 0  # net steps shown on the bar
        self.vol_at = 0
        self.last_input = ticks_ms()
        self.last_refresh = 0
        self.down_at = None  # button press start (ticks)
        self.hold_fired = False

        self.tvs = []
        self.ip = [192, 168, 1, 2]
        self.ip_part = 0

        self.dirty = True
        app.on(app.events.MOUSEWHEEL, self._on_wheel)
        app.on(app.events.MOUSEBUTTONDOWN, self._on_down)
        app.on(app.events.MOUSEBUTTONUP, self._on_up)
        app.on(app.events.KEYDOWN, self._on_key)
        app.on(app.events.KEYUP, self._on_keyup)
        app.every(30, self._tick)

        if start_page == "remote" and self.engine.host:
            self._go("now")
        else:
            self._open_tvs()

    # --- input ----------------------------------------------------------

    def _on_wheel(self, e):
        try:
            steps = int(e.y) or int(e.x)
        except Exception:
            return
        self.turn(steps * KNOB_DIR)

    def _on_down(self, e):
        # appdev hands the encoder's push over as button 2; a desktop mouse
        # click is button 1 and belongs to nobody here.
        if getattr(e, "button", 0) == 2:
            self.button(True)

    def _on_up(self, e):
        if getattr(e, "button", 0) == 2:
            self.button(False)

    def _on_key(self, e):
        k = e.key
        if k in (keys.K_ESCAPE, keys.K_AC_BACK):
            app.request_quit()
        elif k in (keys.K_UP, keys.K_RIGHT):
            self.turn(1)
        elif k in (keys.K_DOWN, keys.K_LEFT):
            self.turn(-1)
        elif k in (keys.K_RETURN, keys.K_SPACE, keys.K_KP_ENTER):
            if self.down_at is None:  # ignore key repeat
                self.button(True)

    def _on_keyup(self, e):
        if e.key in (keys.K_RETURN, keys.K_SPACE, keys.K_KP_ENTER):
            self.button(False)

    def turn(self, steps):
        """The knob moved *steps* detents (clockwise positive)."""
        if not steps:
            return
        self.last_input = ticks_ms()
        page = self.page
        if page == "now":
            self.vol_pending += steps
            self.vol_recent += steps
            self.vol_at = self.last_input
        elif page == "nav":
            if self.nav_axis == _NAV_UD:
                key = "Down" if steps > 0 else "Up"
            else:
                key = "Right" if steps > 0 else "Left"
            for _ in range(min(abs(steps), 4)):
                self._queue(self._press, key)
            self._flash(key)
        elif page == "ip":
            self.ip[self.ip_part] = (self.ip[self.ip_part] + steps) % 256
        elif self.rows:
            self.sel = max(0, min(len(self.rows) - 1, self.sel + steps))
        self.dirty = True

    def button(self, down):
        """The knob's button went down (True) or up (False)."""
        now = ticks_ms()
        self.last_input = now
        if down:
            self.down_at = now
            self.hold_fired = False
            return
        if self.down_at is None:
            return
        self.down_at = None
        if not self.hold_fired:
            self.press()

    def hold(self):
        """A long press: play / pause everywhere but the address editor."""
        if self.page == "ip":
            self._go("tvs")
            return
        self._queue(self._press, "Play")
        self._flash("Play / Pause")

    def press(self):
        """A short press."""
        page = self.page
        if page == "now":
            self._open_menu()
        elif page == "nav":
            self._queue(self._press, "Select")
            self._flash("OK")
        elif page == "ip":
            if self.ip_part < 3:
                self.ip_part += 1
            else:
                host = "%d.%d.%d.%d" % tuple(self.ip)
                self._flash("Trying " + host)
                self._queue(self._connect, host)
        elif self.rows:
            _label, action, arg = self.rows[self.sel]
            action(arg)
        self.dirty = True

    # --- pages ----------------------------------------------------------

    def _go(self, page, rows=None, sel=0):
        self.page = page
        self.rows = rows or []
        self.sel = sel
        self.top = 0
        self.dirty = True

    def _open_menu(self, _=None):
        on = self.engine.power_is_on() if self.engine.device_info else True
        rows = [
            ("< Now playing", lambda _a: self._go("now"), None),
            ("Navigate up/down", self._nav, _NAV_UD),
            ("Navigate left/right", self._nav, _NAV_LR),
            ("OK", self._key_row, "Select"),
            ("Back", self._key_row, "Back"),
            ("Home", self._key_row, "Home"),
            ("Mute", self._key_row, "VolumeMute"),
            ("Info  *", self._key_row, "Info"),
            ("Apps", self._open_apps, None),
            ("Pick TV", self._open_tvs, None),
            ("Power off" if on else "Power on", self._key_row,
             "PowerOff" if on else "PowerOn"),
        ]
        self._go("menu", rows, 1)

    def _nav(self, axis):
        self.nav_axis = axis
        self._go("nav")

    def _key_row(self, key):
        self._queue(self._press, key)
        self._flash(key)
        if key in ("PowerOff", "PowerOn"):
            self._queue(self._refresh)
            self._go("now")

    def _open_apps(self, _=None):
        self._go("apps", [("< Menu", self._open_menu, None)])
        self._flash("Loading apps")
        self._queue(self._load_apps)

    def _open_tvs(self, _=None):
        rows = [("Type an address", self._open_ip, None)]
        for d in self.engine.cached_devices() or []:
            rows.append((d.get("name") or d.get("host"), self._pick, d.get("host")))
        self._go("tvs", rows, 1 if len(rows) > 1 else 0)
        self._flash("Searching the LAN")
        self._queue(self._discover)

    def _open_ip(self, _=None):
        host = self.engine.host or ""
        parts = host.split(".") if host else []
        if len(parts) != 4:
            try:
                from roku_engine import _local_ipv4

                parts = (_local_ipv4() or "192.168.1.2").split(".")
            except Exception:
                parts = ["192", "168", "1", "2"]
        try:
            self.ip = [int(p) & 255 for p in parts]
        except ValueError:
            self.ip = [192, 168, 1, 2]
        self.ip_part = 3 if self.ip[:3] != [0, 0, 0] else 0
        self._go("ip")

    def _pick(self, host):
        self._flash("Connecting")
        self._queue(self._connect, host)

    # --- work -----------------------------------------------------------
    #
    # Nothing here waits for the TV. Each job queues a request with the
    # engine's sender and returns; the reply comes back through
    # ``engine.deliver()`` at the top of the next tick, and the callbacks
    # below run there. The tick hands the sender one job at a time, so keys
    # go in the order they were asked for and a fast spin can't pile up
    # requests behind a TV that has stopped answering.

    def _queue(self, fn, *args):
        self.jobs.append((fn, args))

    def _press(self, key):
        self.engine.press_async(key, done=lambda ok: self._sent(key, ok))

    def _sent(self, key, ok):
        if not ok:
            why = self.engine.last_error or "failed"
            self._flash("%s: %s" % (key, why), WARN)

    def _refresh(self):
        self.last_refresh = ticks_ms()
        self.engine.refresh_async(done=self._refreshed)

    def _refreshed(self, _status=None):
        self.last_refresh = ticks_ms()
        self.dirty = True

    def _load_apps(self):
        self.engine.query_apps_async(done=self._apps_loaded)

    def _apps_loaded(self, apps):
        apps = apps or []
        rows = [("< Menu", self._open_menu, None)]
        for a in apps:
            rows.append((app_label(a.get("name") or a.get("id")), self._launch, a))
        if self.page == "apps":
            self._go("apps", rows, min(1, len(rows) - 1))
        self._flash("%d apps" % len(apps))

    def _launch(self, a):
        self._queue(self._send_launch, a)
        self._flash("Launching " + (a.get("name") or ""))
        self._go("now")

    def _send_launch(self, a):
        name = a.get("name") or a.get("id") or ""

        def done(ok):
            if ok:
                self.last_refresh = 0  # show what came up
            else:
                self._flash("%s: %s" % (name, self.engine.last_error or "failed"), WARN)

        self.engine.launch_async(a.get("id"), done=done)

    def _discover(self):
        self.engine.discover_async(done=self._discovered, timeout=1.5, scan_fallback=False)

    def _discovered(self, found):
        if found is None:
            self._flash("search: %s" % (self.engine.last_error or "failed"), WARN)
            return
        if self.page != "tvs":
            return
        have = {r[2] for r in self.rows}
        for d in found:
            host = d.get("host")
            if host and host not in have:
                self.rows.append((d.get("name") or host, self._pick, host))
                have.add(host)
        self._flash("%d TV%s found" % (len(found), "" if len(found) == 1 else "s"))
        self.dirty = True

    def _connect(self, host):
        def done(ok):
            if ok:
                self._flash("Connected")
                self._go("now")
            else:
                self._flash("No Roku at " + host, WARN)
                self.dirty = True

        self.engine.connect_async(host, done=done)

    def _flash(self, text, colour=ACCENT):
        self.message = (text, colour)
        self.message_until = ticks_ms() + 1800
        self.dirty = True

    def _tick(self, _t=None):
        try:
            self._tick_body()
        except Exception as exc:  # keep the app alive on a bad reply
            print("roku_knob:", exc)

    def _tick_body(self):
        self.engine.deliver()  # replies land here, never mid-request
        now = ticks_ms()
        if self.down_at is not None and not self.hold_fired:
            if ticks_diff(now, self.down_at) >= HOLD_MS:
                self.hold_fired = True
                self.hold()
        # Volume first, and one request at a time: the next goes when the
        # last has its answer, so a fast spin never floods the TV.
        idle_sender = self.engine.sender_idle()
        if idle_sender and self.vol_pending:
            step = 1 if self.vol_pending > 0 else -1
            self.vol_pending -= step
            self._press("VolumeUp" if step > 0 else "VolumeDown")
            idle_sender = False
        elif idle_sender and self.jobs:
            fn, args = self.jobs.pop(0)
            fn(*args)
            idle_sender = self.engine.sender_idle()
        idle = ticks_diff(now, self.last_input)
        if self.page == "nav" and idle > NAV_IDLE_MS:
            self._go("now")
        elif self.page in ("menu", "apps") and idle > MENU_IDLE_MS:
            self._go("now")
        if (
            self.page == "now"
            and self.engine.host
            and idle_sender
            and not self.jobs
            and not self.vol_pending
            and idle > QUIET_AFTER_MS
            and ticks_diff(now, self.last_refresh) > REFRESH_MS
        ):
            self._refresh()
        if self.vol_recent and ticks_diff(now, self.vol_at) > VOL_SHOW_MS:
            self.vol_recent = 0
            self.dirty = True
        if self.message and ticks_diff(now, self.message_until) > 0:
            self.message = ""
            self.dirty = True
        if self.dirty:
            self.dirty = False
            self.draw()

    # --- drawing --------------------------------------------------------

    def _text(self, s, x, y, colour=INK, scale=1):
        self.fb.text(s, x, y, colour, scale=scale, height=16)

    def _header(self, title):
        fb = self.fb
        fb.fill_rect(0, 0, self.w, 22, PANEL)
        self._text(_clip(title, self.cols - 1), 4, 3, INK)

    def _footer(self, hint):
        """Three short lines of 8 px text: what the knob does here, or news."""
        y = self.h - FOOT_H
        self.fb.fill_rect(0, y, self.w, FOOT_H, PANEL)
        if self.message:
            text, colour = self.message
            self.fb.text(_clip(text, self.cols), 4, y + 12, colour)
            return
        for i, line in enumerate(hint.split("|")[:3]):
            self.fb.text(_clip(line.strip(), self.cols), 4, y + 2 + 10 * i, DIM)

    def draw(self):
        self.fb.fill(BG)
        page = self.page
        if page == "now":
            self._draw_now()
        elif page == "nav":
            self._draw_nav()
        elif page == "ip":
            self._draw_ip()
        else:
            title = {"menu": "Menu", "apps": "Apps", "tvs": "Pick TV"}.get(page, page)
            self._draw_list(title)
        display_drv.blit_rect(self.buf, 0, 0, self.w, self.h)

    def _tv_name(self):
        info = self.engine.device_info or {}
        return info.get("user-device-name") or info.get("model-name") or self.engine.host or "no TV"

    def _draw_now(self):
        eng = self.engine
        fb = self.fb
        self._header(self._tv_name())
        big = 2 if self.w >= 160 else 1
        chars = max(4, self.w // (8 * big))
        app_name = eng.playback_app_label() or ""
        y = 34
        self._text(_clip(app_name, chars), 6, y, INK, big)
        y += 16 * big + 8
        state = (eng.playback_state_label() or "").lower()
        word = {"play": "Playing", "pause": "Paused", "buffer": "Buffering",
                "stop": "Stopped", "close": "Closed", "open": "Opening"}.get(state, "")
        if word:
            self._text(word, 6, y, PLAY if state == "play" else DIM)
        y += 20
        pos = eng.position_label()
        if pos:
            self._text(pos, 6, y, DIM)
        y += 20
        frac = eng.progress_fraction()
        if frac is not None:
            fb.fill_rect(6, y, self.w - 12, 4, PANEL)
            fb.fill_rect(6, y, int((self.w - 12) * frac), 4, ACCENT)
        y += 14
        # Volume: ECP cannot read the level, so show the steps just sent.
        fb.text("VOL", 6, y + 4, DIM)
        cx = self.w // 2 + 10
        half = self.w - cx - 8
        fb.fill_rect(cx - half, y + 2, 2 * half, 12, PANEL)
        fb.vline(cx, y, 16, DIM)
        n = self.vol_recent
        if n:
            span = min(half, abs(n) * max(2, half // 10))
            x0 = cx if n > 0 else cx - span
            fb.fill_rect(x0, y + 4, span, 8, ACCENT)
            self._text(("+%d" % n) if n > 0 else "%d" % n, 6, y + 20, ACCENT)
        self._footer("turn: volume|press: menu|hold: play/pause")

    def _draw_nav(self):
        self._header(self._tv_name())
        ud = self.nav_axis == _NAV_UD
        cx, cy = self.w // 2, self.h // 2 - 10
        fb = self.fb
        r = min(self.w, self.h) // 3
        fb.circle(cx, cy, r, PANEL, True)
        fb.circle(cx, cy, r // 3, ACCENT, True)
        self._text("OK", cx - 8, cy - 8, INK)
        a = r - 10
        if ud:
            fb.triangle(cx, cy - a, cx - 10, cy - a + 14, cx + 10, cy - a + 14, INK, True)
            fb.triangle(cx, cy + a, cx - 10, cy + a - 14, cx + 10, cy + a - 14, INK, True)
        else:
            fb.triangle(cx - a, cy, cx - a + 14, cy - 10, cx - a + 14, cy + 10, INK, True)
            fb.triangle(cx + a, cy, cx + a - 14, cy - 10, cx + a - 14, cy + 10, INK, True)
        idle = ticks_diff(ticks_ms(), self.last_input)
        left = max(0, (NAV_IDLE_MS - idle + 999) // 1000)
        self.fb.text("volume in %ds" % left, 6, self.h - FOOT_H - 14, DIM)
        self._footer("turn: move|press: OK|hold: play/pause")
        self.dirty = True  # keep the countdown moving

    def _draw_ip(self):
        self._header("Type an address")
        y = self.h // 2 - 30
        x = 6
        for i, part in enumerate(self.ip):
            s = "%d" % part
            colour = ACCENT if i == self.ip_part else INK
            self._text(s, x, y, colour)
            if i == self.ip_part:
                self.fb.hline(x, y + 18, 8 * len(s), ACCENT)
            x += 8 * len(s)
            if i < 3:
                self._text(".", x, y, DIM)
                x += 8
        self.fb.text(":8060  (ECP)", 6, y + 30, DIM)
        self._footer("turn: set|press: next part|hold: cancel")

    def _draw_list(self, title):
        self._header(title)
        row_h = 22
        top_y = 26
        fits = max(1, (self.h - top_y - FOOT_H) // row_h)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + fits:
            self.top = self.sel - fits + 1
        for i in range(self.top, min(len(self.rows), self.top + fits)):
            y = top_y + (i - self.top) * row_h
            on = i == self.sel
            if on:
                self.fb.fill_rect(0, y, self.w, row_h - 2, ACCENT)
            self._text(_clip(self.rows[i][0], self.cols - 1), 6, y + 2, INK if on else DIM)
        if len(self.rows) > fits:  # a thin scroll bar
            bar = max(8, (self.h - top_y - FOOT_H) * fits // len(self.rows))
            span = self.h - top_y - FOOT_H - bar
            off = span * self.top // max(1, len(self.rows) - fits)
            self.fb.fill_rect(self.w - 3, top_y + off, 3, bar, DIM)
        self._footer("turn: scroll|press: pick|hold: play/pause")


remote = None  # the running KnobRemote, for a REPL or a harness to reach


def create(engine=None, start_page="devices"):
    """Build the knob front end (the app keeps itself alive)."""
    global remote
    remote = KnobRemote(engine=engine, start_page=start_page)
    return remote


def run(engine=None, start_page="devices"):
    create(engine=engine, start_page=start_page)


# Direct import / example kit: auto-start. ``roku_remote`` owns launch when set.
import roku_engine as _roku_engine  # noqa: E402

if not getattr(_roku_engine, "_LAUNCHER_OWNS_RUN", False):
    _eng = make_engine()
    run(engine=_eng, start_page=_roku_engine.start_page_for_engine(_eng))
