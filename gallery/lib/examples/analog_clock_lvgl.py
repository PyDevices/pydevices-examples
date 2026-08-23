# deps: lvgl
"""Responsive, skinnable analog clock for LVGL.

Set ``DEFAULT_SKIN`` to any of the eight built-in names below.  Applications may
register additional skins with ``AnalogClock.register_skin(name, mapping)``
before constructing the widget.
"""

import math
import time

from board_config import display_drv
import display_driver
from display_driver import app
import lvgl as lv

try:
    from js import Date as _JSDate
except ImportError:
    _JSDate = None

_CIRCLE = getattr(lv, "RADIUS_CIRCLE", 0x7FFF)
DEFAULT_SKIN = "Grand Classic"


BUILTIN_SKINS = {
    "Grand Classic": {
        "bezel_shape": "round",
        "face_shape": "round",
        "bezel": 0xC8AA68,
        "bezel_hi": 0xFFF0B0,
        "bezel_lo": 0x5B421E,
        "face": 0xF4E8C8,
        "face_grad": 0xCDBB91,
        "marks": 0x241A10,
        "hands": 0x17100B,
        "second": 0x9E1D18,
        "accent": 0x8A651E,
        "hand_style": "dauphine",
        "numerals": "roman",
        "brand": "CHRONOMETER",
    },
    "Midnight Diver": {
        "bezel_shape": "round",
        "face_shape": "round",
        "bezel": 0x17202A,
        "bezel_hi": 0x6B7784,
        "bezel_lo": 0x05080B,
        "face": 0x07121A,
        "face_grad": 0x102C3A,
        "marks": 0xD9F5EF,
        "hands": 0xF4FFF8,
        "second": 0xFF6B24,
        "accent": 0x42D6B5,
        "hand_style": "diver",
        "numerals": "quarters",
        "brand": "200 m  AUTOMATIC",
    },
    "Swiss Rail": {
        "bezel_shape": "round",
        "face_shape": "round",
        "bezel": 0xD7D9D8,
        "bezel_hi": 0xFFFFFF,
        "bezel_lo": 0x5C6162,
        "face": 0xF2F2EC,
        "face_grad": 0xD6D8D3,
        "marks": 0x111111,
        "hands": 0x151515,
        "second": 0xE32322,
        "accent": 0xE32322,
        "hand_style": "railway",
        "numerals": "none",
        "brand": "HELVETICA",
    },
    "Aviator": {
        "bezel_shape": "round",
        "face_shape": "round",
        "bezel": 0x4A4740,
        "bezel_hi": 0xA49B87,
        "bezel_lo": 0x0C0C0B,
        "face": 0x171914,
        "face_grad": 0x303427,
        "marks": 0xE7E1C2,
        "hands": 0xF5EED0,
        "second": 0xD47C2B,
        "accent": 0xC99A50,
        "hand_style": "sword",
        "numerals": "arabic",
        "brand": "FLIEGER",
    },
    "Deco Salon": {
        "bezel_shape": "rounded",
        "face_shape": "round",
        "bezel_radius": 0.13,
        "bezel_aspect": 0.86,
        "bezel": 0xC7A65A,
        "bezel_hi": 0xF8E4A5,
        "bezel_lo": 0x443315,
        "face": 0x182723,
        "face_grad": 0x31554B,
        "marks": 0xE9D49B,
        "hands": 0xF8E9B8,
        "second": 0xD36B42,
        "accent": 0xE7C568,
        "hand_style": "skeleton",
        "numerals": "roman",
        "brand": "ART DECO",
    },
    "Tank": {
        "bezel_shape": "rect",
        "face_shape": "rect",
        "bezel_aspect": 0.78,
        "bezel": 0xBDA76E,
        "bezel_hi": 0xF1E3B5,
        "bezel_lo": 0x4C4027,
        "face": 0xE8DFC5,
        "face_grad": 0xBEB397,
        "marks": 0x252118,
        "hands": 0x245478,
        "second": 0x245478,
        "accent": 0x725D29,
        "hand_style": "breguet",
        "numerals": "roman",
        "brand": "PARIS",
    },
    "Metro Square": {
        "bezel_shape": "rounded",
        "face_shape": "rounded",
        "bezel_radius": 0.18,
        "face_radius": 0.14,
        "bezel_aspect": 1.0,
        "bezel": 0x31343B,
        "bezel_hi": 0x8F96A3,
        "bezel_lo": 0x08090B,
        "face": 0xDDE3E6,
        "face_grad": 0xA9B5BB,
        "marks": 0x172129,
        "hands": 0x15212A,
        "second": 0x0077D9,
        "accent": 0x0077D9,
        "hand_style": "baton",
        "numerals": "quarters",
        "brand": "METRO",
    },
    "Rose Nocturne": {
        "bezel_shape": "round",
        "face_shape": "round",
        "bezel": 0x8C5D55,
        "bezel_hi": 0xE3B4A4,
        "bezel_lo": 0x321C1A,
        "face": 0x160F19,
        "face_grad": 0x38233C,
        "marks": 0xE8C9C1,
        "hands": 0xF0D8CF,
        "second": 0xD889A8,
        "accent": 0xCF8F82,
        "hand_style": "leaf",
        "numerals": "none",
        "brand": "NOCTURNE",
    },
}

BUILTIN_SKIN_ORDER = (
    "Grand Classic",
    "Midnight Diver",
    "Swiss Rail",
    "Aviator",
    "Deco Salon",
    "Tank",
    "Metro Square",
    "Rose Nocturne",
)


def _color(value):
    return lv.color_hex(int(value))


def _shape_radius(shape, radius, short_side):
    if shape == "round":
        return _CIRCLE
    if shape == "rect":
        return 0
    return max(2, int(short_side * float(radius)))


def _font_for(size):
    for points in (48, 40, 36, 32, 28, 24, 22, 20, 18, 16, 14):
        if points <= size:
            font = getattr(lv, "font_montserrat_%d" % points, None)
            if font is not None:
                return font, points
    font = getattr(lv, "font_montserrat_14", None)
    return (font, 14) if font is not None else (None, 0)


def _set_scaled_font(label, target_size):
    """Use the nearest compiled font and scale it to the requested visual size."""
    font, points = _font_for(max(1, int(target_size)))
    if font is None:
        return
    label.set_style_text_font(font, 0)
    scale = max(128, min(640, round(256 * target_size / points)))
    if scale != 256:
        try:
            label.set_style_transform_scale(scale, 0)
        except AttributeError:
            label.set_style_transform_scale_x(scale, 0)
            label.set_style_transform_scale_y(scale, 0)


def _plain(obj):
    obj.set_style_pad_all(0, 0)
    obj.set_style_border_width(0, 0)
    obj.set_style_outline_width(0, 0)
    obj.set_style_bg_opa(lv.OPA.TRANSP, 0)
    try:
        obj.remove_flag(lv.obj.FLAG.CLICKABLE)
        obj.remove_flag(lv.obj.FLAG.SCROLLABLE)
    except AttributeError:
        pass


def _local_clock_time():
    """Return browser-local time in PyScript, host/device local time elsewhere."""
    if _JSDate is not None:
        now = _JSDate.new()
        return int(now.getHours()), int(now.getMinutes()), int(now.getSeconds())
    now = time.localtime()
    return now[3], now[4], now[5]


class GlassShimmer:
    """Subtle specular layers drawn above the dial to suggest curved glass."""

    def __init__(self, parent, width, height, radius, light, dark):
        self.wash = lv.obj(parent)
        self.wash.set_size(max(1, width - 6), max(1, height * 43 // 100))
        self.wash.align(lv.ALIGN.TOP_MID, 0, 3)
        self.wash.set_style_radius(radius, 0)
        self.wash.set_style_border_width(0, 0)
        self.wash.set_style_bg_color(_color(light), 0)
        self.wash.set_style_bg_grad_color(_color(dark), 0)
        self.wash.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.wash.set_style_bg_opa(32, 0)
        self.wash.set_style_pad_all(0, 0)

        self.glint = lv.arc(parent)
        glint_size = max(24, min(width, height) * 88 // 100)
        self.glint.set_size(glint_size, glint_size)
        self.glint.center()
        self.glint.set_bg_angles(205, 302)
        self.glint.set_angles(205, 302)
        self.glint.set_style_arc_width(max(2, glint_size // 70), lv.PART.MAIN)
        self.glint.set_style_arc_color(_color(light), lv.PART.MAIN)
        self.glint.set_style_arc_opa(72, lv.PART.MAIN)
        self.glint.set_style_arc_width(max(2, glint_size // 70), lv.PART.INDICATOR)
        self.glint.set_style_arc_color(_color(light), lv.PART.INDICATOR)
        self.glint.set_style_arc_opa(72, lv.PART.INDICATOR)
        self.glint.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.KNOB)
        self.glint.set_style_pad_all(0, 0)
        try:
            self.glint.remove_flag(lv.obj.FLAG.CLICKABLE)
            self.glint.remove_flag(lv.obj.FLAG.SCROLLABLE)
            self.wash.remove_flag(lv.obj.FLAG.CLICKABLE)
            self.wash.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass


class AnalogClock:
    """Responsive analog clock widget with a validated, extensible skin registry."""

    skins = {}
    _skin_order = []

    @classmethod
    def register_skin(cls, name, mapping):
        skin = dict(mapping)
        bezel_shape = skin.get("bezel_shape", "round")
        face_shape = skin.get("face_shape", bezel_shape)
        shapes = ("round", "rect", "rounded")
        if bezel_shape not in shapes or face_shape not in shapes:
            raise ValueError("shapes must be round, rect, or rounded")
        if bezel_shape == "round" and face_shape != "round":
            raise ValueError("a round bezel can contain only a round face")
        required = (
            "bezel",
            "bezel_hi",
            "bezel_lo",
            "face",
            "face_grad",
            "marks",
            "hands",
            "second",
            "accent",
        )
        missing = [key for key in required if key not in skin]
        if missing:
            raise ValueError("skin is missing: " + ", ".join(missing))
        skin["bezel_shape"] = bezel_shape
        skin["face_shape"] = face_shape
        name = str(name)
        if name not in cls.skins:
            cls._skin_order.append(name)
        cls.skins[name] = skin

    @classmethod
    def register_skins(cls, mappings):
        for name, skin in mappings.items():
            cls.register_skin(name, skin)

    @classmethod
    def skin_names(cls):
        return tuple(cls._skin_order)

    def __init__(self, parent, skin="Grand Classic", open_picker=None):
        self.parent = parent
        self._open_picker = open_picker
        self._skin_name = skin if isinstance(skin, str) else "External"
        self.skin = self._resolve_skin(skin)
        self._timer = None
        self._build()

    def _resolve_skin(self, skin):
        if isinstance(skin, str):
            if skin not in self.skins:
                raise KeyError("unknown clock skin: " + skin)
            return dict(self.skins[skin])
        temporary = "__external__"
        self.register_skin(temporary, skin)
        result = dict(self.skins.pop(temporary))
        self._skin_order.remove(temporary)
        return result

    def _available_size(self):
        width = int(getattr(display_drv, "width", 320) or 320)
        height = int(getattr(display_drv, "height", 480) or 480)
        margin = max(8, min(width, height) // 30)
        return width, height, margin

    def _build(self):
        width, height, margin = self._available_size()
        self.parent.set_style_bg_color(_color(0x000000), 0)
        self.parent.set_style_bg_opa(lv.OPA.COVER, 0)
        self.parent.set_style_pad_all(0, 0)
        try:
            self.parent.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass

        aspect = float(self.skin.get("bezel_aspect", 1.0))
        available_w = width - 2 * margin
        available_h = height - 2 * margin
        bezel_w = min(available_w, int(available_h * aspect))
        bezel_h = min(available_h, int(available_w / aspect))
        short = min(bezel_w, bezel_h)

        self.shadow = lv.obj(self.parent)
        self.shadow.set_size(bezel_w, bezel_h)
        self.shadow.center()
        self.shadow.set_style_translate_y(max(3, short // 45), 0)
        self.shadow.set_style_radius(
            _shape_radius(
                self.skin["bezel_shape"],
                self.skin.get("bezel_radius", 0.12),
                short,
            ),
            0,
        )
        self.shadow.set_style_bg_color(_color(0x000000), 0)
        self.shadow.set_style_bg_opa(210, 0)
        self.shadow.set_style_shadow_color(_color(self.skin["bezel_hi"]), 0)
        self.shadow.set_style_shadow_width(max(8, short // 16), 0)
        self.shadow.set_style_shadow_opa(70, 0)
        self.shadow.set_style_border_width(0, 0)

        self.bezel = lv.obj(self.parent)
        self.bezel.set_size(bezel_w, bezel_h)
        self.bezel.center()
        bezel_radius = _shape_radius(
            self.skin["bezel_shape"],
            self.skin.get("bezel_radius", 0.12),
            short,
        )
        self.bezel.set_style_radius(bezel_radius, 0)
        self.bezel.set_style_bg_color(_color(self.skin["bezel_hi"]), 0)
        self.bezel.set_style_bg_grad_color(_color(self.skin["bezel_lo"]), 0)
        self.bezel.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.bezel.set_style_bg_opa(lv.OPA.COVER, 0)
        self.bezel.set_style_border_color(_color(self.skin["bezel"]), 0)
        self.bezel.set_style_border_width(max(2, short // 45), 0)
        self.bezel.set_style_pad_all(max(7, short // 19), 0)
        try:
            self.bezel.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass

        face_w = bezel_w - 2 * max(8, short // 12)
        face_h = bezel_h - 2 * max(8, short // 12)
        self.face = lv.obj(self.bezel)
        self.face.set_size(face_w, face_h)
        self.face.center()
        face_radius = _shape_radius(
            self.skin["face_shape"],
            self.skin.get("face_radius", 0.10),
            min(face_w, face_h),
        )
        self.face.set_style_radius(face_radius, 0)
        self.face.set_style_bg_color(_color(self.skin["face"]), 0)
        self.face.set_style_bg_grad_color(_color(self.skin["face_grad"]), 0)
        self.face.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.face.set_style_bg_opa(lv.OPA.COVER, 0)
        self.face.set_style_border_color(_color(self.skin["accent"]), 0)
        self.face.set_style_border_width(max(1, short // 95), 0)
        self.face.set_style_pad_all(0, 0)
        try:
            self.face.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass

        dial = min(face_w, face_h)
        self.scale = lv.scale(self.face)
        self.scale.set_size(dial, dial)
        self.scale.center()
        _plain(self.scale)
        self.scale.set_mode(lv.scale.MODE.ROUND_INNER)
        self.scale.set_range(0, 720)
        self.scale.set_angle_range(360)
        self.scale.set_rotation(270)
        self.scale.set_total_tick_count(61)
        self.scale.set_major_tick_every(5)
        self.scale.set_label_show(False)

        minor = lv.style_t()
        minor.init()
        minor.set_line_color(_color(self.skin["marks"]))
        minor.set_line_width(max(1, dial // 180))
        minor.set_length(max(3, dial // 34))
        self.scale.add_style(minor, lv.PART.ITEMS)

        major = lv.style_t()
        major.init()
        major.set_line_color(_color(self.skin["marks"]))
        major.set_line_width(max(2, dial // 100))
        major.set_length(max(7, dial // 17))
        major.set_line_rounded(True)
        self.scale.add_style(major, lv.PART.INDICATOR)
        self._styles = [minor, major]

        self._add_numerals(dial)
        self._add_brand(dial)
        self._make_hands(dial)
        self._make_hub(dial)
        self.glass = GlassShimmer(
            self.face,
            face_w,
            face_h,
            face_radius,
            0xFFFFFF,
            self.skin["face_grad"],
        )
        self.hitbox = lv.obj(self.parent)
        self.hitbox.set_size(bezel_w, bezel_h)
        self.hitbox.center()
        self.hitbox.set_style_radius(bezel_radius, 0)
        self.hitbox.set_style_bg_opa(lv.OPA.TRANSP, 0)
        self.hitbox.set_style_border_width(0, 0)
        self.hitbox.set_style_pad_all(0, 0)
        try:
            self.hitbox.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass
        if self._open_picker is not None:
            self.hitbox.add_event_cb(self._clock_clicked, lv.EVENT.CLICKED, None)
        self.update_time()
        self._timer = lv.timer_create(self._tick, 200, None)

    def _add_numerals(self, dial):
        mode = self.skin.get("numerals", "none")
        if mode == "none":
            return
        roman = ("XII", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI")
        arabic = ("12", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11")
        values = roman if mode == "roman" else arabic
        radius = dial * (0.365 if mode != "quarters" else 0.36)
        for hour in range(12):
            if mode == "quarters" and hour not in (0, 3, 6, 9):
                continue
            label = lv.label(self.scale)
            label.set_text(values[hour])
            label.set_style_text_color(_color(self.skin["marks"]), 0)
            _set_scaled_font(label, max(14, dial // 13))
            label.set_style_pad_all(0, 0)
            angle = math.radians(hour * 30 - 90)
            x = int(math.cos(angle) * radius)
            y = int(math.sin(angle) * radius)
            label.align(lv.ALIGN.CENTER, x, y)

    def _add_brand(self, dial):
        text = self.skin.get("brand")
        if not text:
            return
        label = lv.label(self.face)
        label.set_text(text)
        label.set_style_text_color(_color(self.skin["accent"]), 0)
        _set_scaled_font(label, max(12, dial // 20))
        label.align(lv.ALIGN.CENTER, 0, -dial // 7)

    def _line(self, color, width):
        line = lv.line(self.scale)
        style = lv.style_t()
        style.init()
        style.set_line_color(_color(color))
        style.set_line_width(width)
        style.set_line_rounded(True)
        line.add_style(style, 0)
        self._styles.append(style)
        return line

    def _make_hands(self, dial):
        style = self.skin.get("hand_style", "baton")
        hour_length = dial * 27 // 100
        minute_length = dial * 39 // 100
        second_length = dial * 43 // 100
        hour_w = max(4, dial // 34)
        minute_w = max(3, dial // 42)
        second_w = max(1, dial // 115)
        hands = self.skin["hands"]
        accent = self.skin["accent"]
        face = self.skin["face"]
        second = self.skin["second"]
        self.hand_layers = {"hour": [], "minute": [], "second": []}

        def add(which, color, width, length):
            self.hand_layers[which].append((self._line(color, max(1, width)), max(2, length)))

        if style == "dauphine":
            # Wide lower facets and fine full-length tips suggest tapered hands.
            for which, length, width in (
                ("hour", hour_length, hour_w),
                ("minute", minute_length, minute_w),
            ):
                add(which, 0x090705, width + 4, length + 2)
                add(which, hands, width + 1, length * 82 // 100)
                add(which, accent, max(1, width // 3), length)
        elif style == "diver":
            # Heavy black outlines around luminous centers stay legible underwater.
            for which, length, width in (
                ("hour", hour_length, hour_w + 3),
                ("minute", minute_length, minute_w + 2),
            ):
                add(which, 0x010304, width + 5, length + 2)
                add(which, hands, width, length)
                add(which, accent, max(1, width // 4), length * 84 // 100)
        elif style == "railway":
            # Restrained black batons and the iconic high-contrast red seconds hand.
            add("hour", hands, hour_w + 1, hour_length)
            add("minute", hands, minute_w, minute_length)
        elif style == "sword":
            # Dark edging, a broad pale blade, and a fine warm center ridge.
            for which, length, width in (
                ("hour", hour_length, hour_w + 1),
                ("minute", minute_length, minute_w + 1),
            ):
                add(which, 0x030403, width + 5, length + 2)
                add(which, hands, width + 1, length)
                add(which, accent, max(1, width // 4), length * 90 // 100)
        elif style == "skeleton":
            # A face-colored channel cuts through a bright outlined framework.
            for which, length, width in (
                ("hour", hour_length, hour_w + 1),
                ("minute", minute_length, minute_w + 1),
            ):
                add(which, accent, width + 5, length)
                add(which, face, width, length * 91 // 100)
                add(which, hands, max(1, width // 3), length)
        elif style == "breguet":
            # Fine heat-blued tips over a shorter, broader traditional body.
            for which, length, width in (
                ("hour", hour_length, hour_w),
                ("minute", minute_length, minute_w),
            ):
                add(which, 0x101820, width + 3, length + 1)
                add(which, hands, width, length)
                add(which, self.skin["face_grad"], max(1, width // 3), length * 68 // 100)
        elif style == "leaf":
            # Layered short and long strokes produce a soft leaf-like silhouette.
            for which, length, width in (
                ("hour", hour_length, hour_w),
                ("minute", minute_length, minute_w),
            ):
                add(which, 0x080509, width + 4, length + 1)
                add(which, hands, width + 2, length * 76 // 100)
                add(which, hands, max(1, width // 2), length)
        else:  # geometric baton
            for which, length, width in (
                ("hour", hour_length, hour_w + 2),
                ("minute", minute_length, minute_w + 1),
            ):
                add(which, 0x05080A, width + 4, length + 2)
                add(which, hands, width, length)

        if style in ("diver", "sword", "skeleton", "baton"):
            add("second", 0x050505, second_w + 2, second_length + 1)
        add("second", second, second_w, second_length)

    def _make_hub(self, dial):
        self.hub = lv.obj(self.face)
        hub_size = max(10, dial // 17)
        self.hub.set_size(hub_size, hub_size)
        self.hub.center()
        self.hub.set_style_radius(_CIRCLE, 0)
        self.hub.set_style_bg_color(_color(self.skin["bezel_hi"]), 0)
        self.hub.set_style_bg_grad_color(_color(self.skin["bezel_lo"]), 0)
        self.hub.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.hub.set_style_bg_opa(lv.OPA.COVER, 0)
        self.hub.set_style_border_color(_color(self.skin["accent"]), 0)
        self.hub.set_style_border_width(max(1, hub_size // 8), 0)
        self.hub.set_style_pad_all(0, 0)
        try:
            self.hub.remove_flag(lv.obj.FLAG.CLICKABLE)
            self.hub.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass

    def _tick(self, _timer):
        self.update_time()

    def _clock_clicked(self, _event):
        self._open_picker()

    def set_hidden(self, hidden):
        flag = lv.obj.FLAG.HIDDEN
        for obj in (self.shadow, self.bezel, self.hitbox):
            if hidden:
                obj.add_flag(flag)
            else:
                obj.remove_flag(flag)

    def update_time(self):
        hour, minute, second = _local_clock_time()
        second_value = second * 12
        minute_value = minute * 12 + second // 5
        hour_value = (hour % 12) * 60 + minute
        for which, value in (
            ("hour", hour_value),
            ("minute", minute_value),
            ("second", second_value),
        ):
            for hand, length in self.hand_layers[which]:
                self.scale.set_line_needle_value(hand, length, value)


class ClockSkinPicker:
    """Full-screen LVGL skin selector, normally hidden above the clock."""

    def __init__(self, parent, skins, names, select_callback):
        self.skins = skins
        self.names = names
        self.select_callback = select_callback
        self.buttons = {}
        width = int(getattr(display_drv, "width", 320) or 320)
        height = int(getattr(display_drv, "height", 480) or 480)
        short = min(width, height)
        pad = max(8, short // 24)
        title_h = max(34, short // 7)
        gap = max(5, short // 42)

        self.panel = lv.obj(parent)
        self.panel.set_size(width, height)
        self.panel.set_pos(0, 0)
        self.panel.set_style_radius(0, 0)
        self.panel.set_style_bg_color(_color(0x050608), 0)
        self.panel.set_style_bg_grad_color(_color(0x171A20), 0)
        self.panel.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
        self.panel.set_style_bg_opa(lv.OPA.COVER, 0)
        self.panel.set_style_border_width(0, 0)
        self.panel.set_style_pad_all(0, 0)
        try:
            self.panel.remove_flag(lv.obj.FLAG.SCROLLABLE)
        except AttributeError:
            pass

        title = lv.label(self.panel)
        title.set_text("Choose a skin")
        title.set_style_text_color(_color(0xF3E6C5), 0)
        _set_scaled_font(title, max(18, short // 14))
        title.align(lv.ALIGN.TOP_MID, 0, max(6, pad // 2))

        self.list = lv.obj(self.panel)
        self.list.set_size(width - 2 * pad, height - title_h - pad)
        self.list.align(lv.ALIGN.BOTTOM_MID, 0, -pad)
        self.list.set_style_radius(max(8, short // 28), 0)
        self.list.set_style_bg_color(_color(0x0A0C10), 0)
        self.list.set_style_bg_opa(220, 0)
        self.list.set_style_border_color(_color(0x3A3E47), 0)
        self.list.set_style_border_width(1, 0)
        self.list.set_style_pad_all(gap, 0)
        self.list.set_style_pad_row(gap, 0)
        self.list.set_style_pad_column(gap, 0)
        self.list.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.list.set_flex_align(
            lv.FLEX_ALIGN.START,
            lv.FLEX_ALIGN.CENTER,
            lv.FLEX_ALIGN.START,
        )

        button_h = max(44, short // 5)
        label_size = max(15, min(30, short // 15))
        for number, name in enumerate(names, 1):
            skin = skins[name]
            button = lv.button(self.list)
            button.set_size(lv.pct(100), button_h)
            button.set_style_radius(max(6, button_h // 5), 0)
            button.set_style_bg_color(_color(skin["face"]), 0)
            button.set_style_bg_grad_color(_color(skin["face_grad"]), 0)
            button.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)
            button.set_style_border_color(_color(skin["bezel_hi"]), 0)
            button.set_style_border_width(max(1, short // 120), 0)
            button.set_style_shadow_color(_color(skin["accent"]), 0)
            button.set_style_shadow_width(max(2, short // 80), 0)
            button.set_style_shadow_opa(80, 0)

            label = lv.label(button)
            label.set_text("%d. %s" % (number, name))
            label.set_style_text_color(_color(skin["marks"]), 0)
            _set_scaled_font(label, label_size)
            label.center()

            def _make_callback(skin_name):
                def _selected(_event):
                    self.select_callback(skin_name)

                return _selected

            button.add_event_cb(_make_callback(name), lv.EVENT.CLICKED, None)
            self.buttons[name] = button

        self.hide()

    def show(self, selected):
        for name, button in self.buttons.items():
            skin = self.skins[name]
            button.set_style_border_color(_color(skin["accent"]), 0)
            button.set_style_border_width(3 if name == selected else 1, 0)
        self.panel.remove_flag(lv.obj.FLAG.HIDDEN)
        self.panel.move_foreground()

    def hide(self):
        self.panel.add_flag(lv.obj.FLAG.HIDDEN)


class ClockDeck:
    """Own the picker and lazily cache clock objects for instant skin changes."""

    def __init__(self, parent, default_skin=DEFAULT_SKIN):
        self.parent = parent
        self.clocks = {}
        self.current = None
        self.picker = ClockSkinPicker(
            parent,
            AnalogClock.skins,
            AnalogClock.skin_names(),
            self.select,
        )
        self.select(default_skin)

    def open_picker(self):
        self.picker.show(self.current._skin_name)

    def select(self, skin_name):
        if skin_name not in AnalogClock.skins:
            raise KeyError("unknown clock skin: " + str(skin_name))
        if self.current is not None:
            self.current.set_hidden(True)
        clock = self.clocks.get(skin_name)
        if clock is None:
            clock = AnalogClock(self.parent, skin_name, self.open_picker)
            self.clocks[skin_name] = clock
        self.current = clock
        clock.set_hidden(False)
        for obj in (clock.shadow, clock.bezel, clock.hitbox):
            obj.move_foreground()
        self.picker.hide()


for _skin_name in BUILTIN_SKIN_ORDER:
    AnalogClock.register_skin(_skin_name, BUILTIN_SKINS[_skin_name])
_clock = None


def main():
    global _clock
    event_loop = getattr(display_driver, "event_loop", None)
    current = event_loop.current_instance() if event_loop is not None else None
    if current is not None:
        current.disable()
    try:
        screen = lv.screen_active()
        _clock = ClockDeck(screen, DEFAULT_SKIN)
        # Keep the widget reachable on interpreters whose Python GC does not trace
        # every reference held by the LVGL C object graph.
    finally:
        if current is not None:
            current.enable()


main()
