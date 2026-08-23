# Why this hub: roadmap TV web path is PyScript-only (no native SDL on webOS /
# Tizen). Python demos live under lib/examples/ so the gallery loader can see
# them; this folder holds remote-key notes for TV browsers.

# TV remote / PyScript notes (webOS / Tizen)

pydevices-examples on LG **webOS** and Samsung **Tizen** is **browser / PyScript only** —
use `PSDisplay`, not native `SDLDisplay` / `usdl2`.

## Try the demo

From the [PyScript gallery](../index.html) or:

- [tv_remote_menu](../micropython.html?modules=tv_remote_menu) — large-row menu, D-pad / Enter / Back

Desktop arrow keys stand in for the remote during development.

## Expected key → `keys` mapping

| Remote / DOM `KeyboardEvent.key` | `keys` | Notes |
|----------------------------------|----------|--------|
| ArrowUp / ArrowDown / ArrowLeft / ArrowRight | `K_UP` … `K_RIGHT` | D-pad |
| Enter | `K_RETURN` | Select / OK |
| Escape | `K_ESCAPE` | Often Back on desktop |
| BrowserBack, GoBack, Back | `K_AC_BACK` | Why: TV Back should match Android SDL Back → quit |
| ColorF0Red … (optional) | unmapped unless a demo needs them | Host-specific |

Mappings live in `displaydev._domkeys._DOM_NAMED_KEYS`. Unknown TV keys arrive as
`K_UNKNOWN` until added with a why-comment.

## Related

- [Where PWAs run — Smart TVs](https://github.com/PyDevices/pyscript-template/blob/main/docs/pwa-guide.md#where-pwas-run)
- [PSDisplay](https://github.com/PyDevices/pydevices/blob/main/docs/displaydev.md#psdisplay)
