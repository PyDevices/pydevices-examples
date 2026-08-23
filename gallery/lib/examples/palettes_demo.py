# deps: palettes, pygraphics
"""
palettes_demo.py — Palette walk cycling wheel → cube → material (no env vars).
"""
from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from pygraphics import FrameBuffer, RGB565
from palettes import get_palette

if display_drv.requires_byteswap:
    needs_swap = display_drv.disable_auto_byteswap(True)
else:
    needs_swap = False

display_drv.rotation = 0

MODES = ("wheel", "cube", "material")
# Brief hold after a static material draw before advancing.
MATERIAL_HOLD_TICKS = 60


def _setup():
    st = {
        "mode_idx": 0,
        "mode": None,
        # wheel
        "wheel_colors": None,
        "wheel_ci": 0,
        "wheel_i": 0,
        "wheel_lh": 2,
        # cube
        "cube_palette": None,
        "cube_entries": None,
        "cube_fb": None,
        "cube_ba": None,
        "cube_idx": 0,
        "cube_y": 0,
        "cube_scroll": 0,
        "cube_lh": 20,
        "cube_last": 0,
        # material
        "mat_hold": 0,
        "mat_drawn": False,
    }

    def enter_mode(mode):
        st["mode"] = mode
        display_drv.vscsad(0)
        display_drv.fill(0)
        display_drv.show()
        if mode == "wheel":
            palette = get_palette(name="wheel", swapped=needs_swap, length=256, saturation=1.0)
            st["wheel_colors"] = list(palette)
            st["wheel_ci"] = 0
            st["wheel_i"] = 0
        elif mode == "cube":
            palette = get_palette(name="cube", size=5, color_depth=16, swapped=needs_swap)
            lh = st["cube_lh"]
            bpp = display_drv.color_depth // 8
            ba = bytearray(display_drv.width * lh * bpp)
            st["cube_palette"] = palette
            st["cube_entries"] = list(enumerate(palette))
            st["cube_ba"] = ba
            st["cube_fb"] = FrameBuffer(ba, display_drv.width, lh, RGB565)
            st["cube_idx"] = 0
            st["cube_y"] = 0
            st["cube_scroll"] = 0
            st["cube_last"] = display_drv.height - lh
        else:
            st["mat_drawn"] = False
            st["mat_hold"] = 0

    def advance():
        st["mode_idx"] = (st["mode_idx"] + 1) % len(MODES)
        enter_mode(MODES[st["mode_idx"]])

    def poll_wheel():
        colors = st["wheel_colors"]
        n = len(colors)
        lh = st["wheel_lh"]
        if st["wheel_i"] >= display_drv.height:
            # One full screen painted — advance mode.
            advance()
            return
        display_drv.fill_rect(
            0,
            st["wheel_i"] % display_drv.height,
            display_drv.width,
            lh,
            colors[st["wheel_ci"]],
        )
        display_drv.show()
        st["wheel_i"] += lh
        st["wheel_ci"] = (st["wheel_ci"] + 1) % n

    def poll_cube():
        entries = st["cube_entries"]
        n = len(entries)
        palette = st["cube_palette"]
        lh = st["cube_lh"]
        index, color = entries[st["cube_idx"]]
        if st["cube_y"] - st["cube_scroll"] - st["cube_last"] > 0:
            st["cube_scroll"] = (st["cube_y"] - st["cube_last"]) % display_drv.height
            display_drv.vscsad(st["cube_scroll"])
        name = f"{index} - {palette.color_name(index)}"
        text_color = palette.WHITE if palette.brightness(index) < 0.4 else palette.BLACK  # noqa: PLR2004
        st["cube_fb"].fill(color)
        st["cube_fb"].text16(name, 2, 2, text_color)
        display_drv.blit_rect(
            st["cube_ba"], 0, st["cube_y"] % display_drv.height, display_drv.width, lh
        )
        display_drv.show()
        st["cube_y"] += lh
        st["cube_idx"] = (st["cube_idx"] + 1) % n
        # One full walk of the cube palette (and enough rows to fill a screen).
        if st["cube_idx"] == 0 and st["cube_y"] >= display_drv.height:
            advance()

    def poll_material():
        if not st["mat_drawn"]:
            palette = get_palette(name="material_design", color_depth=16, swapped=needs_swap)
            for i, color in enumerate(palette):
                display_drv.fill_rect(0, i, display_drv.width, 1, color)
            display_drv.show()
            st["mat_drawn"] = True
            st["mat_hold"] = 0
            return
        st["mat_hold"] += 1
        if st["mat_hold"] >= MATERIAL_HOLD_TICKS:
            advance()

    def poll():
        mode = st["mode"]
        if mode == "wheel":
            poll_wheel()
        elif mode == "cube":
            poll_cube()
        else:
            poll_material()
        return False

    enter_mode(MODES[0])
    return poll


poll = _setup()


def _tick(_=None):
    poll()


app.every(_tick, period=1, async_=app.timer_async)