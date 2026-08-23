# SPDX-License-Identifier: MIT
"""Multi-group focus navigation for left rail / center / right rail."""

import lvgl as lv


def _set_wrap(group, en=True):
    try:
        group.set_wrap(en)
    except Exception:
        pass


def _focus_first(group):
    if group is None:
        return
    try:
        n = group.get_obj_count()
    except Exception:
        n = 0
    if n <= 0:
        return
    try:
        obj = group.get_obj_by_index(0)
        if obj is not None:
            lv.group_focus_obj(obj)
            return
    except Exception:
        pass
    try:
        group.focus_next()
    except Exception:
        try:
            lv.group_focus_next(group)
        except Exception:
            pass


class FocusNav:
    """Three LVGL groups: left rail, center content, right rail.

    LEFT/RIGHT — switch active group (and point keypad indev at it)
    UP/DOWN    — previous/next within the active group
    ENTER      — activate focused control (via KEY_ENTER to the indev path)
    """

    LEFT = 0
    CENTER = 1
    RIGHT = 2

    def __init__(self):
        self.left = lv.group_create()
        self.center = lv.group_create()
        self.right = lv.group_create()
        for g in (self.left, self.center, self.right):
            _set_wrap(g, True)
        self._groups = (self.left, self.center, self.right)
        self._active = self.CENTER
        self._keypad_indev = None

        # Keep default group empty so display_driver doesn't dump everything here.
        default = lv.group_get_default()
        if default is None:
            default = self.center
            default.set_default()
        self._default = default

    def bind_keypad_indev(self, indev):
        self._keypad_indev = indev
        self._apply_indev_group()

    def active_group(self):
        return self._groups[self._active]

    def _apply_indev_group(self):
        g = self.active_group()
        if self._keypad_indev is not None:
            try:
                self._keypad_indev.set_group(g)
            except Exception:
                pass
        try:
            g.set_default()
        except Exception:
            pass

    def set_active(self, index):
        index = int(index) % 3
        if index == self._active:
            self._apply_indev_group()
            return
        prev = self.active_group()
        self._defocus_group(prev)
        self._active = index
        self._apply_indev_group()
        g = self.active_group()
        focused = None
        try:
            focused = g.get_focused()
        except Exception:
            try:
                focused = lv.group_get_focused(g)
            except Exception:
                focused = None
        if focused is None:
            _focus_first(g)
        else:
            try:
                lv.group_focus_obj(focused)
            except Exception:
                pass

    def focus_next(self):
        g = self.active_group()
        try:
            g.focus_next()
        except Exception:
            try:
                lv.group_focus_next(g)
            except Exception:
                pass

    def focus_prev(self):
        g = self.active_group()
        try:
            g.focus_prev()
        except Exception:
            try:
                lv.group_focus_prev(g)
            except Exception:
                pass

    def _defocus_group(self, group):
        focused = None
        try:
            focused = group.get_focused()
        except Exception:
            try:
                focused = lv.group_get_focused(group)
            except Exception:
                focused = None
        if focused is None:
            return
        try:
            focused.remove_state(lv.STATE.FOCUSED)
        except Exception:
            pass
        try:
            focused.remove_state(lv.STATE.FOCUS_KEY)
        except Exception:
            pass

    def handle_nav_key(self, lv_key):
        """Handle remapped lv.KEY value. Return True if consumed.

        UP/DOWN  — previous/next member in the active group
        LEFT/RIGHT — switch active group (left / center / right)
        """
        if lv_key == lv.KEY.UP:
            self.focus_prev()
            return True
        if lv_key == lv.KEY.DOWN:
            self.focus_next()
            return True
        if lv_key == lv.KEY.LEFT:
            self.set_active(self._active - 1)
            return True
        if lv_key == lv.KEY.RIGHT:
            self.set_active(self._active + 1)
            return True
        return False
