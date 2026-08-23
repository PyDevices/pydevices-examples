# gallery: binaries
# deps: pygraphics
# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
This script gathers font files from a specified directory and displays them on a display driver.
It uses the Font class to load and render the fonts.
The font files should have a naming convention of "fontname_WxH.bin", where W is the width and H is the height of the font.
The script iterates through the font files, creates a framebuffer, and renders the font on it.
The rendered font is then displayed on the display driver.
"""

from board_config import display_drv
from pygraphics import Font, FrameBuffer, RGB565
import os


EXPORT = False  # Set to True to export the font to a .py file

display_drv.fill(0)
y_pos = 0


def main():
    global y_pos

    # Specify the directory containing the .bin files
    directory = "examples/assets/"

    def gather_font_files(directory):
        font_files = []
        for file in os.listdir(directory):
            if file.endswith(".bin"):
                file_path = "/".join([directory, file])
                font_files.append(file_path)
        return font_files

    font_files = gather_font_files(directory)

    bg_color = 0
    fg_color = 0x07E0
    scale = 1

    for font_file in font_files:
        try:
            font = Font(font_file)
        except RuntimeError as e:
            print(e)
            continue

        if EXPORT:
            font.export(font.font_data.replace(".bin", ".py"))

        height = font.height
        font_name = font.font_name

        buffer = bytearray(display_drv.width * height * 2)
        fb = FrameBuffer(buffer, display_drv.width, height, RGB565)
        fb.fill(bg_color)
        string = "".join([chr(i) for i in range(65, 91)]) + ": " + font_name.split("/")[-1]
        font.text(fb, string, 0, 0, fg_color, scale)
        display_drv.blit_rect(buffer, 0, y_pos % display_drv.height, display_drv.width, height)
        y_pos += height
        if y_pos > display_drv.height:
            display_drv.vscsad((y_pos - display_drv.height) % display_drv.height)
        display_drv.show()


main()