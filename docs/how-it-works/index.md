# How it works

pydevices-examples is the showcase and the browser gallery for the PyDevices
driver stack. It holds runnable applications and helpers. The reusable drivers
and published packages live in
[pydevices](https://github.com/PyDevices/pydevices), and these examples
demonstrate them without publishing them.

## How an example reaches a screen

```text
published pydevices product libraries and board_config
                    |
                    v
this repository's lib/examples application scripts
                    |
        +-----------+-----------+
        v                       v
desktop / board runs       .site/pyscript gallery
```

A script runs on MicroPython, CircuitPython or CPython when a board config and
the packages it imports are present. Editing `lib/` updates the gallery,
because `.site/pyscript/lib` is a symlink to that tree.

## Application ownership

Board configs describe hardware. They export neutral pieces such as
`display_drv`, `touch_read` and `host_read`; they do not create an
application-level `appdev.App`.

Non-LVGL examples opt into the optional `appdev` coordinator:

```python
import board_config
from board_config import display_drv
import appdev

app = appdev.App(board_config)
```

The app keeps itself alive past the end of the script, so no trailing
`app.run()` is needed. Call it only when you want the script to block at that
point, or need a nonzero exit code.

LVGL examples use the coordinator bundled with the LVGL binding and do not
import `appdev`:

```python
from board_config import display_drv
from display_driver import app
```

Don't mix `appdev` into an LVGL example unless its architecture needs it. This
separation keeps hardware policy out of board configs and lets an application
bring a different event loop or traffic controller when it wants one.

## Where to read next

How [casting to a TV](casting.md) works. The cross-interpreter test matrix and
the PyScript and Playwright debugging notes are in
[`tools/README.md`](https://github.com/PyDevices/pydevices-examples/blob/main/tools/README.md).

## Related repositories

- [pydevices](https://github.com/PyDevices/pydevices): the core driver package and the board configs.
- [mip](https://github.com/PyDevices/mip): the PyDevices MIP index.
- [lvgl-bindings](https://github.com/PyDevices/lvgl-bindings): the shared LVGL binding source.
  [lvgl-micropython](https://github.com/PyDevices/lvgl-micropython),
  [lvgl-circuitpython](https://github.com/PyDevices/lvgl-circuitpython) and
  [lvgl-python](https://github.com/PyDevices/lvgl-python) are the interpreter-specific distributions.
- [pygraphics](https://github.com/PyDevices/pygraphics),
  [palettes](https://github.com/PyDevices/palettes) and
  [pdwidgets](https://github.com/PyDevices/pdwidgets): drawing, colors and widgets.
- [android-runner](https://github.com/PyDevices/android-runner) is the prebuilt Runner that `android.py` stages examples onto.
  [android-template](https://github.com/PyDevices/android-template) packages an Android app.
- [pyscript-template](https://github.com/PyDevices/pyscript-template): a standalone PyScript application.
