"""
A simple test of an encoder in appdev.
"""

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)

color_byte = 1
bg_color = 0xFF00
w = display_drv.width
h = display_drv.height
thickness = 10
y_pos = h // 2
x_pos = w // 2
factor = -1  # change the sign to invert the direction


def draw_line():
    color = color_byte << 8 | color_byte
    display_drv.fill_rect(0, 0, x_pos, thickness, color)
    display_drv.fill_rect(x_pos, 0, w - x_pos, thickness, bg_color)
    display_drv.show()


display_drv.vscsad(y_pos)
draw_line()


_EPSILON = 1e-3  # rejects float32-reinterpreted-int garbage on some usdl2 builds
_accum_x = 0.0
_accum_y = 0.0


def _wheel_axes(e):
    """Resolve one wheel event to (x, y), deciding once per event — not
    per axis — which field pair to trust. Which pair carries real data is
    a per-usdl2-build fact, not a general rule: the desktop MicroPython
    build mislabels vertical motion onto the legacy integer x field while
    precise_y is correct at the *same time*, so trusting whichever field
    is nonzero independently per axis double-counts that one motion as
    two. Some builds also garble precise_x/y into denormals near 1e-45 (a
    small int's bit pattern misread as a float) when there's no real
    precise data at all — the epsilon guard rejects that. So: if this
    event has any real precise data, take both axes from precise and
    ignore legacy entirely; otherwise take both from legacy.
    """
    px, py = e.precise_x, e.precise_y
    if -_EPSILON < px < _EPSILON:
        px = 0.0
    if -_EPSILON < py < _EPSILON:
        py = 0.0
    return (px, py) if (px or py) else (e.x, e.y)


def _whole_steps(accum, raw):
    """Accumulate a fractional delta and extract whole steps from it, so a
    slow swipe (many sub-1.0 deltas) still crosses a whole step eventually
    instead of being rounded away every time."""
    accum += raw
    steps = int(accum)  # truncate toward zero, keep the remainder
    return steps, accum - steps


def _on_wheel(e):
    global y_pos, x_pos, _accum_x, _accum_y
    raw_x, raw_y = _wheel_axes(e)
    steps, _accum_y = _whole_steps(_accum_y, raw_y)
    if steps != 0:
        direction = factor if steps > 0 else -factor
        delta = steps * steps * direction  # Quadratic acceleration
        y_pos = (y_pos + delta) % h
        display_drv.vscsad(y_pos)
        display_drv.show()
    steps, _accum_x = _whole_steps(_accum_x, raw_x)
    if steps != 0:
        direction = factor if steps > 0 else -factor
        delta = steps * steps * direction
        x_pos = (x_pos + delta) % w
        draw_line()


def _on_button(e):
    global color_byte, bg_color
    if e.button == 2:
        color_byte = color_byte << 1 & 0xFF
        if color_byte == 0:
            color_byte = 1
        draw_line()
    elif e.button == 3:
        bg_color = ~bg_color
        draw_line()


app.on(app.events.MOUSEWHEEL, _on_wheel)
app.on(app.events.MOUSEBUTTONDOWN, _on_button)