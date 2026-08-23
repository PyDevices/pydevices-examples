# deps: lvgl
"""Minimal LVGL interactive test: tap button + animated spinning arc.

Demonstrates self-driving background timers without a main application loop:

* **Interactive REPL (`python -i`, `micropython -i`, or MCU prompt)**:
  The script drops out the bottom to the `>>>` prompt. On interpreters with
  hardware interrupts or signal-based timers (`machine.Timer` on MicroPython,
  `librt` on Linux, `uwin32` on Windows), animations and button tap inputs
  continue running live in the background while the REPL remains fully usable.

* **Desktop Non-Interactive (`python lv_interactive_test.py`)**:
  Because there is no keep-alive loop, the script exits immediately to the
  OS upon reaching EOF, closing the window and appearing as though it crashed.

* **MicroPython on-device (`machine.Timer`)**:
  Continues to run and update correctly after the script completes because
  hardware timer interrupts keep firing in the background.

* **CircuitPython, PyScript, and Jupyter**:
  Because these environments lack hardware interrupt/signal timers and rely on
  cooperative/pumped timers, the display will never update without an active
  event loop, and the app will appear hung.
"""

import display_driver  # noqa: F401 - initializes display, input, and timer

import lvgl as lv


_taps = 0
_angle = 0

scr = lv.screen_active()

# 1. Tap Button
btn = lv.button(scr)
btn.set_size(140, 50)
btn.align(lv.ALIGN.CENTER, 0, 40)
btn_lbl = lv.label(btn)
btn_lbl.set_text("Tap me (0)")
btn_lbl.center()

def on_click(_e):
    global _taps
    _taps += 1
    btn_lbl.set_text(f"Tap me ({_taps})")

btn.add_event_cb(on_click, lv.EVENT.CLICKED, None)

# 2. Spinning Arc (driven by LVGL timer)
arc = lv.arc(scr)
arc.set_size(80, 80)
arc.align(lv.ALIGN.CENTER, 0, -40)
arc.set_bg_angles(0, 360)
arc.set_angles(0, 0)
arc.remove_style(None, lv.PART.KNOB)
arc.remove_flag(lv.obj.FLAG.CLICKABLE)

def on_arc_timer(_t):
    global _angle
    _angle = (_angle + 10) % 360
    arc.set_angles(0, _angle)

lv.timer_create(on_arc_timer, 50, None)

print("UI initialized. Dropping out bottom to REPL...")
