# pydevices-examples on Wokwi (ESP32-S3 + ILI9341 touch)

Browser project for [wokwi.com](https://wokwi.com): PyDevices core + `pygraphics` + Wokwi board config + [`testris`](../../lib/examples/testris.py) (a touch + joystick Tetris demo).

**Wokwi reference:** [pydevices/docs/wokwi.md](https://github.com/PyDevices/pydevices/blob/main/docs/wokwi.md)

Board config: [`wokwi_ili9341_ft6x36_esp32s3`](https://github.com/PyDevices/pydevices/tree/main/board_configs/busdisplay/spi/wokwi_ili9341_ft6x36_esp32s3)

## Files

| File | Purpose |
|------|---------|
| `main.py` | WiFi (when `WOKWI = True`, target `lib`) + `mip.install` of the board config, `pygraphics`, and `testris` |
| `diagram.json` | ESP32-S3 + `board-ili9341-cap-touch` wiring |

## Run in the browser

1. Create a [new ESP32-S3 MicroPython project](https://wokwi.com/projects/new/micropython-esp32-s3).
2. Replace the project's **main.py** and **diagram.json** with the files from this directory.
3. Start the simulation. Serial shows `mip` downloads, then the demo UI appears.

## Quick try (default)

Use `main.py` as committed. On first boot, `mip` downloads PyDevices core + `pygraphics` from the
PyDevices MIP index (network required), then runs **testris** — a touch + joystick Tetris demo. You
should see the game running — drive it with the on-screen touch keypad.

Only `testris.py` is installed from `lib/examples/`; the rest of the example catalog is not fetched.
To try a different example, edit the `mip.install(PYDEVICES_EXAMPLES + ...)` line in `main.py` to
point at another script under [`lib/examples/`](../../lib/examples/) and update the `import testris`
line at the bottom to match.

## Wiring (GPIO)

| Signal | GPIO |
|--------|------|
| SPI SCK | 12 (SPI2 IOMUX) |
| SPI MOSI | 11 |
| SPI MISO | 13 |
| Display D/C | 16 |
| Display CS | 5 |
| Display LED / RST | 3V3 |
| Touch I2C SDA | 7 |
| Touch I2C SCL | 6 |

SPI baudrate **20 MHz**. Matches [`wokwi_ili9341_ft6x36_esp32s3/board_config.py`](https://github.com/PyDevices/pydevices/blob/main/board_configs/busdisplay/spi/wokwi_ili9341_ft6x36_esp32s3/board_config.py).
