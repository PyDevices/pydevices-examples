# deps: palettes
# utils: tft_config, tft_text
"""
color_test.py
=============

.. figure:: ../_static/color_test.jpg
    :align: center

    Test color with gradients.

Draws Red, Green and Blues gradients on the display and writes the color name centered in the
gradient.  Then repeatedly draws a borders around the display in the same colors.

.. note:: This example requires the following modules:

  .. hlist::
    :columns: 3

    - `st7789py`
    - `tft_config`
    - `vga2_bold_16x32`

"""

import board_config
import appdev

app = appdev.App(board_config)

import tft_config
import tft_text
import vga2_bold_16x32 as font

palette = tft_config.palette


def interpolate(value1, value2, position, total_range):
    """
    Perform linear interpolation between two values based on a position within a range.

    Args:
        value1 (float): Starting value.
        value2 (float): Ending value.
        position (float): Current position within the range.
        total_range (float): Total range of positions.

    Returns:
        (float): Interpolated value.
    """
    return value1 + (value2 - value1) * position / total_range


def main():
    tft = tft_config.config(tft_config.WIDE)

    names = ["Red", "Green", "Blue"]

    color_values = (255, 255, 255)
    height_division = tft.height // len(color_values)
    for i, color_value in enumerate(color_values):
        start_row = i * height_division
        end_row = (i + 1) * height_division
        for row in range(start_row, end_row):
            rgb_color = [
                (
                    0
                    if idx != i
                    else int(interpolate(0, color_value, row - start_row, height_division))
                )
                for idx in range(3)
            ]
            color = palette.color565(rgb_color)
            tft.draw.hline(0, row, tft.width, color)

        name = names[i]
        text_x = (tft.width - font.WIDTH * len(name)) // 2
        text_y = start_row + (end_row - start_row - font.HEIGHT) // 2
        tft_text.text(tft, font, name, text_x, text_y, palette.WHITE, color)

    tft.show()

    border_colors = [palette.RED, palette.GREEN, palette.BLUE]
    st = {"ci": 0}

    def poll():
        color = border_colors[st["ci"]]
        for x in range(tft.width):
            tft.draw.pixel(x, 0, color)
            tft.draw.pixel(x, tft.height - 1, color)
        for y in range(tft.height):
            tft.draw.pixel(0, y, color)
            tft.draw.pixel(tft.width - 1, y, color)
        tft.show()
        st["ci"] = (st["ci"] + 1) % len(border_colors)
        return False

    # The app keeps itself alive after main() returns; on PyScript and Jupyter
    # (app.timer_async) the host's own loop drives it, so the browser main
    # thread stays live.
    def _tick(_=None):
        poll()

    app.every(_tick, period=1000, async_=app.timer_async)
main()