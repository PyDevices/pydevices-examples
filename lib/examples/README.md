# lib/examples

Portable examples and complete demo applications for the PyDevices driver
stack. Each script runs unmodified on MicroPython, CircuitPython, and CPython
wherever a `board_config` is available.

The easiest way to browse and run these examples is the interactive
[PyScript gallery](https://PyDevices.github.io/pydevices-examples/pyscript/) —
it runs the real scripts in this folder directly in a web browser.

## Invocation forms

Run from `lib/` in both cases.

Most examples only need `board_config` and the published product packages
(`displaydev`, `appdev`, `pygraphics`, etc.), already importable once
`requirements.txt` is installed:

```bash
../.venv/bin/python examples/pydevices_demo.py
```

Examples that also import helpers from [`lib/utils`](../utils/README.md)
(see each script's `# utils:` header comment) need `utils/` on the import
path:

```bash
PYTHONPATH=.:lib:utils ../.venv/bin/python examples/hello.py
```

See the top-level [README](../../README.md) for environment setup.
