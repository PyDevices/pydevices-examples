"""
A simple paint application demonstrating the use of displaydev.
"""

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)

colors = [0xFFFF, 0xF800, 0x07E0, 0x001F, 0x07FF, 0xF81F, 0xFFE0, 0x0000]

on_x_axis = display_drv.width < display_drv.height
block_size = min(display_drv.width, display_drv.height) // len(colors)
selected_pad = block_size // 10
brush_size = 5
selected = 0


def draw_block(index, color):
    x, y = (index * block_size, 0) if on_x_axis else (0, index * block_size)
    if index == selected:
        display_drv.fill_rect(x, y, block_size, block_size, 0x8410)
        display_drv.fill_rect(
            x + selected_pad,
            y + selected_pad,
            block_size - 2 * selected_pad,
            block_size - 2 * selected_pad,
            color,
        )
    else:
        display_drv.fill_rect(x, y, block_size, block_size, color)


def paint(x, y, color):
    display_drv.fill_rect(
        x - brush_size // 2, y - brush_size // 2, brush_size, brush_size, color
    )


for i, color in enumerate(colors):
    draw_block(i, color)

display_drv.show()
print("Application loaded.  Select a color and PAINT!")


def _on_button(e):
    global selected
    x, y = e.pos
    last_selected = selected
    if on_x_axis and y < block_size or not on_x_axis and x < block_size:
        if on_x_axis:
            selected = x // block_size
        else:
            selected = y // block_size
        if selected != last_selected:
            draw_block(last_selected, colors[last_selected])
            draw_block(selected, colors[selected])
        if e.button == 3:
            if on_x_axis:
                display_drv.fill_rect(
                    0,
                    block_size,
                    display_drv.width,
                    display_drv.height - block_size,
                    colors[selected],
                )
            else:
                display_drv.fill_rect(
                    block_size,
                    0,
                    display_drv.width - block_size,
                    display_drv.height,
                    colors[selected],
                )
        display_drv.show()
    elif e.button == 1:
        paint(x, y, colors[selected])
        display_drv.show()


def _on_motion(e):
    if e.buttons[0] != 1:
        return
    x, y = e.pos
    if (on_x_axis and y > block_size) or (not on_x_axis and x > block_size):
        paint(x, y, colors[selected])
        display_drv.show()


app.on(app.events.MOUSEBUTTONDOWN, _on_button)
app.on(app.events.MOUSEMOTION, _on_motion)