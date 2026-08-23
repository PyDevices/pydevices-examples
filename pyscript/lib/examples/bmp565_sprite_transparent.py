# deps: pygraphics
# utils: color_setup
# gallery: binaries
from collections import namedtuple

try:
    from random import choice
except ImportError:

    def choice(seq):
        return seq[0]


import board_config
import appdev

app = appdev.App(board_config)
from color_setup import ssd as canvas
from pygraphics import BMP565

image = BMP565("examples/assets/warrior.bmp", streamed=True)
print(f"\n{image.width=}, {image.height=}, {image.bpp=}")
sprite_height = image.height // 4
sprite_width = image.width // 3
transparent = image[0]
bg = -1
print(f"{sprite_width=}, {sprite_height=} {bg=:#0x}\n")

back, right, fwd, left = [x * sprite_height for x in range(4)]
directions = [fwd, left, right, back]
a, b, c = [x * sprite_width for x in range(3)]
positions = [a, b, c, b]
pos_per_step = len(positions)
print("Sprite coordinates:")
for col in [fwd, left, right, back]:
    print(f"{(a, col)} {(b, col)} {(c, col)} {(b, col)}")


def draw_sprite(
    dest_x,
    dest_y,
    source_x,
    source_y,
    source_image=image,
    width=sprite_width,
    height=sprite_height,
):
    return canvas.blit_transparent(
        source_image[source_x : source_x + width, source_y : source_y + height],
        dest_x,
        dest_y,
        width,
        height,
        transparent,
    )


canvas.fill(bg)
canvas.show()

point = namedtuple("point", "x y")
step = 3
st = {
    "location": point(0, 0),
    "dir": choice(directions),
    "pos_i": 0,
}

canvas.show(draw_sprite(*st["location"], a, fwd))


def _tick(_=None):
    if app.quit_requested if app else False:
        return
    location = st["location"]
    direction = st["dir"]
    if st["pos_i"] == 0 and choice((True, False, False, False, False)):
        direction = choice(directions)
        st["dir"] = direction
    if direction == fwd and location.y + sprite_height > canvas.height - step * pos_per_step:
        return
    if direction == back and location.y < step * pos_per_step:
        return
    if direction == left and location.x < step * pos_per_step:
        return
    if direction == right and location.x + sprite_width > canvas.width - step * pos_per_step:
        return

    pos = positions[st["pos_i"]]
    dirty = canvas.fill_rect(location.x, location.y, sprite_width, sprite_height, bg)
    if direction == fwd:
        location = point(location.x, location.y + step)
    elif direction == back:
        location = point(location.x, location.y - step)
    elif direction == left:
        location = point(location.x - step, location.y)
    elif direction == right:
        location = point(location.x + step, location.y)
    st["location"] = location
    dirty += draw_sprite(*location, pos, direction)
    canvas.show(dirty)
    st["pos_i"] = (st["pos_i"] + 1) % len(positions)


app.every(_tick, period=100, async_=app.timer_async)