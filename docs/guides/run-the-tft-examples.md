# Run the TFT examples

Many of the examples were ported from [@russhughes st7789py_mpy](https://github.com/russhughes/st7789py_mpy).

## Config

Use or adapt [`lib/utils/tft_config.py`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/utils/tft_config.py). If an example fails to import its config, compare it with that file.

## Font and image tools

- [text_font_converter.py](https://github.com/russhughes/st7789py_mpy/blob/master/utils/text_font_converter.py) → `tft_text.text()`
- [write_font_converter.py](https://github.com/russhughes/st7789py_mpy/blob/master/utils/write_font_converter.py) → `tft_write.write()`
- [image_converter.py](https://github.com/russhughes/st7789py_mpy/blob/master/utils/image_converter.py) → `.bitmap()`

See the pygraphics [docs](https://pygraphics.readthedocs.io) for drawing text and loading bitmaps.

## Notable examples

`tiny_hello.py`, `feathers.py`, `proverbs/`, `chango/` and `tiny_toasters/`, a game port, are under
[`lib/examples/`](https://github.com/PyDevices/pydevices-examples/tree/main/lib/examples/).
