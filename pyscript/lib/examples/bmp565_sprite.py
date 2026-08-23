# deps: pygraphics
# gallery: binaries
from collections import namedtuple

try:
    from random import choice
except ImportError:

    def choice(seq):
        return seq[0]


from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from pygraphics import BMP565

image = BMP565("examples/assets/warrior.bmp", streamed=True)
print(f"\n{image.width=}, {image.height=}, {image.bpp=}")
sprite_height = image.height // 4
sprite_width = image.width // 3
bg = image[0]
print(f"{sprite_width=}, {sprite_height=} {bg=:#0x}\n")

back, right, fwd, left = [x * sprite_height for x in range(4)]
directions = [fwd, left, right, back]
a, b, c = [x * sprite_width for x in range(3)]
positions = [a, b, c, b]
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
    display_drv.blit_rect(
        source_image[source_x : source_x + width, source_y : source_y + height],
        dest_x,
        dest_y,
        width,
        height,
    )


display_drv.fill(bg)
display_drv.show()

point = namedtuple("point", "x y")
step = 3
st = {
    "location": point(0, 0),
    "dir": choice(directions),
    "pos_i": 0,
}

draw_sprite(*st["location"], a, fwd)


def _tick(_=None):
    if app.quit_requested if app else False:
        return
    location = st["location"]
    direction = st["dir"]
    if st["pos_i"] == 0 and choice((True, False, False, False, False)):
        direction = choice(directions)
        st["dir"] = direction
    if direction == fwd and location.y + sprite_height > display_drv.height - step * 4:
        return
    if direction == back and location.y < step * 4:
        return
    if direction == left and location.x < step * 4:
        return
    if direction == right and location.x + sprite_width > display_drv.width - step * 4:
        return

    pos = positions[st["pos_i"]]
    if direction == fwd:
        display_drv.fill_rect(location.x, location.y, sprite_width, step, bg)
        location = point(location.x, location.y + step)
    elif direction == back:
        display_drv.fill_rect(
            location.x, location.y + sprite_height - step, sprite_width, step, bg
        )
        location = point(location.x, location.y - step)
    elif direction == left:
        display_drv.fill_rect(
            location.x + sprite_width - step, location.y, step, sprite_height, bg
        )
        location = point(location.x - step, location.y)
    elif direction == right:
        display_drv.fill_rect(location.x, location.y, step, sprite_height, bg)
        location = point(location.x + step, location.y)
    st["location"] = location
    draw_sprite(*location, pos, direction)
    display_drv.show()
    st["pos_i"] = (st["pos_i"] + 1) % len(positions)


app.every(_tick, period=100, async_=app.timer_async)