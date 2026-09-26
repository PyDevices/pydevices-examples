# spectrum

A spectrum analyzer that is built to look good rather than to measure
anything. It draws log-spaced bars from 20 Hz to 20 kHz in a cool gradient,
with peak caps that hang and then fall, a faint reflection under the baseline,
and frequency labels along the bottom. For now it's fed fake music. Later the
levels will come from C code sitting where the audio passes.

![800x480](../../../docs/screenshots/spectrum_800x480.gif)

| 800x480, segmented | 320x170 (T-Embed) |
|:--:|:--:|
| ![segmented](../../../docs/screenshots/spectrum_800x480_segmented.png) | ![320x170](../../../docs/screenshots/spectrum_320x170.png) |

## Run it

From `lib/`:

```bash
micropython examples/spectrum/spectrum.py
SPECTRUM_STYLE=segmented micropython examples/spectrum/spectrum.py
PYDEVICES_WIDTH=320 PYDEVICES_HEIGHT=170 PYDEVICES_SCALE=3 micropython examples/spectrum/spectrum.py
```

On desktop the window opens at 800x480. On a board, the example takes its size
from the panel. It prints the frame rate and the cost of each part of a frame
every five seconds.

## What's where

`spectrum_view.py` does the drawing and knows nothing about audio. Hand
`SpectrumView.update()` one level per band, from 0 to 1, and it handles the
ballistics itself: bars rise fast and fall at a steady rate, and the peak caps
hold for about half a second before dropping with gravity. The palette, band
count, timings and colours are constants at the top of the file.

`fake_music.py` is the stand-in source: a four-bar loop at 120 BPM with kick,
snare, hats, bass, a pad and a lead, plus a dead stop and a breakdown so you
can watch the fall-off. Its docstring has the arrangement. The loop is seeded,
so every run is the same.

`capture.py` renders headless under MicroPython and reports timings, and
`make_captures.py` (CPython with Pillow) turns those renders into the images
in `docs/screenshots/`.

## How it stays cheap

Every bar is a single `blit` from a gradient column that was built once, so a
tall bar costs the same as a short one. The segment gaps and the reflection's
scanlines use a colour key, so the grid shows through them. The static art
(background, grid, labels) is painted once into a second framebuffer. Each
frame copies back only the row strip the bars could have touched, and that
strip is all that goes to the panel.

On desktop MicroPython at 800x480 with 48 bands, a frame costs about 0.2 ms to
generate the data, 0.7–1.5 ms to draw and 0.9 ms to blit to the SDL window.
The timer caps it at 50 fps.
