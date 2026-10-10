"""
twatch.services -- what every T-Watch app shares, and what outlives them.

The display, touch, the AXP2101 power chip, the accelerometer's step counter
and gestures, the clock, the vibration motor and the IR LED are set up once,
here, and stay up while apps come and go. So do the screen's dimming and
sleep, and the crown:

* The screen dims, then goes dark, when you leave it alone. The crown, a
  touch, a wrist tilt or a double tap wakes it. On battery the watch sleeps
  while the screen is dark (light sleep, so it wakes in a moment); on USB it
  only blanks the screen, so the REPL stays usable.
* The crown wakes a dark screen. In any app but the watch face it goes back
  to the face; on the face it turns the screen off.

An app borrows all of this: it imports this module, reads ``rtc``,
``battery``, ``accel`` and the rest, and calls ``use(scope, update)`` so the
screen's tick calls its ``update()`` while the screen is on. Nothing an app
makes here outlives it.
"""

import time

import board_config as board
from board_config import display_drv
import display_driver  # noqa: F401  (wires LVGL to the display and inputs)
from display_driver import app  # noqa: F401
import lvgl as lv

# -- settings ---------------------------------------------------------------

DIM_AFTER_S = 12  # idle seconds before the screen dims
DARK_AFTER_S = 18  # ... and goes dark (and, on battery, the watch sleeps)
DIM_LEVEL = 0.15
TICK_MS = 250

PERIPHERALS = getattr(board, "PERIPHERALS", frozenset())
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _role(name):
    """A board role, or None when the board hasn't got it or it fails."""
    if name not in PERIPHERALS:
        return None
    try:
        return getattr(board, name)
    except Exception as e:  # a chip that doesn't answer: apps show what's missing
        print("twatch: %s unavailable: %r" % (name, e))
        return None


rtc = _role("rtc")
battery = _role("battery")
accel = _role("accelerometer")
haptic = _role("haptic")
ir = _role("ir")
sleep = _role("sleep")
has_lora = "lora" in PERIPHERALS
has_mic = "pcm_in" in PERIPHERALS
has_speaker = "pcm_out" in PERIPHERALS

# The BMA423's feature engine: steps, wrist tilt, double tap. The chip keeps
# it loaded while the watch has power, so the step count survives a restart.
features = False
bma423 = None
if accel is not None and hasattr(accel, "load_features"):
    try:
        import bma423

        accel.load_features()
        accel.enable_features(bma423.STEP_COUNTER | bma423.ACTIVITY | bma423.WRIST_WEAR | bma423.DOUBLE_TAP)
        accel.map_interrupts(bma423.INT_WRIST_WEAR | bma423.INT_DOUBLE_TAP)
        features = True
    except Exception as e:
        print("twatch: no step counter or gestures: %r" % (e,))
wake_on_tilt = features
wake_on_tap = features

EVENTS = []  # the last few things that happened, newest last (read them at the REPL)


def event(text):
    """Note an event without printing: a console nobody reads must never
    hold the watch up."""
    EVENTS.append(text)
    if len(EVENTS) > 40:
        del EVENTS[0]


def ticks():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.monotonic() * 1000)


def buzz(*effects):
    if haptic is not None:
        haptic.play(*effects)


# -- look ---------------------------------------------------------------------

base = lv.screen_active()  # shown between apps; each app loads its own screen
W, H = base.get_width(), base.get_height()
font = getattr(lv, "font_montserrat_16", None) or lv.font_default()
small = getattr(lv, "font_montserrat_14", None) or font
big = getattr(lv, "font_montserrat_40", None) or getattr(lv, "font_montserrat_32", None) or font
huge = getattr(lv, "font_montserrat_48", None) or big
try:
    lv.display_get_default().set_theme(
        lv.theme_default_init(
            lv.display_get_default(), lv.palette_main(lv.PALETTE.TEAL), lv.palette_main(lv.PALETTE.AMBER), True, font
        )
    )
except AttributeError:
    pass
base.set_style_bg_color(lv.color_hex(0x000000), 0)
MUTED = lv.palette_main(lv.PALETTE.GREY)
ACCENT = lv.palette_main(lv.PALETTE.TEAL)


# -- time and battery, which more than one app shows ---------------------------


def now():
    """``(year, month, day, weekday, hour, minute, second)`` from the RTC,
    or the interpreter's clock without one."""
    if rtc is not None:
        try:
            return rtc.datetime()[:7]
        except Exception:
            pass
    t = time.localtime()
    return (t[0], t[1], t[2], t[6], t[3], t[4], t[5])


def battery_text():
    if battery is None:
        return "no battery reading"
    status = getattr(battery, "battery_status", None)
    if status in ("missing", "dead"):
        return "battery missing or dead"
    pct = battery.percent
    text = "%d%%" % pct if pct is not None else "%.2f V" % battery.voltage
    if status == "charging":
        text += ", charging"
    elif status == "full":
        text += ", full"
    return text


# -- the running app ---------------------------------------------------------------

launcher = None  # set by main.py
_update = None


def use(scope, update=None):
    """Called by an app's ``main(scope)``: the screen's tick calls *update*
    while the screen is on, until the app closes."""
    global _update
    _update = update

    def _forget():
        global _update
        _update = None

    scope.on_close(_forget)


def go(name):
    """Switch to app *name* after the current callback."""
    if launcher is not None and launcher.current != name:
        launcher.request(name)


def refresh():
    if _update is not None:
        try:
            _update()
        except Exception as e:  # a failing app must not stop the screen's tick
            event("update failed: %r" % (e,))


# -- the screen, the crown and sleep ---------------------------------------------------


class RaiseDetector:
    """Raise-to-look from the acceleration, in the watch's frame (X toward
    the hand, Y toward 12 o'clock, Z out of the face).

    The BMA423's own wrist-tilt gesture catches a raise from an arm hanging
    down, but not a glance from a desk, where the face is already up. This
    catches both: the watch settles face up and tilted toward you (12 o'clock
    raised) after being somewhere else within the last ``window_ms``."""

    def __init__(self, window_ms=1500):
        self.window_ms = window_ms
        self._away_at = None
        self._view = 0

    @staticmethod
    def viewing(x, y, z):
        return z > 0.6 and y > 0.28 and -0.45 < x < 0.6

    def feed(self, xyz, now):
        x, y, z = xyz
        if self.viewing(x, y, z):
            self._view += 1
            fresh = self._away_at is not None and now - self._away_at < self.window_ms
            if self._view == 2 and fresh:
                return True
        else:
            self._view = 0
            if y < 0.12 or x < -0.6 or z < 0.4:
                self._away_at = now
        return False


raise_detector = RaiseDetector()

screen = "on"  # on, dim, dark
brightness = 1.0
_dimmed_at = ticks()  # when the screen last left "on"
woke_at = ticks()  # when it last came on


def awake_for():
    """Milliseconds the screen has been on, or 0 when it's dim or dark: a
    tap that woke the screen shouldn't also press what it landed on."""
    return ticks() - woke_at if screen == "on" else 0


def set_brightness(level):
    global brightness
    brightness = level
    if screen == "on":
        display_drv.brightness = level


def wake_screen():
    global screen, woke_at
    if screen != "on":
        woke_at = ticks()
    screen = "on"
    # A gesture isn't input to LVGL: count it as some, or the next tick
    # dims the screen again at once.
    lv.display_get_default().trigger_activity()
    display_drv.brightness = brightness
    refresh()


def screen_off():
    global screen, _dimmed_at
    if screen == "on":
        _dimmed_at = ticks()
    screen = "dark"
    display_drv.brightness = 0
    if features:
        accel.interrupt_status()  # forget gestures from while the screen was on
    if sleep is not None and battery is not None and not getattr(battery, "vbus_present", True):
        doze()


def _wake_sources():
    sources = ["crown", "touch"]
    if wake_on_tilt or wake_on_tap:
        sources.append("motion")
    return tuple(sources)


def _set_gestures(any_motion=False):
    if features:
        accel.map_interrupts(bma423.INT_WRIST_WEAR, wake_on_tilt)
        accel.map_interrupts(bma423.INT_DOUBLE_TAP, wake_on_tap)
        # Any motion wakes the watch for a moment to look for a raise the
        # chip's own gesture misses (a glance from a desk).
        accel.set_any_motion(any_motion and wake_on_tilt)
        accel.map_interrupts(bma423.INT_ANY_MOTION, any_motion and wake_on_tilt)


def _raised_since_motion():
    """After an any-motion wake: watch the acceleration for a moment."""
    raise_detector._away_at = ticks()  # it was moving, so it wasn't being looked at
    for _ in range(12):
        if raise_detector.feed(accel.acceleration, ticks()):
            return True
        time.sleep_ms(100)
    return False


def doze():
    """Light sleep until the crown, a touch or a gesture; then the screen comes back."""
    _set_gestures(any_motion=True)
    while True:
        why = sleep(wake=_wake_sources())
        if why != "motion":
            break
        st = accel.interrupt_status()
        if st & (bma423.INT_WRIST_WEAR | bma423.INT_DOUBLE_TAP):
            why = "wrist tilt" if st & bma423.INT_WRIST_WEAR else "double tap"
            break
        if _raised_since_motion():
            why = "raise"
            break
    _set_gestures()
    event("woke from sleep by " + why)
    if hasattr(battery, "key_events"):
        battery.key_events()  # the crown press that woke us mustn't also turn the screen off
    buzz(1)
    wake_screen()


def deep_sleep():
    """Deep sleep: the watch restarts when it wakes, into the watch face."""
    display_drv.brightness = 0
    _set_gestures()
    sleep(deep=True, wake=_wake_sources())


# The crown is the board's keypad (ENTER). It gets a group of its own, holding
# one invisible object on the system layer, so it never presses an app's
# buttons and works whichever app's screen is showing.
_crown_group = lv.group_create()
_crown_catcher = lv.obj(lv.layer_sys())
_crown_catcher.remove_style_all()
_crown_catcher.set_size(1, 1)
_crown_group.add_obj(_crown_catcher)


def _on_crown(e):
    if e.get_key() != lv.KEY.ENTER:
        return
    event("crown")
    if screen != "on":
        wake_screen()
    elif launcher is not None and launcher.current != "face":
        go("face")
    else:
        screen_off()


_crown_catcher.add_event_cb(_on_crown, lv.EVENT.KEY, None)
# display_driver keeps each input device's LVGL indev in its user_data, and
# put the keypad in the default group, where ENTER would press the focused
# widget. (The bindings have no lv.indev_get_next to walk the indevs with.)
for _dev in app.devices:
    _indev = getattr(_dev, "user_data", None)
    if _indev is not None and _indev.get_type() == lv.INDEV_TYPE.KEYPAD:
        _indev.set_group(_crown_group)
_dev = _indev = None


def _tick(_t):
    global screen, _dimmed_at
    idle = lv.display_get_default().get_inactive_time()
    since = ticks() - _dimmed_at
    # touched since the screen dimmed (not counting the crown's own release)
    if screen != "on" and since > 800 and idle + 50 < since:
        event("woke by touch")
        wake_screen()
        return
    if features and screen != "on":
        # a gesture while dim or dark (on USB, where the watch doesn't sleep)
        st = accel.interrupt_status()
        raised = wake_on_tilt and raise_detector.feed(accel.acceleration, ticks())
        if (st & bma423.INT_WRIST_WEAR and wake_on_tilt) or (st & bma423.INT_DOUBLE_TAP and wake_on_tap) or raised:
            what = "wrist tilt" if st & bma423.INT_WRIST_WEAR else "double tap" if st & bma423.INT_DOUBLE_TAP else "raise"
            event("woke by " + what)
            wake_screen()
            return
    if screen == "dark":
        return
    if screen == "on" and idle > DIM_AFTER_S * 1000:
        screen = "dim"
        _dimmed_at = ticks()
        display_drv.brightness = min(brightness, DIM_LEVEL)
    elif screen == "dim" and idle > DARK_AFTER_S * 1000:
        screen_off()
        return
    refresh()


_timer = lv.timer_create(_tick, TICK_MS, None)
