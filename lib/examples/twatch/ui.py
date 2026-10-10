"""twatch.ui -- the few widgets the T-Watch apps build their screens from."""

import lvgl as lv

from . import services as sv


def screen(scope, title=None, center=False):
    """The app's own screen, a column, with *title* at the top. Deleted, with
    everything on it, when the app closes."""
    scr = scope.screen()
    scr.set_style_bg_color(lv.color_hex(0x000000), 0)
    scr.set_style_text_font(sv.font, 0)
    scr.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    main = lv.FLEX_ALIGN.CENTER if center else lv.FLEX_ALIGN.START
    scr.set_flex_align(main, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    scr.set_style_pad_all(8, 0)
    scr.set_style_pad_row(6, 0)
    if title:
        label(scr, title, color=sv.ACCENT)
    return scr


def label(parent, text="", font=None, color=None):
    lbl = lv.label(parent)
    lbl.set_text(text)
    if font is not None:
        lbl.set_style_text_font(font, 0)
    if color is not None:
        lbl.set_style_text_color(color, 0)
    return lbl


def row(parent):
    r = lv.obj(parent)
    r.remove_style_all()
    r.set_size(lv.pct(100), lv.SIZE_CONTENT)
    r.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    r.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    r.set_style_pad_row(6, 0)
    return r


def button(parent, text, cb, width=None, height=None):
    """A button that calls ``cb()``, unless the tap was the one that woke
    the screen."""
    b = lv.button(parent)
    if width:
        b.set_width(width)
    if height:
        b.set_height(height)
    lbl = lv.label(b)
    lbl.set_text(text)
    lbl.center()

    def clicked(e):
        if sv.awake_for() > 300:
            cb()

    b.add_event_cb(clicked, lv.EVENT.CLICKED, None)
    return b


def missing(parent, what):
    label(parent, what, sv.small, sv.MUTED)
