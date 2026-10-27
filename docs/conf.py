"""Sphinx configuration for the pydevices-examples documentation.

Everything shared by the PyDevices documentation projects (theme, top bar,
Markdown and docstring setup, the reference map) comes from pydevices-docs.
"""

from pydevices_docs import configure

globals().update(
    configure(
        "pydevices-examples",
        __file__,
        repo="PyDevices/pydevices-examples",
        edit_path="docs",
        version_file=None,
    )
)

# index.md is plain Markdown so the docs read on GitHub too; the site
# navigation lives in contents.md.
master_doc = "contents"
