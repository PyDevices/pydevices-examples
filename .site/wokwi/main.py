WOKWI = True
TARGET = "/tmp/lib"

if WOKWI:
    import wifi

    wifi.connect_from_secrets()
    TARGET = "lib"


import mip  # noqa: E402

MICROPYTHON_LIB = "https://PyDevices.github.io/mip"
PYDEVICES = "github:PyDevices/pydevices"
PYDEVICES_EXAMPLES = "github:PyDevices/pydevices-examples"

# index= is required so bare deps like "displaydev" resolve from PyDevices MIP
# (not micropython.org). The application installs optional appdev explicitly
# when it needs the non-LVGL event traffic controller.
mip.install(
    PYDEVICES + "/board_configs/busdisplay/spi/wokwi_ili9341_ft6x36_esp32s3/",
    index=MICROPYTHON_LIB,
    target=TARGET,
)
mip.install("pygraphics", index=MICROPYTHON_LIB, target=TARGET)
mip.install(PYDEVICES_EXAMPLES + "/lib/examples/testris.py", target=TARGET)

# isort: off
if WOKWI:
    import testris
