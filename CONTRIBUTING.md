# Contributing

Examples, integrations and gallery work belong here. Fixes to the reusable
libraries and to hardware support belong in
[pydevices](https://github.com/PyDevices/pydevices). A new example, or a fix
to one that doesn't run on a board you have, is a good first contribution.

## Where things are

| Path | What's there |
|---|---|
| [`lib/examples/`](lib/examples/) | Portable examples and complete demo applications |
| [`lib/utils/`](lib/utils/) | Example helpers and third-party GUI adapters |
| [`.site/pyscript/`](.site/pyscript/) | The PyScript gallery and the browser demo runners |
| [`docs/`](docs/) | The documentation site's source, and the screenshots |
| [`tools/`](tools/) | Cross-interpreter example and LVGL test harnesses |
| [`packages/`](packages/) | GitHub MIP manifests for examples and helpers |
| [`tests/`](tests/) | Unit tests for the examples, utilities, gallery and tooling |

## Set up and run the tests

```bash
python3 -m venv .venv
.venv/bin/pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m pytest -s tests -q
.venv/bin/ruff check lib tests tools scripts
```

[`tools/README.md`](tools/README.md) describes the cross-interpreter example
matrix and the PyScript and Playwright debugging notes. [`AGENTS.md`](AGENTS.md)
lists the repository's conventions for application ownership and board configs.

## Take a screenshot or a recording

```bash
python tools/screenshot.py hello.py
python tools/record.py bouncing_balls 10
```

Output goes to [`docs/screenshots/`](docs/screenshots/) and [`docs/videos/`](docs/videos/).

## Build the docs

```bash
pip install -r docs/requirements.txt
sphinx-build -W --keep-going -b html docs _site
```

`-W` fails on any warning, as Read the Docs does.
