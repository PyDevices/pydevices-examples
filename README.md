![A grey box with a yellow ellipse, the word Hello and a green line, drawn in a 320 by 480 window](docs/images/hello_shapes.png)

pydevices-examples is the gallery of runnable programs for OmniPython: the same
scripts draw on MicroPython-compatible boards, CircuitPython-compatible boards,
a desktop window, a browser tab and an Android phone.

## Install

On a desktop:

```bash
git clone --depth 1 https://github.com/PyDevices/pydevices-examples.git
cd pydevices-examples
python3 -m venv .venv
.venv/bin/pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ -r requirements.txt
```

On a MicroPython-compatible board:

```python
import mip

mip.install("pydevices", index="https://PyDevices.github.io/mip")
```

## Example

Save this as `hello_shapes.py` and run `.venv/bin/python hello_shapes.py`:

```python
import board_config
import appdev
import pygraphics
from palettes import get_palette

display = board_config.display_drv
pal = get_palette()
w, h = display.width, display.height
print(f"drawing on a {w}x{h} display")

pygraphics.fill(display, pal.BLACK)
pygraphics.fill_rect(display, w // 6, h // 3, w * 2 // 3, h // 3, pal.GREY)
pygraphics.ellipse(display, w // 2, h // 2, w // 4, h // 8, pal.YELLOW, True)
pygraphics.line(display, 0, 0, w - 1, h - 1, pal.GREEN)
pygraphics.text(display, "Hello", (w - 40) // 2, h // 2 - 4, pal.BLACK)
display.show()

app = appdev.App(board_config)  # keeps the window open until you close it
```

It opens the window at the top of this page and prints:

```text
drawing on a 320x480 display
```

[Docs](https://github.com/PyDevices/pydevices-examples/blob/main/docs/index.md) · [Examples](https://pydevices.github.io/pydevices-examples/pyscript/) · [Roadmap](ROADMAP.md)

Made by [PyDevices](https://pydevices.com).
