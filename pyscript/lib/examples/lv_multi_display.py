# deps: lvgl
# utils: lv_encoder_emu
"""
Multi-display LVGL demo: primary UI + secondary encoder emulator.

Same-backend second window/canvas (SDL / PG / PS / JN). The emulator is a
reusable :class:`lv_encoder_emu.EncoderEmu` stand-in for hardware
``machine.Encoder`` / ``rotaryio`` on MCU boards.
"""

import display_driver  # noqa: F401 — primary LVGL + event loop
import lvgl as lv
from display_driver import app
from lv_encoder_emu import EncoderEmu

# Soft encoder emulator on a secondary surface; EncoderDevice drives primary LVGL.
emu = EncoderEmu(app, title="Encoder")

# Primary: focusable widgets navigated by the encoder indev.
scr = (
    display_driver._drivers[0].lv_display.get_screen_active()
    if getattr(display_driver, "_drivers", None)
    else lv.screen_active()
)
group = lv.group_get_default()

status = lv.label(scr)
status.set_text("Last: —")
status.align(lv.ALIGN.BOTTOM_MID, 0, -8)


def _on_pushed(e, name):
    status.set_text(f"Last: {name}")


for i, label in enumerate(("Alpha", "Beta", "Gamma", "Delta")):
    btn = lv.button(scr)
    btn.set_size(lv.pct(40), 40)
    btn.align(lv.ALIGN.TOP_MID, 0, 20 + i * 50)
    lab = lv.label(btn)
    lab.set_text(label)
    lab.center()
    group.add_obj(btn)
    btn.add_event_cb(
        lambda e, n=label: _on_pushed(e, n), lv.EVENT.CLICKED, None
    )

# group.add_obj focuses the first widget but only keypad/encoder navigation sets
# FOCUS_KEY (the theme's focus ring). Match that for the initial selection.
focused = group.get_focused()
if focused is not None:
    focused.add_state(lv.STATE.FOCUS_KEY)
