# Newcomer's guide to pydevices-examples

pydevices-examples is the showcase, integration documentation, and browser gallery for the PyDevices driver ecosystem. It contains runnable applications and helpers; reusable drivers and published core packages belong in the sibling [pydevices](https://github.com/PyDevices/pydevices) repository.

## Start with an example

The fastest path is the [PyScript gallery](https://PyDevices.github.io/pydevices-examples/pyscript/), which runs the real example scripts in a browser.

To run the examples from a desktop clone, including the helpers under lib/utils, follow the [README's "Try it" section](../README.md#try-it); the [examples README](../lib/examples/README.md) explains both invocation forms.

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

The [README's repository layout](../README.md#repository-layout) maps the tree. Repository unit tests live in tests/.

## Application ownership

Board configurations expose hardware; they do not create an appdev.App. Non-LVGL examples opt into appdev themselves, and LVGL examples use the display_driver coordinator instead. The [README's app ownership section](../README.md#app-ownership) shows both. Don't mix appdev into an LVGL example unless its architecture specifically requires it.

## Interpreter boundaries

The same script may run on MicroPython, CircuitPython, or CPython when an appropriate board_config and product stack are present. MicroPython setup uses the PyDevices MIP index and a board package; the [pydevices installation workflows](https://github.com/PyDevices/pydevices/blob/main/docs/install-workflows.md) are authoritative.

The test matrix is intentionally broader than a quick script run. Read tools/README.md before cross-interpreter or LVGL testing. For a focused contribution, use the repo virtual environment, run the relevant unit tests, and keep reusable product fixes in pydevices rather than here.

