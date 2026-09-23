# google_photos — Google Photos on a PyDevices display

Pick photos from your phone, browse them as a thumbnail list on the board,
view them full screen, or run a slideshow. LVGL front end; runs on
MicroPython, CircuitPython, and CPython wherever a `board_config` and the
PyDevices LVGL binding are available.

| List | View | Pairing |
|:--:|:--:|:--:|
| ![list](../../../docs/screenshots/google_photos.png) | ![view](../../../docs/screenshots/google_photos_view.png) | ![connect](../../../docs/screenshots/google_photos_connect.png) |

```bash
cd lib
micropython -m examples.google_photos      # or python / circuitpython
```

Without a tokens file (below) the launcher runs a **simulator** with sample
photos, so the UI can be explored anywhere — including the
[PyScript gallery](https://PyDevices.github.io/pydevices-examples/pyscript/).
Set `GPHOTOS_SIM=1` to force it, `GPHOTOS_SIM=0` to force the real client.

## How it works

Since March 31, 2025 the Google Photos *Library* API only returns media that
the calling app uploaded itself, so a third-party app can no longer browse a
whole library. The self-serve path is the **Picker API**:

1. The device creates a *picker session* and shows its link as a QR code.
2. You scan it with your phone, choose photos in Google Photos, tap **Done**.
3. The device polls the session, lists the picked items, and downloads
   sized thumbnails (list tiles are exact-size center crops, the viewer asks
   for an image that fits the panel).

Google returns only what you picked; nothing else in the library is visible
to the device. Picks persist on the device (see *Files*) so a reboot lands on
the list, and thumbnails are cached on flash so they download once.

The Google login cannot run on the microcontroller: Google's TV
"enter this code on your phone" flow refuses the Picker scope, and a LAN
address cannot be registered as an OAuth redirect. So the browser login runs
**once on a PC** (`tools/gphotos_auth.py`) and its output — a refresh token —
is copied to the board. From then on the device only trades that refresh
token for hour-long access tokens.

## Setup (one time)

1. **Google Cloud project** — <https://console.cloud.google.com/>: create a
   project (any name), then *APIs & Services → Library → enable
   **Google Photos Picker API***.
2. **OAuth consent screen** (*Google Auth Platform* in the current console)
   — user type *External*. To keep the sign-in working indefinitely,
   **publish the app to Production** on the *Audience* page. Google keeps
   *Publish app* greyed out until the *Branding* page has an app name, a
   support e-mail, a home page URL and a privacy policy URL; this example's
   page and its [Privacy](#privacy) section serve for the last two. An
   unverified app is fine for personal use: the sign-in shows a "Google
   hasn't verified this app" warning once (*Advanced → Go to …*).
   Alternatively stay in *Testing* and add your account under *Test users*,
   but Testing refresh tokens expire after **7 days**, and an account that
   isn't listed gets "Error 403: access_denied". A Google Workspace account
   can use *Internal* instead.
3. **Credentials** — *Create credentials → OAuth client ID → Desktop app*.
   Download the JSON (`client_secret_….json`). It has to be *Desktop app*:
   a *TVs and Limited Input devices* client downloads as an identical-looking
   file, and the sign-in then fails with Google's "Error 400:
   invalid_request" ("Localhost URI is not allowed for 'NATIVE_DEVICE'
   client type").
4. **Sign in on the PC** (CPython 3.8+, stdlib only):

   ```bash
   python tools/gphotos_auth.py --client-secrets ~/Downloads/client_secret_XXX.json --verify
   ```

   A browser opens (or copy the printed URL). Sign in with the account whose
   photos you want to show. The script writes `~/.gphotos_tokens.json`
   (owner-only permissions) and, with `--verify`, refreshes the token and
   creates + deletes a picker session to prove the API is enabled.
5. **Copy to the board** (join Wi-Fi first on MicroPython/CircuitPython):

   ```bash
   mpremote cp ~/.gphotos_tokens.json :/gphotos_tokens.json
   ```

   Desktop runs read `~/.gphotos_tokens.json` directly. `GPHOTOS_TOKENS`
   overrides the path.

Then run the example, tap **PICK**, scan the code with your phone, pick
photos, tap **Done** — the list appears on the board.

## Using it

| Page | Buttons |
|---|---|
| **list** | **PICK** new session · **SLIDES** slideshow from the first photo · **MORE** next page (long picks are paged to keep RAM bounded) · tap a row to view it |
| **view** | **BACK** · **PREV** · **PLAY / PAUSE** slideshow · **NEXT** · tapping the photo also advances |
| **connect** | QR code of the session link · **OPEN** (desktop only: opens the link in the local browser) · **RETRY** new session · **BACK** to the list |

The slideshow interval is `slideshow_s` in the prefs file (default 5).

## Files

| Desktop | Microcontroller | Contents |
|---|---|---|
| `~/.gphotos_tokens.json` | `/gphotos_tokens.json` | `client_id`, `client_secret`, `refresh_token` (written by `tools/gphotos_auth.py`; read-only on the device) |
| `~/.gphotos_prefs` | `/gphotos_prefs` | JSON: current session, picked items (without their short-lived URLs), `slideshow_s` |
| `~/.gphotos_cache/` | `/gphotos_cache/` | `<hash>_<w>x<h>[c].jpg\|png` thumbnails, at most 48 files |

Override with `GPHOTOS_TOKENS`, `GPHOTOS_PREFS`, `GPHOTOS_CACHE`.

## Privacy

This example has no server. Everything it stores stays on your own PC or
board, in the three files above. It talks only to Google: the one-time
sign-in (`accounts.google.com`, `oauth2.googleapis.com`), the Photos Picker
API (`photospicker.googleapis.com`), and the image links Google returns for
the photos you picked. It can't see any photo you didn't pick. The QR code
is drawn on the device, not fetched from a service. To revoke its access,
remove the app at <https://myaccount.google.com/permissions> and delete
the tokens file.

## Images on each platform

Google serves JPEG (PNG for PNG originals). LVGL decodes:

| Runtime | JPEG | PNG |
|---|---|---|
| CPython (`pydevices-lvgl`) | LVGL's built-in TJPGD | LODEPNG |
| MicroPython LVGL firmware (lvgl-micropython + displayif) | displayif's `jpegio`, registered as an LVGL image decoder ([displayif#23](https://github.com/PyDevices/displayif/issues/23)) | LODEPNG |
| CircuitPython LVGL firmware | CircuitPython's `jpegio` via lvgl-circuitpython | LODEPNG |

Without a JPEG decoder the list still works: tiles keep a placeholder and
the viewer explains why. Both decoders hold the decoded image
(`width × height × 2` bytes) while it is drawn, so the viewer requests an
image no larger than the panel; a 320×480 panel needs ~300 KB of heap for
the full-screen photo — comfortable with PSRAM, tight without. Thumbnails
are tiny. Only one page of tiles is resident at a time.

## Limits and gotchas

- **Thumbnail URLs expire after 60 minutes.** The engine re-lists the
  session (one request) to refresh them; nothing is re-picked.
- **Picker sessions expire** (about a week). After that the cached list still
  shows, but new downloads fail with *session expired* until you **PICK**
  again. The prefs keep the picked list either way.
- **Refresh tokens die after 7 days while the consent screen is in
  *Testing*.** Publish to Production (see Setup) and they last until revoked.
- **`invalid_grant` on start** means the refresh token was revoked or expired:
  run `tools/gphotos_auth.py` again and copy the new file.
- **`HTTP 403 … SERVICE_DISABLED`** means the Picker API is not enabled in
  the project (Setup step 1). **`access_denied` in the browser** means your
  account is not a test user of a Testing app.
- **TLS on MicroPython** does not verify Google's certificate (the platform
  default: boards ship no CA bundle). The refresh token is the secret to
  protect — treat the tokens file like a password.
- **`-m` launches** (`python -m examples.google_photos`) block inside the
  launcher's `app.run()` because the shared app host-loop declines `-m`
  entry points; a script-path launch (`python examples/google_photos/google_photos.py`)
  keeps itself alive like every other example.
- Videos appear in the list with a *video* tag; the viewer shows their poster
  frame.

## Module layout

```
google_photos/
  google_photos.py    launcher: sim detection, restore prefs, start LVGL front end
  gphotos_engine.py   Picker API client, token refresh, prefs, thumbnail cache (no UI)
  gphotos_sim.py      simulator (sample photos) + make_engine()
  gphotos_lvgl.py     LVGL front end: connect (QR), list, view, slideshow
  assets/             sim_NN_*.jpg sample photos + gen_sim_assets.py (Pillow)
tools/gphotos_auth.py PC-side one-time Google sign-in (stdlib, PKCE, loopback)
tests/test_gphotos_engine.py
```

`gphotos_engine` has no display, event, or UI imports, so a pdwidgets or
pygraphics front end can be added the way `roku_remote` has three. All
network calls are blocking and are queued on the LVGL pump from the main
thread (no `_thread`, like the Roku example).

## Testing

```bash
.venv/bin/python -m unittest discover -s tests -p "test_gphotos_engine.py"
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy .venv/bin/python tools/example_test_kit.py \
  --no-unit-tests --only-interpreter cpython-venv --only-example google_photos gphotos_lvgl
```

The unit tests fake every HTTP call (token refresh, sessions, paging,
downloads, the raw-socket fallback, the MicroPython `requests` path) and the
login tool's loopback redirect. The kit run exercises the real LVGL UI in
simulator mode.
