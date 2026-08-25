# Tests

This suite covers the pydevices-examples-owned examples, utilities, PyScript gallery,
and developer tooling.

Product-library tests moved with their sources to
[`pydevices/tests`](https://github.com/PyDevices/pydevices/tree/main/tests),
including `appdev`, `displaydev`, `audiodev`, `multimer`, `events`, `keys`,
and `boarddev`.

## Running

From the repository root:

```bash
python -m unittest discover -s tests -v
```

The test environment adds the sibling `pydevices` product paths so
the example and tooling tests exercise canonical sources rather than copied
libraries.

## What remains here

- PyScript URL, loader, and gallery generation
- screenshot and recording tools
- Peter Hinch gallery integration
- example manifest and harness behavior
