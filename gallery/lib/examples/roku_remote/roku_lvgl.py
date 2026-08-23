# deps: lvgl
# modules: roku_engine
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
roku_lvgl
====================================================
Museum-quality Roku remote built with LVGL.

The flagship of three interchangeable Roku front ends (``roku_graphics``,
``roku_widgets``, ``roku_lvgl``); ``roku_remote`` launches this one. All three
drive the same :class:`roku_engine.RokuEngine`, so the display layer is fully
replaceable.

Design: a deep charcoal chassis with a single violet accent, a brushed status
"plaque", a circular D-pad cluster, a refined transport bar, and slim side
volume / channel columns on wider panels. Geometry derives from
``display_drv.width`` / ``height`` so it scales from 320x480 phones up through
desktop windows.

Import order matters: ``display_driver`` must be imported after ``board_config``
so LVGL's display / input devices are wired before widgets are created. Blocking
ECP/scan work is queued and drained from an ``lv.timer`` pump (no ``_thread`` —
ESP32 thread stacks are too small for network). The pump only touches LVGL on
the main thread; queued jobs touch the engine and set mailbox flags.

Launch via ``roku_remote`` (prefs + MRU). Direct ``roku_lvgl.run()`` also works.
Requires Roku **Control by mobile apps -> Enabled**. Join WiFi before running
on a microcontroller.
"""

import sys
import time

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

import board_config  # noqa: E402 — before display_driver so LVGL wiring sees it
import display_driver  # noqa: E402 — wires LVGL display/input into the app
import lvgl as lv  # noqa: E402
from board_config import display_drv  # noqa: E402
from display_driver import app  # noqa: E402
from roku_engine import (  # noqa: E402
    FRONTEND_BUTTONS,
    app_label,
    ascii_label,
    format_delete_status,
    format_switch_status,
    get_ui_pref,
    other_frontends,
    restart_app,
    set_frontend,
    set_ui_pref,
    unicast_scan_supported,
)
from roku_sim import make_engine  # noqa: E402
from multimer import ticks_diff, ticks_ms  # noqa: E402

FRONTEND = "lvgl"


# Museum charcoal chassis + single violet accent.
_COL = {
    "bg_top": 0x0E1014,
    "bg_bot": 0x161A22,
    "plaque": 0x1A1F2A,
    "plaque_edge": 0x2A3140,
    "key": 0x323A4A,
    "key_alt": 0x272E3B,
    "accent": 0x7C5CFC,
    "accent2": 0x5A3ED0,
    "power": 0xE0574A,
    "power2": 0xB23A30,
    "transport": 0x3A5A72,
    "transport2": 0x274152,
    "ui": 0x232A36,
    "text": 0xF2F4F8,
    "muted": 0x9AA0B0,
    "on_accent": 0xFFFFFF,
    "dpad_ring": 0x1E2530,
}


def _hex(rgb):
    return lv.color_hex(rgb)


def _shade(rgb, factor):
    r = (rgb >> 16) & 0xFF
    g = (rgb >> 8) & 0xFF
    b = rgb & 0xFF
    r = max(0, min(255, int(r * factor)))
    g = max(0, min(255, int(g * factor)))
    b = max(0, min(255, int(b * factor)))
    return (r << 16) | (g << 8) | b


def _sym(name, fallback):
    sym = getattr(lv, "SYMBOL", None)
    if sym is not None:
        val = getattr(sym, name, None)
        if val:
            return val
    return fallback


def _pick_font(unit, ref_obj=None):
    # Largest request is 24 (common LVGL montserrat build); fall through if missing.
    if unit >= 560:
        candidates = (24, 22, 20, 18, 16, 14, 12)
    elif unit >= 400:
        candidates = (24, 22, 20, 18, 16, 14, 12)
    else:
        candidates = (20, 18, 16, 14, 12)
    return _pick_font_from(candidates, ref_obj)


def _pick_font_from(candidates, ref_obj=None, allow_theme=True):
    for size in candidates:
        font = getattr(lv, "font_montserrat_" + str(size), None)
        if font is not None:
            return font
    if not allow_theme:
        return None
    if ref_obj is not None:
        for getter in ("theme_get_font_large", "theme_get_font_normal", "theme_get_font_small"):
            fn = getattr(lv, getter, None)
            if fn is None:
                continue
            try:
                font = fn(ref_obj)
                if font is not None:
                    return font
            except Exception:
                pass
    fn = getattr(lv, "font_get_default", None)
    if fn is not None:
        try:
            return fn()
        except Exception:
            pass
    return None


def _pick_font_at_most(max_size, ref_obj=None):
    """Largest built-in montserrat face with pixel size ``<= max_size``.

    Does not fall back to the theme font (often "large") — that defeated the
    small-panel ``font_sm`` cap when montserrat_12 was not compiled in.
    """
    sizes = tuple(s for s in (24, 22, 20, 18, 16, 14, 12) if s <= int(max_size))
    if not sizes:
        sizes = (12,)
    return _pick_font_from(sizes, ref_obj, allow_theme=False)


def _apply_font(obj, font):
    if font is not None:
        obj.set_style_text_font(font, 0)


def _no_scroll(obj):
    if hasattr(obj, "remove_flag"):
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
    elif hasattr(obj, "clear_flag"):
        obj.clear_flag(lv.obj.FLAG.SCROLLABLE)


class _RokuLvgl:
    def __init__(self, engine=None, start_page="devices"):
        self.engine = engine if engine is not None else make_engine()
        self.ip_buf = self.engine.host or ""
        self.page = start_page if start_page in ("devices", "remote", "apps", "more") else "devices"
        self.app_offset = 0
        self.app_page_size = 1
        self.selected_app_id = ""
        self.discover_list = []
        # When discover runs inline (no worker thread), paint each new TV immediately.
        self._scan_progressive_inline = False
        # Long-press delete arm: host waiting for Scan confirm on the Select page.
        self._delete_armed = None
        # MORE: arm a front-end switch; confirm with REMOTE (then restart app).
        self._switch_armed = None

        # Persistent (screen / plaque) styles vs per-page styles.
        self._styles = []
        self._page_styles = []

        # Cross-thread mailboxes: worker writes, lv.timer applies on main thread.
        self._pending_status = None
        self._pending_state = None
        self._pending_devices = []
        self._pending_select_list = None
        self._pending_rebuild = False
        # Last play/power faces; pump applies label text without full rebuild.
        self._chrome_face = ""
        self._pending_chrome = None
        self._play_lbl = None
        self._power_lbl = None
        self._playback_busy = False
        self._status_ticks = 0
        self._scan_busy = False
        self._scan_full = False
        self._scan_kind = None
        self._scan_cancel = False
        self._last_scan_busy = False
        # Explicit Scan only (see _start_scan); Select opens the cached list.
        self._pending_scan = False
        self._scan_yield = False
        self._scan_worker_active = False
        # ECP keys currently held (keydown without keyup); avoids double keyup.
        self._held_keys = {}
        # Cooperative bg queue (drained by ``_pump`` — no ``_thread``).
        self._bg_q = []
        self._bg_busy = False

        # Prefs-backed chrome / load (defaults favor MCU + SW-rotate panels).
        self.ui_shadows = bool(get_ui_pref("ui_shadows", False))
        self.ui_gradients = bool(get_ui_pref("ui_gradients", False))
        self.show_progress = bool(get_ui_pref("show_progress", False))
        # Software rotation: every dirty button costs ~0.5–2s to blit.
        self._sw_rotate = False
        try:
            self._sw_rotate = bool(
                getattr(display_driver._driver_ref, "_sw_rotate", False)
            )
        except Exception:
            self._sw_rotate = False
        try:
            self.playback_poll_s = int(get_ui_pref("playback_poll_s", 5) or 5)
        except (TypeError, ValueError):
            self.playback_poll_s = 5
        if self.playback_poll_s < 1:
            self.playback_poll_s = 1

        self.W = display_drv.width
        self.H = display_drv.height
        self.unit = min(self.W, self.H)
        self.pad = max(4, self.unit // 64)
        self.radius = max(6, self.unit // 26)
        # Short panels (T-HMI 240x320): keep plaque compact so remote chrome fits.
        self.plaque_h = max(40 if self.H <= 360 else 64, self.H // 10)
        self.font = None
        self.font_sm = None
        self.plaque = None
        self.name_lbl = None
        self.state_lbl = None
        self.status_lbl = None
        self.time_lbl = None
        self.progress_track = None
        self.progress_fill = None
        self.progress_w = 0
        self.progress_h = 2
        # Last plaque strings — skip LVGL set_text when unchanged (SW-rotate cost).
        self._last_status_text = None
        self._last_state_text = None
        self._last_time_text = None
        self._last_name_text = None
        self.content = None
        self._ecp_q = []
        self._remote_key_btns = {}
        # Lazy page roots under ``content`` (hide/show instead of destroy/rebuild).
        self._page_roots = {}
        self._page_bags = {}
        self._page_dirty = {}
        self._page_build_parent = None

        self.build_ui()

    # ----- styles ---------------------------------------------------------

    def _mk_style(self, page_scoped=True):
        style = lv.style_t()
        style.init()
        (self._page_styles if page_scoped else self._styles).append(style)
        return style

    def _panel_style(self, top, bottom, radius, edge=None, page_scoped=True):
        style = self._mk_style(page_scoped)
        style.set_bg_color(_hex(top))
        style.set_bg_opa(lv.OPA.COVER)
        if (
            self.ui_gradients
            and hasattr(style, "set_bg_grad_color")
            and bottom is not None
            and bottom != top
        ):
            style.set_bg_grad_color(_hex(bottom))
            if hasattr(style, "set_bg_grad_dir"):
                style.set_bg_grad_dir(lv.GRAD_DIR.VER)
        style.set_radius(radius)
        if edge is not None:
            style.set_border_color(_hex(edge))
            style.set_border_width(1)
            style.set_border_opa(lv.OPA.COVER)
        else:
            style.set_border_width(0)
        return style

    # ----- build ----------------------------------------------------------

    def build_ui(self):
        inst = display_driver.event_loop.current_instance()
        if inst is not None:
            inst.disable()
        try:
            scr = lv.screen_active()
            # Short panels (T-HMI 240x320): montserrat 16 reads heavier than the
            # 16px romfont used by graphics/widgets — cap at 14. Two-line status
            # prefers 12 when built in, else the same 14 face.
            if self.H <= 360 or self.unit < 280:
                self.font = (
                    _pick_font_at_most(14, scr)
                    or _pick_font(self.unit, scr)
                )
                self.font_sm = (
                    _pick_font_at_most(12, scr)
                    or self.font
                )
            else:
                self.font = _pick_font(self.unit, scr)
                self.font_sm = _pick_font_at_most(14, scr) or self.font

            bg = self._panel_style(
                _COL["bg_top"], _COL["bg_bot"], 0, page_scoped=False
            )
            scr.add_style(bg, 0)
            _no_scroll(scr)

            # Status plaque (persists across page swaps; only its text updates).
            # Zero theme pad — default LVGL padding plus label offsets looked too
            # wide on short panels; inset labels with a small plaque gutter only.
            plaque = lv.obj(scr)
            plaque.set_size(self.W - 2 * self.pad, self.plaque_h)
            plaque.align(lv.ALIGN.TOP_MID, 0, self.pad)
            plaque_style = self._panel_style(
                _shade(_COL["plaque"], 1.15),
                _COL["plaque"],
                self.radius,
                edge=_COL["plaque_edge"],
                page_scoped=False,
            )
            if hasattr(plaque_style, "set_pad_all"):
                plaque_style.set_pad_all(0)
            plaque.add_style(plaque_style, 0)
            _no_scroll(plaque)
            self.plaque = plaque

            half_h = max(1, self.plaque_h // 2)
            plaque_w = self.W - 2 * self.pad
            # Tight left/right gutter inside the plaque (not the chassis pad).
            inset = max(2, self.pad // 2)
            self._plaque_inset = inset
            # Top-left: device name. Top-right: media-player state (raw).
            # Bottom-left: app or user feedback. Bottom-right: position[/duration].
            self.name_lbl = lv.label(plaque)
            self.name_lbl.set_text("Roku Remote")
            self.name_lbl.set_style_text_color(_hex(_COL["text"]), 0)
            _apply_font(self.name_lbl, self.font)
            self.name_lbl.align(lv.ALIGN.LEFT_MID, inset, -half_h // 2)

            self.state_lbl = lv.label(plaque)
            self.state_lbl.set_text("")
            self.state_lbl.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(self.state_lbl, self.font)
            ta = getattr(lv, "TEXT_ALIGN", None)
            right = getattr(ta, "RIGHT", None) if ta is not None else None
            if right is not None and hasattr(self.state_lbl, "set_style_text_align"):
                try:
                    self.state_lbl.set_style_text_align(right, 0)
                except Exception:
                    pass
            self.state_lbl.align(lv.ALIGN.RIGHT_MID, -inset, -half_h // 2)

            self.status_lbl = lv.label(plaque)
            self.status_lbl.set_text("")
            self.status_lbl.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(self.status_lbl, self.font)
            self._status_time_reserve = max(72, self.unit // 3)
            self._status_inner_pad = inset
            self._layout_status_width(reserve_time=(self.page != "devices"))
            self.status_lbl.align(lv.ALIGN.LEFT_MID, inset, half_h // 2)
            if hasattr(self.status_lbl, "set_long_mode"):
                lm = getattr(lv.label, "LONG_MODE", None)
                mode = None
                # Prefer WRAP so two-line prompts (e.g. delete confirm) are visible.
                for name in ("WRAP", "DOT", "CLIP"):
                    mode = getattr(lm, name, None) if lm is not None else None
                    if mode is not None:
                        break
                if mode is not None:
                    self.status_lbl.set_long_mode(mode)

            self.time_lbl = lv.label(plaque)
            self.time_lbl.set_text("")
            self.time_lbl.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(self.time_lbl, self.font)
            if right is not None and hasattr(self.time_lbl, "set_style_text_align"):
                try:
                    self.time_lbl.set_style_text_align(right, 0)
                except Exception:
                    pass
            self.time_lbl.align(lv.ALIGN.RIGHT_MID, -inset, half_h // 2)

            # Hairline scrub rail under the plaque (hidden until duration known).
            self.progress_w = plaque_w
            track = lv.obj(scr)
            track.set_size(plaque_w, self.progress_h)
            track_style = self._panel_style(
                _COL["plaque_edge"], _COL["plaque_edge"], 0, page_scoped=False
            )
            track_style.set_pad_all(0)
            if hasattr(track_style, "set_border_width"):
                track_style.set_border_width(0)
            track.add_style(track_style, 0)
            _no_scroll(track)
            gap_y = max(1, (self.pad - self.progress_h) // 2)
            track.align_to(plaque, lv.ALIGN.OUT_BOTTOM_MID, 0, gap_y)
            self.progress_track = track

            fill = lv.obj(track)
            fill.set_size(0, self.progress_h)
            fill.set_pos(0, 0)
            fill_style = self._panel_style(
                _COL["transport"], _COL["transport"], 0, page_scoped=False
            )
            fill_style.set_pad_all(0)
            if hasattr(fill_style, "set_border_width"):
                fill_style.set_border_width(0)
            fill.add_style(fill_style, 0)
            _no_scroll(fill)
            self.progress_fill = fill
            self._set_progress_visible(False)

            # Content region below the plaque; cleaned + rebuilt per page.
            self.content = lv.obj(scr)
            self.content.set_size(self.W, self.H - self.plaque_h - 2 * self.pad)
            self.content.set_pos(0, self.plaque_h + 2 * self.pad)
            transparent = self._mk_style(page_scoped=False)
            transparent.set_bg_opa(lv.OPA.TRANSP)
            transparent.set_border_width(0)
            transparent.set_pad_all(0)
            self.content.add_style(transparent, 0)
            _no_scroll(self.content)

            # One page build only — never _show_page then _open_select (that was
            # a double Select paint: ~5s + ~15s under SW-rotate).
            if self.page == "remote" and (self.engine.host or "").strip():
                self._show_page("remote")
            else:
                self.page = "devices"
                # Populate list before first paint (open_select would rebuild).
                self.discover_list = self._merge_device_lists(
                    self.engine.cached_devices(), self.discover_list
                )
                self._show_page("devices")
        finally:
            if inst is not None:
                inst.enable()

        self._install_pump()
        if self.page == "remote" and (self.engine.host or "").strip():
            name = ""
            try:
                info = self.engine.device_info or {}
                name = info.get("user-device-name") or info.get("model-name") or ""
            except Exception:
                pass
            self._set_name(name or self.engine.host or "Roku")
            self._set_state("")
            self._refresh_playback_bg()
        else:
            err = (getattr(self.engine, "last_error", None) or "").strip()
            n = len(self.discover_list or [])
            if err in ("last TV offline", "TV changed"):
                self._set_status(err)
            elif n:
                self._set_status("%d saved" % n)
            else:
                self._set_status("no TVs - press Scan")
            self._set_state("")

    def _install_pump(self):
        self._timer = None
        creator = getattr(lv, "timer_create", None)
        if creator is not None:
            try:
                self._timer = creator(self._pump, 250, None)
            except Exception:
                self._timer = None

    # ----- button factory -------------------------------------------------

    def _role_colors(self, role):
        if role == "accent":
            return _COL["accent"], _COL["accent2"], _COL["on_accent"]
        if role == "power":
            return _COL["power"], _COL["power2"], _COL["text"]
        if role == "transport":
            return _COL["transport"], _COL["transport2"], _COL["text"]
        if role == "alt":
            return _COL["key_alt"], _shade(_COL["key_alt"], 0.7), _COL["text"]
        if role == "ui":
            return _COL["ui"], _shade(_COL["ui"], 0.7), _COL["muted"]
        return _COL["key"], _shade(_COL["key"], 0.7), _COL["text"]

    def _key_button(
        self,
        parent,
        text,
        x,
        y,
        w,
        h,
        role,
        on_click=None,
        round_btn=False,
        font=None,
        hold_key=None,
        wrap=False,
        on_long=None,
    ):
        top, bottom, fg = self._role_colors(role)
        btn = lv.button(parent)
        btn.set_size(int(w), int(h))
        btn.set_pos(int(x), int(y))
        # Touch remote: no keyboard focus ring (theme focus looked like a stuck
        # accent on the first apps tile).
        try:
            flag = getattr(lv.obj.FLAG, "CLICK_FOCUSABLE", None)
            if flag is not None and hasattr(btn, "remove_flag"):
                btn.remove_flag(flag)
            elif flag is not None and hasattr(btn, "clear_flag"):
                btn.clear_flag(flag)
        except Exception:
            pass
        rad = (min(int(w), int(h)) // 2) if round_btn else self.radius

        style = self._panel_style(top, bottom, rad, edge=_shade(top, 0.55))
        # Round D-pad faces must be geometrically centered — zero theme pad /
        # margin and drop shadow Y offset (it reads as "shifted down").
        if round_btn:
            style.set_pad_all(0)
            if hasattr(style, "set_margin_all"):
                style.set_margin_all(0)
            if hasattr(style, "set_shadow_width"):
                style.set_shadow_width(0)
            if hasattr(style, "set_shadow_ofs_x"):
                style.set_shadow_ofs_x(0)
            if hasattr(style, "set_shadow_ofs_y"):
                style.set_shadow_ofs_y(0)
        elif self.ui_shadows and hasattr(style, "set_shadow_width"):
            style.set_shadow_width(max(4, self.pad))
            style.set_shadow_color(_hex(0x000000))
            if hasattr(style, "set_shadow_opa"):
                style.set_shadow_opa(lv.OPA._40)
            if hasattr(style, "set_shadow_ofs_y"):
                style.set_shadow_ofs_y(max(2, self.pad // 2))
        btn.add_style(style, 0)

        # Native PRESSED style — LVGL owns the face while the finger is down.
        pressed = self._mk_style()
        pressed.set_bg_color(_hex(_shade(top, 1.25)))
        pressed.set_bg_opa(lv.OPA.COVER)
        if round_btn:
            pressed.set_pad_all(0)
            if hasattr(pressed, "set_translate_x"):
                pressed.set_translate_x(0)
            if hasattr(pressed, "set_translate_y"):
                pressed.set_translate_y(0)
        elif hasattr(pressed, "set_translate_y"):
            pressed.set_translate_y(max(1, self.pad // 3))
        btn.add_style(pressed, lv.STATE.PRESSED)

        lbl = lv.label(btn)
        lbl.set_text(text)
        lbl.set_style_text_color(_hex(fg), 0)
        _apply_font(lbl, font or self.font)
        if wrap:
            try:
                lbl.set_width(max(8, int(w) - max(4, self.pad)))
            except Exception:
                pass
            lm = getattr(lv.label, "LONG_MODE", None)
            wrap_mode = getattr(lm, "WRAP", None) if lm is not None else None
            if wrap_mode is not None and hasattr(lbl, "set_long_mode"):
                try:
                    lbl.set_long_mode(wrap_mode)
                except Exception:
                    pass
            ta = getattr(lv, "TEXT_ALIGN", None)
            center = getattr(ta, "CENTER", None) if ta is not None else None
            if center is not None and hasattr(lbl, "set_style_text_align"):
                try:
                    lbl.set_style_text_align(center, 0)
                except Exception:
                    pass
        lbl.center()
        # Stash for chrome updates (play/power) without a page rebuild.
        self._last_btn_label = lbl

        if hold_key:
            # Send on release; PRESSED style is visual only while the finger is down.
            def _send_key(_e, _k=hold_key):
                self._ecp_press_now(_k)

            btn.add_event_cb(_send_key, lv.EVENT.RELEASED, None)
            if isinstance(hold_key, str):
                btns = getattr(self, "_remote_key_btns", None)
                if btns is None:
                    self._remote_key_btns = {}
                    btns = self._remote_key_btns
                btns[hold_key] = btn
        elif on_click is not None:
            # Long-press delete disabled: inject/hold and slow indev drain were
            # firing LONG_PRESSED and suppressing SHORT_CLICKED (pick stayed on
            # devices). Use plain CLICKED only. (on_long ignored when passed.)
            def _cb(_e, _fn=on_click):
                _fn()

            btn.add_event_cb(_cb, lv.EVENT.CLICKED, None)
        return btn

    # ----- pages ----------------------------------------------------------

    def _page_parent(self):
        """Active page root (or content pane while building chrome-less UI)."""
        return self._page_build_parent or self.content

    def _hidden_flag(self):
        obj_flag = getattr(getattr(lv, "obj", None), "FLAG", None)
        if obj_flag is not None and hasattr(obj_flag, "HIDDEN"):
            return obj_flag.HIDDEN
        return getattr(getattr(lv, "OBJ_FLAG", None), "HIDDEN", None)

    def _set_hidden(self, obj, hidden):
        if obj is None:
            return
        flag = self._hidden_flag()
        try:
            if flag is not None:
                if hidden:
                    obj.add_flag(flag)
                else:
                    obj.clear_flag(flag)
            elif hasattr(obj, "add_flag") and hasattr(lv, "obj"):
                # Last resort: move off-screen.
                if hidden:
                    obj.set_pos(-4096, -4096)
                else:
                    obj.set_pos(0, 0)
        except Exception:
            pass

    def _invalidate_page(self, page):
        """Mark a cached page root stale (next show rebuilds)."""
        self._page_dirty[page] = True

    def _delete_page_root(self, page):
        root = self._page_roots.pop(page, None)
        self._page_bags.pop(page, None)
        self._page_dirty.pop(page, None)
        if root is None:
            return
        try:
            if hasattr(root, "delete"):
                root.delete()
            elif hasattr(root, "del_async"):
                root.del_async()
        except Exception:
            pass

    def _clear_content(self):
        """Delete all cached page roots (full content reset)."""
        for page in list(self._page_roots.keys()):
            self._delete_page_root(page)
        self._page_build_parent = None
        c = self.content
        if c is None:
            return
        try:
            c.clean()
        except Exception:
            pass
        for _ in range(128):
            try:
                n = c.get_child_count() if hasattr(c, "get_child_count") else (
                    c.get_child_cnt() if hasattr(c, "get_child_cnt") else 0
                )
            except Exception:
                break
            if not n:
                break
            try:
                child = c.get_child(0)
            except Exception:
                break
            try:
                if hasattr(child, "delete"):
                    child.delete()
                elif hasattr(child, "del_async"):
                    child.del_async()
                else:
                    break
            except Exception:
                break

    def _restore_page_bag(self, page):
        bag = self._page_bags.get(page) or {}
        self._play_lbl = bag.get("play_lbl")
        self._power_lbl = bag.get("power_lbl")
        self._page_styles = bag.get("styles") or []
        if page == "remote":
            self._remote_key_btns = bag.get("key_btns") or {}

    def _store_page_bag(self, page):
        bag = {
            "play_lbl": self._play_lbl,
            "power_lbl": self._power_lbl,
            "styles": self._page_styles,
        }
        if page == "remote":
            bag["key_btns"] = getattr(self, "_remote_key_btns", None) or {}
        self._page_bags[page] = bag

    def _show_page(self, page, force=False):
        self.page = page
        if self.content is None:
            return
        # Page swap may change plaque layout; allow status width to refresh.
        self._last_status_text = None

        # Hide every cached root; show or rebuild the requested one.
        for name, root in self._page_roots.items():
            self._set_hidden(root, name != page)

        dirty = bool(self._page_dirty.get(page))
        root = self._page_roots.get(page)
        if root is not None and not force and not dirty:
            self._set_hidden(root, False)
            self._page_build_parent = root
            self._restore_page_bag(page)
            return

        if root is not None:
            self._delete_page_root(page)

        root = lv.obj(self.content)
        # content.get_* can report 0 before the first layout pass — a 0×0 root
        # clips every child (blank pane under a live plaque).
        cw = ch = 0
        try:
            cw = int(self.content.get_width())
            ch = int(self.content.get_height())
        except Exception:
            pass
        if cw < 80:
            cw = int(self.W)
        if ch < 80:
            ch = max(80, int(self.H - self.plaque_h - 2 * self.pad))
        root.set_size(cw, ch)
        root.set_pos(0, 0)
        transparent = self._mk_style(page_scoped=False)
        transparent.set_bg_opa(lv.OPA.TRANSP)
        transparent.set_border_width(0)
        transparent.set_pad_all(0)
        root.add_style(transparent, 0)
        _no_scroll(root)
        # Ensure not clipped/hidden; some ports start children with odd flags.
        try:
            flag = self._hidden_flag()
            if flag is not None and hasattr(root, "clear_flag"):
                root.clear_flag(flag)
        except Exception:
            pass
        self._page_roots[page] = root
        self._page_build_parent = root
        self._page_dirty.pop(page, None)
        self._set_hidden(root, False)
        for name, other in self._page_roots.items():
            if name != page:
                self._set_hidden(other, True)

        self._play_lbl = None
        self._power_lbl = None
        self._page_styles = []
        if page == "devices":
            self._build_devices()
            # Ignore SCAN/FULL briefly after rebuild — recreating those buttons
            # under a held or ghost touch re-fires discover in a tight loop.
            # Keep Cancel responsive while a scan is already running.
            if not self._scan_busy:
                try:
                    self._scan_ignore_until = ticks_ms() + 700
                except Exception:
                    self._scan_ignore_until = 0
            else:
                self._scan_ignore_until = 0
        elif page == "apps":
            self._build_apps()
        elif page == "more":
            self._build_more()
        else:
            self._build_remote()
        self._store_page_bag(page)

    def _content_metrics(self):
        W = self.W
        fallback = max(80, self.H - self.plaque_h - 2 * self.pad)
        H = fallback
        if self.content is not None and hasattr(self.content, "get_height"):
            try:
                reported = int(self.content.get_height())
                # Ignore 0 / nonsense before LVGL has laid out the content pane.
                if reported >= 80:
                    H = reported
            except Exception:
                pass
        return W, H

    def _row(self, w, row_h, row_bg, parent=None):
        """Transparent band; buttons align within it."""
        r = lv.obj(parent if parent is not None else self._page_parent())
        r.set_size(w, row_h)
        r.add_style(row_bg, 0)
        _no_scroll(r)
        return r

    def _place3(self, row, w, row_h, gap, specs, font=None):
        """Place up to three equal buttons: left / center / right of the band.

        Each spec is ``(text, role, action)`` where *action* is a callable
        (click) or an ECP key name string (press/hold via keydown/keyup).
        Returns the created buttons (same order as *specs*).
        """
        bw = (w - 2 * gap) // 3
        out = []
        labels = []
        for (text, role, action), al in zip(
            specs, (lv.ALIGN.LEFT_MID, lv.ALIGN.CENTER, lv.ALIGN.RIGHT_MID)
        ):
            if isinstance(action, str):
                btn = self._key_button(
                    row, text, 0, 0, bw, row_h, role, hold_key=action, font=font
                )
            else:
                btn = self._key_button(
                    row, text, 0, 0, bw, row_h, role, action, font=font
                )
            btn.align(al, 0, 0)
            out.append(btn)
            labels.append(self._last_btn_label)
        return out, labels

    def _build_remote(self):
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        # Prefer the computed content height; some ports report 0 from
        # get_height() before the first layout pass.
        if H < 80:
            H = max(80, self.H - self.plaque_h - 2 * self.pad)
        self._remote_key_btns = {}
        # Landscape: two columns (nav+D-pad | transport/chrome). Prefer this
        # on wide panels instead of a tall portrait stack.
        if W > H:
            self._build_remote_landscape(W, H, pad, gap)
        else:
            self._build_remote_portrait(W, H, pad, gap)

    def _remote_row_bg(self):
        row_bg = self._mk_style()
        row_bg.set_bg_opa(lv.OPA.TRANSP)
        row_bg.set_border_width(0)
        row_bg.set_pad_all(0)
        return row_bg

    def _add_dpad(self, parent, ring, font):
        """Circular D-pad (Up/Down/Left/Right/OK) sized ``ring``×``ring``."""
        ringobj = lv.obj(parent)
        ringobj.set_size(ring, ring)
        ring_style = self._panel_style(
            _COL["dpad_ring"], _shade(_COL["dpad_ring"], 0.7),
            ring // 2, edge=_COL["plaque_edge"],
        )
        ring_style.set_pad_all(0)
        if hasattr(ring_style, "set_margin_all"):
            ring_style.set_margin_all(0)
        ringobj.add_style(ring_style, 0)
        _no_scroll(ringobj)
        cell = max(1, ring // 3)
        margin = max(2, min(self.pad, cell // 6))
        arrow = max(1, cell - 2 * margin)
        up = self._key_button(
            ringobj, _sym("UP", "^"), 0, 0, arrow, arrow, "key",
            hold_key="Up", round_btn=True, font=font,
        )
        up.align(lv.ALIGN.CENTER, 0, -cell)
        down = self._key_button(
            ringobj, _sym("DOWN", "v"), 0, 0, arrow, arrow, "key",
            hold_key="Down", round_btn=True, font=font,
        )
        down.align(lv.ALIGN.CENTER, 0, cell)
        left = self._key_button(
            ringobj, _sym("LEFT", "<"), 0, 0, arrow, arrow, "key",
            hold_key="Left", round_btn=True, font=font,
        )
        left.align(lv.ALIGN.CENTER, -cell, 0)
        right = self._key_button(
            ringobj, _sym("RIGHT", ">"), 0, 0, arrow, arrow, "key",
            hold_key="Right", round_btn=True, font=font,
        )
        right.align(lv.ALIGN.CENTER, cell, 0)
        ok = self._key_button(
            ringobj, "OK", 0, 0, cell, cell, "accent",
            hold_key="Select", round_btn=True, font=font,
        )
        ok.align(lv.ALIGN.CENTER, 0, 0)
        # Ring chrome must not steal presses from the arrow/OK buttons.
        try:
            flag = getattr(getattr(lv, "obj", lv).FLAG, "CLICKABLE", None)
            if flag is not None:
                if hasattr(ringobj, "remove_flag"):
                    ringobj.remove_flag(flag)
                elif hasattr(ringobj, "clear_flag"):
                    ringobj.clear_flag(flag)
        except Exception:
            pass
        return ringobj

    def _build_remote_portrait(self, W, H, pad, gap):
        """Stacked remote for tall/narrow panels."""
        w = W - 2 * pad
        row_bg = self._remote_row_bg()
        n_rows = 5
        n_gaps = n_rows
        gaps = n_gaps * gap
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

        font = self.font
        util = self._row(w, row_h, row_bg)
        util.align(lv.ALIGN.TOP_MID, 0, 0)
        _util_btns, util_lbls = self._place3(util, w, row_h, gap, [
            (_sym("LEFT", "BACK"), "key", "Back"),
            (_sym("HOME", "HOME"), "accent", "Home"),
            (_sym("POWER", "PWR") + " " + self.engine.power_label(), "power", self._toggle_power),
        ], font=font)
        self._power_lbl = util_lbls[2] if len(util_lbls) > 2 else None

        ringobj = self._add_dpad(self._page_parent(), ring, font)
        ringobj.align_to(util, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)

        opts = self._row(w, row_h, row_bg)
        opts.align_to(ringobj, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        self._place3(opts, w, row_h, gap, [
            (_sym("REFRESH", "RPL"), "alt", "InstantReplay"),
            (_sym("LIST", "*"), "alt", "Info"),
            (_sym("EYE_OPEN", "CC"), "alt", "ClosedCaption"),
        ], font=font)

        play_face = self.engine.play_label()
        play = self._play_face_text(play_face)
        self._chrome_face = "%s|%s" % (play_face, self.engine.power_label())
        trans = self._row(w, row_h, row_bg)
        trans.align_to(opts, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        _trans_btns, trans_lbls = self._place3(trans, w, row_h, gap, [
            (_sym("PREV", "<<"), "transport", "Rev"),
            (play, "transport", "Play"),
            (_sym("NEXT", ">>"), "transport", "Fwd"),
        ], font=font)
        self._play_lbl = trans_lbls[1] if len(trans_lbls) > 1 else None

        vol = self._row(w, row_h, row_bg)
        vol.align_to(trans, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        self._place3(vol, w, row_h, gap, [
            (_sym("VOLUME_MID", "VOL-"), "key", "VolumeDown"),
            (_sym("MUTE", "MUTE"), "alt", "VolumeMute"),
            (_sym("VOLUME_MAX", "VOL+"), "key", "VolumeUp"),
        ], font=font)

        chrome = self._row(w, row_h, row_bg)
        chrome.align_to(vol, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        self._place3(chrome, w, row_h, gap, [
            ("APPS", "ui", self._open_apps),
            ("MORE", "ui", self._open_more),
            ("SELECT", "ui", self._open_select),
        ], font=font)

    def _build_remote_landscape(self, W, H, pad, gap):
        """Wide panel: left = Back/Home/Power + D-pad; right = other rows."""
        row_bg = self._remote_row_bg()
        font = self.font
        col_gap = pad
        col_w = (W - 2 * pad - col_gap) // 2
        if col_w < 80:
            # Too narrow for a real split — fall back to the stacked layout.
            self._build_remote_portrait(W, H, pad, gap)
            return

        panel_style = self._mk_style()
        panel_style.set_bg_opa(lv.OPA.TRANSP)
        panel_style.set_border_width(0)
        panel_style.set_pad_all(0)

        host = self._page_parent()
        left = lv.obj(host)
        left.set_size(col_w, H)
        left.set_pos(pad, 0)
        left.add_style(panel_style, 0)
        _no_scroll(left)

        right = lv.obj(host)
        right.set_size(col_w, H)
        right.set_pos(pad + col_w + col_gap, 0)
        right.add_style(panel_style, 0)
        _no_scroll(right)

        # Right column: four equal rows (opts / transport / vol / chrome).
        n_right = 4
        row_h = max(28, (H - (n_right - 1) * gap) // n_right)
        while n_right * row_h + (n_right - 1) * gap > H and row_h > 22:
            row_h -= 1

        # Left: util row + D-pad using leftover height.
        ring = min(col_w, max(64, H - row_h - gap))
        while row_h + gap + ring > H and ring > 56:
            ring -= 4

        util = self._row(col_w, row_h, row_bg, parent=left)
        util.align(lv.ALIGN.TOP_MID, 0, 0)
        _util_btns, util_lbls = self._place3(util, col_w, row_h, gap, [
            (_sym("LEFT", "BACK"), "key", "Back"),
            (_sym("HOME", "HOME"), "accent", "Home"),
            (_sym("POWER", "PWR") + " " + self.engine.power_label(), "power", self._toggle_power),
        ], font=font)
        self._power_lbl = util_lbls[2] if len(util_lbls) > 2 else None

        ringobj = self._add_dpad(left, ring, font)
        ringobj.align_to(util, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)

        opts = self._row(col_w, row_h, row_bg, parent=right)
        opts.align(lv.ALIGN.TOP_MID, 0, 0)
        self._place3(opts, col_w, row_h, gap, [
            (_sym("REFRESH", "RPL"), "alt", "InstantReplay"),
            (_sym("LIST", "*"), "alt", "Info"),
            (_sym("EYE_OPEN", "CC"), "alt", "ClosedCaption"),
        ], font=font)

        play_face = self.engine.play_label()
        play = self._play_face_text(play_face)
        self._chrome_face = "%s|%s" % (play_face, self.engine.power_label())
        trans = self._row(col_w, row_h, row_bg, parent=right)
        trans.align_to(opts, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        _trans_btns, trans_lbls = self._place3(trans, col_w, row_h, gap, [
            (_sym("PREV", "<<"), "transport", "Rev"),
            (play, "transport", "Play"),
            (_sym("NEXT", ">>"), "transport", "Fwd"),
        ], font=font)
        self._play_lbl = trans_lbls[1] if len(trans_lbls) > 1 else None

        vol = self._row(col_w, row_h, row_bg, parent=right)
        vol.align_to(trans, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        self._place3(vol, col_w, row_h, gap, [
            (_sym("VOLUME_MID", "VOL-"), "key", "VolumeDown"),
            (_sym("MUTE", "MUTE"), "alt", "VolumeMute"),
            (_sym("VOLUME_MAX", "VOL+"), "key", "VolumeUp"),
        ], font=font)

        chrome = self._row(col_w, row_h, row_bg, parent=right)
        chrome.align_to(vol, lv.ALIGN.OUT_BOTTOM_MID, 0, gap)
        self._place3(chrome, col_w, row_h, gap, [
            ("APPS", "ui", self._open_apps),
            ("MORE", "ui", self._open_more),
            ("SELECT", "ui", self._open_select),
        ], font=font)


    def _build_devices(self):
        """Select page: cached TVs + Scan/Full (network discover is explicit only)."""
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        x0 = pad
        w = W - 2 * pad
        row_h = max(40, H // 11)
        scanning = bool(self._scan_busy)
        kind = self._scan_kind
        scan_lab = "Cancel" if scanning and kind == "scan" else "SCAN"
        full_lab = "Cancel" if scanning and kind == "full" else "FULL"
        remote_cb = (lambda: None) if scanning else self._goto_remote
        show_full = unicast_scan_supported()
        parent = self._page_parent()
        if show_full:
            third = (w - 2 * gap) // 3
            self._key_button(parent, "REMOTE", x0, 0, third, row_h, "ui",
                             remote_cb)
            self._key_button(parent, scan_lab, x0 + third + gap, 0, third, row_h,
                             "accent", self._scan_button)
            self._key_button(parent, full_lab, x0 + 2 * (third + gap), 0, third, row_h,
                             "accent", self._full_scan_button)
        else:
            half = (w - gap) // 2
            self._key_button(parent, "REMOTE", x0, 0, half, row_h, "ui",
                             remote_cb)
            self._key_button(parent, scan_lab, x0 + half + gap, 0, half, row_h,
                             "accent", self._scan_button)
        y = row_h + gap
        slot_h = max(44, self.plaque_h - 2 * pad)
        devices = self.discover_list or []
        avail = H - y
        max_slots = max(1, (avail + gap) // (slot_h + gap))
        for i, dev in enumerate(devices[:max_slots]):
            name = ascii_label((dev.get("name") or "").strip() or "")
            host = ascii_label((dev.get("host") or "").strip() or "")
            label = name or host or "Roku"
            pick = (lambda d=dev: self._pick_device(d))
            if scanning:
                pick = lambda: None
            self._key_button(
                parent, label, x0, y + i * (slot_h + gap), w, slot_h,
                "accent" if i == 0 else "key",
                pick,
                font=self.font,
                wrap=True,
            )

    def _build_apps(self):
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        x0 = pad
        w = W - 2 * pad
        row_h = max(40, H // 11)
        third = (w - 2 * gap) // 3
        parent = self._page_parent()
        self._key_button(parent, "REMOTE", x0, 0, third, row_h, "ui",
                         self._goto_remote)
        self._key_button(parent, "REFRESH", x0 + third + gap, 0, third, row_h, "ui",
                         self._refresh_apps)
        self._key_button(parent, "NEXT", x0 + 2 * (third + gap), 0, third, row_h, "ui",
                         self._apps_next)
        y = row_h + gap
        cols = 3
        bw = (w - gap * (cols - 1)) // cols
        bh = bw
        avail = H - y
        rows = max(1, (avail + gap) // (bh + gap))
        max_slots = rows * cols
        self.app_page_size = max_slots
        apps = self.engine.store_apps()
        window = apps[self.app_offset : self.app_offset + max_slots]
        sel = str(
            self.selected_app_id
            or (self.engine.active_app or {}).get("id")
            or ""
        )
        for i, app in enumerate(window):
            name = app_label(app.get("name") or app.get("id") or "?")
            col = i % cols
            row = i // cols
            aid = str(app.get("id") or "")
            self._key_button(
                parent, name, x0 + col * (bw + gap), y + row * (bh + gap), bw, bh,
                "accent" if aid and aid == sel else "key",
                (lambda a=app: self._launch(a)),
                wrap=True,
            )

    def _toggle_ui_pref(self, key, label):
        """Flip a boolean UI pref from MORE; rebuild this page for new chrome."""
        cur = bool(getattr(self, key, False))
        new = not cur
        pref_key = {
            "ui_shadows": "ui_shadows",
            "ui_gradients": "ui_gradients",
            "show_progress": "show_progress",
        }.get(key)
        if not pref_key or not set_ui_pref(pref_key, new):
            self._set_status("save failed")
            return
        setattr(self, key, new)
        self._set_status("%s %s" % (label, "on" if new else "off"))
        if key == "show_progress":
            self._update_progress()
        self._show_page("more")

    def _build_more(self):
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        x0 = pad
        w = W - 2 * pad
        row_h = max(40, H // 11)
        half = (w - gap) // 2
        third = (w - 2 * gap) // 3
        others = other_frontends(FRONTEND)
        parent = self._page_parent()
        self._key_button(parent, "REMOTE", x0, 0, third, row_h, "ui",
                         self._goto_remote)
        for i, fe in enumerate(others[:2]):
            lab = FRONTEND_BUTTONS.get(fe, fe.upper())
            self._key_button(
                parent,
                lab,
                x0 + (i + 1) * (third + gap),
                0,
                third,
                row_h,
                "ui",
                (lambda f=fe: self._arm_switch(f)),
            )
        y = row_h + gap

        # Chrome toggles (prefs; defaults off for MCU / SW-rotate panels).
        t_w = (w - 2 * gap) // 3
        self._key_button(
            parent,
            "SHD %s" % ("ON" if self.ui_shadows else "OFF"),
            x0,
            y,
            t_w,
            row_h,
            "ui",
            (lambda: self._toggle_ui_pref("ui_shadows", "shadows")),
            font=self.font_sm,
        )
        self._key_button(
            parent,
            "GRAD %s" % ("ON" if self.ui_gradients else "OFF"),
            x0 + t_w + gap,
            y,
            t_w,
            row_h,
            "ui",
            (lambda: self._toggle_ui_pref("ui_gradients", "gradients")),
            font=self.font_sm,
        )
        self._key_button(
            parent,
            "SCRUB %s" % ("ON" if self.show_progress else "OFF"),
            x0 + 2 * (t_w + gap),
            y,
            t_w,
            row_h,
            "ui",
            (lambda: self._toggle_ui_pref("show_progress", "scrub")),
            font=self.font_sm,
        )
        y += row_h + gap

        # Primary MORE list: TV inputs only (type=tvin / tvinput.*).
        inputs = self.engine.inputs()
        if not inputs:
            self._key_button(
                parent, "no inputs", x0, y, w, row_h, "alt", lambda: None
            )
            return
        avail = H - y
        max_slots = max(1, (avail + gap) // (row_h + gap)) * 2
        for i, app in enumerate(inputs[:max_slots]):
            lab = ascii_label((app.get("name") or "").strip())
            if not lab:
                lab = self.engine.input_short_label(app, max_chars=10)
            col = i % 2
            row = i // 2
            self._key_button(
                parent,
                lab,
                x0 + col * (half + gap),
                y + row * (row_h + gap),
                half,
                row_h,
                "alt",
                (lambda a=app: self._launch(a)),
                wrap=True,
            )

    # ----- navigation -----------------------------------------------------

    def _arm_switch(self, frontend):
        """MORE: arm a front-end change; same button again cancels."""
        if self._switch_armed == frontend:
            self._cancel_switch()
            return
        self._switch_armed = frontend
        self._layout_status_width(reserve_time=False)
        avail = self._status_avail_width()

        def fits(s):
            first = s.split("\n", 1)[0]
            return self._text_px(first, self._status_font(2)) <= avail

        self._set_status(format_switch_status(frontend, fits=fits))

    def _cancel_switch(self):
        """Disarm MORE front-end switch; restore inputs status."""
        self._switch_armed = None
        n = len(self.engine.inputs() or [])
        self._set_status(("%d inputs" % n) if n else "no inputs")

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
            self._set_status("save failed")
            return True
        msg = restart_app()
        if msg:
            self._set_status(msg)
        return True

    def _goto_remote(self):
        """Confirm front-end switch if armed; else open remote when a TV is set."""
        if self._scan_busy:
            return
        if self._switch_armed:
            self._confirm_switch()
            return
        host = (self.engine.host or "").strip()
        if not host:
            self._set_status("pick a TV first")
            return
        # Leaving apps/more via cache-hit left a blank content pane on MCU
        # (UDP: page_cache_hit remote after YouTube / REMOTE). Force rebuild
        # whenever we are not already on remote.
        force = self.page != "remote"
        self._show_page("remote", force=force)
        # Replace sticky "N apps" / "N inputs" plaque text with live playback.
        self._refresh_playback_bg()

    def _play_face_text(self, play_face=None):
        if play_face is None:
            play_face = self.engine.play_label()
        return _sym("PAUSE", "||") if play_face == "PAUSE" else _sym("PLAY", ">")

    def _power_face_text(self, power_face=None):
        if power_face is None:
            power_face = self.engine.power_label()
        return _sym("POWER", "PWR") + " " + power_face

    def _apply_chrome_face(self):
        """Update play/power label text in place (LVGL main thread only)."""
        play_face = self.engine.play_label()
        power_face = self.engine.power_label()
        self._chrome_face = "%s|%s" % (play_face, power_face)
        if self._play_lbl is not None:
            try:
                self._play_lbl.set_text(self._play_face_text(play_face))
            except Exception:
                pass
        if self._power_lbl is not None:
            try:
                self._power_lbl.set_text(self._power_face_text(power_face))
            except Exception:
                pass

    def _note_playback_chrome(self, force_rebuild=False):
        """Mailbox plaque (app + state) and in-place play/power chrome."""
        # Skip mailbox when labels unchanged — avoids LVGL work + pump churn.
        app = ascii_label(self.engine.playback_app_label())
        state = ascii_label(self.engine.playback_state_label())
        if app != getattr(self, "_last_status_text", None):
            self._queue_status(app)
        if state != getattr(self, "_last_state_text", None):
            self._queue_state(state)
        aid = str((self.engine.active_app or {}).get("id") or "")
        if aid:
            self.selected_app_id = aid
        face = "%s|%s" % (self.engine.play_label(), self.engine.power_label())
        if self.page != "remote":
            self._chrome_face = face
            return
        if force_rebuild:
            self._chrome_face = face
            self._pending_rebuild = True
            return
        if face != self._chrome_face:
            self._chrome_face = face
            self._pending_chrome = True

    def _refresh_playback_bg(self):
        """Refresh plaque from active-app + media-player on a worker."""

        def _work():
            try:
                self.engine.refresh_playback()
            except Exception:
                pass
            # Only queue LVGL work when labels / play-power face actually change.
            self._note_playback_chrome(force_rebuild=False)

        self._run_bg(_work)

    def _open_more(self):
        """Show MORE; load apps if needed so TV inputs can appear."""
        self._switch_armed = None
        self._show_page("more")
        if self.engine.apps:
            n = len(self.engine.inputs() or [])
            if n:
                self._set_status("%d inputs" % n)
            return
        self._set_status("loading inputs...")

        def _work():
            self.engine.query_apps()
            n = len(self.engine.inputs() or [])
            self._queue_status(("%d inputs" % n) if n else "no inputs")
            self._pending_rebuild = True

        self._run_bg(_work)

    def _open_apps(self):
        self.app_offset = 0
        if not self.selected_app_id:
            self.selected_app_id = str((self.engine.active_app or {}).get("id") or "")
        if self.engine.apps:
            self._set_status("%d apps" % len(self.engine.store_apps()))
            self._show_page("apps")
        else:
            self._refresh_apps()

    def _apps_next(self):
        n = len(self.engine.store_apps())
        step = max(1, int(self.app_page_size or 1))
        if n:
            self.app_offset = (self.app_offset + step) % n
        self._show_page("apps", force=True)

    # ----- status ---------------------------------------------------------

    def _layout_status_width(self, reserve_time=True):
        """Size the status label; on Select, reclaim the blank time column."""
        if self.status_lbl is None:
            return
        plaque_w = self.W - 2 * self.pad
        reserve = self._status_time_reserve if reserve_time else 0
        inner = getattr(self, "_status_inner_pad", self.pad)
        self.status_lbl.set_width(max(40, plaque_w - 2 * inner - reserve))

    def _status_avail_width(self):
        """Pixel width available for status text (Select uses full plaque)."""
        if self.status_lbl is not None and hasattr(self.status_lbl, "get_width"):
            try:
                w = int(self.status_lbl.get_width())
                if w > 0:
                    return w
            except Exception:
                pass
        plaque_w = self.W - 2 * self.pad
        inner = getattr(self, "_status_inner_pad", self.pad)
        reserve = 0 if self.page == "devices" else getattr(self, "_status_time_reserve", 0)
        return max(40, plaque_w - 2 * inner - reserve)

    def _text_px(self, text, font=None):
        """Measure a single line of plaque status text in pixels."""
        s = text or ""
        font = self.font if font is None else font
        if font is None and hasattr(lv, "font_get_default"):
            try:
                font = lv.font_get_default()
            except Exception:
                font = None
        if font is not None and hasattr(lv, "text_get_width"):
            try:
                attrs = lv.text_attributes_t()
                if hasattr(attrs, "init"):
                    attrs.init()
                return int(lv.text_get_width(s, len(s), font, attrs))
            except Exception:
                pass
        # Fallback: ~0.55em per ASCII glyph.
        em = 12
        try:
            em = int(getattr(font, "line_height", em) or em)
        except Exception:
            pass
        return max(1, len(s) * max(6, (em * 11) // 20))

    def _status_font(self, nlines=1):
        """Main face for one line; ``font_sm`` when status wraps to two lines."""
        if int(nlines or 1) >= 2 and self.font_sm is not None:
            return self.font_sm
        return self.font

    def _set_status(self, line):
        """Bottom-left plaque: app name or user feedback (Scanning, Netflix, …)."""
        on_select = self.page == "devices"
        # Select + switch-confirm prompts use the full plaque width.
        full_width = on_select or bool(getattr(self, "_switch_armed", None))
        if self.status_lbl is not None:
            raw = line if line is not None else ""
            # Preserve newlines (ascii_label treats control chars as spaces).
            if "\n" in raw:
                text = "\n".join(ascii_label(p) for p in raw.split("\n"))
            else:
                text = ascii_label(raw)
            changed = text != self._last_status_text
            if changed:
                self._layout_status_width(reserve_time=not full_width)
                nlines = 2 if "\n" in text else 1
                _apply_font(self.status_lbl, self._status_font(nlines))
                self.status_lbl.set_text(text)
                self._last_status_text = text
        if on_select:
            # Right-side clock / state stay blank on Select — full width for status.
            self._set_time("")
            self._set_progress_visible(False)
            return
        # Clock/scrub: only when scrub enabled — otherwise 5s polls flash the
        # plaque under SW-rotate for a ticking position label.
        if self.show_progress:
            self._set_time(self.engine.position_label())
            self._update_progress()

    def _set_state(self, line):
        """Top-right plaque: raw media-player state."""
        if self.state_lbl is not None:
            text = ascii_label(line if line is not None else "")
            if text != self._last_state_text:
                self.state_lbl.set_text(text)
                self._last_state_text = text

    def _set_time(self, line):
        if self.time_lbl is not None:
            text = ascii_label(line if line is not None else "")
            if text != self._last_time_text:
                self.time_lbl.set_text(text)
                self._last_time_text = text

    def _set_progress_visible(self, visible):
        track = self.progress_track
        if track is None:
            return
        flag = getattr(getattr(lv, "obj", lv), "FLAG", None)
        hidden = getattr(flag, "HIDDEN", None) if flag is not None else None
        if hidden is None:
            try:
                track.set_height(self.progress_h if visible else 0)
            except Exception:
                pass
            return
        try:
            if visible:
                if hasattr(track, "remove_flag"):
                    track.remove_flag(hidden)
                elif hasattr(track, "clear_flag"):
                    track.clear_flag(hidden)
            else:
                if hasattr(track, "add_flag"):
                    track.add_flag(hidden)
        except Exception:
            pass

    def _update_progress(self):
        """Under-plaque scrub rail from position/duration (hidden when unusable)."""
        if self.progress_track is None or self.progress_fill is None:
            return
        if not self.show_progress:
            self._set_progress_visible(False)
            return
        frac = self.engine.progress_fraction()
        if frac is None:
            self._set_progress_visible(False)
            try:
                self.progress_fill.set_width(0)
            except Exception:
                pass
            return
        self._set_progress_visible(True)
        w = int(self.progress_w * frac + 0.5)
        if w < 0:
            w = 0
        if w > self.progress_w:
            w = self.progress_w
        try:
            self.progress_fill.set_width(w)
            self.progress_fill.set_height(self.progress_h)
        except Exception:
            pass

    def _set_name(self, line):
        if self.name_lbl is not None:
            text = ascii_label(line or "Roku Remote")
            if text != self._last_name_text:
                self.name_lbl.set_text(text)
                self._last_name_text = text

    def _queue_status(self, line):
        if line is not None:
            self._pending_status = ascii_label(line)

    def _queue_state(self, line):
        # Allow clearing (empty string) when media has no play/pause/buffer.
        if line is not None:
            self._pending_state = ascii_label(line)

    def _queue_playback_plaque(self):
        """Queue bottom-left app + top-right state from the latest engine probe."""
        self._queue_status(self.engine.playback_app_label())
        self._queue_state(self.engine.playback_state_label())

    # ----- ECP actions (queued; drained by ``_pump``; no LVGL in jobs) -----

    def _run_bg(self, fn):
        """Queue ``fn`` for the LVGL soft-pump (no ``_thread``).

        ESP32-P4 ``_thread`` stacks are ~5KiB; network/ECP there overflowed
        ``mp_thread``. Jobs run on the main tick via :meth:`_pump` instead.
        """
        q = self._bg_q
        if len(q) >= 8:
            q.pop(0)
        q.append(fn)
        return True

    def _drain_bg(self):
        """Drain keypress queue (fast), then at most one other bg job."""
        if self._bg_busy:
            return
        self._bg_busy = True
        try:
            kq = getattr(self, "_ecp_q", None)
            if kq:
                # One fire-and-forget keypress. Usually invoked immediately from
                # ``_ecp_press_now`` (not the 250ms pump) so tap→wire is ~10ms.
                key = kq.pop(0)
                try:
                    self.engine.press(key, timeout=0.25, wait=False)
                except Exception:
                    pass
                return
            # Between taps: finish the previous keep-alive response so the next
            # press is send-only (bench: ~11ms vs drain+send ~60–100ms).
            try:
                if self.engine.ecp_idle_drain():
                    return
            except Exception:
                pass
            q = self._bg_q
            if not q:
                return
            job = q.pop(0)
            try:
                job()
            except Exception:
                pass
        finally:
            self._bg_busy = False

    def _ecp(self, key):
        """One-shot keypress (chrome / non-hold actions)."""

        def _work():
            self.engine.press(key, timeout=0.8, wait=False)
            try:
                self.engine.refresh_playback()
                self._note_playback_chrome()
            except Exception:
                pass

        self._run_bg(_work)

    def _ecp_press_now(self, key):
        """Queue ECP ``/keypress/`` and send on this tick (not the 250ms pump).

        Waiting for ``lv.timer`` (250ms) was the dominant tap→TV lag vs the
        manufacturer app. Call rate is owned by the LVGL button callback
        (``RELEASED``); no app-side debounce.
        """
        q = getattr(self, "_ecp_q", None)
        if q is None:
            self._ecp_q = []
            q = self._ecp_q
        if len(q) >= 12:
            q.pop(0)
        q.append(key)
        # Send on the LVGL callback tick — do not wait for the soft pump.
        self._drain_bg()

    def _ecp_press(self, key):
        """Queue one-shot keypress (non-hold chrome paths)."""
        def _work():
            try:
                self.engine.press(key, timeout=1.0)
            except Exception:
                pass

        self._run_bg(_work)

    def _ecp_down(self, key):
        """Start an ECP hold (``keydown``)."""
        self._held_keys[key] = True

        def _work():
            self.engine.keydown(key)

        self._run_bg(_work)

    def _ecp_up(self, key):
        """End an ECP hold (``keyup`` only — no playback refresh)."""
        if not self._held_keys.pop(key, None):
            return

        def _work():
            self.engine.keyup(key)

        self._run_bg(_work)

    def _toggle_power(self):
        key = self.engine.mark_power_optimistic()
        if self.page == "remote":
            self._apply_chrome_face()

        def _work():
            self.engine.press(key)
            try:
                self.engine.query_device_info()
                self.engine.refresh_playback()
                self._note_playback_chrome()
            except Exception:
                pass

        self._run_bg(_work)

    def _launch(self, app):
        if self._switch_armed:
            self._cancel_switch()
        app_id = app.get("id", "")
        self.selected_app_id = str(app_id or "")
        # Launch then return to remote (force — apps→remote cache-hit was blank).
        self._show_page("remote", force=True)

        def _work():
            self.engine.launch_refresh(app_id)
            try:
                self._note_playback_chrome()
            except Exception:
                pass

        self._run_bg(_work)

    def _refresh_apps(self):
        self.app_offset = 0
        self._set_status("loading apps...")
        self._show_page("apps", force=True)

        def _work():
            self.engine.query_apps()
            n = len(self.engine.store_apps())
            self._queue_status(("%d apps" % n) if n else (self.engine.last_error or "no apps"))
            self._pending_rebuild = True

        self._run_bg(_work)

    def _show_dev_info(self):
        self._set_status("device info...")

        def _work():
            info = self.engine.query_device_info()
            line = (info.get("model-name", "") + " " + info.get("power-mode", "")).strip()
            self._queue_status(line or self.engine.last_error or "no info")

        self._run_bg(_work)

    def _show_media(self):
        self._set_status("media...")

        def _work():
            try:
                self.engine.refresh_playback()
            except Exception:
                pass
            self._queue_playback_plaque()

        self._run_bg(_work)

    def _show_tv_channel(self):
        self._set_status("tv channel...")

        def _work():
            raw = self.engine.query_tv_active_channel() or self.engine.query_tv_channels()
            self._queue_status((raw.replace("\n", " ")[:48]) if raw else "n/a")

        self._run_bg(_work)

    def _show_perf(self):
        self._set_status("perf...")

        def _work():
            raw = self.engine.query_chanperf()
            self._queue_status(
                (raw.replace("\n", " ")[:48]) if raw else (self.engine.last_error or "perf n/a")
            )

        self._run_bg(_work)

    # ----- Select page (cached TVs) + explicit Scan -----------------------

    def _merge_device_lists(self, *lists):
        """Union device dicts by host; serial wins IP updates when present."""
        by_host = {}
        by_serial = {}
        for lst in lists:
            for item in lst or []:
                host = ((item or {}).get("host") or "").strip()
                if not host:
                    continue
                serial = ((item or {}).get("serial") or "").strip()
                name = ((item or {}).get("name") or "").strip()
                if serial and serial in by_serial:
                    old = by_serial[serial]
                    old_host = (old.get("host") or "").strip()
                    if old_host and old_host != host:
                        by_host.pop(old_host, None)
                prev = by_host.get(host) or {}
                row = {
                    "host": host,
                    "name": name or prev.get("name") or "",
                    "serial": serial or prev.get("serial") or "",
                }
                by_host[host] = row
                if row["serial"]:
                    by_serial[row["serial"]] = row
        rows = list(by_host.values())
        rows.sort(key=lambda r: (r.get("name") or r.get("host") or "").lower())
        return rows

    def _open_select(self, soft_refresh=False):
        """Show the Select page from cache — no network scan.

        ``soft_refresh`` (opt-in) re-probes cached hosts for names. Default off:
        those ECP calls run on the LVGL pump and freeze/flash the UI for seconds
        per TV under software rotation.
        """
        self._delete_armed = None
        self.discover_list = self._merge_device_lists(
            self.engine.cached_devices(), self.discover_list
        )
        self._show_page("devices", force=True)
        n = len(self.discover_list)
        if n:
            self._set_status("%d saved" % n)
        else:
            self._set_status("no TVs - press Scan")
        self._set_state("")
        if not soft_refresh:
            return

        def _work():
            try:
                devices = self.engine.refresh_cached_names()
            except Exception:
                devices = self.engine.cached_devices()
            self._pending_select_list = devices
            n2 = len(devices or [])
            if n2:
                self._queue_status("%d saved" % n2)
            else:
                self._queue_status("no TVs - press Scan")

        self._run_bg(_work)

    def _arm_delete(self, dev):
        """Long-press: arm delete; confirm with Scan on the Select page."""
        if self._scan_busy:
            return
        host = ((dev or {}).get("host") or "").strip()
        if not host:
            return
        name = ascii_label(((dev or {}).get("name") or "").strip() or host)
        self._delete_armed = host
        # Select page: reclaim the blank time column, then fit by pixel width.
        self._layout_status_width(reserve_time=False)
        avail = self._status_avail_width()

        def fits(s):
            first = s.split("\n", 1)[0]
            return self._text_px(first, self._status_font(2)) <= avail

        self._set_status(format_delete_status(name, fits, tail="\npress Scan"))

    def _scan_button(self):
        """Select-page Scan: confirm delete if armed, else quick discover."""
        if self._scan_busy:
            if self._scan_kind == "scan":
                self._cancel_scan()
            return
        host = self._delete_armed
        if host:
            self._delete_armed = None
            try:
                self.engine.forget_device(host)
            except Exception:
                pass
            self.discover_list = [
                d for d in (self.discover_list or []) if (d.get("host") or "") != host
            ]
            self._set_status("deleted")
            self._show_page("devices", force=True)
            return
        if self._scan_input_blocked():
            return
        self._start_scan(full=False)

    def _full_scan_button(self):
        """Select FULL: disarm delete; /24 when supported, else same as SCAN."""
        if self._scan_busy:
            if self._scan_kind == "full":
                self._cancel_scan()
            return
        self._delete_armed = None
        if self._scan_input_blocked():
            return
        self._start_scan(full=unicast_scan_supported())

    def _scan_input_blocked(self):
        """True while SCAN/FULL should ignore clicks after a devices rebuild."""
        until = getattr(self, "_scan_ignore_until", 0) or 0
        if not until:
            return False
        try:
            return ticks_diff(ticks_ms(), until) < 0
        except Exception:
            return False

    def _cancel_scan(self):
        if not self._scan_busy or self._scan_cancel:
            return
        self._scan_cancel = True
        self._pending_scan = False
        self._scan_yield = False
        try:
            self.engine.cancel_discover()
        except Exception:
            pass
        self._set_status("Cancelling...")

    def _pick_device(self, dev):
        if self._scan_busy:
            return
        host = (dev or {}).get("host") or ""
        name = ((dev or {}).get("name") or "").strip() or host
        if not host:
            self._set_status("no host")
            return
        self._delete_armed = None
        # Drop a late soft-refresh mailbox so it cannot rebuild Select under us.
        self._pending_select_list = None
        self.engine.set_host(host)
        self.ip_buf = host
        self.app_offset = 0
        self._set_name(name)
        self._set_state("")
        self._set_status("")
        # Drop any queued ECP/connect so the LVGL pump can finish painting Remote.
        self._bg_q = []
        self._playback_busy = False
        try:
            # Optimistic — keypress does not need device-info first.
            self.engine.connected = True
        except Exception:
            pass
        # Host changed — remote/apps/more chrome must not reuse another TV's tree.
        self._invalidate_page("remote")
        self._invalidate_page("apps")
        self._invalidate_page("more")
        self._show_page("remote", force=True)
        # Do NOT connect/query on the soft pump here: that blocked LVGL flushes
        # (Remote stayed half-painted for seconds, then a 4–7s full redraw).

    def _start_scan(self, full=False):
        """Explicit network discover — merges into cache; never clears the list."""
        if self._scan_busy:
            return
        self._delete_armed = None
        self._scan_busy = True
        self._scan_full = bool(full)
        self._scan_kind = "full" if full else "scan"
        self._scan_cancel = False
        self._last_scan_busy = True
        self._pending_devices = []
        self._set_status("Full scan..." if full else "Scanning...")
        self._set_state("")
        # Keep the Select page painted, then defer discover via the soft pump
        # (one yield tick). Do not use lv.timer_create here — those timers are
        # periodic; a failed delete re-fires discover forever and wedges USB.
        self._show_page("devices")
        self._scan_yield = True
        self._pending_scan = True

    def _paint_now(self):
        """Force one presented frame (safe to call from an LVGL timer callback)."""
        try:
            disp = None
            for name in ("display_get_default", "disp_get_default"):
                getter = getattr(lv, name, None)
                if getter is None:
                    continue
                try:
                    disp = getter()
                    break
                except Exception:
                    disp = None
            if hasattr(lv, "refr_now"):
                lv.refr_now(disp)
            show = getattr(display_drv, "show", None)
            if show is not None:
                show()
        except Exception:
            pass

    def _flush_scan_devices(self):
        """Merge newly discovered TVs into the Select list and rebuild the page."""
        if self.page != "devices":
            return False
        if not self._pending_devices:
            return False
        batch = self._pending_devices
        self._pending_devices = []
        before = {d.get("host") for d in (self.discover_list or [])}
        self.discover_list = self._merge_device_lists(self.discover_list, batch)
        after = {d.get("host") for d in (self.discover_list or [])}
        if after == before and not self._scan_busy:
            return False
        self._show_page("devices", force=True)
        self._set_status("found %d..." % len(self.discover_list))
        return True

    def _run_scan_work(self):
        # Only an armed _start_scan may run. Orphan LVGL kicks (or a second pump
        # tick) must not start another discover after _scan_busy clears.
        if self._scan_worker_active or not self._scan_busy:
            return
        if self._scan_cancel:
            self._scan_busy = False
            self._scan_kind = None
            self._scan_cancel = False
            self._scan_worker_active = False
            self._set_status("cancelled")
            self._show_page("devices", force=True)
            return
        self._scan_worker_active = True
        scan_fallback = bool(getattr(self, "_scan_full", False))
        # Present the devices page before a possibly-blocking inline discover.
        self._paint_now()

        def _on_device(dev):
            if self._scan_cancel:
                return
            host = (dev or {}).get("host") or ""
            if not host:
                return
            for d in self._pending_devices:
                if d.get("host") == host:
                    return
            self._pending_devices.append(dev)
            # No-thread ports run discover on the LVGL thread — paint each hit now.
            if self._scan_progressive_inline:
                if self._flush_scan_devices():
                    self._paint_now()

        def _work():
            cancelled = False
            try:
                devices = self.engine.discover(
                    timeout=3.0,
                    retries=1,
                    ssdp=True,
                    scan_fallback=scan_fallback,
                    on_device=_on_device,
                )
                cancelled = bool(self._scan_cancel)
                if cancelled:
                    return
                for dev in devices or []:
                    _on_device(dev)
                # Merge final results into the persistent cache (additive).
                merged = self._merge_device_lists(
                    self.discover_list, self._pending_devices, devices
                )
                self._pending_select_list = merged
                if not merged:
                    self._queue_status(self.engine.last_error or "no Roku found")
                else:
                    self._queue_status("found %d - pick one" % len(merged))
            except Exception as e:
                if not self._scan_cancel:
                    self._queue_status(str(e))
            finally:
                cancelled = cancelled or bool(self._scan_cancel)
                self._scan_busy = False
                self._scan_kind = None
                self._scan_cancel = False
                self._scan_worker_active = False
                self._scan_progressive_inline = False
                if cancelled:
                    self._pending_select_list = None
                    self._queue_status("cancelled")
                    self._pending_rebuild = True

        # Queue on the soft-pump (same as ECP). Progressive list updates land
        # after discover returns; avoid ``_thread`` on ESP32.
        self._scan_progressive_inline = True
        self._run_bg(_work)

    # ----- soft pump (LVGL main thread) -----------------------------------

    def _pump(self, _timer=None):
        # Do not _paint_now() before drain: under SW-rotate that flashed the
        # dirty key for ~4s (queue_ms) before ECP even started.
        self._drain_bg()

        if self._pending_scan:
            if self._scan_yield:
                # Skip one pump so the app tick can paint first.
                self._scan_yield = False
            else:
                self._pending_scan = False
                self._run_scan_work()

        if self._pending_status is not None:
            self._set_status(self._pending_status)
            self._pending_status = None

        if self._pending_state is not None:
            self._set_state(self._pending_state)
            self._pending_state = None

        if self._pending_chrome:
            self._pending_chrome = False
            if self.page == "remote":
                self._apply_chrome_face()

        if self._pending_select_list is not None:
            incoming = self._pending_select_list
            self._pending_select_list = None
            # Already left Select (picked a TV) — keep remote; only refresh cache.
            if self.page != "devices":
                self.discover_list = self._merge_device_lists(
                    self.discover_list, incoming
                )
            else:
                before = [
                    (d.get("host") or "") for d in (self.discover_list or [])
                ]
                self.discover_list = self._merge_device_lists(
                    self.discover_list, incoming
                )
                after = [
                    (d.get("host") or "") for d in (self.discover_list or [])
                ]
                # Soft-refresh often only refreshes names (~5s of ECP). Rebuild
                # only when the host set changes — name-only updates were a full
                # SW-rotate page flash and killed in-flight taps (wrong TV).
                if after != before:
                    self._show_page("devices", force=True)

        if self._pending_devices and self.page == "devices":
            if self._flush_scan_devices():
                self._paint_now()

        if self._last_scan_busy and not self._scan_busy:
            # List/status already applied via _pending_select_list. A second
            # _show_page here recreates SCAN under a held/ghost touch and can
            # immediately re-arm discover.
            self._last_scan_busy = False

        if self._pending_rebuild:
            self._pending_rebuild = False
            self._show_page(self.page, force=True)

        self._status_ticks += 1
        # Prefs ``playback_poll_s`` (default 5); pump period is 250ms → N*4 ticks.
        # Periodic ECP updates the plaque (app / state / chrome) while on Remote.
        _poll_every = max(1, int(self.playback_poll_s) * 4)
        if (
            self.page == "remote"
            and (self.engine.host or "").strip()
            and self._status_ticks % _poll_every == 0
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


def create(engine=None, start_page="devices"):
    """Build the LVGL front end (does not call ``App.run``)."""
    return _RokuLvgl(engine=engine, start_page=start_page)


def run(engine=None, start_page="devices"):
    """Create the UI and let the app run itself."""
    create(engine=engine, start_page=start_page)


# Direct import / example kit: auto-start. ``roku_remote`` sets
# ``roku_engine._LAUNCHER_OWNS_RUN`` and calls ``run()`` itself.
import roku_engine as _roku_engine  # noqa: E402

if not getattr(_roku_engine, "_LAUNCHER_OWNS_RUN", False):
    run()
