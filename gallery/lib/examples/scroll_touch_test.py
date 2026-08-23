# deps: palettes, pygraphics
# utils: displaybuf
# Vertical scroll + touch/click. Cycles display_drv ↔ DisplayBuffer on a timer
# (no env vars). Chrome labels show which path is active (drv / dbuf).
from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from pygraphics import Draw
from palettes import get_palette
from random import getrandbits

line_height = 16
# Switch canvas backends every N ticks of the mode timer (~5s at period=100).
MODE_SWITCH_TICKS = 50

pal = get_palette()
st = {
    "use_displaybuf": False,
    "canvas": display_drv,
    "draw": Draw(display_drv),
    "ticks": 0,
}


def _present():
    st["canvas"].show()
    if st["use_displaybuf"]:
        display_drv.show()


def _label():
    return "dbuf" if st["use_displaybuf"] else "drv"


def _rebuild():
    if st["use_displaybuf"]:
        from displaybuf import DisplayBuffer

        canvas = DisplayBuffer(display_drv)
    else:
        canvas = display_drv
    st["canvas"] = canvas
    st["draw"] = Draw(canvas)
    draw = st["draw"]

    canvas.set_vscroll(16, 16)
    tag = _label()

    if canvas.tfa > 0:
        draw.fill_rect(0, 0, canvas.width, canvas.tfa, pal.RED)
        if canvas.tfa > 15:
            draw.text14(f"0 TFA {tag}", 1, 1, pal.WHITE)
            draw.round_rect(canvas.width - 44, 1, 40, 12, 4, pal.GREEN, True)
            draw.text("Up", canvas.width - 32, 4, pal.WHITE)
    if canvas.bfa > 0:
        draw.fill_rect(0, canvas.height - canvas.bfa, canvas.width, canvas.bfa, pal.BLUE)
        if canvas.bfa > 15:
            draw.text14(
                f"{canvas.height - canvas.bfa} BFA {tag}",
                1,
                canvas.height - canvas.bfa + 1,
                pal.WHITE,
            )
            draw.round_rect(
                canvas.width - 44, canvas.height - canvas.bfa + 1, 40, 12, 4, pal.GREEN, True
            )
            draw.text("Down", canvas.width - 40, canvas.height - canvas.bfa + 5, pal.WHITE)

    for i, y in enumerate(range(canvas.tfa, canvas.vsa + canvas.tfa, line_height)):
        fg, bg = pal.WHITE, pal.BLACK
        if i % 2:
            fg, bg = bg, fg
        draw.fill_rect(0, y, canvas.width, line_height, bg)
        txt = f"vssa: {y}, vscroll: {y - canvas.tfa}"
        draw.text14(txt, 1, y + 1, fg)
        draw.rect(canvas.width - 20, y + 2, 12, 12, fg)

    _present()


def _on_click(e):
    canvas = st["canvas"]
    x, y = canvas.translate_point(e.pos)
    if y < canvas.tfa:
        canvas.vscroll -= line_height
    elif y > canvas.height - canvas.bfa:
        canvas.vscroll += line_height
    else:
        y_pos = (y // line_height) * line_height
        canvas.fill_rect(
            canvas.width - 20, y_pos + 2, 12, 12, getrandbits(canvas.color_depth)
        )
    _present()


def _on_mode_tick(_=None):
    st["ticks"] += 1
    if st["ticks"] < MODE_SWITCH_TICKS:
        return
    st["ticks"] = 0
    st["use_displaybuf"] = not st["use_displaybuf"]
    _rebuild()


_rebuild()
app.on(app.events.MOUSEBUTTONDOWN, _on_click)
app.every(_on_mode_tick, period=100, async_=app.timer_async)