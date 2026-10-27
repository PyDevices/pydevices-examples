# Package names

Python distributions on TestPyPI use the organization prefix. Imports and MIP
packages are unprefixed. `pydevices` ships the whole core `lib/` tree as one
distribution, and the MIP index publishes it the same way: one `pydevices`
package, not one per component.

| TestPyPI distribution | Python import / MIP name |
|---|---|
| `pydevices` | `displaydev`, `audiodev`, `appdev`, `events`, `keys`, `multimer`, `boarddev` |
| `pydevices-pygraphics` | `pygraphics` |
| `pydevices-palettes` | `palettes` |
| `pydevices-pdwidgets` | `pdwidgets` |
| `pydevices-lvgl` | `lvgl` |
