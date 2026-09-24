# deps: lvgl
# modules: gphotos_engine, gphotos_sim
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
gphotos_lvgl
====================================================
Google Photos picker, list, viewer, and slideshow built with LVGL.

Pages:

* **connect** -- QR code of the Picker session link, with the three steps
  spelled out: scan it with your phone, choose photos in Google Photos,
  tap Done there. A live "Waiting for your picks" line counts up while the
  device polls the session; it jumps to the list by itself. **New link**
  starts a fresh session; desktop hosts also get **Open on this PC**
  (opens the link in the local browser); **Back** returns to the list.
* **list** -- paged rows of thumbnail + file name + date. PICK starts a new
  session, SLIDES starts the slideshow, MORE pages through long picks.
* **view** -- one photo fitted to the panel with BACK / PREV / PLAY / NEXT;
  tapping the photo advances. PLAY auto-advances every ``slideshow_s``
  seconds (prefs; default 5).

Import order matters: ``display_driver`` must be imported after
``board_config`` so LVGL's display / input devices are wired before widgets
are created. All network work (token refresh, session polling, image
downloads) is queued and drained from an ``lv.timer`` pump on the main
thread -- no ``_thread`` (ESP32 thread stacks are too small for TLS). Jobs
only touch the engine and post results into mailboxes; the pump applies
them to LVGL.

JPEG decoding: CPython's LVGL keeps TJPGD; MicroPython / CircuitPython LVGL
firmware decodes through displayif's ``jpegio``, registered as an LVGL image
decoder. PNG goes through LODEPNG on every build. Without a JPEG decoder the
list still works -- tiles keep a placeholder and the viewer says why.

Launch via ``google_photos`` (prefs + sim detection). Direct
``gphotos_lvgl.run()`` also works. Join Wi-Fi before running on a
microcontroller.
"""

import gc
import sys

_EXAMPLES = __file__.replace("\\", "/").rsplit("/", 1)[0]
if _EXAMPLES not in sys.path:
    sys.path.insert(0, _EXAMPLES)

import board_config  # noqa: E402,F401 — before display_driver so LVGL wiring sees it
import display_driver  # noqa: E402 — wires LVGL display/input into the app
import lvgl as lv  # noqa: E402
from board_config import display_drv  # noqa: E402
from gphotos_engine import date_label, time_label  # noqa: E402
from gphotos_sim import make_engine  # noqa: E402
from multimer import ticks_diff, ticks_ms  # noqa: E402

try:
    import webbrowser as _webbrowser
except ImportError:  # MicroPython / CircuitPython
    _webbrowser = None

FRONTEND = "lvgl"
PUMP_MS = 250
DEFAULT_SLIDESHOW_S = 5

# Charcoal chassis, one teal accent (distinct from the Roku violet).
_COL = {
    "bg": 0x10141A,
    "plaque": 0x1B2129,
    "plaque_edge": 0x2C3540,
    "row": 0x222B35,
    "row_alt": 0x1D252E,
    "tile": 0x33404D,
    "accent": 0x1E9E8A,
    "accent2": 0x157A6A,
    "ui": 0x2F3A47,
    "ui2": 0x243039,
    "text": 0xF3F5F7,
    "muted": 0x9AA5B1,
    "on_accent": 0xFFFFFF,
    "black": 0x000000,
    "white": 0xFFFFFF,
}


def _hex(rgb):
    return lv.color_hex(rgb)


def _shade(rgb, factor):
    r = max(0, min(255, int(((rgb >> 16) & 0xFF) * factor)))
    g = max(0, min(255, int(((rgb >> 8) & 0xFF) * factor)))
    b = max(0, min(255, int((rgb & 0xFF) * factor)))
    return (r << 16) | (g << 8) | b


def _sym(name, fallback):
    sym = getattr(lv, "SYMBOL", None)
    if sym is not None:
        val = getattr(sym, name, None)
        if val:
            return val
    return fallback


def _pick_font_from(candidates, ref_obj=None):
    for size in candidates:
        font = getattr(lv, "font_montserrat_" + str(size), None)
        if font is not None:
            return font
    if ref_obj is not None:
        for getter in ("theme_get_font_normal", "theme_get_font_small"):
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
    return _pick_font_from([s for s in (24, 22, 20, 18, 16, 14, 12) if s <= max_size], ref_obj)


def _apply_font(obj, font):
    if font is None:
        return
    try:
        obj.set_style_text_font(font, 0)
    except Exception:
        pass


def _flag(name):
    obj_flag = getattr(getattr(lv, "obj", None), "FLAG", None)
    if obj_flag is not None:
        return getattr(obj_flag, name, None)
    return getattr(getattr(lv, "OBJ_FLAG", None), name, None)


def _add_flag(obj, name):
    flag = _flag(name)
    if flag is None or obj is None:
        return
    try:
        obj.add_flag(flag)
    except Exception:
        pass


def _remove_flag(obj, name):
    flag = _flag(name)
    if flag is None or obj is None:
        return
    try:
        if hasattr(obj, "remove_flag"):
            obj.remove_flag(flag)
        else:
            obj.clear_flag(flag)
    except Exception:
        pass


def _no_scroll(obj):
    _remove_flag(obj, "SCROLLABLE")


def _set_hidden(obj, hidden):
    if hidden:
        _add_flag(obj, "HIDDEN")
    else:
        _remove_flag(obj, "HIDDEN")


# ----- image decoding ---------------------------------------------------

_JPEG_OK = None
_PNG_OK = None


def jpeg_supported():
    """True when LVGL can decode JPEG on this build (TJPGD or jpegio)."""
    global _JPEG_OK
    if _JPEG_OK is not None:
        return _JPEG_OK
    ok = hasattr(lv, "tjpgd_init")  # CPython: registered by lv.init()
    if not ok:
        try:
            import jpegio  # MicroPython (displayif) / CircuitPython

            ok = True
            reg = getattr(jpegio, "register_lvgl_decoder", None)
            if reg is not None:
                try:
                    reg()
                except RuntimeError:
                    ok = False
            names = getattr(jpegio, "lvgl_decoders", None)
            if ok and names is not None:
                try:
                    ok = "jpegio" in tuple(names())
                except Exception:
                    pass
        except ImportError:
            ok = False
    _JPEG_OK = ok
    return ok


def png_supported():
    global _PNG_OK
    if _PNG_OK is None:
        _PNG_OK = hasattr(lv, "lodepng_init")
    return _PNG_OK


def _jpeg_size(data):
    """(width, height) from the SOF marker, or (0, 0)."""
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        seg = (data[i] << 8) | data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
            return (data[i + 5] << 8) | data[i + 6], (data[i + 3] << 8) | data[i + 4]
        i += seg
    return 0, 0


def _png_size(data):
    if len(data) < 24:
        return 0, 0
    w = (data[16] << 24) | (data[17] << 16) | (data[18] << 8) | data[19]
    h = (data[20] << 24) | (data[21] << 16) | (data[22] << 8) | data[23]
    return w, h


def image_descriptor(path):
    """``(dsc, data, w, h)`` for a cached JPEG/PNG, else ``(None, None, 0, 0)``.

    ``data`` must stay referenced as long as ``dsc`` is an image source.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None, None, 0, 0
    if data[:3] == b"\xff\xd8\xff":
        if not jpeg_supported():
            return None, None, 0, 0
        w, h = _jpeg_size(data)
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        if not png_supported():
            return None, None, 0, 0
        w, h = _png_size(data)
    else:
        return None, None, 0, 0
    if not w or not h:
        return None, None, 0, 0
    try:
        dsc = lv.image_dsc_t()
        dsc.header.magic = lv.IMAGE_HEADER_MAGIC
        dsc.header.cf = lv.COLOR_FORMAT.RAW
        dsc.header.w = w
        dsc.header.h = h
        dsc.header.stride = 0
        dsc.data_size = len(data)
        dsc.data = data
    except Exception:
        try:
            dsc = lv.image_dsc_t(
                {
                    "header": {
                        "magic": lv.IMAGE_HEADER_MAGIC,
                        "w": w,
                        "h": h,
                        "cf": lv.COLOR_FORMAT.RAW,
                    },
                    "data_size": len(data),
                    "data": data,
                }
            )
        except Exception:
            return None, None, 0, 0
    return dsc, data, w, h


# ----- front end ----------------------------------------------------------


class _GPhotosLvgl:
    PAGES = ("connect", "list", "view")

    def __init__(self, engine=None, start_page="list"):
        self.engine = engine if engine is not None else make_engine()
        self.page = start_page if start_page in self.PAGES else "list"
        self.index = 0
        self.list_offset = 0
        self.page_size = 1
        self.slideshow = False
        try:
            self.slideshow_s = int(self.engine.get_pref("slideshow_s", DEFAULT_SLIDESHOW_S))
        except (TypeError, ValueError):
            self.slideshow_s = DEFAULT_SLIDESHOW_S
        if self.slideshow_s < 1:
            self.slideshow_s = 1

        # Cooperative bg queue (drained by ``_pump`` -- no ``_thread``).
        self._bg_q = []
        self._bg_busy = False
        # Mailboxes: jobs write, the pump applies on the LVGL thread.
        self._pending_status = None
        self._pending_thumbs = []
        self._pending_view = None
        self._pending_list = False
        self._pending_connect = False
        self._creating = False
        self._picked = False
        self._before_pick = None  # engine.snapshot() of the list PICK replaces
        self._pending_back = False
        self._wait_lbl = None
        self._wait_short = False
        self._last_wait_text = None
        self._poll_busy = False
        self._poll_at = None
        self._session_started = None
        self._poll_timed_out = False
        self._thumb_busy = {}
        self._images = {}  # item id -> (dsc, data): resident tiles (current page)
        self._rows = {}  # item id -> (tile image, placeholder label)
        self._view_ref = None  # (dsc, data) for the viewer
        self._view_fetching = None
        self._view_loaded_at = None
        self._prefetched = None
        self._page_root = None
        self._last_status_text = None
        self._last_title_text = None
        self._last_count_text = None

        self.W = display_drv.width
        self.H = display_drv.height
        self.unit = min(self.W, self.H)
        self.pad = max(4, self.unit // 64)
        self.radius = max(6, self.unit // 26)
        self.plaque_h = max(40 if self.H <= 360 else 60, self.H // 10)
        self.font = None
        self.font_sm = None
        self.title_lbl = None
        self.count_lbl = None
        self.status_lbl = None
        self.content = None
        self.view_img = None
        self.view_msg = None
        self.play_lbl = None
        self._timer = None

        self.build_ui()

    # ----- chrome ---------------------------------------------------------

    def _panel(self, obj, bg, radius=0, edge=None):
        try:
            obj.set_style_bg_color(_hex(bg), 0)
            obj.set_style_bg_opa(lv.OPA.COVER, 0)
            obj.set_style_radius(radius, 0)
            obj.set_style_pad_all(0, 0)
            if edge is None:
                obj.set_style_border_width(0, 0)
            else:
                obj.set_style_border_color(_hex(edge), 0)
                obj.set_style_border_width(1, 0)
            obj.set_style_shadow_width(0, 0)
        except Exception:
            pass

    def build_ui(self):
        loop = getattr(display_driver, "event_loop", None)
        inst = loop.current_instance() if loop is not None else None
        if inst is not None:
            inst.disable()
        try:
            scr = lv.screen_active()
            if self.H <= 360 or self.unit < 280:
                self.font = _pick_font_at_most(14, scr)
                self.font_sm = _pick_font_at_most(12, scr) or self.font
            else:
                self.font = _pick_font_at_most(16, scr)
                self.font_sm = _pick_font_at_most(14, scr) or self.font
            self._panel(scr, _COL["bg"])
            _no_scroll(scr)

            plaque = lv.obj(scr)
            plaque_w = self.W - 2 * self.pad
            plaque.set_size(plaque_w, self.plaque_h)
            plaque.align(lv.ALIGN.TOP_MID, 0, self.pad)
            self._panel(plaque, _COL["plaque"], self.radius, edge=_COL["plaque_edge"])
            _no_scroll(plaque)
            inset = max(3, self.pad)
            half = max(1, self.plaque_h // 2)

            self.count_lbl = lv.label(plaque)
            self.count_lbl.set_text("")
            self.count_lbl.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(self.count_lbl, self.font)
            self.count_lbl.align(lv.ALIGN.RIGHT_MID, -inset, -half // 2)

            self.title_lbl = lv.label(plaque)
            self.title_lbl.set_text("Google Photos")
            self.title_lbl.set_style_text_color(_hex(_COL["text"]), 0)
            _apply_font(self.title_lbl, self.font)
            self.title_lbl.set_width(plaque_w - 2 * inset - max(48, self.unit // 5))
            self._long_mode(self.title_lbl, "DOTS")
            self.title_lbl.align(lv.ALIGN.LEFT_MID, inset, -half // 2)

            self.status_lbl = lv.label(plaque)
            self.status_lbl.set_text("")
            self.status_lbl.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(self.status_lbl, self.font_sm)
            self.status_lbl.set_width(plaque_w - 2 * inset)
            self._long_mode(self.status_lbl, "DOTS")
            self.status_lbl.align(lv.ALIGN.LEFT_MID, inset, half // 2)

            self.content = lv.obj(scr)
            self.content.set_size(self.W, self.H - self.plaque_h - 2 * self.pad)
            self.content.set_pos(0, self.plaque_h + 2 * self.pad)
            self._panel(self.content, _COL["bg"])
            self.content.set_style_bg_opa(lv.OPA.TRANSP, 0)
            _no_scroll(self.content)

            if self.page == "connect":
                self._start_pick(rebuild=False)
            if self.page == "view" and not self.engine.items:
                self.page = "list"
            self._show_page(self.page)
        finally:
            if inst is not None:
                inst.enable()
        self._install_pump()

    def _long_mode(self, lbl, name):
        lm = getattr(lv.label, "LONG_MODE", None)
        mode = getattr(lm, name, None) if lm is not None else None
        if mode is None and name == "DOTS":
            mode = getattr(lm, "DOT", None) if lm is not None else None
        if mode is not None:
            try:
                lbl.set_long_mode(mode)
            except Exception:
                pass

    def _install_pump(self):
        creator = getattr(lv, "timer_create", None)
        if creator is None:
            return
        try:
            self._timer = creator(self._pump, PUMP_MS, None)
        except Exception:
            self._timer = None

    def _set_label(self, lbl, text, attr):
        if lbl is None:
            return
        text = text or ""
        if getattr(self, attr) == text:
            return
        setattr(self, attr, text)
        try:
            lbl.set_text(text)
        except Exception:
            pass

    def _set_status(self, text):
        self._set_label(self.status_lbl, text, "_last_status_text")

    def _set_title(self, text):
        self._set_label(self.title_lbl, text, "_last_title_text")

    def _set_count(self, text):
        self._set_label(self.count_lbl, text, "_last_count_text")

    def _content_metrics(self):
        W = self.W
        H = max(80, self.H - self.plaque_h - 2 * self.pad)
        if self.content is not None:
            try:
                reported = int(self.content.get_height())
                if reported >= 80:
                    H = reported
            except Exception:
                pass
        return W, H

    def _button(self, parent, text, x, y, w, h, role, on_click, font=None):
        if role == "accent":
            top, fg = _COL["accent"], _COL["on_accent"]
        else:
            top, fg = _COL["ui"], _COL["text"]
        btn = lv.button(parent)
        btn.set_size(int(w), int(h))
        btn.set_pos(int(x), int(y))
        _remove_flag(btn, "CLICK_FOCUSABLE")
        self._panel(btn, top, self.radius, edge=_shade(top, 0.6))
        try:
            btn.set_style_bg_color(_hex(_shade(top, 1.25)), lv.STATE.PRESSED)
        except Exception:
            pass
        lbl = lv.label(btn)
        lbl.set_text(text)
        lbl.set_style_text_color(_hex(fg), 0)
        _apply_font(lbl, font or self.font)
        lbl.center()

        def _cb(_e, _fn=on_click):
            _fn()

        btn.add_event_cb(_cb, lv.EVENT.CLICKED, None)
        return btn, lbl

    # ----- pages ----------------------------------------------------------

    def _clear_content(self):
        root = self._page_root
        self._page_root = None
        self._rows = {}
        self._wait_lbl = None
        self.view_img = None
        self.view_msg = None
        self.play_lbl = None
        if root is not None:
            try:
                root.delete()
            except Exception:
                pass

    def _show_page(self, page):
        self.page = page
        if self.content is None:
            return
        self._clear_content()
        if page != "view":
            self._view_ref = None
            self._view_fetching = None
            self._view_loaded_at = None
            if self.slideshow and page == "list":
                pass  # SLIDES re-arms it; PLAY on the viewer toggles it
        root = lv.obj(self.content)
        W, H = self._content_metrics()
        root.set_size(W, H)
        root.set_pos(0, 0)
        self._panel(root, _COL["bg"])
        root.set_style_bg_opa(lv.OPA.TRANSP, 0)
        _no_scroll(root)
        self._page_root = root
        if page == "connect":
            self._build_connect(root)
        elif page == "view":
            self._build_view(root)
        else:
            self._build_list(root)
        gc.collect()

    # connect ------------------------------------------------------------

    def _build_connect(self, parent):
        """QR + three plain steps + a live waiting line + self-explaining buttons.

        Portrait panels stack steps, QR, waiting line and buttons; landscape
        panels put the QR on the left and everything else beside it.
        """
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        btn_h = max(36, H // 11)
        session = None if self._creating else self.engine.session
        uri = (session or {}).get("pickerUri") or ""
        self._set_title("Google Photos")
        self._set_count("")
        self._wait_lbl = None
        self._last_wait_text = None

        labels = []
        if uri and _webbrowser is not None and not self.engine.sim:
            labels.append(("Open on this PC", "accent", self._open_browser))
        labels.append(("New link", "accent" if not labels else "ui", self._start_pick))
        if self.engine.items:
            labels.append(("Back", "ui", self._goto_list))
        elif self._before_pick is not None:
            labels.append(("Back", "ui", self._cancel_pick))

        landscape = W > H + H // 8
        if landscape:
            qr_side = min(H - 2 * gap, (W * 45) // 100, 320)
            col_x = qr_side + 3 * pad
            col_w = W - col_x - pad
        else:
            col_x = pad
            col_w = W - 2 * pad

        # Buttons: one row when every label gets a fair width, else the first
        # button on its own row and the rest sharing the row below it.
        n = len(labels)
        need = max(self._text_w(text, self.font_sm) for text, _r, _c in labels) + 4 * pad
        rows = [labels] if n == 1 or (col_w - (n - 1) * gap) // n >= need else [labels[:1], labels[1:]]
        y = H - btn_h
        for row in reversed(rows):
            bw = (col_w - (len(row) - 1) * gap) // len(row)
            for i, (text, role, cb) in enumerate(row):
                self._button(parent, text, col_x + i * (bw + gap), y, bw, btn_h, role, cb, self.font_sm)
            y -= btn_h + gap
        buttons_top = y + btn_h + gap

        tight = (H if landscape else W) < 260
        self._wait_short = col_w < 200
        steps = self._text(parent, col_w, _COL["text"], self.font_sm)
        if tight:
            steps.set_text("Scan with your phone, pick photos, tap Done. This screen moves on by itself.")
        else:
            steps.set_text(
                "1. Scan this code with your phone.\n"
                "2. Pick photos in Google Photos.\n"
                "3. Tap Done. This screen moves on by itself."
            )
        steps.set_pos(col_x, 0 if landscape else gap)

        wait = self._text(parent, col_w, _COL["accent"], self.font_sm)
        self._long_mode(wait, "CLIP")
        self._wait_lbl = wait
        self._update_wait()
        wait.set_pos(col_x, buttons_top - gap - self._line_h(self.font_sm))

        if not landscape:
            try:
                steps.update_layout()
                steps_h = int(steps.get_height())
            except Exception:
                steps_h = 4 * self._line_h(self.font_sm)
            top = gap + steps_h + gap
            bottom = buttons_top - 2 * gap - self._line_h(self.font_sm)
            qr_side = min(W - 4 * pad, bottom - top, 320)
            qr_x = (W - qr_side) // 2
            qr_y = top + max(0, (bottom - top - qr_side) // 2)
        else:
            qr_x = pad
            qr_y = (H - qr_side) // 2

        if uri:
            qr_cls = getattr(lv, "qrcode", None)
            if qr_cls is not None and qr_side >= 48:
                try:
                    qr = qr_cls(parent)
                    qr.set_size(int(qr_side))
                    qr.set_dark_color(_hex(_COL["black"]))
                    qr.set_light_color(_hex(_COL["white"]))
                    if hasattr(qr, "set_quiet_zone"):
                        qr.set_quiet_zone(True)
                    raw = uri.encode("utf-8")  # bytes: buffer protocol on every binding
                    qr.update(raw, len(raw))
                    qr.set_pos(int(qr_x), int(qr_y))
                except Exception as err:
                    self._link_label(parent, uri, col_w, "QR unavailable (%s)" % err)
            else:
                self._link_label(parent, uri, col_w, "")
            self._set_status(
                "simulator: picks arrive by themselves" if self.engine.sim else "pick photos on your phone"
            )
        elif self._creating:
            self._set_status("pick photos on your phone")
        elif self.engine.last_error:
            self._set_status(self.engine.last_error)
        elif not self.engine.has_credentials():
            self._set_status("no tokens file - see README")

    def _text(self, parent, w, color, font):
        lbl = lv.label(parent)
        lbl.set_width(int(w))
        self._long_mode(lbl, "WRAP")
        lbl.set_style_text_color(_hex(color), 0)
        _apply_font(lbl, font)
        return lbl

    @staticmethod
    def _text_w(text, font):
        """Pixel width of one line of ``text`` (a rough estimate if LVGL can't say)."""
        try:
            lbl = lv.label(lv.screen_active())
            _apply_font(lbl, font)
            lbl.set_text(text)
            lbl.update_layout()
            w = int(lbl.get_width())
            lbl.delete()
            return w
        except Exception:
            return len(text) * 8

    @staticmethod
    def _line_h(font):
        try:
            return int(font.get_line_height())
        except Exception:
            try:
                return int(font.line_height)
            except Exception:
                return 16

    def _wait_text(self):
        """The live line under the QR: what the screen is doing right now."""
        if self._creating:
            return "Getting a link from Google..."
        if self._picked:
            return "Got your picks - loading them..."
        session = self.engine.session
        if not session:
            return "Tap New link to get a code."
        if self._poll_timed_out:
            return "This code timed out. Tap New link."
        started = self._session_started
        secs = ticks_diff(ticks_ms(), started) // 1000 if started is not None else 0
        dots = "." * (1 + secs % 3)
        if self._wait_short:
            return "Waiting%s %d:%02d" % (dots + " " * (3 - len(dots)), secs // 60, secs % 60)
        return "Waiting for your picks%s  %d:%02d" % (dots + " " * (3 - len(dots)), secs // 60, secs % 60)

    def _update_wait(self):
        lbl = self._wait_lbl
        if lbl is None:
            return
        text = self._wait_text()
        if text != self._last_wait_text:
            self._last_wait_text = text
            try:
                lbl.set_text(text)
            except Exception:
                pass

    def _link_label(self, parent, uri, w, note):
        lbl = lv.label(parent)
        lbl.set_width(w)
        self._long_mode(lbl, "WRAP")
        lbl.set_style_text_color(_hex(_COL["muted"]), 0)
        _apply_font(lbl, self.font_sm)
        lbl.set_text((note + "\n" if note else "") + uri)
        lbl.align(lv.ALIGN.TOP_MID, 0, self.pad)

    def _open_browser(self):
        uri = (self.engine.session or {}).get("pickerUri") or ""
        if not uri or _webbrowser is None:
            return
        try:
            _webbrowser.open(uri)
            self._set_status("opened in your browser - pick, then tap Done there")
        except Exception as err:
            self._set_status("browser: %s" % err)

    def _start_pick(self, rebuild=True):
        """Create a fresh picker session in the background, then show its QR.

        Until the new session arrives the page says so instead of showing a
        leftover session's code (a restored one from the last run, or the
        one New link is replacing). The link is printed once, here, when
        Google hands out a new session -- not on every redraw of the page.
        """
        self._poll_timed_out = False
        self._session_started = None
        self._poll_at = None
        self._poll_busy = False
        self._picked = False
        self._creating = True
        self.slideshow = False
        self.list_offset = 0
        engine = self.engine
        if engine.items:
            self._before_pick = engine.snapshot()

        def _work():
            s = engine.create_session()
            self._creating = False
            if s:
                self._session_started = ticks_ms()
                if not engine.sim:
                    print("google_photos: new picker session; open this link in Google Photos:\n  " + s.get("pickerUri", ""))
            else:
                self._pending_status = engine.last_error or "could not start a session"
            self._pending_connect = True

        self._run_bg(_work)
        if rebuild:
            self._show_page("connect")

    def _cancel_pick(self):
        """Back from a PICK: put the old list back and drop the new session."""
        snap = self._before_pick
        self._before_pick = None
        if snap is None:
            self._goto_list()
            return
        self._creating = True  # no polling of the session we are abandoning
        engine = self.engine

        def _work():
            abandoned = engine.put_back(snap)
            self._creating = False
            if abandoned is not None and abandoned is not snap[0]:
                engine.delete_session(abandoned)
            self._pending_back = True

        self._run_bg(_work)

    def _poll_pick(self):
        engine = self.engine
        self._poll_busy = True

        def _work():
            if self._pending_back or self._creating:  # Back was tapped meanwhile
                self._poll_busy = False
                return
            try:
                done = engine.poll_session()
                if done:
                    self._picked = True
                    items = engine.list_items()
                    if items is None:
                        self._picked = False
                        self._pending_status = engine.last_error
                        self._pending_connect = True
                    else:
                        self._pending_list = True
                elif engine.session is None:
                    self._pending_status = engine.last_error or "session ended"
                    self._pending_connect = True
                elif engine.last_error:
                    self._pending_status = engine.last_error
            except Exception as err:
                self._pending_status = "poll: %s" % err
            self._poll_at = ticks_ms()
            self._poll_busy = False

        self._run_bg(_work)

    # list -----------------------------------------------------------------

    def _goto_list(self):
        self.slideshow = False
        self._show_page("list")

    def _build_list(self, parent):
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        engine = self.engine
        items = engine.items
        n = len(items)
        btn_h = max(36, H // 11)
        x0 = pad
        w = W - 2 * pad
        row_h = max(48, min(104, H // 6))
        inner = max(3, pad // 2)
        tile = row_h - 2 * inner
        avail = H - btn_h - gap
        page_size = max(1, (avail + gap) // (row_h + gap))
        self.page_size = page_size
        if self.list_offset >= n or self.list_offset < 0:
            self.list_offset = 0
        offset = self.list_offset

        labels = [("PICK", "accent", self._start_pick)]
        if n:
            labels.append(("SLIDES", "ui", self._start_slideshow))
        if n > page_size:
            labels.append(("MORE", "ui", self._next_page))
        count = len(labels)
        bw = (w - (count - 1) * gap) // count
        for i, (text, role, cb) in enumerate(labels):
            self._button(parent, text, x0 + i * (bw + gap), 0, bw, btn_h, role, cb)
        y = btn_h + gap

        self._set_title("Google Photos")
        self._set_count(engine.count_label() if n else "")
        notice = getattr(engine, "sim_notice", "") or ""
        if not n:
            msg = lv.label(parent)
            msg.set_width(w)
            self._long_mode(msg, "WRAP")
            msg.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(msg, self.font)
            msg.set_text("No photos picked yet.\nTap PICK, then scan the code with your phone.")
            msg.align(lv.ALIGN.CENTER, 0, y // 2)
            self._set_status(notice or engine.last_error or "")
            return

        # Drop tiles that are not on this page (bounded RAM on MCUs).
        page_items = items[offset : offset + page_size]
        keep = set(it.get("id") for it in page_items)
        for key in list(self._images.keys()):
            if key not in keep:
                self._images.pop(key, None)
        name_x = tile + 2 * inner
        name_w = w - name_x - inner
        for i, item in enumerate(page_items):
            key = item.get("id", "")
            row = lv.obj(parent)
            row.set_size(w, row_h)
            row.set_pos(x0, y + i * (row_h + gap))
            self._panel(row, _COL["row"] if i % 2 == 0 else _COL["row_alt"], self.radius)
            _no_scroll(row)
            _add_flag(row, "CLICKABLE")
            try:
                row.set_style_bg_color(_hex(_shade(_COL["row"], 1.3)), lv.STATE.PRESSED)
            except Exception:
                pass

            def _open(_e, _idx=offset + i):
                self._open_view(_idx)

            row.add_event_cb(_open, lv.EVENT.CLICKED, None)

            img = lv.image(row)
            img.set_size(tile, tile)
            img.set_pos(inner, inner)
            self._panel(img, _COL["tile"], max(2, self.radius // 2))
            _remove_flag(img, "CLICKABLE")
            try:
                img.set_inner_align(lv.image.ALIGN.CENTER)
            except Exception:
                pass
            ph = lv.label(row)
            ph.set_text(_sym("IMAGE", "#"))
            ph.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(ph, self.font)
            ph.align_to(img, lv.ALIGN.CENTER, 0, 0)

            name = lv.label(row)
            name.set_width(name_w)
            self._long_mode(name, "DOTS")
            name.set_style_text_color(_hex(_COL["text"]), 0)
            _apply_font(name, self.font)
            name.set_text(item.get("filename") or key or "photo")
            name.align(lv.ALIGN.TOP_LEFT, name_x, inner)

            meta = lv.label(row)
            meta.set_width(name_w)
            self._long_mode(meta, "DOTS")
            meta.set_style_text_color(_hex(_COL["muted"]), 0)
            _apply_font(meta, self.font_sm)
            meta.set_text(self._meta_text(item))
            meta.align(lv.ALIGN.BOTTOM_LEFT, name_x, -inner)

            self._rows[key] = (img, ph)
            cached = self._images.get(key)
            if cached is not None:
                self._apply_tile(key, cached[0])
            else:
                self._queue_thumb(item, tile)

        last = min(n, offset + page_size)
        if n > page_size:
            self._set_status("photos %d-%d of %d%s" % (offset + 1, last, n, ("  " + notice) if notice else ""))
        else:
            self._set_status(notice or "tap a photo to view it")

    @staticmethod
    def _meta_text(item):
        parts = []
        d = date_label(item.get("createTime"))
        t = time_label(item.get("createTime"))
        if d:
            parts.append(d + (" " + t if t else ""))
        if item.get("width") and item.get("height"):
            parts.append("%dx%d" % (item["width"], item["height"]))
        if (item.get("type") or "").upper() == "VIDEO":
            parts.append("video")
        return "  ".join(parts)

    def _next_page(self):
        n = len(self.engine.items)
        if not n:
            return
        self.list_offset += self.page_size
        if self.list_offset >= n:
            self.list_offset = 0
        self._show_page("list")

    def _queue_thumb(self, item, size):
        key = item.get("id", "")
        if not key or key in self._thumb_busy:
            return
        self._thumb_busy[key] = True
        engine = self.engine

        def _work():
            path = ""
            try:
                path = engine.thumbnail_path(item, size, size, crop=True) or ""
            except Exception as err:
                engine.last_error = "thumbnail: %s" % err
            if not path:
                self._pending_status = engine.last_error
            self._pending_thumbs.append((key, path))

        self._run_bg(_work)

    def _apply_tile(self, key, dsc):
        row = self._rows.get(key)
        if row is None:
            return
        img, ph = row
        try:
            img.set_src(dsc)
            _set_hidden(ph, True)
        except Exception:
            pass

    # view -----------------------------------------------------------------

    def _open_view(self, idx):
        n = len(self.engine.items)
        if not n:
            return
        self.index = idx % n
        self._show_page("view")

    def _start_slideshow(self):
        if not self.engine.items:
            return
        self.slideshow = True
        self.index = 0
        self._show_page("view")

    def _build_view(self, parent):
        W, H = self._content_metrics()
        pad = self.pad
        gap = pad
        bar_h = max(36, H // 11)
        img_h = H - bar_h - gap
        self.view_w = W
        self.view_h = img_h

        frame = lv.obj(parent)
        frame.set_size(W, img_h)
        frame.set_pos(0, 0)
        self._panel(frame, _COL["black"])
        _no_scroll(frame)
        _add_flag(frame, "CLICKABLE")

        def _tap(_e):
            self._go(1)

        frame.add_event_cb(_tap, lv.EVENT.CLICKED, None)

        img = lv.image(frame)
        img.set_size(W, img_h)
        img.set_pos(0, 0)
        _remove_flag(img, "CLICKABLE")
        try:
            img.set_inner_align(lv.image.ALIGN.CENTER)
        except Exception:
            pass
        self.view_img = img

        msg = lv.label(frame)
        msg.set_width(W - 2 * pad)
        self._long_mode(msg, "WRAP")
        msg.set_style_text_color(_hex(_COL["muted"]), 0)
        _apply_font(msg, self.font)
        ta = getattr(lv, "TEXT_ALIGN", None)
        center = getattr(ta, "CENTER", None) if ta is not None else None
        if center is not None:
            try:
                msg.set_style_text_align(center, 0)
            except Exception:
                pass
        msg.set_text("loading...")
        msg.center()
        self.view_msg = msg

        w = W - 2 * pad
        bw = (w - 3 * gap) // 4
        y = img_h + gap
        specs = (
            ("BACK", "ui", self._goto_list),
            (_sym("PREV", "<"), "ui", lambda: self._go(-1)),
            ("", "accent", self._toggle_slideshow),
            (_sym("NEXT", ">"), "ui", lambda: self._go(1)),
        )
        for i, (text, role, cb) in enumerate(specs):
            _btn, lbl = self._button(parent, text, pad + i * (bw + gap), y, bw, bar_h, role, cb)
            if i == 2:
                self.play_lbl = lbl
        self._refresh_play_face()
        self._show_view_meta()
        self._load_view(self.index)

    def _refresh_play_face(self):
        if self.play_lbl is None:
            return
        try:
            self.play_lbl.set_text(_sym("PAUSE", "||") if self.slideshow else _sym("PLAY", ">"))
            self.play_lbl.center()
        except Exception:
            pass

    def _toggle_slideshow(self):
        self.slideshow = not self.slideshow
        self._view_loaded_at = ticks_ms() if self.slideshow else None
        self._refresh_play_face()

    def _show_view_meta(self):
        items = self.engine.items
        n = len(items)
        if not n:
            return
        item = items[self.index]
        self._set_title(item.get("filename") or "photo")
        self._set_count("%d/%d" % (self.index + 1, n))
        self._set_status(self._meta_text(item) or " ")

    def _go(self, delta):
        n = len(self.engine.items)
        if not n or self.page != "view":
            return
        self.index = (self.index + delta) % n
        self._show_view_meta()
        self._load_view(self.index)

    def _load_view(self, idx):
        items = self.engine.items
        if idx >= len(items) or self.view_img is None:
            return
        item = items[idx]
        self._view_ref = None
        self._view_loaded_at = None
        gc.collect()
        path = self.engine.cached_path(item, self.view_w, self.view_h)
        if path:
            self._apply_view(idx, path)
            return
        try:
            self.view_img.set_src(None)
        except Exception:
            pass
        _set_hidden(self.view_msg, False)
        try:
            self.view_msg.set_text("loading...")
        except Exception:
            pass
        self._view_fetching = idx
        engine = self.engine
        vw, vh = self.view_w, self.view_h

        def _work():
            got = ""
            try:
                got = engine.thumbnail_path(item, vw, vh) or ""
            except Exception as err:
                engine.last_error = "photo: %s" % err
            self._pending_view = (idx, got)

        self._run_bg(_work)

    def _apply_view(self, idx, path):
        if self.page != "view" or idx != self.index or self.view_img is None:
            return
        self._view_fetching = None
        if not path:
            self._say_view(self.engine.last_error or "photo unavailable")
            self._view_loaded_at = ticks_ms()  # keep the slideshow moving
            return
        dsc, data, w, h = image_descriptor(path)
        if dsc is None:
            if not jpeg_supported():
                self._say_view("no JPEG decoder in this firmware\n(see README: jpegio)")
            else:
                self._say_view("could not decode image")
            self._view_loaded_at = ticks_ms()
            return
        self._view_ref = (dsc, data)
        try:
            self.view_img.set_src(dsc)
            _set_hidden(self.view_msg, True)
        except Exception as err:
            self._say_view("display: %s" % err)
        self._view_loaded_at = ticks_ms()
        self._prefetch(idx + 1)

    def _say_view(self, text):
        if self.view_msg is None:
            return
        try:
            self.view_msg.set_text(text)
            _set_hidden(self.view_msg, False)
        except Exception:
            pass

    def _prefetch(self, idx):
        """Warm the cache for the next photo so PLAY / NEXT is instant."""
        items = self.engine.items
        if len(items) < 2:
            return
        idx = idx % len(items)
        item = items[idx]
        if self._prefetched == item.get("id"):
            return
        self._prefetched = item.get("id")
        if self.engine.cached_path(item, self.view_w, self.view_h):
            return
        engine = self.engine
        vw, vh = self.view_w, self.view_h

        def _work():
            try:
                engine.thumbnail_path(item, vw, vh)
            except Exception:
                pass

        self._run_bg(_work)

    # ----- background queue + pump ----------------------------------------

    def _run_bg(self, fn):
        """Queue ``fn`` for the LVGL soft-pump (no ``_thread``)."""
        self._bg_q.append(fn)
        return True

    def _drain_bg(self):
        """Run at most one queued job per pump tick."""
        if self._bg_busy or not self._bg_q:
            return
        self._bg_busy = True
        job = self._bg_q.pop(0)
        try:
            job()
        except Exception as err:
            self._pending_status = "error: %s" % err
        finally:
            self._bg_busy = False

    def _pump(self, _timer=None):
        self._drain_bg()

        if self._pending_status is not None:
            text = self._pending_status
            self._pending_status = None
            if text:
                self._set_status(text)

        if self._pending_back:
            self._pending_back = False
            self._pending_connect = False
            self._goto_list()
            return

        if self._pending_list:
            self._pending_list = False
            self._before_pick = None
            self.list_offset = 0
            self.index = 0
            self._show_page("list")
            n = len(self.engine.items)
            self._set_status("%d picked" % n if n else "nothing was picked")
            return

        if self._pending_connect:
            self._pending_connect = False
            if self.page == "connect":
                self._show_page("connect")

        while self._pending_thumbs:
            key, path = self._pending_thumbs.pop(0)
            self._thumb_busy.pop(key, None)
            if not path:
                continue
            dsc, data, _w, _h = image_descriptor(path)
            if dsc is None:
                if not jpeg_supported() and path.endswith(".jpg"):
                    self._set_status("no JPEG decoder in this firmware (see README)")
                continue
            self._images[key] = (dsc, data)
            self._apply_tile(key, dsc)

        if self._pending_view is not None:
            idx, path = self._pending_view
            self._pending_view = None
            self._apply_view(idx, path)

        if self.page == "connect":
            session = self.engine.session
            if session and not self._creating and not self._poll_busy and not self._poll_timed_out:
                started = self._session_started
                timeout_ms = int(float(session.get("timeoutIn") or 1800.0) * 1000)
                if started is not None and ticks_diff(ticks_ms(), started) > timeout_ms:
                    self._poll_timed_out = True
                else:
                    interval = int(self.engine.poll_interval_s() * 1000)
                    if self._poll_at is None or ticks_diff(ticks_ms(), self._poll_at) >= interval:
                        self._poll_pick()
            self._update_wait()

        if (
            self.page == "view"
            and self.slideshow
            and self._view_loaded_at is not None
            and self._view_fetching is None
            and not self._bg_q
            and ticks_diff(ticks_ms(), self._view_loaded_at) >= self.slideshow_s * 1000
        ):
            self._go(1)


# Most recent front end instance (harnesses / screenshots / REPL poking).
_LAST = None


def create(engine=None, start_page="list"):
    """Build the LVGL front end (does not call ``App.run``)."""
    global _LAST
    _LAST = _GPhotosLvgl(engine=engine, start_page=start_page)
    return _LAST


def run(engine=None, start_page="list"):
    """Create the UI and let the app run itself."""
    create(engine=engine, start_page=start_page)


# Direct import / example kit: auto-start. ``google_photos`` sets
# ``gphotos_engine._LAUNCHER_OWNS_RUN`` and calls ``run()`` itself.
import gphotos_engine as _gphotos_engine  # noqa: E402

if not getattr(_gphotos_engine, "_LAUNCHER_OWNS_RUN", False):
    _engine = make_engine()
    _engine.restore()
    run(engine=_engine, start_page="list" if _engine.items else "connect")
