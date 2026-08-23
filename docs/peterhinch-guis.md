# Peter Hinch GUIs

Three of [Peter Hinch](https://github.com/peterhinch)'s MicroPython GUI
libraries run unchanged on PyDevices hardware, which makes them the clearest
demonstration of the stack's portability. Each is showcased on its own gallery
page: [peterhinch.html](https://PyDevices.github.io/pydevices-examples/pyscript/peterhinch.html).

| GUI | Input style | Setup module |
|---|---|---|
| [Nano-GUI](https://github.com/peterhinch/micropython-nano-gui) | Display-only, no input — for memory-constrained boards | `color_setup.py` |
| [Micro-GUI](https://github.com/peterhinch/micropython-micro-gui) | Buttons / encoder, callback-style widgets (asyncio underneath) | `hardware_setup.py` |
| [MicroPython-Touch](https://github.com/peterhinch/micropython-touch) | Touch widgets and async UI (developed from Micro-GUI) | `touch_setup.py` |

## How the integration works

This repository does **not** vendor any of the three. Importing the setup module
for the GUI you want calls
[`fetch_ph_gui`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/utils/fetch_ph_gui.py),
which `mip`-installs the upstream `gui/` tree into `lib/utils/gui/` and patches
its `pygraphics.FrameBuffer` isinstance checks. Display wiring goes through
[`displaybuf.py`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/utils/displaybuf.py),
which supplies the `ssd` framebuffer the GUIs expect.

**Only one Hinch GUI may occupy `utils/gui/` at a time.** `fetch_ph_gui` empties
the directory when you switch between them. `lib/utils/gui/` is gitignored.

**Do not install Peter Hinch's `drivers/` tree.** It targets bare-metal MCU
displays; here the display comes from your PyDevices `board_config` and
`color_setup.ssd` / `displaybuf` instead. The same goes for upstream's `touch/`
package — touch input comes from the board config and, for non-LVGL apps, the
application-owned `appdev` app.

### Shared requirements

| Component | Location | Notes |
|---|---|---|
| `board_config.py` | `pydevices/board_configs/` | Display plus neutral input capabilities |
| *setup module* | `lib/utils/` | `color_setup.py`, `hardware_setup.py`, or `touch_setup.py` — see the table above |
| `fetch_ph_gui.py` | `lib/utils/` | `mip` install into `utils/gui/` plus the FrameBuffer patches |
| `displaybuf.py` | `lib/utils/` | The `ssd` framebuffer |
| `uctypes.py` | `lib/utils/` | CircuitPython shim for the GUIs' `writer.py` |
| `gui/` | `lib/utils/gui/` | **Upstream** — installed by the fetch, not in git |

### Installing manually

Usually unnecessary — importing the setup module does it. To install ahead of
time, or on a target without `mip` at import time:

```python
import mip
mip.install("github:PyDevices/pydevices-examples/packages/<name>.json", target="./utils")
```

where `<name>` is `micropython-nano-gui`, `micropython-micro-gui`, or
`micropython-touch`.

### Examples

Each GUI has a smoke test under `lib/examples/`, and each has a browser gallery
loader that fetches the GUI through its setup module:

| GUI | Example | Gallery |
|---|---|---|
| Nano-GUI | [`nano_gui_simpletest.py`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/examples/nano_gui_simpletest.py) | [loader](https://PyDevices.github.io/pydevices-examples/pyscript/micropython.html?modules=nano_gui_simpletest) |
| Micro-GUI | [`micro_gui_simpletest.py`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/examples/micro_gui_simpletest.py) | [loader](https://PyDevices.github.io/pydevices-examples/pyscript/micropython.html?modules=micro_gui_simpletest) |
| MicroPython-Touch | [`touch_gui_simpletest.py`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/examples/touch_gui_simpletest.py) | [loader](https://PyDevices.github.io/pydevices-examples/pyscript/micropython.html?modules=touch_gui_simpletest) |

```bash
cd pydevices-examples/lib
micropython -i utils/path.py examples/nano_gui_simpletest.py
```

For the Micro-GUI and MicroPython-Touch full demos, import the setup module then
`import gui.demos.simple`.

## Per-GUI notes

### Nano-GUI

`nano_gui_simpletest.py` is the upstream
[hardware verification](https://github.com/peterhinch/micropython-nano-gui#23-verifying-hardware-configuration)
routine. For development against an editable upstream checkout, clone the whole
`gui/` tree in place of the fetch:

```bash
curl -sL https://github.com/peterhinch/micropython-nano-gui/archive/refs/heads/master.tar.gz \
  | tar xz --strip-components=2 -C src/utils micropython-nano-gui-master/gui
```

### Micro-GUI

`hardware_setup.py` builds `Display` from `appdev.App` devices. Desktop
navigation defaults:

| Key | Action |
|---|---|
| Tab / Right | Next control |
| Left | Previous control |
| Enter / Space | Select |
| Up / Down | Increase / decrease |

### MicroPython-Touch

Upstream renamed `hardware_setup.py` → `touch_setup.py` in December 2024, and
this repository follows that name. `touch_setup.py` wires a mouse/touch `Poller`
into `Display(ssd, tpad)`:

```python
import touch_setup  # fetch + Display
from gui.core.tgui import Screen, ssd
```
