# Newcomer's guide to pydevices-examples

pydevices-examples is the showcase, integration documentation, and browser gallery for the PyDevices driver ecosystem. It contains runnable applications and helpers; reusable drivers and published core packages belong in the sibling [pydevices](https://github.com/PyDevices/pydevices) repository.

## Start with an example

The fastest path is the [PyScript gallery](https://PyDevices.github.io/pydevices-examples/pyscript/), which runs the real example scripts in a browser.

For a desktop checkout:

```bash
git clone https://github.com/PyDevices/pydevices-examples.git
cd pydevices-examples
python3 -m venv .venv
.venv/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ -r requirements.txt
cd lib
../.venv/bin/python examples/pydevices_demo.py
```

Some scripts use local helpers under lib/utils. Their header comments identify that requirement; run them with `PYTHONPATH=.:lib:utils` from lib/. The [examples README](../lib/examples/README.md) explains both invocation forms.

## Mental model

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

Examples demonstrate the portable product stack; they do not publish it. Editing lib/ updates the gallery because .site/pyscript/lib is a symlink to that tree.

## Repository map

| Path | Purpose |
|---|---|
| lib/examples/ | Portable demos, applications, assets, and example-specific READMEs. |
| lib/utils/ | Helpers and third-party GUI adapters used by selected examples. |
| .site/pyscript/ | Browser gallery runners; its lib link points at lib/. |
| tools/ | Cross-interpreter and LVGL example test harnesses. |
| tests/ | Repository unit tests. |
| packages/ | MIP manifests for examples and helpers. |
| docs/ | GUI integration notes and screenshots. |

## Application ownership

Board configurations expose hardware such as display_drv and input readers; they do not create an appdev.App. Non-LVGL examples choose the optional coordinator themselves:

```python
import board_config
import appdev

app = appdev.App(board_config)
```

LVGL examples instead import display_driver after the board setup; its coordinator owns LVGL ticking and presentation. This separation is intentional: do not mix appdev into an LVGL example unless its architecture specifically requires it.

## Interpreter boundaries

The same script may run on MicroPython, CircuitPython, or CPython when an appropriate board_config and product stack are present. MicroPython setup uses the PyDevices MIP index and a board package; the [pydevices installation workflows](https://github.com/PyDevices/pydevices/blob/main/docs/install-workflows.md) are authoritative.

The test matrix is intentionally broader than a quick script run. Read tools/README.md before cross-interpreter or LVGL testing. For a focused contribution, use the repo virtual environment, run the relevant unit tests, and keep reusable product fixes in pydevices rather than here.

