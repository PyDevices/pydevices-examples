# deps: pdwidgets
# utils: audio
"""
widgets_locker_kiosk
====================================================
Parcel locker and community-room booking kiosk with audio feedback.

Plum / mint palette on a landscape grid (90-degree rotation on portrait panels).
Enter PIN 1234 to unlock a compartment; book a room with date and accent color.
Short UI blips via ``utils.audio.AudioEngine``.
"""

import board_config
import board_config
import appdev

app = appdev.App(board_config)
import pdwidgets as pd
from audio import AudioEngine

pd.DEBUG = False

display_drv = board_config.display_drv
if display_drv.width < display_drv.height:
    display_drv.rotation = (display_drv.rotation + 90) % 360

try:
    w = int(display_drv.width or 0)
    h = int(display_drv.height or 0)
    if w * h >= 480 * 480:
        pd.Display.tick_period = 100
    elif max(w, h) <= 400:
        pd.Display.tick_period = 50
except Exception:
    pass

display = pd.Display(display_drv, app)
pal = display.pal

W = display.width
H = display.height
unit = min(W, H)
pad = max(3, unit // 64)
radius = max(4, unit // 40)
btn_style = "flat" if W * H >= 480 * 480 else "raised"

BG = pal.color565(0x2D, 0x1B, 0x2E)
SURFACE = pal.color565(0x43, 0x2E, 0x38)
PRIMARY = pal.color565(0x7D, 0xCE, 0xA0)
ACCENT = pal.color565(0xF5, 0xE6, 0xCC)
PIN_FACE = pal.color565(0x1F, 0x15, 0x22)
OPEN = pal.color565(0x52, 0xB7, 0x88)
ERROR = pal.color565(0x9B, 0x22, 0x26)

eng = None
try:
    audio_out = board_config.audio_out
    eng = AudioEngine(audio_out, chunk_ms=40, master=0.45, wave="sine")
    eng.attach(app)
except Exception:
    pass

DEMO_PIN = "1234"

screen = pd.Screen(display, bg=BG, visible=False)
toast = pd.Toast(screen)

drawer = pd.Drawer(screen, title="Help")
pd.Label(drawer.content, value="Locker bay A — front desk ext. 204", y=36, x=pad, fg=ACCENT, bg=SURFACE)
pd.Label(drawer.content, value="Report damage via the sheet below.", y=56, x=pad, fg=ACCENT, bg=SURFACE)

sheet = pd.BottomSheet(screen, title="Report problem", h=H // 2)
acc = pd.Accordion(sheet.content, x=pad, y=36, w=sheet.content.width - 2 * pad, h=120)
acc_body1 = pd.Label(sheet.content, value="Door stuck — call maintenance.", visible=False, w=200, h=20, fg=ACCENT)
acc_body2 = pd.Label(sheet.content, value="Wrong parcel — leave note on locker.", visible=False, w=200, h=20, fg=ACCENT)
acc.add_panel("Hardware", acc_body1, open_=True)
acc.add_panel("Delivery", acc_body2)

bar = pd.AppBar(screen, title="Parcel Locker", bg=SURFACE, fg=ACCENT)
pd.IconButton(
    bar,
    align=pd.ALIGN.RIGHT,
    x=-pad,
    icon_file=pd.icon_theme.info(pd.ICON_SIZE.SMALL),
    fg=ACCENT,
    bg=SURFACE,
).add_event_cb(pd.events.MOUSEBUTTONDOWN, lambda _s=None, _e=None: drawer.show())  # help icon

body_y = bar.height + pad
left_w = W // 2 - pad

info_col = pd.Column(screen, x=pad, y=body_y, w=left_w, h=H - body_y - pad, spacing=6, bg=BG)
pd.Label(info_col, value="Scan or enter PIN", fg=ACCENT, bg=BG)
qr = pd.Image(
    info_col,
    w=min(80, left_w - pad),
    h=60,
    value=pd.icon_theme.home(pd.ICON_SIZE.XLARGE),
    bg=SURFACE,
)
status_box = pd.TextBox(info_col, w=left_w - pad, value="Select a locker", fg=ACCENT, bg=SURFACE, scale=1)
err_lbl = pd.Label(info_col, value="", fg=ERROR, bg=BG)
pwd = pd.PasswordField(info_col, hint="PIN", w=left_w - pad, h=28, max_length=6, bg=PIN_FACE, fg=ACCENT)

spinner = pd.Spinner(info_col, visible=False)
book_btn = pd.Button(info_col, label="Book room", radius=radius, style=btn_style, bg=PRIMARY, fg=BG)
sheet_btn = pd.Button(info_col, label="Report", radius=radius, style=btn_style, bg=SURFACE, fg=ACCENT)
notify_toggle = pd.ToggleButton(info_col, value=True, size=pd.ICON_SIZE.MEDIUM)
pd.Label(info_col, value="Notify", fg=ACCENT, bg=BG)
sound_toggle = pd.Toggle(
    info_col,
    on_file=pd.icon_theme.toggle_on(pd.ICON_SIZE.SMALL),
    off_file=pd.icon_theme.toggle_off(pd.ICON_SIZE.SMALL),
    value=True,
)
pd.Label(info_col, value="Sound", fg=ACCENT, bg=BG)

sv = pd.ScrollView(
    drawer.content,
    x=pad,
    y=80,
    w=drawer.content.width - 2 * pad,
    h=drawer.content.height - 90,
    content_h=160,
    bg=SURFACE,
)
for i, line in enumerate(("Code: 1234 demo PIN", "Hours: 6am–10pm", "Lost key? See front desk.")):
    pd.Label(sv, value=line, y=i * 22, x=4, fg=ACCENT, bg=SURFACE)

# Booking pickers (hidden until book flow)
picker_row = pd.Row(info_col, spacing=6, visible=False)
date_lbl = pd.TextBox(picker_row, value="2026-08-06", w=90, h=22, fg=ACCENT, bg=SURFACE, scale=1)
color_swatch = pd.TextBox(picker_row, value="mint", w=50, h=22, bg=PRIMARY, fg=BG, scale=1)
confirm_book = pd.Button(picker_row, label="Confirm", radius=radius, style=btn_style, bg=OPEN, fg=BG)

date_picker = pd.DatePicker(
    info_col,
    w=min(180, left_w),
    h=100,
    value=(2026, 8, 6),
    visible=False,
)
color_picker = pd.ColorPicker(
    info_col,
    w=min(140, left_w),
    h=80,
    visible=False,
)

right_x = left_w + pad * 2
grid = pd.Grid(
    screen,
    x=right_x,
    y=body_y,
    w=W - right_x - pad,
    h=H - body_y - pad - 110,
    columns=4,
    spacing=pad,
    bg=BG,
)
CELLS = []
for row in "ABCD":
    for col in "1234":
        lbl = row + col
        btn = pd.Button(
            grid,
            label=lbl,
            h=max(22, (H - body_y - pad - 110) // 4 - pad),
            radius=radius,
            style=btn_style,
            bg=SURFACE,
            fg=ACCENT,
        )
        CELLS.append((lbl, btn))

pad_widget = pd.PinPad(
    screen,
    x=right_x,
    y=H - 108,
    w=W - right_x - pad,
    h=100,
    target=pwd,
    bg=PIN_FACE,
    fg=ACCENT,
    max_length=6,
)

_state = {"selected": None, "open": set(), "booking": False, "task": None, "poll_n": 0}


def _blip(hz, ms=40):
    if eng is not None and sound_toggle.value:
        try:
            eng.blip(hz, ms=ms)
        except Exception:
            pass


def _on_digit(_d=None, _value=None):
    _blip(660, ms=25)


pad_widget.on_digit = _on_digit


def _validate_pin(v):
    if len(v or "") < 4:
        return "PIN too short"
    return None


form = pd.Form(on_commit=lambda vals: None, error_label=err_lbl)
form.add("pin", pwd, validator=_validate_pin)


def _tint_open(lbl):
    for name, btn in CELLS:
        if name == lbl:
            btn.bg = OPEN
            btn.fg = BG
            btn.invalidate()
            break


def _finish_fetch():
    spinner.stop()
    spinner.visible = False
    if _state["task"] is not None:
        try:
            display.remove_task(_state["task"])
        except ValueError:
            pass
        _state["task"] = None
    picker_row.visible = True
    date_picker.visible = True
    color_picker.visible = True


def _poll_fetch():
    _state["poll_n"] += 1
    if _state["poll_n"] >= 6:
        _finish_fetch()


def _start_book(_s=None, _e=None):
    _state["booking"] = True
    spinner.visible = True
    spinner.start()
    _state["poll_n"] = 0
    if _state["task"] is None:
        _state["task"] = display.add_task(_poll_fetch, 100)
    status_box.set_value("Loading calendar…")


def _on_pin_enter(pin):
    sel = _state["selected"]
    if not sel:
        err_lbl.set_value("Pick a locker first")
        return
    if pin == DEMO_PIN:
        _state["open"].add(sel)
        _tint_open(sel)
        status_box.set_value("Locker %s open" % sel)
        err_lbl.set_value("")
        _blip(880, ms=120)
        _blip(1175, ms=150)
        toast.show("Unlocked %s" % sel)
        pwd.value = ""
    else:
        err_lbl.set_value("Wrong PIN")
        _blip(220, ms=200)
        toast.show("Invalid PIN")


pad_widget.on_enter = _on_pin_enter


def _select_cell(lbl):
    def handler(_s=None, _e=None):
        _state["selected"] = lbl
        status_box.set_value("Locker %s — enter PIN" % lbl)
        err_lbl.set_value("")
        pwd.value = ""

    return handler


for lbl, btn in CELLS:
    btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, _select_cell(lbl))


def _on_date(w):
    y, m, d = w.value
    date_lbl.set_value("%04d-%02d-%02d" % (y, m, d))


def _on_color(w):
    color_swatch.bg = w.value
    color_swatch.invalidate()


date_picker.set_change_cb(_on_date)
color_picker.set_change_cb(_on_color)


def _confirm_booking(_s=None, _e=None):
    _blip(523, ms=80)
    toast.show("Room booked %s" % date_lbl.value)
    picker_row.visible = False
    date_picker.visible = False
    color_picker.visible = False
    status_box.set_value("Booking confirmed")


book_btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, _start_book)
sheet_btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, lambda _s=None, _e=None: sheet.show())
confirm_book.add_event_cb(pd.events.MOUSEBUTTONDOWN, _confirm_booking)

screen.visible = True