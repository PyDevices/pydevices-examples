# Cast methods on each runtime

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
[Miracast to a Windows laptop](../guides/cast-to-a-tv.md#miracast-to-a-windows-laptop)). From CPython
it needs a second PC as the receiver: Windows won't take a cast from itself.

On a desktop, a frame costs a few milliseconds of PNG encoding. On the P4 it's
about 180 ms at 480x270 and on the S3 about 380 ms, which is why the boards get
2 frames a second over the Companion channel and 18 to 29 over Miracast, where the P4's H.264 encoder
does the work.
