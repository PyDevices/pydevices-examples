# deps: pygraphics
# gallery: binaries
from collections import namedtuple

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from pygraphics import BMP565

point = namedtuple("point", "x y")

display_drv.rotation = 90

display_drv.fill(0)

image = BMP565("examples/assets/longstreet.bmp", streamed=True, mirrored=True)
print(f"\n{image.width=}, {image.height=}, {image.bpp=}")


def draw_bg(dest_x, source_y, count=1, source=image):
    # 1D row slice is ``count * source.width`` pixels; blit as a vertical
    # strip (width=count, height=source.width). Do not use display_drv.height —
    # tall panels (e.g. Android after rotation) are larger than the bitmap.
    display_drv.blit_rect(
        source[source_y : source_y + count], dest_x, 0, count, source.width
    )


char_sprites = BMP565("examples/assets/runner.bmp", streamed=True)
print(f"\n{char_sprites.width=}, {char_sprites.height=}, {char_sprites.bpp=}")
char_height = char_sprites.height // 3
char_width = char_sprites.width // 6
bg = char_sprites[0]
print(f"{char_width=}, {char_height=} {bg=:#0x}\n")

run_sprites = [point(x * char_width, 0) for x in range(6)]
shoot_sprites = [point(x * char_width, char_height) for x in range(6)]
jump_sprites = [point(x * char_width, char_height * 2) for x in range(2)]
jump_shoot_sprites = [point((x + 2) * char_width, char_height * 2) for x in range(2)]
shot_sprite = point(4 * char_width, char_height * 2)


def draw_sprite(
    dest_x, dest_y, source_x, source_y, source=char_sprites, width=char_width, height=char_height
):
    display_drv.blit_rect(
        source[source_x : source_x + width, source_y : source_y + height],
        dest_x,
        dest_y,
        width,
        height,
    )


def main():
    st = {
        "i": 0,
        "scroll": 0,
        "char_y": display_drv.height - char_height,
        "char_x": 200,
        "shot_location": 0,
        "sprites": run_sprites,
    }

    def _on_motion(event):
        if not event.buttons[0]:
            st["sprites"] = run_sprites
            return
        touched_point = event.pos
        if touched_point[1] < display_drv.height // 2:
            st["sprites"] = jump_shoot_sprites
            if not st["shot_location"]:
                st["shot_location"] = 1
        elif touched_point[0] < display_drv.width // 2:
            st["sprites"] = jump_sprites
        elif touched_point[0] > display_drv.width // 2:
            st["sprites"] = shoot_sprites
            if not st["shot_location"]:
                st["shot_location"] = 1
        else:
            st["sprites"] = run_sprites

    def _tick(_=None):
        # Auto-service handles QUIT; never poll from on_tick.
        if app.quit_requested:
            return
        i = st["i"]
        if i > display_drv.width:
            st["scroll"] = i % display_drv.width
            display_drv.vscsad(st["scroll"])
        draw_bg(i % display_drv.width, i % image.height, 1)
        st["i"] = i + 1
        if i < display_drv.width:
            display_drv.show()
            return

        draw_x = st["scroll"] + st["char_x"]
        sprite = st["sprites"][st["i"] % len(st["sprites"])]
        draw_sprite(draw_x, st["char_y"], sprite.x, sprite.y)
        if st["shot_location"]:
            draw_sprite(
                draw_x + char_width + st["shot_location"],
                st["char_y"],
                shot_sprite.x,
                shot_sprite.y,
            )
            st["shot_location"] += 8
            if st["shot_location"] > (display_drv.width - char_width) // 2:
                display_drv.fill_rect(
                    draw_x + char_width + st["shot_location"],
                    st["char_y"],
                    char_width,
                    char_height,
                    bg,
                )
                st["shot_location"] = 0
        display_drv.show()

    app.on(app.events.MOUSEMOTION, _on_motion)
    # ~20 fps once scrolling; first columns also tick so quit is always serviced.
    app.every(_tick, period=50, async_=app.timer_async)


main()