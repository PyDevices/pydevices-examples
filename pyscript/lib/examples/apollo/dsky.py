# gallery: binaries
"""
Apollo Guidance Computer DSKY Emulator

Image source:  https://commons.wikimedia.org/wiki/File:Apollo_DSKY_interface.svg
"""

from board_config import display_drv
import board_config
import appdev

# apollo.py already built the App; a second instance would steal App.current().
app = appdev.App.current() or appdev.App(board_config)
from appdev import TouchGrid
from pygraphics import Area, BMP565

try:
    from os import sep
except ImportError:  # PyScipt doesn't have os.sep
    sep = "/"

########### Load the BMP file
# get the path this module is in
_source_dir = __file__.split(sep)[0:-1]
_source_dir = sep.join(_source_dir) + sep
_bmp = BMP565(f"{_source_dir}Apollo_DSKY_interface.bmp", streamed=True)

########### Define the screen layout
width = 320
height = 372

_led_area = Area(184, 19, 106, 190)
_acty_area = Area(186, 24, 34, 28)

# The light area starts at (26, 19) and is 7 lights tall and 2 lights wide
# Each light is 54x27 pixels
_light_areas = [Area(26 + 54 * i, 19 + 27 * j, 54, 27) for i in range(2) for j in range(7)]

########### Define the character areas
# The charactar area starts at (0, 380) and is 40 characters wide by 1 character tall
# Each full character is 14x24 pixels and each half character is 7x24 pixels
# Half character areas
_hca = [Area(0 + i * 7, 380, 7, 24) for i in range(8)]
# Full character areas
_fca = [Area(0 + i * 14, 380, 14, 24) for i in range(4, 34)]
_char_areas = {
    "<": _hca[0],
    "!": _hca[1],
    "+": _hca[2],
    "-": _hca[3],
    ":": _hca[4],
    ";": _hca[5],
    ".": _hca[6],
    ",": _hca[7],
    ">": _fca[0],
    " ": _fca[1],
    "0": _fca[2],
    "1": _fca[3],
    "2": _fca[4],
    "3": _fca[5],
    "4": _fca[6],
    "5": _fca[7],
    "6": _fca[8],
    "7": _fca[9],
    "8": _fca[10],
    "9": _fca[11],
    "A": _fca[12],
    "B": _fca[12],
    "C": _fca[14],
    "D": _fca[15],
    "E": _fca[16],
    "F": _fca[17],
    "G": _fca[18],
    "H": _fca[19],
    "I": _fca[20],
    "J": _fca[21],
    "L": _fca[22],
    "N": _fca[23],
    "P": _fca[24],
    "Q": _fca[25],
    "R": _fca[26],
    "T": _fca[27],
    "U": _fca[28],
    "Y": _fca[29],
    "O": _fca[2],
    "S": _fca[7],
}

############ Define the locations where text will be written
prog_pos = (257, 32)
verb_pos = (190, 77)
noun_pos = (257, 77)
data1_pos = (187, 116)
data2_pos = (187, 150)
data3_pos = (187, 184)

########### Define the keypad
# The keypad area starts at (2, 233) and is 7 keys wide and 3 keys tall
# The keys are 45x45 pixels
keypad = TouchGrid(
    app, 2, 233, 7 * 45, 3 * 45, cols=7, rows=3, translate=display_drv.translate_point
)

########### Define the states of the screen elements
acty_status = False
light_status = [False] * len(_light_areas)


########### Define the screen functions
def init_screen():
    display_drv.blit_rect(_bmp(0, 0, width, height), 0, 0, width, height)
    display_drv.blit_rect(_bmp(*_led_area.shift(width)), *_led_area)
    set_acty(False)


def write_char(char, pos):
    char_area = _char_areas[char]
    display_drv.blit_rect(_bmp(*char_area), pos[0], pos[1], char_area.w, char_area.h)


def write_string(string, pos):
    x, y = pos
    for char in string:
        write_char(char, (x, y))
        x += _char_areas[char].w


def set_area(area, status):
    offset = width if status else 0
    display_drv.blit_rect(_bmp(*area.shift(offset)), *area)


def set_light(light, status=None):
    light_status[light] = status if status is not None else not light_status[light]
    set_area(_light_areas[light], light_status[light])


def set_acty(status=None):
    global acty_status
    acty_status = status if status is not None else not acty_status
    set_area(_acty_area, acty_status)


def set_button(button, status=False):
    set_area(keypad.areas[button], status)