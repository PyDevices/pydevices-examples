# Run an example in the browser

The [PyScript gallery](https://PyDevices.github.io/pydevices-examples/pyscript/)
runs the real scripts from [`lib/examples/`](../../lib/examples/) in a modern web browser. Open it,
pick an example and it runs; there is nothing to install. The same example
that opens a window on your desktop draws on a canvas in the page.

## Turn an example into an app

To start a standalone browser app or an offline PWA, use the
[pyscript-template](https://github.com/PyDevices/pyscript-template). Its
[bring in a bigger app](https://github.com/PyDevices/pyscript-template/blob/main/docs/guides/bring-in-a-bigger-app.md)
page turns the piano and the drum machine into installable apps.

## Edit an example and see it in the gallery

`.site/pyscript/lib` is a symlink to `lib/`, so a change to a script under
`lib/` shows up in the gallery. From a clone, serve the repository with the
development server and open the gallery on it:

```bash
python tools/serve.py
# then open http://127.0.0.1:8000/.site/pyscript/index.html
```

The server sends the cross-origin-isolation headers that PyScript's worker
pages need, the way the published site does. Browser debugging notes are in
[`tools/README.md`](https://github.com/PyDevices/pydevices-examples/blob/main/tools/README.md).
