# pydevices-examples utils

The files in this folder extend the functionality of pydevices-examples. They are not required for the basic functionality of pydevices-examples, but they can be useful for some applications.  Some of these files are not written by the author of pydevices-examples, but are included here for convenience.  Many of the examples
in the examples folder use these files.

Preferred: set `PYTHONPATH` (CPython) or `MICROPYPATH` (MicroPython/CircuitPython) to `.:lib:utils` and run from `lib/` — no import needed. This package is optional; example scripts never import `utils.path` themselves.

Without those env vars (a bare device REPL, or `boot.py`/`main.py` on a device that keeps `utils/`), set up the path explicitly:

```python
import utils.path  # adds cwd, lib/, and utils/ to sys.path
```

You may instead copy any of the files or directories to a location in your path such as `/lib`.

Install into a device's `utils/`:

```python
import mip

mip.install("github:PyDevices/pydevices-examples/packages/utils.json", target="./utils")
```

Product-owned desktop modules — `mip`, the `micropython` shim, `frame_recorder` —
live in [pydevices `utils/`](https://github.com/PyDevices/pydevices/tree/main/utils)
instead, and are installed by `pydevices-desktop`.

## Notable modules

| Module | Purpose |
|---|---|
| `framebuf.py` | The `framebuf` API on CPython and CircuitPython |
| `displaybuf.py` | Peter Hinch's `DisplayBuffer` API |
| `keypins.py` | Presents key events as pin-like objects |
| `wifi.py` | MicroPython `network.WLAN` shim used by the examples |
| `viper_tools.py` | Optional MicroPython Viper accelerators |
| `console.py` | Scrolling character terminal; an `os.dupterm` target that mirrors the REPL onto a display |
| `lv_encoder_emu.py` | Desktop-only soft encoder on a secondary surface, standing in for MCU `machine.Encoder` / `rotaryio` (see `examples/lv_multi_display.py`) |
| `tft_text.py`, `tft_write.py` | @russhughes font rendering |
| `png.py` | Experimental PNG support |
| `color_setup.py`, `hardware_setup.py`, `touch_setup.py`, `fetch_ph_gui.py` | [Peter Hinch GUI](../../docs/peterhinch-guis.md) integration |

`gui/` is an upstream Peter Hinch tree fetched on demand and gitignored — one of
nano / micro / touch at a time. See
[peterhinch-guis.md](../../docs/peterhinch-guis.md).

`pdwidgets/` and `palettes/` moved out to their own repositories:
[pdwidgets](https://github.com/PyDevices/pdwidgets),
[palettes](https://github.com/PyDevices/palettes).

Many scripts in `lib/examples/` depend on these modules. They are excluded from
the MIP packages — install from GitHub only. Some files are third-party ports
included for convenience; see the file headers for attribution.
