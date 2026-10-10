# twatch: switchable apps for the T-Watch S3

The [wristwatch](../wristwatch.py) example split into separate apps that
appdev's launcher switches between, on the LILYGO T-Watch S3 with
MicroPython:

- **Watch face**: the time, the date, the battery and today's steps. Tap it
  for the home screen.
- **Home**: a button for each app.
- **Steps**, **TV remote**, **Sound**, **Power** and **LoRa**, as in the
  wristwatch example.

The crown goes back to the watch face from any app. On the face it turns
the screen off, and on a dark screen it wakes it.

Only one app is in memory at a time. A switch closes the old app (its
screen, timers and anything else it made) and starts the next in about
0.3 s. If memory ever runs low, the launcher restarts the watch's program
straight into the app you asked for, in about 3 s, so it can't run out
however long you wear it.

## Run it

Copy the `twatch` folder to the watch's `/lib`, and `main.py` from it to
`/main.py`. The watch needs the T-Watch S3 board config and an `appdev` that
has `appdev.launcher`. If the firmware's frozen `appdev` is older, copy
pydevices' `lib/appdev` to the watch's root folder, which comes first on the
import path. Then reset it.

At the REPL, `launcher.switch("steps")` switches apps the way the home
screen does, and `launcher.last` says how the last switch went:
`("switch", ms, free_heap)`.

## What the apps share

`services.py` sets up what every app uses and keeps it running across
switches: the display and touch, the AXP2101 power chip, the accelerometer's
step counter and gestures, the clock, the vibration motor, the IR LED, the
screen's dimming and sleep, and the crown. An app borrows them; nothing it
makes outlives it.

The screen dims, then goes dark, when you leave it alone. Wake it with the
crown, a touch, a wrist tilt or a double tap. On battery the watch sleeps
while the screen is dark (light sleep, so it wakes in a moment). On USB it
only blanks the screen, so the REPL stays usable.

## Writing another app

An app is a module with `main(scope)` that does no work when it's imported.
It builds its screen with `ui.screen(scope, "Title")`, makes timers and
anything else through `scope` (see appdev's "Switchable apps"), and calls
`services.use(scope, update)` so the screen's tick calls `update()` while
the screen is on. Add its name to `APPS` in `main.py` and a button for it in
`home.py`.
