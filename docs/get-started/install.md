# Install

The examples are plain scripts in
[`lib/examples/`](https://github.com/PyDevices/pydevices-examples/tree/main/lib/examples).
You run them from a clone, once the PyDevices packages are installed.

## On a desktop

`--depth 1` skips the history, which is most of the download: about 67 MB
instead of 270 MB.

```bash
git clone --depth 1 https://github.com/PyDevices/pydevices-examples.git
cd pydevices-examples
python3 -m venv .venv
.venv/bin/pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ -r requirements.txt
```

On Windows, use the same commands with `.venv\Scripts\python.exe` and
`.venv\Scripts\pip.exe`.

Run an example from `lib/`:

```bash
cd lib
../.venv/bin/python examples/pydevices_demo.py
```

Examples that import helpers from `lib/utils` say so in a `# utils:` comment at
the top. They need `utils/` on the import path:

```bash
cd lib
PYTHONPATH=.:lib:utils ../.venv/bin/python examples/hello.py
```

## On MicroPython-compatible boards

Install the PyDevices packages from the PyDevices MIP index, then a board
package for your board:

```python
import mip

INDEX = "https://PyDevices.github.io/mip"
mip.install("pydevices", index=INDEX)  # displaydev, appdev, and the rest of lib/
```

[Install workflows](https://github.com/PyDevices/pydevices/blob/main/docs/install-workflows.md)
and [board configs](https://github.com/PyDevices/pydevices/blob/main/docs/board-configs.md)
in the pydevices docs cover the board package and complete device setup.

## On MicroPython on your desktop

Build MicroPython with
[micropython-pydevices](https://github.com/PyDevices/micropython-pydevices),
using its `pydevices` variant and every module. That variant freezes the desktop
board config and, on Windows, `uwin32`, which the Windows display and audio
backends need. On Windows, build from PowerShell as its
[Windows steps](https://github.com/PyDevices/micropython-pydevices/blob/main/docs/guides/build-on-windows.md)
say, then run an example from `lib/`:

```powershell
python build_mp.py --port windows --variant pydevices --modules all   # in micropython-pydevices
cd pydevices-examples\lib
..\..\micropython-pydevices\builds\windows\pydevices\micropython.exe -X heapsize=64M examples\hello.py
```

On Linux the same build with `--port unix` gives `builds/unix/pydevices/micropython`.
`micropython.exe` already has `lib` and `utils` on its path, so it needs no
`MICROPYPATH`. If you set one on Windows, separate the entries with `;`, not `:`.

## In a browser or on a phone

Nothing to install for the browser: the
[PyScript gallery](https://PyDevices.github.io/pydevices-examples/pyscript/)
runs the real example scripts in a modern web browser. See
[Run an example in the browser](../guides/run-in-the-browser.md).

On an Android phone, install the prebuilt Runner and stage a script from your
clone with `android.py`; see
[pydevices' Android page](https://github.com/PyDevices/pydevices/blob/main/docs/android.md#staging-a-script-with-androidpy).
