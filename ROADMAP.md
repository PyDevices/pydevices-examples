# Roadmap

The examples are heading toward one showcase of the whole stack, with each
package's own demos living beside that package.

## Examples

- CastDisplay: the Roku remote as input on a Miracast cast, so arrows, OK and
  Back reach the app as keys, the way they already do with RokuDisplay.
- google_photos: playlists. Keep several saved picks (Wedding, Christmas,
  Grandkids) and choose which one the frame shows.
- A live-audio example built on one object that owns the codec, the audio
  graph and the pump behind a safe surface: the way to build a live instrument.

## Layout

- Single-package demos move into their own repositories. This one stays the
  showcase and gallery, and the shared helpers (`tft_config`, `console`,
  `wifi.py` and others) become a package you can install whole or file by file.

Bugs, and things you need that don't work yet, go to
[issues](https://github.com/PyDevices/pydevices-examples/issues).
