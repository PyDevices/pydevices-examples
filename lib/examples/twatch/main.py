"""The T-Watch S3's apps under appdev's launcher. Copy this file to the
watch as ``/main.py`` (with the ``twatch`` folder in ``/lib``) to boot into
the watch face.

``launcher.switch("steps")`` at the REPL switches apps, as the home screen
does; ``launcher.last`` says how the last switch went.
"""

# True or False switches the battery charger on or off at boot; None leaves
# it as the power chip has it.
CHARGER = None

from appdev.launcher import Launcher

from twatch import services

if CHARGER is not None and services.battery is not None:
    services.battery.charger(CHARGER)

APPS = ("face", "home", "steps", "remote", "sound", "power", "lora")

launcher = Launcher(services.app, {name: "twatch." + name for name in APPS}, home="face")
services.launcher = launcher
launcher.boot()
