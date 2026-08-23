# modules: roku_engine
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_graphics
====================================================
Portrait Roku remote drawn with ``pygraphics.FrameBuffer``.

One of three interchangeable Roku front ends (``roku_graphics``,
``roku_widgets``, ``roku_lvgl``) that all drive the same
:class:`roku_engine.RokuEngine`; the flagship LVGL UI ships as ``roku_lvgl``
and is what ``roku_remote`` launches.

Shares :class:`roku_engine.RokuEngine` for ECP over the LAN (SSDP discover +
HTTP keypress / apps / queries). Uses only three core PyDevices packages
(``pygraphics``, ``displaydev`` via ``board_config``, ``appdev``, ``multimer``).

Geometry scales from a 320x480 reference up through tall phone portraits.
Remote chrome matches ``roku_lvgl``: utility, D-pad, options (replay / info /
CC), transport, volume, channel, then APPS | MORE | SELECT. MORE lists TV
inputs (not diagnostic probes). Status uses a four-field plaque (name /
state / app / time) plus an under-plaque scrub rail.

Launch via ``roku_remote`` (prefs + MRU). Direct ``roku_graphics.run()`` also works.
Requires Roku **Control by mobile apps → Enabled**. Join WiFi before running
on a microcontroller.

Possible additions in the future: jpg/png icons (ECP ``GET /query/icon/{id}``,
via ``RokuEngine.query_icon``) for APPS tiles / status.
"""

import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
import keys
from pygraphics import RGB565, Area, FrameBuffer
from multimer import auto as timer
from roku_engine import (
    FRONTEND_BUTTONS,
    app_label,
    ascii_label,
    format_delete_status,
    format_switch_status,
    other_frontends,
    restart_app,
    set_frontend,
    unicast_scan_supported,
)
from roku_sim import make_engine

FRONTEND = "graphics"


def _c565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def _channels(c):
    return (c >> 8) & 0xF8, (c >> 3) & 0xFC, (c << 3) & 0xF8


def _lerp(c1, c2, t):
    r1, g1, b1 = _channels(c1)
    r2, g2, b2 = _channels(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return _c565(r, g, b)


def _wrap_label(text, max_chars, max_lines):
    """Wrap ``text`` into up to ``max_lines`` lines of ``max_chars`` each."""
    text = (text or "").strip()
    if max_chars < 1 or max_lines < 1:
        return [""]
    if not text:
        return [""]
    lines = []
    cur = ""
    for word in text.split(" "):
        if not word:
            continue
        while len(word) > max_chars:
            piece = word[:max_chars]
            word = word[max_chars:]
            if cur:
                lines.append(cur)
                cur = ""
                if len(lines) >= max_lines:
                    return lines
            if len(lines) + 1 >= max_lines and word:
                lines.append(piece[: max(1, max_chars - 1)] + ".")
                return lines
            lines.append(piece)
            if len(lines) >= max_lines:
                return lines
        trial = word if not cur else (cur + " " + word)
        if len(trial) <= max_chars:
            cur = trial
        else:
            lines.append(cur)
            if len(lines) >= max_lines:
                return lines
            cur = word
    if cur:
        if len(lines) < max_lines:
            lines.append(cur)
        else:
            # No room; mark overflow on the last line.
            last = lines[-1]
            if len(last) >= max_chars:
                lines[-1] = last[: max(1, max_chars - 1)] + "."
            else:
                lines[-1] = (last + ".")[:max_chars]
    return lines or [""]


def _shade(c, factor):
    """factor < 1 darkens, > 1 lightens (clamped)."""
    r, g, b = _channels(c)
    r = max(0, min(255, int(r * factor)))
    g = max(0, min(255, int(g * factor)))
    b = max(0, min(255, int(b * factor)))
    return _c565(r, g, b)


# Chassis + key roles (matches LVGL midnight palette).
_THEME = {
    "chassis": _c565(0x12, 0x14, 0x1A),
    "chassis2": _c565(0x1A, 0x1E, 0x28),
    "bezel": _c565(0x0A, 0x0C, 0x10),
    "status_bg": _c565(0x1C, 0x22, 0x2E),
    "plaque_edge": _c565(0x2A, 0x31, 0x40),
    "dpad_ring": _c565(0x1E, 0x25, 0x30),
    "key": _c565(0x3A, 0x40, 0x4E),
    "key_alt": _c565(0x2E, 0x34, 0x40),
    "accent": _c565(0x7C, 0x5C, 0xFC),
    "accent2": _c565(0x5A, 0x3E, 0xD0),
    "power": _c565(0xE0, 0x5A, 0x4A),
    "transport": _c565(0x3A, 0x5A, 0x72),
    "text": _c565(0xF2, 0xF4, 0xF8),
    "muted": _c565(0x9A, 0xA0, 0xB0),
    "ok_text": _c565(0xFF, 0xFF, 0xFF),
    "press": _c565(0xE8, 0xEC, 0xF4),
    "press_text": _c565(0x18, 0x1A, 0x22),
}


class _Btn:
    __slots__ = ("id", "label", "area", "role", "ecp", "meta", "round")

    def __init__(
        self, bid, label, x, y, w, h, role="key", ecp=None, meta=None, round=False
    ):
        self.id = bid
        self.label = label
        self.area = Area(x, y, w, h)
        self.role = role
        self.ecp = ecp
        self.meta = meta
        self.round = bool(round)


class _Remote:
    FONT_W = 8
    FONT_H = 16
    FONT_H14 = 14  # two-line plaque status (text14)

    def __init__(self, engine=None, start_page="devices"):
        self.width = display_drv.width
        self.height = display_drv.height
        self.bpp = display_drv.color_depth // 8
        self.unit = min(self.width, self.height)

        self.pad = max(3, self.unit // 64)
        self.radius = max(5, self.unit // 36)
        # 320→1 (comfortable); 480+→2 — bare unit//280 stays 1 until 560.
        self.font_scale = max(1, self.unit // 280) + (1 if self.unit >= 400 else 0)

        self.theme = _THEME
        self._chassis_rows = None
        self.engine = engine if engine is not None else make_engine()
        self.ip_buf = self.engine.host or ""
        self.page = (
            start_page if start_page in ("devices", "remote", "apps", "more") else "devices"
        )
        self.app_offset = 0
        self.app_page_size = 1
        self.selected_app_id = ""
        self.discover_list = []
        # Plaque fields (TL name / TR state / BL status / BR time) — match widgets/lvgl.
        self._name_line = "Roku Remote"
        self._state_line = ""
        self._status_line = "ready"
        self._time_line = ""
        self._progress_visible = False
        self._switch_armed = None
        self._delete_armed = None
        self._chrome_face = ""
        self._pending_chrome = False
        # Remote D-pad disc: (cx, cy, radius) or None when not on remote.
        self._dpad_ring = None

        # Layout regions — tall plaque like widgets/lvgl (two text rows + pads).
        self.progress_h = 2
        _plaque_floor = 40 if self.height <= 360 else 64
        self.plaque_h = max(
            _plaque_floor,
            self.height // 10,
            self.FONT_H * self.font_scale * 2 + 4 * self.pad,
        )
        self.status_h = self.plaque_h  # content offset alias
        self.margin_x = self.pad

        self.buttons = []
        self._by_id = {}
        self._status_timer = timer.Timer(-1)
        self._pending_status = None
        self._pending_state = None
        self._playback_busy = False
        self._status_ticks = 0
        # Discovery / ECP jobs queue here; ``_status_pump`` drains one per tick
        # (no ``_thread`` — ESP32 stacks are too small for network).
        self._bg_q = []
        self._bg_busy = False
        self._pending_devices = []
        self._pending_select_list = None
        self._pending_scan_status = None
        self._scan_busy = False
        self._scan_kind = None
        self._scan_cancel = False
        self._scan_full = False
        # Select-page long-press delete (MOUSEBUTTONDOWN → UP), like widgets.
        self._press_t0 = 0
        self._press_btn = None
        # Soft Timer callbacks can re-enter Python while _draw_all/_flash/_present
        # is running (schedule between bytecodes). Concurrent FBDisplay.show() on
        # DPI has been observed to reboot the ESP32-P4; skip pump while UI draws.
        self._ui_lock = 0

        # Compose into the display's own buffer when possible (FBDisplay / DPI).
        # A full-frame Python blit_rect on 720×720 is ~12s; direct compose + show is ~20ms.
        # SDL/PG keep a texture handle in ``_buffer`` (int) — not a sized pixel buffer.
        need = self.width * self.height * self.bpp
        drv_buf = getattr(display_drv, "_buffer", None)
        self._compose_direct = False
        if drv_buf is not None:
            try:
                self._compose_direct = len(drv_buf) >= need
            except TypeError:
                self._compose_direct = False
        self.ba = drv_buf if self._compose_direct else bytearray(need)
        self.fb = FrameBuffer(self.ba, self.width, self.height, RGB565)
        max_w = self.width
        max_h = max(48, self.height // 8)
        self.btn_ba = bytearray(max_w * max_h * self.bpp)
        self.btn_fb = FrameBuffer(self.btn_ba, max_w, max_h, RGB565)

        resume = self.page == "remote" and (self.engine.host or "").strip()
        if resume:
            name = ""
            try:
                name = (self.engine.device_info or {}).get("user-device-name") or ""
            except Exception:
                pass
            self._name_line = ascii_label(name or self.engine.host or "Roku")
            self._state_line = ""
            self._status_line = self.engine.playback_app_label() or "ready"
            self._time_line = self.engine.position_label()
            self._build_layout()
            self._draw_all()
            self._refresh_playback_bg()
        else:
            # Select page from cache (no auto network scan). Scan is explicit.
            self.page = "devices"
            self.discover_list = list(self.engine.cached_devices() or [])
            n = len(self.discover_list)
            self._status_line = ("%d saved" % n) if n else "no TVs - press Scan"
            self._state_line = ""
            self._time_line = ""
            self._progress_visible = False
            self._build_layout()
            self._draw_all()

            def _soft():
                try:
                    devices = self.engine.refresh_cached_names()
                except Exception:
                    devices = self.engine.cached_devices()
                self._pending_select_list = list(devices or [])
                n2 = len(devices or [])
                self._pending_scan_status = (
                    ("%d saved" % n2) if n2 else "no TVs - press Scan"
                )

            self._run_bg(_soft)

        app.on(app.events.MOUSEBUTTONDOWN, self._on_mouse_down)
        app.on(app.events.MOUSEBUTTONUP, self._on_mouse_up)
        app.on(app.events.KEYDOWN, self._on_key)
        # Soft pump: apply playback status from bg workers + periodic refresh.
        # Must not call Timer.deinit from this callback (librt deadlock).
        try:
            self._status_timer.init(
                mode=timer.Timer.PERIODIC,
                period=250,
                callback=self._status_pump,
                hard=False,
            )
        except Exception:
            pass

    # ----- layout ---------------------------------------------------------

    def _build_layout(self):
        self.buttons = []
        self._by_id = {}
        self._dpad_ring = None
        y = self.pad
        # Status band is drawn separately; reserve space.
        y += self.status_h + self.pad

        content_x = self.margin_x
        content_w = self.width - 2 * self.margin_x

        if self.page == "apps":
            self._layout_apps(content_x, y, content_w)
            return
        if self.page == "more":
            self._layout_more(content_x, y, content_w)
            return
        if self.page == "devices":
            self._layout_devices(content_x, y, content_w)
            return

        self._layout_remote(content_x, y, content_w)

    def _add(
        self, bid, label, x, y, w, h, role="key", ecp=None, meta=None, round=False
    ):
        b = _Btn(
            bid,
            label,
            int(x),
            int(y),
            int(w),
            int(h),
            role=role,
            ecp=ecp,
            meta=meta,
            round=round,
        )
        self.buttons.append(b)
        self._by_id[bid] = b
        return b

    def _place3(self, x0, y, w, row_h, gap, specs):
        """Place three equal-width buttons (LVGL ``_place3`` parity)."""
        n = 3
        bw = (w - gap * (n - 1)) // n
        for i, (bid, lab, ecp, role) in enumerate(specs):
            self._add(bid, lab, x0 + i * (bw + gap), y, bw, row_h, role=role, ecp=ecp)

    def _layout_remote(self, x0, y0, w):
        """Match ``roku_lvgl._build_remote``: 5 rows + circular D-pad."""
        gap = self.pad
        H = self.height - y0 - self.pad
        if H < 80:
            H = max(80, self.height - self.plaque_h - 2 * self.pad)

        gaps = 5 * gap
        n_rows = 5
        min_row = 24 if H <= 280 else 38
        ring_ideal = int(min(w * 0.72, H * 0.42))
        ring_max = max(0, H - gaps - n_rows * min_row)
        ring = max(64, min(ring_ideal, ring_max))
        row_h = max(min_row, (H - ring - gaps) // n_rows)
        leftover = H - ring - gaps - n_rows * row_h
        if leftover > 0:
            row_h += leftover // n_rows
        while ring + n_rows * row_h + gaps > H and ring > 56:
            ring -= 4
            row_h = max(20, (H - ring - gaps) // n_rows)

        # 1) Utility: BACK | HOME | PWR
        pwr_lab = "PWR " + self.engine.power_label()
        self._place3(
            x0,
            y0,
            w,
            row_h,
            gap,
            (
                ("back", "BACK", "Back", "key"),
                ("home", "HOME", "Home", "accent"),
                ("power", pwr_lab, None, "power"),
            ),
        )
        y = y0 + row_h + gap

        # 2) Circular D-pad disc + round arrows/OK (LVGL ring parity).
        dx = x0 + (w - ring) // 2
        cell = max(1, ring // 3)
        margin = max(2, min(self.pad, cell // 6))
        arrow = max(1, cell - 2 * margin)
        cx = dx + ring // 2
        cy = y + ring // 2
        self._dpad_ring = (cx, cy, ring // 2)

        def _round_at(bid, lab, ox, oy, size, role, ecp):
            self._add(
                bid,
                lab,
                cx + ox - size // 2,
                cy + oy - size // 2,
                size,
                size,
                role=role,
                ecp=ecp,
                round=True,
            )

        _round_at("up", "^", 0, -cell, arrow, "dpad", "Up")
        _round_at("down", "v", 0, cell, arrow, "dpad", "Down")
        _round_at("left", "<", -cell, 0, arrow, "dpad", "Left")
        _round_at("right", ">", cell, 0, arrow, "dpad", "Right")
        _round_at("ok", "OK", 0, 0, cell, "accent", "Select")
        y += ring + gap

        # 3) Options: Replay | Info | CC
        cc_role = "accent" if self.engine.captions_track_hint() else "key_alt"
        self._place3(
            x0,
            y,
            w,
            row_h,
            gap,
            (
                ("replay", "RPL", "InstantReplay", "key_alt"),
                ("info", "*", "Info", "key_alt"),
                ("cc", "CC", "ClosedCaption", cc_role),
            ),
        )
        y += row_h + gap

        # 4) Transport
        play_face = self.engine.play_label()
        self._chrome_face = "%s|%s" % (play_face, self.engine.power_label())
        self._place3(
            x0,
            y,
            w,
            row_h,
            gap,
            (
                ("rev", "<<", "Rev", "transport"),
                ("play", play_face, "Play", "transport"),
                ("fwd", ">>", "Fwd", "transport"),
            ),
        )
        y += row_h + gap

        # 5) Volume
        self._place3(
            x0,
            y,
            w,
            row_h,
            gap,
            (
                ("vol_dn", "VOL-", "VolumeDown", "key"),
                ("vol_mute", "MUTE", "VolumeMute", "key_alt"),
                ("vol_up", "VOL+", "VolumeUp", "key"),
            ),
        )
        y += row_h + gap

        # 6) Chrome: APPS | MORE | SELECT
        self._place3(
            x0,
            y,
            w,
            row_h,
            gap,
            (
                ("apps_pg", "APPS", None, "ui"),
                ("more_pg", "MORE", None, "ui"),
                ("find", "SELECT", None, "ui"),
            ),
        )

    def _layout_apps(self, x0, y0, w):
        row_h = max(36, self.height // 14)
        gap = self.pad
        self._add("back_pg", "REMOTE", x0, y0, w // 3 - gap, row_h, role="ui")
        self._add("apps_refresh", "REFRESH", x0 + w // 3, y0, w // 3 - gap, row_h, role="ui")
        self._add("apps_next", "NEXT", x0 + 2 * w // 3, y0, w // 3, row_h, role="ui")
        y = y0 + row_h + gap
        # Square tiles, 3 across; as many rows as fit below the chrome.
        cols = 3
        bw = (w - gap * (cols - 1)) // cols
        bh = bw
        avail_h = self.height - y - self.pad
        rows = max(1, (avail_h + gap) // (bh + gap))
        while rows > 1 and rows * bh + (rows - 1) * gap > avail_h:
            rows -= 1
        max_slots = rows * cols
        self.app_page_size = max_slots
        apps = self.engine.store_apps()
        slice_apps = apps[self.app_offset : self.app_offset + max_slots]
        sel = str(
            self.selected_app_id
            or (self.engine.active_app or {}).get("id")
            or ""
        )
        for i, app in enumerate(slice_apps):
            name = app_label(app.get("name") or app.get("id") or "?")
            col = i % cols
            row = i // cols
            aid = str(app.get("id") or "")
            role = "accent" if (sel and aid == sel) or (not sel and i == 0) else "key"
            self._add(
                "app_%d" % i,
                name,
                x0 + col * (bw + gap),
                y + row * (bh + gap),
                bw,
                bh,
                role=role,
                meta=app,
            )

    def _layout_devices(self, x0, y0, w):
        """Pick among discovered Rokus (friendly name only)."""
        row_h = max(36, self.height // 14)
        gap = self.pad
        scanning = bool(self._scan_busy)
        kind = self._scan_kind
        scan_lab = "Cancel" if scanning and kind == "scan" else "SCAN"
        full_lab = "Cancel" if scanning and kind == "full" else "FULL"
        if unicast_scan_supported():
            third = (w - 2 * gap) // 3
            self._add("back_pg", "REMOTE", x0, y0, third, row_h, role="ui")
            self._add("find", scan_lab, x0 + third + gap, y0, third, row_h, role="accent")
            self._add(
                "find_full",
                full_lab,
                x0 + 2 * (third + gap),
                y0,
                third,
                row_h,
                role="accent",
            )
        else:
            half = (w - gap) // 2
            self._add("back_pg", "REMOTE", x0, y0, half, row_h, role="ui")
            self._add("find", scan_lab, x0 + half + gap, y0, half, row_h, role="accent")
        y = y0 + row_h + gap
        slot_h = max(32, self.FONT_H * self.font_scale + 2 * self.pad)
        devices = self.discover_list or []
        max_slots = max(1, (self.height - y - self.pad) // (slot_h + gap))
        for i, dev in enumerate(devices[:max_slots]):
            name = ascii_label((dev.get("name") or "").strip() or "")
            host = ascii_label((dev.get("host") or "").strip() or "")
            label = name or host or "Roku"
            self._add(
                "dev_%d" % i,
                label,
                x0,
                y + i * (slot_h + gap),
                w,
                slot_h,
                role="accent" if i == 0 else "key",
                meta=dev,
            )

    def _layout_more(self, x0, y0, w):
        """MORE: REMOTE + other frontends; TV inputs grid (LVGL parity)."""
        row_h = max(40, self.height // 11)
        gap = self.pad
        half = (w - gap) // 2
        third = (w - 2 * gap) // 3
        others = other_frontends(FRONTEND)
        self._add("back_pg", "REMOTE", x0, y0, third, row_h, role="ui")
        for i, fe in enumerate(others[:2]):
            lab = FRONTEND_BUTTONS.get(fe, fe.upper())
            self._add(
                "fe_%s" % fe,
                lab,
                x0 + (i + 1) * (third + gap),
                y0,
                third,
                row_h,
                role="ui",
                meta=fe,
            )
        y = y0 + row_h + gap
        inputs = self.engine.inputs()
        if not inputs:
            self._add("no_inputs", "no inputs", x0, y, w, row_h, role="key_alt")
            return
        avail = self.height - y - self.pad
        max_slots = max(1, (avail + gap) // (row_h + gap)) * 2
        for i, app in enumerate(inputs[:max_slots]):
            lab = ascii_label((app.get("name") or "").strip())
            if not lab:
                lab = self.engine.input_short_label(app, max_chars=10)
            col = i % 2
            row = i // 2
            self._add(
                "in_%d" % i,
                lab,
                x0 + col * (half + gap),
                y + row * (row_h + gap),
                half,
                row_h,
                role="key_alt",
                meta=app,
            )

    # ----- drawing --------------------------------------------------------

    def _role_colors(self, role, pressed=False):
        t = self.theme
        if pressed:
            return t["press_text"], t["press"], _shade(t["press"], 0.85), _shade(t["press"], 1.08)
        if role == "accent":
            face = t["accent"]
            return t["ok_text"], face, t["accent2"], _shade(face, 1.15)
        if role == "power":
            face = t["power"]
            return t["text"], face, _shade(face, 0.75), _shade(face, 1.12)
        if role == "transport":
            face = t["transport"]
            return t["text"], face, _shade(face, 0.8), _shade(face, 1.12)
        if role == "dpad":
            face = t["key"]
            return t["text"], face, _shade(face, 0.78), _shade(face, 1.14)
        if role == "ui":
            face = t["key_alt"]
            return t["muted"], face, _shade(face, 0.8), _shade(face, 1.1)
        if role == "key_alt":
            face = t["key_alt"]
            return t["text"], face, _shade(face, 0.8), _shade(face, 1.1)
        face = t["key"]
        return t["text"], face, _shade(face, 0.78), _shade(face, 1.12)

    def _ui_begin(self):
        self._ui_lock += 1

    def _ui_end(self):
        if self._ui_lock > 0:
            self._ui_lock -= 1

    def _present(self):
        if not self._compose_direct:
            display_drv.blit_rect(self.ba, 0, 0, self.width, self.height)
        display_drv.show()

    def _draw_chassis(self):
        t = self.theme
        h = self.height
        w = self.width
        rows = self._chassis_rows
        if rows is None or len(rows) != h:
            rows = []
            for j in range(h):
                rows.append(
                    _lerp(t["chassis"], t["chassis2"], j / (h - 1) if h > 1 else 0)
                )
            self._chassis_rows = rows
        for j, c in enumerate(rows):
            self.fb.fill_rect(0, j, w, 1, c)
        # Inset bezel
        m = max(2, self.pad // 2)
        self.fb.rect(m, m, w - 2 * m, h - 2 * m, t["bezel"])

    def _draw_button(self, btn, pressed=False):
        x, y, w, h = btn.area.x, btn.area.y, btn.area.w, btn.area.h
        if w <= 0 or h <= 0:
            return
        # Cap scratch buffer; oversized keys draw straight onto the screen FB.
        if w * h * self.bpp > len(self.btn_ba):
            fg, face, lo, hi = self._role_colors(btn.role, pressed)
            self.fb.fill_rect(x, y, w, h, face)
            return

        fg, face, lo, hi = self._role_colors(btn.role, pressed)
        self.btn_fb = FrameBuffer(self.btn_ba, w, h, RGB565)
        # Round D-pad keys sit on the disc — fill corners with ring color so a
        # partial redraw does not punch chassis-colored holes in the disc.
        if btn.round and self._dpad_ring:
            self.btn_fb.fill(self.theme.get("dpad_ring", self.theme["key_alt"]))
        else:
            self.btn_fb.fill(self.theme["chassis"])
        if btn.round:
            r = min(w, h) // 2
        else:
            r = min(self.radius, w // 3, h // 3)

        # 3D: top-lit gradient round rect
        for j in range(h):
            if j < r:
                d = r - j
            elif j >= h - r:
                d = r - (h - 1 - j)
            else:
                d = 0
            if d:
                # approximate circular inset
                inset = 0
                rr = r * r
                dd = d * d
                # integer sqrt-ish: try
                s = 0
                while (s + 1) * (s + 1) <= rr - dd:
                    s += 1
                inset = r - s
            else:
                inset = 0
            t = j / (h - 1) if h > 1 else 0
            # pressed → invert lighting
            if pressed:
                c = _lerp(lo, hi, t)
            else:
                c = _lerp(hi, lo, t)
            ww = w - 2 * inset
            if ww > 0:
                self.btn_fb.fill_rect(inset, j, ww, 1, c)

        # Soft rim
        self.btn_fb.round_rect(0, 0, w, h, r, _shade(face, 0.55), False)

        text = btn.label or ""
        scale = self.font_scale
        pad = 2
        avail_w = max(1, w - 2 * pad)
        avail_h = max(1, h - 2 * pad)
        while scale > 1 and (
            self.FONT_W * scale > avail_w or self.FONT_H * scale > avail_h
        ):
            scale -= 1
        cw = self.FONT_W * scale
        ch = self.FONT_H * scale
        max_chars = max(1, avail_w // cw)
        max_lines = max(1, avail_h // ch)
        lines = _wrap_label(text, max_chars, max_lines)
        total_h = len(lines) * ch
        ty0 = max(0, (h - total_h) // 2)
        for li, line in enumerate(lines):
            tw = len(line) * cw
            tx = max(0, (w - tw) // 2)
            ty = ty0 + li * ch
            if scale != 1:
                self.btn_fb.text16(line, tx, ty, fg, scale)
            else:
                self.btn_fb.text16(line, tx, ty, fg)
        self.fb.blit(self.btn_fb, x, y)

    def _text16(self, text, x, y, color, scale=None):
        if scale is None:
            scale = self.font_scale
        if scale != 1:
            self.fb.text16(text, x, y, color, scale)
        else:
            self.fb.text16(text, x, y, color)

    def _text14(self, text, x, y, color, scale=None):
        if scale is None:
            scale = self.font_scale
        if scale != 1:
            self.fb.text14(text, x, y, color, scale)
        else:
            self.fb.text14(text, x, y, color)

    def _draw_plaque(self):
        """Brushed plaque: TL name, TR state, BL status (≤2 lines), BR time."""
        t = self.theme
        x = self.pad
        y = self.pad
        w = self.width - 2 * self.pad
        h = self.plaque_h
        edge = _shade(t["status_bg"], 1.2)
        self.fb.fill_rect(x, y, w, h, t["status_bg"])
        self.fb.rect(x, y, w, h, edge)
        # Name/state/buttons: text16. Two-line BL status: text14.
        scale = self.font_scale
        cw = self.FONT_W * scale
        ch = self.FONT_H * scale
        half = max(1, h // 2)
        y_top = y + max(2, (half - ch) // 2)
        inner = self.pad

        # Top-left device name
        name = self._name_line or "Roku Remote"
        max_name = max(4, (w - 2 * inner - 8 * cw) // cw)
        if len(name) > max_name:
            name = name[: max(1, max_name - 1)] + "."
        self._text16(name, x + inner, y_top, t["text"], scale)

        # Top-right media state
        state = self._state_line or ""
        if state:
            max_st = max(2, (w // 3) // cw)
            if len(state) > max_st:
                state = state[: max(1, max_st - 1)] + "."
            tx = x + w - inner - len(state) * cw
            self._text16(state, tx, y_top, t["muted"], scale)

        # Bottom-left status (app / prompts); may be two lines
        status = self._status_line or ""
        on_select = self.page == "devices"
        full_width = on_select or bool(self._switch_armed)
        time_txt = "" if full_width else (self._time_line or "")
        # Fit BR clock first (pos/dur needs ~11+ glyphs; the old w//3 cap clipped
        # duration on 240-wide panels). Budget up to half the plaque.
        if time_txt:
            max_time_chars = max(4, (w - 2 * inner) // (2 * cw))
            if len(time_txt) > max_time_chars:
                time_txt = time_txt[: max(1, max_time_chars - 1)] + "."
        reserve = (len(time_txt) * cw + inner) if time_txt else 0
        max_status_w = max(40, w - 2 * inner - reserve)
        max_chars = max(4, max_status_w // cw)
        if "\n" in status:
            parts = status.split("\n")
        else:
            parts = [status]
        lines = []
        for p in parts:
            p = ascii_label(p) if p else ""
            wrapped = _wrap_label(p, max_chars, 2)
            lines.extend(wrapped)
            if len(lines) >= 2:
                break
        lines = lines[:2] or [""]
        nlines = len(lines)
        # Two lines use text14 so the stack fits the plaque better.
        st_ch = (self.FONT_H14 if nlines >= 2 else self.FONT_H) * scale
        block_h = nlines * st_ch
        y_bot = y + h - block_h - max(2, inner // 2)
        # Keep BL under TL when two lines; clamp into lower half.
        y_bot = max(y + half // 2, min(y_bot, y + h - block_h - 2))
        draw_st = self._text14 if nlines >= 2 else self._text16
        for li, line in enumerate(lines):
            if len(line) > max_chars:
                line = line[: max(1, max_chars - 1)] + "."
            draw_st(line, x + inner, y_bot + li * st_ch, t["muted"], scale)

        # Bottom-right clock (right-aligned; already fitted above)
        if time_txt:
            tx = x + w - inner - len(time_txt) * cw
            if tx < x + inner:
                tx = x + inner
            self._text16(time_txt, tx, y_bot, t["muted"], scale)

        # Hairline scrub rail in the pad gap under the plaque
        gap_y = max(1, (self.pad - self.progress_h) // 2)
        ty = y + h + gap_y
        track_c = edge
        fill_c = t["transport"]
        self.fb.fill_rect(x, ty, w, self.progress_h, track_c)
        if self._progress_visible:
            frac = self.engine.progress_fraction()
            if frac is not None:
                fw = int(w * frac + 0.5)
                if fw > 0:
                    if fw > w:
                        fw = w
                    self.fb.fill_rect(x, ty, fw, self.progress_h, fill_c)

    def _draw_dpad_ring(self):
        """Filled disc behind the D-pad (matches LVGL ``dpad_ring`` panel)."""
        ring = self._dpad_ring
        if not ring:
            return
        cx, cy, r = ring
        if r <= 0:
            return
        t = self.theme
        face = t.get("dpad_ring", t["key_alt"])
        edge = t.get("plaque_edge", t["bezel"])
        self.fb.circle(cx, cy, r, face, True)
        self.fb.circle(cx, cy, r, edge, False)

    def _draw_all(self):
        self._ui_begin()
        try:
            self._draw_chassis()
            self._draw_plaque()
            self._draw_dpad_ring()
            for btn in self.buttons:
                self._draw_button(btn, pressed=False)
            self._present()
        finally:
            self._ui_end()

    def _apply_chrome_face(self):
        """In-place Play / Power faces (no full page rebuild)."""
        play_face = self.engine.play_label()
        power_face = self.engine.power_label()
        self._chrome_face = "%s|%s" % (play_face, power_face)
        play = self._by_id.get("play")
        if play is not None and play.label != play_face:
            play.label = play_face
            self._draw_button(play, pressed=False)
        power = self._by_id.get("power")
        pwr_lab = "PWR " + power_face
        if power is not None and power.label != pwr_lab:
            power.label = pwr_lab
            self._draw_button(power, pressed=False)
        cc = self._by_id.get("cc")
        if cc is not None:
            role = "accent" if self.engine.captions_track_hint() else "key_alt"
            if cc.role != role:
                cc.role = role
                self._draw_button(cc, pressed=False)

    def _note_playback_chrome(self, force_rebuild=False):
        """Mailbox plaque (app + state) and in-place play/power chrome."""
        self._queue_playback_plaque()
        aid = str((self.engine.active_app or {}).get("id") or "")
        if aid:
            self.selected_app_id = aid
        face = "%s|%s" % (self.engine.play_label(), self.engine.power_label())
        if self.page != "remote":
            self._chrome_face = face
            return
        if force_rebuild:
            self._chrome_face = face
            return
        self._chrome_face = face
        self._pending_chrome = True

    def _set_name(self, line):
        self._name_line = ascii_label(line or "Roku Remote")

    def _set_state(self, line):
        self._state_line = ascii_label(line if line is not None else "")

    def _set_time(self, line):
        self._time_line = ascii_label(line if line is not None else "")

    def _set_progress_visible(self, visible):
        self._progress_visible = bool(visible)

    def _update_progress(self):
        frac = self.engine.progress_fraction()
        self._progress_visible = frac is not None

    def _set_status(self, line):
        """Bottom-left plaque: app name or user feedback; sync BR clock + rail."""
        on_select = self.page == "devices"
        full_width = on_select or bool(self._switch_armed)
        raw = line if line is not None else ""
        if "\n" in raw:
            self._status_line = "\n".join(ascii_label(p) for p in raw.split("\n"))
        else:
            self._status_line = ascii_label(raw)
        if on_select:
            self._set_time("")
            self._set_progress_visible(False)
            return
        if full_width:
            self._set_time("")
            self._set_progress_visible(False)
            return
        self._set_time(self.engine.position_label())
        self._update_progress()

    def _refresh_status(self, line=None):
        """Redraw plaque. Pass ``line`` for BL status; else playback app label."""
        if line is None:
            line = self.engine.playback_app_label()
        self._set_status(line)
        self._ui_begin()
        try:
            self._draw_plaque()
            if self.page == "remote":
                self._apply_chrome_face()
            self._present()
        finally:
            self._ui_end()

    def _queue_status(self, line):
        """Publish BL status for the soft pump (safe from worker threads)."""
        if line is None:
            return
        # Always queue — even when the app label is unchanged — so the pump
        # can refresh BR time / scrub from the latest engine probe (widgets/LVGL).
        if "\n" in line:
            self._pending_status = "\n".join(ascii_label(p) for p in line.split("\n"))
        else:
            self._pending_status = ascii_label(line)

    def _queue_state(self, line):
        if line is not None:
            self._pending_state = ascii_label(line)

    def _queue_playback_plaque(self):
        self._queue_status(self.engine.playback_app_label())
        self._queue_state(self.engine.playback_state_label())

    def _status_pump(self, _=None):
        """Drain pending plaque/chrome; periodically refresh playback."""
        self._drain_bg()
        if self._ui_lock:
            return
        dirty = False
        pending = self._pending_status
        if pending is not None:
            self._pending_status = None
            # Always apply: ``_set_status`` syncs position/duration + progress.
            self._set_status(pending)
            dirty = True
        pending_st = self._pending_state
        if pending_st is not None:
            self._pending_state = None
            if pending_st != self._state_line:
                self._set_state(pending_st)
                dirty = True
        if self._pending_chrome:
            self._pending_chrome = False
            if self.page == "remote":
                try:
                    self._apply_chrome_face()
                    dirty = True
                except Exception:
                    pass
        if dirty:
            try:
                self._draw_plaque()
                self._present()
            except Exception:
                pass

        # Soft-refresh / full Select list replace (name updates for cached TVs).
        if self._pending_select_list is not None:
            self.discover_list = list(self._pending_select_list)
            self._pending_select_list = None
            if self.page == "devices":
                self._build_layout()
                self._draw_all()

        # Apply background discovery results on the main tick.
        if self.page == "devices" and self._pending_devices:
            known = {d.get("host") for d in self.discover_list}
            new = [d for d in self._pending_devices if d.get("host") not in known]
            if new:
                self.discover_list.extend(new)
                self._set_status("Scanning... %d" % len(self.discover_list))
                self._build_layout()
                self._draw_all()
        if self.page == "devices" and self._pending_scan_status is not None:
            self._set_status(self._pending_scan_status)
            self._pending_scan_status = None
            self._build_layout()
            self._draw_all()

        self._status_ticks += 1
        # ~1s (pump is 250ms) — match widgets/LVGL so the clock/scrub keep up.
        if (
            self.page == "remote"
            and self.engine.connected
            and self._status_ticks % 4 == 0
            and not self._playback_busy
        ):
            self._playback_busy = True

            def _work():
                try:
                    self.engine.refresh_playback()
                    self._note_playback_chrome()
                except Exception:
                    pass
                self._playback_busy = False

            self._run_bg(_work)

    def _refresh_playback_bg(self, flash=None):
        """Background: refresh active-app/media-player and queue plaque."""
        if flash is not None:
            self._refresh_status(flash)

        def _work():
            try:
                self.engine.refresh_playback()
                self._note_playback_chrome(force_rebuild=False)
                self._pending_chrome = True
            except Exception:
                pass

        self._run_bg(_work)

    # ----- interaction ----------------------------------------------------

    def _hit(self, pos):
        for btn in self.buttons:
            if btn.area.contains(pos):
                return btn
        return None

    def _flash(self, btn):
        """Draw pressed face. Caller restores via ``_unpress`` (no soft timer)."""
        self._ui_begin()
        try:
            self._draw_button(btn, pressed=True)
            self._present()
        finally:
            self._ui_end()

    def _unpress(self, bid):
        self._ui_begin()
        try:
            if bid and bid in self._by_id:
                self._draw_button(self._by_id[bid], pressed=False)
                self._present()
        finally:
            self._ui_end()

    def _run_bg(self, fn):
        """Queue ``fn`` for the status soft-pump (no ``_thread``).

        ESP32-P4 ``_thread`` stacks are ~5KiB; network/ECP there overflowed
        ``mp_thread``. Jobs run on the main tick via :meth:`_status_pump`.
        """
        q = self._bg_q
        if len(q) >= 8:
            q.pop(0)
        q.append(fn)
        return True

    def _drain_bg(self):
        """Run at most one queued background job on the main tick."""
        q = self._bg_q
        if not q or self._bg_busy:
            return
        self._bg_busy = True
        job = q.pop(0)
        try:
            job()
        except Exception:
            pass
        self._bg_busy = False

    def _now_ms(self):
        import time as _time

        try:
            if hasattr(_time, "ticks_ms"):
                return _time.ticks_ms()
        except Exception:
            pass
        return int(_time.time() * 1000)

    def _on_mouse_down(self, e):
        btn = self._hit(e.pos)
        if btn is None:
            self._press_btn = None
            self._press_t0 = 0
            return
        # Device rows: track press for long-press delete; activate on UP.
        if btn.id.startswith("dev_"):
            if self._scan_busy:
                return
            self._press_btn = btn
            self._press_t0 = self._now_ms()
            return
        self._press_btn = None
        self._press_t0 = 0
        self._activate(btn)

    def _on_mouse_up(self, e):
        btn = self._press_btn
        self._press_btn = None
        t0 = self._press_t0
        self._press_t0 = 0
        if self._scan_busy:
            return
        if btn is None or not btn.id.startswith("dev_"):
            return
        hit = self._hit(e.pos)
        if hit is not btn:
            return
        dt = self._now_ms() - t0
        try:
            import time as _time

            if hasattr(_time, "ticks_diff") and hasattr(_time, "ticks_ms"):
                dt = _time.ticks_diff(self._now_ms(), t0)
        except Exception:
            pass
        if dt >= 550:
            self._arm_delete(btn.meta)
        else:
            self._pick_device(btn.meta)

    def _arm_delete(self, dev):
        if self._scan_busy:
            return
        host = ((dev or {}).get("host") or "").strip()
        if not host:
            return
        self._delete_armed = host
        name = ascii_label(((dev or {}).get("name") or "").strip() or host)
        max_chars = max(8, (self.width - 4 * self.pad) // (self.FONT_W * self.font_scale))

        def fits(s):
            # Two-line budget: first line + optional "\npress Scan".
            parts = s.split("\n")
            return all(len(p) <= max_chars for p in parts)

        self._refresh_status(
            format_delete_status(name, fits, tail="\npress Scan")
        )

    def _on_key(self, e):
        key = e.key
        mapping = {
            keys.K_UP: "Up",
            keys.K_DOWN: "Down",
            keys.K_LEFT: "Left",
            keys.K_RIGHT: "Right",
            keys.K_RETURN: "Select",
            keys.K_KP_ENTER: "Select",
            keys.K_ESCAPE: "Back",
            keys.K_BACKSPACE: "Backspace",
            keys.K_h: "Home",
            keys.K_i: "Info",
            keys.K_SPACE: "Play",
        }
        ecp = mapping.get(key)
        if ecp:
            self._ecp(ecp)

    def _ecp(self, key):
        """One-shot keypress; plaque/chrome update from a worker."""

        def _press():
            self.engine.press(key)
            try:
                self.engine.refresh_playback()
                self._note_playback_chrome()
            except Exception:
                pass

        self._run_bg(_press)

    def _set_page(self, page):
        self.page = page
        self._build_layout()
        self._draw_all()

    def _refresh_apps(self):
        """Fetch the app list and show the apps page."""
        self.page = "apps"
        self.app_offset = 0
        self._set_status("loading apps...")
        self._build_layout()
        self._draw_all()
        self.engine.query_apps()
        n = len(self.engine.store_apps())
        if n:
            self._set_status("%d apps" % n)
        else:
            self._set_status(self.engine.last_error or "no apps")
        self._build_layout()
        self._draw_all()

    def _on_device_found(self, dev):
        """Progressive discovery callback (runs on the scan worker thread).

        Worker threads must not draw; append to the mailbox and let
        :meth:`_status_pump` add the device on the main tick.
        """
        if self._scan_cancel:
            return
        host = (dev or {}).get("host") or ""
        if not host:
            return
        for existing in self._pending_devices:
            if existing.get("host") == host:
                return
        self._pending_devices.append(dev)

    def _run_scan(self, seed_priority=True, full=False):
        """Compatibility shim: start a background scan (progressive updates)."""
        self._start_scan(seed_priority=seed_priority, full=full)

    def _open_select(self):
        """Show Select page from cache (no network scan); soft-refresh names."""
        self._delete_armed = None
        self.discover_list = list(self.engine.cached_devices() or [])
        self.page = "devices"
        n = len(self.discover_list)
        self._set_state("")
        self._set_status(("%d saved" % n) if n else "no TVs - press Scan")
        self._build_layout()
        self._draw_all()

        def _soft():
            try:
                devices = self.engine.refresh_cached_names()
            except Exception:
                devices = self.engine.cached_devices()
            self._pending_select_list = list(devices or [])
            n2 = len(devices or [])
            self._pending_scan_status = (
                ("%d saved" % n2) if n2 else "no TVs - press Scan"
            )

        self._run_bg(_soft)

    def _start_scan(self, seed_priority=True, full=False):
        """Show the Select page and scan on a worker; merge into cache (no prune)."""
        if self._scan_busy:
            return
        self._delete_armed = None
        if seed_priority and self.discover_list:
            self.engine.discovered = list(self.discover_list)
        self._pending_devices = []
        self._pending_scan_status = None
        self.page = "devices"
        self._set_state("")
        self._scan_busy = True
        self._scan_full = bool(full)
        self._scan_kind = "full" if full else "scan"
        self._scan_cancel = False
        self._set_status("Full scan..." if full else "Scanning...")
        self._build_layout()
        self._draw_all()
        scan_fallback = bool(full)

        def _work():
            cancelled = False
            try:
                devices = self.engine.discover(
                    timeout=3.0,
                    retries=1,
                    ssdp=True,
                    scan_fallback=scan_fallback,
                    on_device=self._on_device_found,
                )
                cancelled = bool(self._scan_cancel)
                if cancelled:
                    return
                for dev in devices or []:
                    self._on_device_found(dev)
                # Merge onto existing list — never clear cached TVs here.
                have = {d.get("host") for d in (self.discover_list or [])}
                for d in self._pending_devices or []:
                    h = d.get("host")
                    if h and h not in have:
                        have.add(h)
                n = len(have) or len(self._pending_devices or []) or len(devices or [])
                if not n:
                    self._pending_scan_status = self.engine.last_error or "no Roku found"
                else:
                    self._pending_scan_status = "found %d - pick one" % n
            except Exception as e:
                if not self._scan_cancel:
                    self._pending_scan_status = str(e)
            finally:
                cancelled = cancelled or bool(self._scan_cancel)
                self._scan_busy = False
                self._scan_kind = None
                self._scan_cancel = False
                if cancelled:
                    self._pending_scan_status = "cancelled"

        self._run_bg(_work)

    def _cancel_scan(self):
        if not self._scan_busy or self._scan_cancel:
            return
        self._scan_cancel = True
        try:
            self.engine.cancel_discover()
        except Exception:
            pass
        self._set_status("Cancelling...")
        self._present()

    def _pick_device(self, dev):
        if self._scan_busy:
            return
        host = (dev or {}).get("host") or ""
        name = ((dev or {}).get("name") or "").strip() or host
        if not host:
            self._refresh_status("no host")
            return
        self._delete_armed = None
        self.engine.set_host(host)
        self.ip_buf = host
        self.app_offset = 0
        # Jump to remote immediately, then finish ECP connect (blocking HTTP).
        self.page = "remote"
        self._set_name(name)
        self._set_state("")
        self._set_status(name)
        self._ui_begin()
        try:
            self._build_layout()
            self._draw_all()
            self.engine.connect(discover_if_empty=False)
            # Rebuild so the power button shows ON/OFF from device-info.
            self._build_layout()
            self._draw_all()
            self._queue_playback_plaque()
            self._refresh_playback_bg()
        finally:
            self._ui_end()

    def _toggle_power(self):
        """Send PowerOn/PowerOff from current state; update the PWR face."""
        key = self.engine.mark_power_optimistic()
        if self.page == "remote":
            self._apply_chrome_face()
            self._present()
        else:
            self._refresh_status(key)

        def _work():
            self.engine.press(key)
            try:
                self.engine.query_device_info()
                self.engine.refresh_playback()
                self._note_playback_chrome()
            except Exception:
                pass

        self._run_bg(_work)

    def _activate(self, btn):
        bid = btn.id
        # Brief pressed face, then restore BEFORE any work. Holding the pressed
        # look across blocking ECP HTTP made ~5s white buttons (socket timeout
        # under the librt soft-tick delivery path).
        skip_flash = bid in ("find", "find_full") or bid.startswith("dev_")
        if not skip_flash:
            self._flash(btn)
            self._unpress(bid)
        self._activate_action(btn)

    def _arm_switch(self, frontend):
        """MORE: arm a front-end change; same button again cancels."""
        if self._switch_armed == frontend:
            self._cancel_switch()
            return
        self._switch_armed = frontend
        max_chars = max(8, (self.width - 4 * self.pad) // (self.FONT_W * self.font_scale))

        def fits(s):
            parts = s.split("\n")
            return all(len(p) <= max_chars for p in parts)

        self._refresh_status(format_switch_status(frontend, fits=fits))

    def _cancel_switch(self):
        """Disarm MORE front-end switch; restore inputs status."""
        self._switch_armed = None
        n = len(self.engine.inputs() or [])
        self._refresh_status(("%d inputs" % n) if n else "no inputs")

    def _confirm_switch(self):
        fe = self._switch_armed
        self._switch_armed = None
        if not fe:
            return False
        try:
            ok = set_frontend(fe)
        except Exception:
            ok = False
        if not ok:
            self._refresh_status("save failed")
            return True
        msg = restart_app()
        if msg:
            self._refresh_status(msg)
        return True

    def _open_more(self):
        """Show MORE; load apps if needed so TV inputs can appear."""
        self._switch_armed = None
        self.page = "more"
        if not self.engine.apps:
            self._set_status("loading inputs...")
            self._build_layout()
            self._draw_all()
            self.engine.query_apps()
        n = len(self.engine.inputs() or [])
        self._set_status(("%d inputs" % n) if n else "no inputs")
        self._build_layout()
        self._draw_all()

    def _activate_action(self, btn):
        bid = btn.id

        if bid == "power":
            self._toggle_power()
            return

        if bid == "apps_pg":
            self.page = "apps"
            self.app_offset = 0
            if not self.engine.apps:
                self._refresh_apps()
            else:
                self._set_status("%d apps" % len(self.engine.store_apps()))
                self._build_layout()
                self._draw_all()
            return
        if bid == "more_pg":
            self._open_more()
            return
        if bid.startswith("fe_") and btn.meta:
            self._arm_switch(btn.meta)
            return
        if bid == "back_pg":
            if self._scan_busy:
                return
            if self._switch_armed:
                self._confirm_switch()
                return
            host = (self.engine.host or "").strip()
            if not host:
                self._refresh_status("pick a TV first")
                return
            self._set_page("remote")
            if self.engine.connected:
                self._refresh_playback_bg()
            return

        if bid.startswith("dev_") and btn.meta:
            # Handled on MOUSEBUTTONUP (tap vs long-press).
            return

        if bid == "find":
            if self.page == "devices":
                if self._scan_busy:
                    if self._scan_kind == "scan":
                        self._cancel_scan()
                    return
                host = getattr(self, "_delete_armed", None)
                if host:
                    self._delete_armed = None
                    try:
                        self.engine.forget_device(host)
                    except Exception:
                        pass
                    self.discover_list = [
                        d
                        for d in (self.discover_list or [])
                        if (d.get("host") or "") != host
                    ]
                    self._refresh_status("deleted")
                    self._build_layout()
                    self._draw_all()
                    return
                self._run_scan(seed_priority=True, full=False)
            else:
                self._open_select()
            return

        if bid == "find_full":
            if self._scan_busy:
                if self._scan_kind == "full":
                    self._cancel_scan()
                return
            self._run_scan(seed_priority=True, full=unicast_scan_supported())
            return

        if bid == "apps_refresh":
            self._refresh_apps()
            return

        if bid == "apps_next":
            n = len(self.engine.store_apps())
            step = max(1, int(self.app_page_size or 1))
            if n:
                self.app_offset = (self.app_offset + step) % n
            self._build_layout()
            self._draw_all()
            return

        if bid.startswith("app_") and btn.meta:
            if self._switch_armed:
                self._cancel_switch()
            app = btn.meta
            app_id = app.get("id", "")
            self.selected_app_id = str(app_id or "")
            if self.page == "apps":
                self._build_layout()
                self._draw_all()

            def _launch():
                self.engine.launch(app_id)
                try:
                    self.engine.refresh_playback()
                    self._note_playback_chrome()
                except Exception:
                    pass

            self._run_bg(_launch)
            return

        if bid.startswith("in_") and btn.meta:
            if self._switch_armed:
                self._cancel_switch()
            app = btn.meta
            app_id = app.get("id", "")

            def _launch_in():
                self.engine.launch(app_id)
                try:
                    self.engine.refresh_playback()
                    self._note_playback_chrome()
                except Exception:
                    pass

            self._run_bg(_launch_in)
            return

        if bid == "no_inputs":
            return

        if btn.ecp:
            self._ecp(btn.ecp)
            return


def create(engine=None, start_page="devices"):
    """Build the FrameBuffer front end (does not call ``App.run``)."""
    return _Remote(engine=engine, start_page=start_page)


def run(engine=None, start_page="devices"):
    """Create the UI and let the app run itself."""
    create(engine=engine, start_page=start_page)


# Direct import / example kit: auto-start. ``roku_remote`` owns launch when set.
import roku_engine as _roku_engine  # noqa: E402

if not getattr(_roku_engine, "_LAUNCHER_OWNS_RUN", False):
    run()