"""The laptop's mouse and keyboard, arriving over the cast's back channel, as a
pydevices input device: a cursor the board integrates from the relative mouse
reports, clicks as touches at the cursor, and HID keyboard reports as the set
of pressed K_* codes. Merged into a board's ``touch_read`` and ``keypad_read``
so an app cannot tell them from the panel's own touch and keys.
"""
import keys

_HID_CHARS = {0x28: 13, 0x29: 27, 0x2A: 8, 0x2B: 9, 0x2C: 32, 0x2D: 45, 0x2E: 61, 0x2F: 91, 0x30: 93,
              0x31: 92, 0x33: 59, 0x34: 39, 0x35: 96, 0x36: 44, 0x37: 46, 0x38: 47}


def hid_keycode(usage):
    """keys.hid_keycode where the board's keys module has it; the same table otherwise."""
    f = getattr(keys, "hid_keycode", None)
    if f:
        return f(usage)
    if 0x04 <= usage <= 0x1D:
        return 97 + usage - 0x04
    if 0x1E <= usage <= 0x26:
        return 49 + usage - 0x1E
    if usage == 0x27:
        return 48
    if usage in _HID_CHARS:
        return _HID_CHARS[usage]
    if usage >= 0x39:
        return usage | 0x40000000
    return None


class UibcInput:
    def __init__(self, width, height, local_touch=None, local_keys=None):
        self.w = width
        self.h = height
        self.cx = width // 2
        self.cy = height // 2
        self.buttons = 0
        self.keys = set()
        self.local_touch = local_touch
        self.local_keys = local_keys
        self.reports = 0
        self.moved = 0

    def feed(self, kind, data):
        """One decoded UIBC report from micecast.Session's on_input."""
        if kind == "hid_mouse" and len(data) >= 4:
            # report ID 0x28: buttons, dx, dy, wheel, pan; the deltas are signed bytes
            dx = data[2] - 256 if data[2] > 127 else data[2]
            dy = data[3] - 256 if data[3] > 127 else data[3]
            if dx or dy:
                self.cx = min(max(self.cx + dx, 0), self.w - 1)
                self.cy = min(max(self.cy + dy, 0), self.h - 1)
                self.moved += 1
            self.buttons = data[1]
            self.reports += 1
        elif kind == "hid_keyboard" and len(data) >= 9:
            # report ID 0x29: modifiers, reserved, six usages
            pressed = set()
            for u in data[3:9]:
                if u:
                    code = hid_keycode(u)
                    if code is not None:
                        pressed.add(code)
            for i in range(8):
                if data[1] & (1 << i):
                    pressed.add(0x400000E0 + i)   # K_LCTRL .. K_RGUI, the HID modifier usages
            self.keys = pressed
            self.reports += 1

    def read_points(self):
        """A touch_read: the panel's own touches first, else the cursor while the
        left button is held."""
        pts = self.local_touch() if self.local_touch else ()
        if pts:
            return pts
        return ((self.cx, self.cy),) if self.buttons & 1 else ()

    def read_keys(self):
        """A keypad_read: the panel's keys plus the laptop's."""
        local = set(self.local_keys() or ()) if self.local_keys else set()
        return local | self.keys

    def install(self, board_config):
        """Make the board read this device: touch_read and keypad_read now include it."""
        self.local_touch = getattr(board_config, "touch_read", None)
        self.local_keys = getattr(board_config, "keypad_read", None)
        board_config.touch_read = self.read_points
        board_config.keypad_read = self.read_keys
        return self
