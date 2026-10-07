# Casting a PyDevices app to a TV

An ESP32-P4 puts its screen on a 65" TV, and in a window on a Windows laptop,
over your own Wi-Fi. The TV gets the sound too, in time with the picture. On
the laptop, the mouse and keyboard drive the board as if they were its own
touch screen. No phone app, no cloud service and no PC sits in between. The
board itself speaks Miracast, encodes the H.264 in its own silicon, and serves
the video.

Any PyDevices app can do this without changing a line. Each method below has
a `board_config.py`: put its folder first on the path and run the app, LVGL or
not, and the app's display is the TV. The same configs run on a desktop too:
[every runtime](#every-runtime) says which methods work where.

## Which way to cast

| Method | The screen | What the screen needs | Sound | Input back | Boards | From a desktop |
|---|---|---|---|---|---|---|
| [Miracast to a Roku](#miracast-to-a-roku-tv) | Roku TV | Screen mirroring on, nothing installed | yes, 48 kHz, in sync | not yet ([#168](https://github.com/PyDevices/pydevices-examples/issues/168)) | ESP32-P4 | CPython with ffmpeg |
| [Miracast to Windows](#miracast-to-a-windows-laptop) | Windows laptop | the Wireless Display app open | yes | the laptop's mouse and keyboard | ESP32-P4 | CPython with ffmpeg, from another PC; glitches on a busy network |
| [The Companion channel](#the-pydevices-companion-channel) | Roku TV | our channel, sideloaded once | through the TV | the TV's remote | any board with Wi-Fi and `pngio` | CPython and MicroPython |
| [HLS video](#hls-video-to-a-roku-or-vlc) | Roku TV, or VLC anywhere | the Companion channel, or any HLS player | not yet (needs AAC) | none | ESP32-P4 | CPython with ffmpeg |

In short: **Miracast** for a live picture with sound, on a TV or a laptop, with
nothing installed on either. **The Companion channel** for a TV you can play
with the remote, from any runtime and any board with Wi-Fi. **HLS** for one
stream that a TV and any number of VLC windows can all watch.

The ESP32-P4 is the only board with an H.264 encoder, so on a board both
Miracast methods and HLS need one. They're proven on the
[Waveshare ESP32-P4 4" panel](https://github.com/PyDevices/micropython-pydevices/blob/main/docs/newcomers.md#boards-we-build-for).
The P4 WIFI6 DEV-KIT builds the same firmware but hasn't cast yet. The firmware
needs `castif`, `h264enc` and `tsmux`, all in `--modules all`.

## Miracast to a Roku TV

Turn on **Screen mirroring** in the Roku's settings and the P4 mirrors to it.
No channel, no account and no pairing on the TV.

```python
import sys
sys.path.insert(0, "/lib/miracast")   # board_config.py: SINK = the TV, KIND = "roku"
import lv_test_timer                  # or any app
```

The picture is the panel's 720x720 in the middle of the TV's 1280x720, at
about 24 fps. A P4 with no screen of its own casts the full 1280x720 at 18 fps
([`cast/headless_cast.py`](../lib/examples/cast/headless_cast.py)). Sound the
P4 plays goes with it as 48 kHz audio on the picture's clock. A ten-minute
drum machine cast drifted about 1 ms, and the drum hits landed with the step
light.

The P4 also controls the TV over its own network API (ECP, built into every
Roku, with **Control by mobile apps** on). It can power the TV on, change the
input or the volume, and press any key.
[`cast/tv_cast.py`](../lib/examples/cast/tv_cast.py) turns the TV on and
casts a melody. The [house panel](../lib/examples/house/) has a button that
puts the whole panel on the TV.

Examples: [`cast/`](../lib/examples/cast/README.md),
[`miracast/board_config.py`](../lib/examples/miracast/board_config.py) for any
app.

## Miracast to a Windows laptop

Open the laptop's **Wireless Display** app (Settings > System > Projecting to
this PC) and the P4 appears in a window. The same `miracast/board_config.py`
works with `KIND = "windows"`. The sink can be the laptop's name, such as
`windows:elitebook`, where the runtime's resolver knows it (Windows'
`python.exe` does; WSL doesn't, so give it the address).

This one talks back. Windows sends the laptop's mouse and keyboard to the
board (Miracast's UIBC), and `CastDisplay` turns them into touch and key
events. An app on the P4 can't tell them from its own touch screen: testris
plays from the laptop's keyboard, and
[`cast/laptop_input.py`](../lib/examples/cast/laptop_input.py) draws the
cursor and a dot per click. The Wireless Display window has to have focus:
it then takes the mouse pointer and the keys, and the Windows key gives them
back.

**Expect glitches on a busy 2.4 GHz network.** Miracast sends its video over
UDP, so a packet Wi-Fi loses is gone. Windows draws the damage instead of
hiding it: a band of smeared or discoloured blocks, or a pink or grey flash,
until the board sends a fresh keyframe a moment later. On this bench, with
about 0.5 % of packets lost, that was one every two to three seconds, the same
from the P4 and from CPython and at any bitrate. A quieter channel, or the
board and laptop closer to the router, means fewer. `CastDisplay.stats()`
counts them as `idr_requests`, the keyframes the laptop asked for after a loss.

## The PyDevices Companion channel

A small Roku channel of ours, in
[`tools/roku_companion_app`](../tools/roku_companion_app/README.md),
sideloaded once with the TV in developer mode. Then a program on the network
can use the TV as a display, read its remote, speak through it and play video
on it.

- **The TV as a display.** `RokuDisplay` is a framebuffer display whose frames
  show full-screen, sent as PNGs. At 480x270 a desktop gets 8 to 13 frames a
  second onto the TV, and a P4 about 2.
- **The remote as input.** All eleven buttons a channel can see arrive as key
  presses and releases, and a held button repeats. testris plays from the
  couch through [`roku/board_config.py`](../lib/examples/roku/board_config.py).
- **Speech, a dashboard, and frames from any URL**: `say()`, `dashboard()`
  and `frames(url)`, which shows the PNG or JPEG a URL serves, over and over.
  One example each in [`lib/examples/roku/`](../lib/examples/roku/).
- **Video**: `video(url)` plays HLS, which is how the next method reaches a
  TV.

The library is plain sockets plus
[`pngio`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/pngio)
for the PNGs, so it needs no video encoder and no P4. PyDevices MicroPython
firmware has `pngio` built in; on CPython it comes with `pydevices-desktop`
and needs Pillow. On a board, an LVGL app keeps Python's threads from running,
so `RokuDisplay` answers the TV from inside `show()` instead of from a thread
of its own. From WSL, give it the TV's address: SSDP discovery doesn't cross
WSL's NAT.

## HLS video to a Roku or VLC

`HlsDisplay` makes a P4's screen a live video stream that anything can watch.
It encodes H.264 and cuts one-second segments in a task on the P4's second
core, so a busy app doesn't starve it, and serves them itself.

```python
import sys
sys.path.insert(0, "/lib/roku_hls")   # board_config.py: TV = the Roku, or None
import analog_clock_lvgl
```

With a TV named, the board wakes it, even from standby, and the Companion
channel plays the stream. On the 65" it ran 7.1-7.7 s behind, with no stalls.
Anywhere else, open `http://<the P4>:8090/stream.m3u8` in VLC. Every viewer
gets the same stream, so a TV and a laptop can watch at once. VLC fetched every
segment in order for 30 s with the LVGL analog clock and with two of the
portal's non-LVGL hero apps, polyhedron and radar_scope.

HLS is video only. A Roku plays HLS audio only as AAC, and there's no AAC
encoder in the firmware yet.

On a desktop, the same `roku_hls/board_config.py` runs under CPython and
ffmpeg makes the stream.

## Every runtime

Each method on each runtime that could run it, with real examples through
their `board_config.py`. The numbers are frames a second reaching the screen,
for testris and for the LVGL `lv_test_timer`.

| Runtime | Companion channel | Miracast to a Roku | Miracast to Windows | HLS |
|---|---|---|---|---|
| `python` (Linux) | 12.7, 11.3 | 30, 30 | 30 | plays |
| `python.exe` (Windows) | 12.2, 10.6 | 30, 30 | 30 | plays |
| `micropython` (unix) | 11.8, 7.4 | no H.264 | no H.264 | no H.264 |
| `micropython.exe` (Windows) | 8.4, 7.7 | no H.264 | no H.264 | no H.264 |
| ESP32-P4 4" panel | 2.2, 2.1 | 29, 18 | 30 | plays |
| ESP32-S3 LCD-7 | 1.8, 1.7 | no H.264 | no H.264 | no H.264 |

**No H.264** is by design. Desktop MicroPython and the S3 have no H.264
encoder, and adding one isn't planned, so `CastDisplay` and `HlsDisplay` stop
there with an error that says so. On CPython, ffmpeg does the encoding: put it
on the PATH, or name it in the `FFMPEG` environment variable (Windows
`python.exe` started from WSL needs that). The Miracast stream from CPython is
the same MPEG-TS over RTP that the P4 sends, byte for byte.

**Miracast to Windows** is testris only, with glitches from Wi-Fi loss (see
[Miracast to a Windows laptop](#miracast-to-a-windows-laptop)). From CPython
it needs a second PC as the receiver: Windows won't take a cast from itself.

On a desktop, a frame costs a few milliseconds of PNG encoding. On the P4 it's
about 180 ms at 480x270 and on the S3 about 380 ms, which is why the boards get
2 frames a second over the Companion channel and 18 to 29 over Miracast, where the P4's H.264 encoder
does the work.

To run any of these from `lib/`, with the TV's address:

```bash
python ../tools/run_cast_example.py roku testris TV_ADDRESS
```

The first argument is the method's folder (`roku`, `miracast` or `roku_hls`),
and `micropython`, `python.exe` and `micropython.exe` run it the same way.
Without the runner, set `CAST_TARGET` to the address, put the method's folder
first on the path and run the example. A board runs the same script through
mpftp, with its settings at the top of the file.

## What isn't done yet

The Roku's remote as input over Miracast is
[#168](https://github.com/PyDevices/pydevices-examples/issues/168).

## How it works

The [cast README](../lib/examples/cast/README.md#how-it-works) covers the
Miracast session (Wi-Fi Display over infrastructure, MICE and RTSP, in
Python), and the C task that streams MPEG-TS over RTP with the audio on the
same clock. The encoders and the muxer are firmware modules of their own:
[`h264enc`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/h264enc),
[`tsmux`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/tsmux)
and the PPA's colour conversion,
[`ppa`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/ppa).
The Companion channel's BrightScript is in
[`tools/roku_companion_app`](../tools/roku_companion_app/README.md), and its
Python side in [`lib/utils/roku_companion.py`](../lib/utils/roku_companion.py).
