# deps: lvgl
# gallery: skip
"""
wristwatch.py -- a watch you can wear, for the LILYGO T-Watch S3.

Swipe left and right between six pages:

* **Time**: the clock (from the watch's battery-backed RTC), the date, the
  battery and today's steps.
* **Steps**: the step counter, what you're doing (still, walking, running),
  the accelerometer live, and whether a wrist tilt or a double tap wakes the
  screen.
* **Remote**: Home, volume and mute for a Roku TV, sent from the watch's IR
  LED. Point the watch at the TV.
* **Sound**: a beep from the speaker, the microphone's level, and vibration
  patterns.
* **Power**: battery voltage, charge and state, screen brightness, and sleep.
* **LoRa**: the radio's identity, a test packet, and listening for activity.

The screen dims, then goes dark, when you leave it alone. Wake it with the
crown, a touch, a wrist tilt or a double tap. On battery the watch sleeps
while the screen is dark (light sleep, so it wakes in a moment). On USB it
only blanks the screen, so the REPL stays usable. A press of the crown also
turns the screen off and on.

Everything is found through ``board_config`` roles, so a page whose hardware
is missing shows what's missing instead. On CircuitPython (with LVGL), the
time, steps and motion, remote, vibration and battery pages work; the beep,
the microphone, sleep and LoRa are MicroPython-only, because they use
``pcm_out``, ``pcm_in``, ``sleep`` and ``lora``, which the CircuitPython
config doesn't have.

Set ``LORA_MHZ`` to a frequency your region allows before sending (915 MHz
suits the Americas; Europe uses 868, much of Asia 433), and ``TV_*`` if your
TV isn't a Roku. The clock reads the RTC as local time; set it once with
``board_config.rtc.datetime((year, month, day, weekday, hour, minute,
second, 0))``.
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
LORA_MHZ = 915.0
LORA_DBM = 10
# Roku TV infrared codes: extended NEC, address 0xEA 0xC7.
TV_ADDRESS = (0xEA, 0xC7)
TV_KEYS = (("Home", 0x03), ("Vol +", 0x0F), ("Vol -", 0x10), ("Mute", 0x20))
# DRV2605 library effects (TI's numbering): name, sequence. A number above 128
# is a pause of (n - 128) x 10 ms.
BUZZ_PATTERNS = (("Tap", (1,)), ("Double", (10,)), ("Buzz", (47,)), ("Alarm", (52, 128 + 20, 52, 128 + 20, 52)))

PERIPHERALS = getattr(board, "PERIPHERALS", frozenset())
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _role(name):
    """A lazy board role, or None when the board hasn't got it or it fails."""
    if name not in PERIPHERALS:
        return None
    try:
        return getattr(board, name)
    except Exception as e:  # a chip that doesn't answer: show the page without it
        print("wristwatch: %s unavailable: %r" % (name, e))
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

# The BMA423's feature engine: steps, wrist tilt, double tap. Loading it is
# skipped when it's already running, so the step count survives a restart.
features = False
if accel is not None and hasattr(accel, "load_features"):
    try:
        import bma423

        accel.load_features()
        accel.enable_features(bma423.STEP_COUNTER | bma423.ACTIVITY | bma423.WRIST_WEAR | bma423.DOUBLE_TAP)
        accel.map_interrupts(bma423.INT_WRIST_WEAR | bma423.INT_DOUBLE_TAP)
        features = True
    except Exception as e:
        print("wristwatch: no step counter or gestures: %r" % (e,))
wake_on_tilt = features
wake_on_tap = features


def _ticks():
    try:
        return time.ticks_ms()
    except AttributeError:
        return int(time.monotonic() * 1000)


# -- look ---------------------------------------------------------------------

scr = lv.screen_active()
W, H = scr.get_width(), scr.get_height()
_font = getattr(lv, "font_montserrat_16", None) or lv.font_default()
_small = getattr(lv, "font_montserrat_14", None) or _font
_big = getattr(lv, "font_montserrat_40", None) or getattr(lv, "font_montserrat_32", None) or _font
_huge = getattr(lv, "font_montserrat_48", None) or _big
try:
    lv.display_get_default().set_theme(
        lv.theme_default_init(
            lv.display_get_default(), lv.palette_main(lv.PALETTE.TEAL), lv.palette_main(lv.PALETTE.AMBER), True, _font
        )
    )
except AttributeError:
    pass
scr.set_style_bg_color(lv.color_hex(0x000000), 0)
scr.set_style_text_font(_font, 0)
MUTED = lv.palette_main(lv.PALETTE.GREY)
ACCENT = lv.palette_main(lv.PALETTE.TEAL)

tiles = lv.tileview(scr)
tiles.set_size(W, H)
tiles.set_style_bg_opa(lv.OPA.TRANSP, 0)
tiles.remove_flag(lv.obj.FLAG.SCROLL_ELASTIC)
_pages = []


def page(title):
    n = len(_pages)
    left = lv.DIR.LEFT if n else 0
    t = tiles.add_tile(n, 0, left | lv.DIR.RIGHT)
    t.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    t.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    t.set_style_pad_all(8, 0)
    t.set_style_pad_row(6, 0)
    if title:
        lbl = lv.label(t)
        lbl.set_text(title)
        lbl.set_style_text_color(ACCENT, 0)
    _pages.append(t)
    return t


def label(parent, text="", font=None, color=None):
    lbl = lv.label(parent)
    lbl.set_text(text)
    if font is not None:
        lbl.set_style_text_font(font, 0)
    if color is not None:
        lbl.set_style_text_color(color, 0)
    return lbl


def row(parent):
    r = lv.obj(parent)
    r.remove_style_all()
    r.set_size(lv.pct(100), lv.SIZE_CONTENT)
    r.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
    r.set_flex_align(lv.FLEX_ALIGN.SPACE_EVENLY, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
    r.set_style_pad_row(6, 0)
    return r


def button(parent, text, cb, width=None):
    b = lv.button(parent)
    if width:
        b.set_width(width)
    lbl = lv.label(b)
    lbl.set_text(text)
    lbl.center()
    b.add_event_cb(lambda e: cb(), lv.EVENT.CLICKED, None)
    return b


def missing(parent, what):
    label(parent, what, _small, MUTED)


# -- page 1: time ---------------------------------------------------------------

p_time = page(None)
p_time.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
lbl_time = label(p_time, "--:--", _huge)
lbl_secs = label(p_time, "", _font, MUTED)
lbl_date = label(p_time, "", _font)
lbl_face_batt = label(p_time, "", _small, MUTED)
lbl_face_steps = label(p_time, "", _small, MUTED)


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


def update_face():
    y, mo, d, wd, h, mi, s = now()
    lbl_time.set_text("%02d:%02d" % (h, mi))
    lbl_secs.set_text("%02d" % s)
    lbl_date.set_text("%s %d %s" % (WEEKDAYS[wd % 7], d, MONTHS[(mo - 1) % 12]))
    lbl_face_batt.set_text(battery_text())
    lbl_face_steps.set_text("%d steps" % accel.steps if features else "")


# -- page 2: steps and motion -------------------------------------------------------

p_steps = page("Steps")
lbl_steps = label(p_steps, "-", _big)
lbl_activity = label(p_steps, "", _small, MUTED)
lbl_accel = label(p_steps, "", _small)
if features:
    r = row(p_steps)

    def _toggle(attr, sw):
        def cb(e):
            globals()[attr] = sw.has_state(lv.STATE.CHECKED)

        return cb

    for attr, text in (("wake_on_tilt", "Tilt wakes"), ("wake_on_tap", "2 taps wake")):
        cell = lv.obj(r)
        cell.remove_style_all()
        cell.set_size(lv.SIZE_CONTENT, lv.SIZE_CONTENT)
        cell.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        cell.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        label(cell, text, _small)
        sw = lv.switch(cell)
        sw.add_state(lv.STATE.CHECKED)
        sw.add_event_cb(_toggle(attr, sw), lv.EVENT.VALUE_CHANGED, None)
    button(p_steps, "Reset steps", lambda: accel.reset_steps())
elif accel is None:
    missing(p_steps, "no accelerometer")
else:
    missing(p_steps, "no step counter on this chip")


def update_steps():
    if features:
        lbl_steps.set_text("%d" % accel.steps)
        lbl_activity.set_text(accel.activity)
    if accel is not None:
        x, y, z = accel.acceleration
        lbl_accel.set_text("x %+.2f  y %+.2f  z %+.2f g" % (x, y, z))


# -- page 3: TV remote ---------------------------------------------------------------

p_remote = page("TV remote")
lbl_ir = label(p_remote, "Point the watch at the TV", _small, MUTED)
if ir is not None:
    from ir_nec import send as ir_send

    r = row(p_remote)

    def _ir(name, code):
        def cb():
            ir_send(ir, TV_ADDRESS[0], code, address2=TV_ADDRESS[1], repeats=1)
            lbl_ir.set_text("sent %s" % name)
            if haptic is not None:
                haptic.play(1)

        return cb

    for name, code in TV_KEYS:
        button(r, name, _ir(name, code), width=W // 2 - 16)
else:
    missing(p_remote, "no IR LED")


# -- page 4: sound and vibration ------------------------------------------------------

p_sound = page("Sound")
_out = None
_mic = None
_mic_buf = None
mic_on = False
r = row(p_sound)


def beep():
    global _out
    import math

    from audiodev import AudioFormat

    if _out is None:
        _out = board.pcm_out(AudioFormat(16000, 1, 16))
    n = 16000 * 150 // 1000
    buf = bytearray(2 * n)
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * 1000 * i / 16000))
        buf[2 * i] = v & 0xFF
        buf[2 * i + 1] = (v >> 8) & 0xFF
    _out.write(buf)


if has_speaker:
    button(r, "Beep", beep)
if has_mic:

    def toggle_mic():
        global mic_on, _mic, _mic_buf
        mic_on = not mic_on
        if mic_on and _mic is None:
            _mic = board.pcm_in()
            _mic_buf = bytearray(1024)
        btn_mic_lbl.set_text("Mic off" if mic_on else "Mic on")

    btn_mic = lv.button(r)
    btn_mic_lbl = label(btn_mic, "Mic on")
    btn_mic_lbl.center()
    btn_mic.add_event_cb(lambda e: toggle_mic(), lv.EVENT.CLICKED, None)
    mic_bar = lv.bar(p_sound)
    mic_bar.set_width(lv.pct(90))
    mic_bar.set_range(0, 90)
    lbl_mic = label(p_sound, "", _small, MUTED)
if not has_speaker and not has_mic:
    missing(p_sound, "no speaker or microphone role")
if haptic is not None:
    r = row(p_sound)
    for name, seq in BUZZ_PATTERNS:
        button(r, name, (lambda s: lambda: haptic.play(*s))(seq), width=W // 2 - 16)
else:
    missing(p_sound, "no vibration motor")


def update_mic():
    import math

    if not (has_mic and mic_on and _mic is not None):
        return
    n = _mic.readinto(_mic_buf)
    peak = 0
    acc = 0
    count = n // 2
    for i in range(0, n, 2):
        v = _mic_buf[i] | (_mic_buf[i + 1] << 8)
        if v & 0x8000:
            v -= 0x10000
        acc += v * v
        if abs(v) > peak:
            peak = abs(v)
    rms = math.sqrt(acc / count) if count else 0
    db = 20 * math.log10(rms / 32768) if rms > 0 else -90
    mic_bar.set_value(int(max(0, 90 + db)), 0)
    lbl_mic.set_text("%.0f dBFS" % db)


# -- page 5: power ------------------------------------------------------------------

p_power = page("Power")
lbl_power = label(p_power, "", _small)
label(p_power, "Brightness", _small, MUTED)
brightness = 1.0
slider = lv.slider(p_power)
slider.set_width(lv.pct(85))
slider.set_range(5, 100)
slider.set_value(100, 0)


def _on_bright(e):
    global brightness
    brightness = slider.get_value() / 100
    display_drv.brightness = brightness


slider.add_event_cb(_on_bright, lv.EVENT.VALUE_CHANGED, None)
r = row(p_power)
button(r, "Screen off", lambda: screen_off())
if sleep is not None:
    button(r, "Deep sleep", lambda: deep_sleep())


def update_power():
    if battery is None:
        lbl_power.set_text("no battery reading")
        return
    lines = [battery_text()]
    v = battery.voltage
    if v is not None:
        lines.append("battery %.2f V" % v)
    state = getattr(battery, "charge_state", None)
    if state is not None:
        lines.append("charger: " + state)
    vbus = getattr(battery, "vbus_voltage", None)
    if vbus:
        lines.append("USB %.2f V" % vbus)
    lbl_power.set_text("\n".join(lines))


# -- page 6: LoRa ---------------------------------------------------------------------

p_lora = page("LoRa")
lbl_lora = label(p_lora, "", _small)
_radio = None
_pings = 0


def radio():
    global _radio
    if _radio is None:
        _radio = board.lora
        _radio.configure(LORA_MHZ, sf=9, power_dbm=LORA_DBM)
    return _radio


def lora_ping():
    global _pings
    try:
        _pings += 1
        ms = radio().send(b"wristwatch %d" % _pings)
        lbl_lora.set_text("%s\nsent #%d, %d ms on air\nat %.1f MHz" % (radio().version, _pings, ms, LORA_MHZ))
    except Exception as e:
        lbl_lora.set_text("send failed: %r" % (e,))


def lora_listen():
    try:
        busy = radio().channel_active()
        lbl_lora.set_text("%s\nchannel %s\nat %.1f MHz" % (radio().version, "busy" if busy else "quiet", LORA_MHZ))
    except Exception as e:
        lbl_lora.set_text("CAD failed: %r" % (e,))


if has_lora:
    try:
        lbl_lora.set_text("%s\n%s\ntap Send or Listen" % (board.lora.version, board.lora.status[0]))
        r = row(p_lora)
        button(r, "Send", lora_ping)
        button(r, "Listen", lora_listen)
    except Exception as e:
        lbl_lora.set_text("radio not answering: %r" % (e,))
else:
    missing(p_lora, "no LoRa radio role")


# -- the screen, the crown and sleep ---------------------------------------------------

screen = "on"  # on, dim, dark
_last_input = _ticks()


def wake_screen():
    global screen, _last_input
    screen = "on"
    _last_input = _ticks()
    display_drv.brightness = brightness
    update_all()


def screen_off():
    global screen
    screen = "dark"
    display_drv.brightness = 0
    if sleep is not None and battery is not None and not getattr(battery, "vbus_present", True):
        doze()


def _wake_sources():
    sources = ["crown", "touch"]
    if wake_on_tilt or wake_on_tap:
        sources.append("motion")
    return tuple(sources)


def _set_gestures():
    if features:
        accel.map_interrupts(bma423.INT_WRIST_WEAR, wake_on_tilt)
        accel.map_interrupts(bma423.INT_DOUBLE_TAP, wake_on_tap)


def doze():
    """Light sleep until the crown, a touch or a gesture; then the screen comes back."""
    _set_gestures()
    why = sleep(wake=_wake_sources())
    print("wristwatch: woke on", why)
    if hasattr(battery, "key_events"):
        battery.key_events()  # the crown press that woke us mustn't also turn the screen off
    if haptic is not None:
        haptic.play(1)
    wake_screen()


def deep_sleep():
    """Deep sleep: the watch restarts when it wakes, and comes back to the REPL
    (or main.py)."""
    display_drv.brightness = 0
    _set_gestures()
    sleep(deep=True, wake=_wake_sources())


# The crown is the board's keypad (ENTER). It gets a group of its own, holding
# one invisible object, so it toggles the screen instead of pressing buttons.
_crown_group = lv.group_create()
_crown_catcher = lv.obj(scr)
_crown_catcher.remove_style_all()
_crown_catcher.set_size(1, 1)
_crown_group.add_obj(_crown_catcher)


def _on_crown(e):
    if e.get_key() == lv.KEY.ENTER:
        if screen == "on":
            screen_off()
        else:
            wake_screen()


_crown_catcher.add_event_cb(_on_crown, lv.EVENT.KEY, None)
_next_indev = getattr(lv, "indev_get_next", None)
_indev = _next_indev(None) if _next_indev else None
while _indev is not None:
    if _indev.get_type() == lv.INDEV_TYPE.KEYPAD:
        _indev.set_group(_crown_group)
    _indev = _next_indev(_indev)


def update_all():
    update_face()
    update_steps()
    update_power()


def _tick(_t):
    global screen
    idle = lv.display_get_default().get_inactive_time()
    if screen != "on" and idle < 500:
        wake_screen()  # touched while dim or dark
        return
    if features and screen != "on":
        # a gesture while dark (on USB, where the watch doesn't sleep)
        st = accel.interrupt_status()
        if (st & bma423.INT_WRIST_WEAR and wake_on_tilt) or (st & bma423.INT_DOUBLE_TAP and wake_on_tap):
            wake_screen()
            return
    if screen == "dark":
        return
    if screen == "on" and idle > DIM_AFTER_S * 1000:
        screen = "dim"
        display_drv.brightness = min(brightness, DIM_LEVEL)
    elif screen == "dim" and idle > DARK_AFTER_S * 1000:
        screen_off()
        return
    active = tiles.get_tile_active()
    update_face()
    if active is p_steps:
        update_steps()
    elif active is p_power:
        update_power()
    elif active is p_sound:
        update_mic()


update_all()
lv.timer_create(_tick, 250, None)
