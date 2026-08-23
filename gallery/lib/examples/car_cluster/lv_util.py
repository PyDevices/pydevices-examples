# SPDX-License-Identifier: MIT
"""Tiny LVGL helpers (flag + group API differences across bindings)."""

import lvgl as lv


def add_flag(obj, flag):
    obj.add_flag(flag)


def remove_flag(obj, flag):
    if hasattr(obj, "remove_flag"):
        obj.remove_flag(flag)
    elif hasattr(obj, "clear_flag"):
        obj.clear_flag(flag)


def hide(obj):
    add_flag(obj, lv.obj.FLAG.HIDDEN)


def show(obj):
    remove_flag(obj, lv.obj.FLAG.HIDDEN)


def hide_clickable(obj):
    remove_flag(obj, lv.obj.FLAG.CLICKABLE)


def group_add(group, obj):
    if group is None:
        return
    if hasattr(group, "add_obj"):
        group.add_obj(obj)
    elif hasattr(lv, "group_add_obj"):
        lv.group_add_obj(group, obj)
