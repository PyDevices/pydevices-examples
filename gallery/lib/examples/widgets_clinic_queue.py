# gallery: featured
# deps: pdwidgets
"""
widgets_clinic_queue
====================================================
Clinic front-desk check-in kiosk with tabs, navigator, and forms.

Warm linen / teal / terracotta palette. Browse today's appointments, walk-in
registration with consent controls, and a help FAQ — all fake data with toasts
and a confirm dialog.
"""

import board_config
import board_config
import appdev

app = appdev.App(board_config)
import pdwidgets as pd
from pdwidgets import pct

pd.DEBUG = False

display = pd.Display(board_config.display_drv, app)
pal = display.pal

W = display.width
H = display.height
unit = min(W, H)
pad = max(3, unit // 64)
radius = max(4, unit // 40)
text_scale = max(1, unit // 280)
btn_style = "flat" if W * H >= 480 * 480 else "raised"

BG = pal.color565(0xF4, 0xF1, 0xDE)
SURFACE = pal.color565(0xFF, 0xFF, 0xFF)
PRIMARY = pal.color565(0x0B, 0x3D, 0x3A)
ACCENT = pal.color565(0xE0, 0x7A, 0x5F)
TEXT = pal.color565(0x1A, 0x1A, 0x2E)
MUTED = pal.color565(0x6B, 0x70, 0x5C)
SUCCESS = pal.color565(0x58, 0x81, 0x57)
CHIP_BG = pal.color565(0xE8, 0xE4, 0xD0)

screen = pd.Screen(display, bg=BG, visible=False)
toast = pd.Toast(screen)
keyboard = pd.Keyboard(screen, visible=False)

nav = pd.Navigator(screen)
root = pd.Page(nav, title="Root", bg=BG)
detail = pd.Page(nav, title="Detail", bg=SURFACE, visible=False)

_state = {"queue": 14, "badge": False}

menu = pd.Menu(
    screen,
    items=[
        ("English", lambda: toast.show("Language: English")),
        ("Espanol", lambda: toast.show("Idioma: Espanol")),
        ("About", lambda: toast.show("Riverside Clinic kiosk")),
    ],
)


def go_back(_=None):
    nav.pop()
    root_bar.on_back = None
    if root_bar.back_button:
        root_bar.back_button.visible = False
    root_bar.set_title("Check-in")


root_bar = pd.AppBar(root, title="Check-in", bg=PRIMARY, fg=SURFACE)
queue_badge = pd.Badge(
    root_bar,
    value=str(_state["queue"]),
    align=pd.ALIGN.RIGHT,
    x=-pad * 2,
    bg=ACCENT,
    visible=False,
)
pd.DigitalClock(root_bar, align=pd.ALIGN.RIGHT, x=-pad * 8, fg=SURFACE, bg=PRIMARY)


def open_menu(_=None, _e=None):
    menu.show()


pd.IconButton(
    root_bar,
    align=pd.ALIGN.RIGHT,
    x=-pad,
    icon_file=pd.icon_theme.menu(pd.ICON_SIZE.SMALL),
    fg=SURFACE,
    bg=PRIMARY,
).add_event_cb(pd.events.MOUSEBUTTONDOWN, open_menu)

# --- Tab pages -----------------------------------------------------------
today = pd.Page(root, title="Today", bg=BG, visible=False)
walkin = pd.Page(root, title="Walk-in", bg=BG, visible=False)
help_tab = pd.Page(root, title="Help", bg=BG, visible=False)

content_y = root_bar.height
content_h = root.height - content_y

# Today tab: chips + list
seg_today = pd.SegmentedControl(
    today,
    labels=["Morning", "Afternoon"],
    x=pad,
    y=8,
    w=today.width - 2 * pad,
    value=0,
    style=btn_style,
)
chip_y = 8 + seg_today.height + 6
chip_row = pd.Row(today, x=pad, y=chip_y, w=today.width - 2 * pad, spacing=6)
chips = []
for i, name in enumerate(("All", "New", "Follow-up")):
    ch = pd.Chip(
        chip_row,
        label=name,
        value=(i == 0),
        style=btn_style,
        bg=CHIP_BG,
        fg=TEXT,
    )
    chips.append(ch)

list_y = chip_y + chip_row.height + 8
lv = pd.ListView(
    today,
    x=pad,
    y=list_y,
    w=today.width - pad * 2 - pd.ICON_SIZE.SMALL,
    h=content_h - list_y - pad,
    bg=SURFACE,
    fg=TEXT,
)
APPOINTMENTS = (
    ("09:15  Lee, A.", "Annual"),
    ("10:00  Park, J.", "Follow-up"),
    ("11:30  Diaz, M.", "Lab review"),
    ("14:00  Chen, L.", "New patient"),
)
appt_btns = []
for title, kind in APPOINTMENTS:
    btn = pd.Button(lv, label=title, h=28, radius=radius, style=btn_style, bg=SURFACE, fg=TEXT)
    appt_btns.append((btn, title, kind))

# Walk-in tab
wi_card = pd.Card(
    walkin,
    w=walkin.width - 2 * pad,
    h=content_h - pad * 2,
    y=pad,
    align=pd.ALIGN.TOP,
    title="Walk-in registration",
    bg=SURFACE,
    fg=TEXT,
    style=btn_style,
)
wi_col = pd.Column(wi_card, x=pad, y=28, w=wi_card.width - 2 * pad, spacing=8)
rg = pd.RadioGroup(wi_col)
pd.Label(wi_col, value="Visit type", fg=MUTED, bg=SURFACE)
rb_row = pd.Row(wi_col, spacing=8)
rb_opts = []
for i, label in enumerate(("Illness", "Injury", "Vaccine")):
    cell = pd.Row(rb_row, spacing=4)
    rb = pd.RadioButton(cell, group=rg, value=(i == 0), size=pd.ICON_SIZE.SMALL)
    pd.Label(cell, value=label, fg=TEXT, bg=SURFACE)
    rb_opts.append(rb)
consent_row = pd.Row(wi_col, spacing=6)
consent = pd.CheckBox(consent_row, value=False, size=pd.ICON_SIZE.SMALL)
pd.Label(consent_row, value="I consent to treatment", fg=TEXT, bg=SURFACE)
pd.Divider(wi_col, w=wi_col.width, fg=MUTED)
row_prov = pd.FormRow(wi_col, label="Provider", w=wi_col.width, fg=TEXT, bg=SURFACE)
provider_dd = pd.Dropdown(row_prov, options=["Any", "Dr. Kim", "Dr. Ortiz"], value="Any", w=100)
pd.Label(wi_col, value="Phone", fg=MUTED, bg=SURFACE)
phone_in = pd.TextInput(wi_col, w=wi_col.width, value="", max_length=14)


def _focus_phone(_s=None, _e=None):
    keyboard.show(target=phone_in)


phone_in.add_event_cb(pd.events.MOUSEBUTTONDOWN, _focus_phone)
checkin_btn = pd.Button(
    wi_col,
    label="Check in",
    radius=radius,
    style=btn_style,
    bg=ACCENT,
    fg=SURFACE,
)

# Help tab
faq_sv = pd.ScrollView(
    help_tab,
    x=pad,
    y=pad,
    w=help_tab.width - 2 * pad,
    h=content_h - 2 * pad,
    content_h=320,
    bg=SURFACE,
)
faq_lines = (
    "Where is parking?",
    "Use the garage behind the building.",
    "",
    "Do I need my ID?",
    "Yes — bring photo ID and insurance card.",
    "",
    "Can I reschedule?",
    "Call the front desk or use the patient portal.",
    "",
    "After-hours?",
    "Dial 911 for emergencies; urgent care opens at 8am.",
)
for i, line in enumerate(faq_lines):
    pd.Label(faq_sv, value=line, y=i * 22, x=4, w=faq_sv.width - 8, fg=TEXT if line else MUTED, bg=SURFACE)

tv = pd.TabView(
    root,
    y=content_y,
    h=content_h,
    tabs=[("Today", today), ("Walk-in", walkin), ("Help", help_tab)],
)

# --- Detail page (navigator push) ------------------------------------------
detail_bar = pd.AppBar(detail, title="Appointment", on_back=go_back, bg=PRIMARY, fg=SURFACE)
detail_body_h = detail.height - detail_bar.height

status_anchor = pd.Label(
    detail,
    value="Status",
    y=detail_bar.height + pad,
    x=pad,
    fg=MUTED,
    bg=SURFACE,
    scale=text_scale,
)
pd.Label(
    detail,
    align=pd.ALIGN.OUTER_RIGHT,
    align_to=status_anchor,
    value="OK",
    fg=SUCCESS,
    bg=SURFACE,
)
pd.Label(
    detail,
    align=pd.ALIGN.OUTER_TOP,
    align_to=status_anchor,
    value="Room 3B",
    fg=TEXT,
    bg=SURFACE,
)

detail_card = pd.Card(
    detail,
    w=detail.width - 2 * pad,
    h=detail_body_h - pad * 3 - 40,
    y=detail_bar.height + pad + 24,
    align=pd.ALIGN.TOP,
    title="Patient details",
    bg=SURFACE,
    fg=TEXT,
    style=btn_style,
)
dy = 28
pd.Label(detail_card, value="Name", x=pad, y=dy, fg=MUTED, bg=SURFACE)
name_box = pd.TextBox(detail_card, x=pad, y=dy + 16, w=detail_card.width - 2 * pad, value="", fg=TEXT, bg=SURFACE)
dy += 44
pd.Label(detail_card, value="Reason", x=pad, y=dy, fg=MUTED, bg=SURFACE)
reason_box = pd.TextBox(detail_card, x=pad, y=dy + 16, w=detail_card.width - 2 * pad, value="", fg=TEXT, bg=SURFACE)
dy += 44
row_rem = pd.FormRow(detail_card, label="Reminders", y=dy, w=detail_card.width - pad * 2, x=pad, fg=TEXT, bg=SURFACE)
pd.Switch(row_rem, value=True)
dy += row_rem.height + 8
row_step = pd.FormRow(detail_card, label="Arrive min early", y=dy, w=detail_card.width - pad * 2, x=pad, fg=TEXT, bg=SURFACE)
pd.NumberStepper(row_step, value=15, minimum=0, maximum=45, w=detail_card.width // 3)

footer = pd.Widget(
    detail,
    w=detail.width - 2 * pad,
    h=36,
    y=detail.height - pad - 36,
    align=pd.ALIGN.TOP,
    x=pad,
    bg=SURFACE,
)
confirm_btn = pd.Button(
    footer,
    label="Confirm arrival",
    align=pd.ALIGN.CENTER,
    w=pct.Width(70, footer),
    h=pct.Height(90, footer),
    radius=radius,
    style=btn_style,
    bg=PRIMARY,
    fg=SURFACE,
)

def _confirm_arrival(label):
    if label == "Confirm":
        toast.show("Checked in — thank you!")
        nav.pop()
        go_back()


def _show_confirm(_s=None, _e=None):
    pd.Dialog(
        screen,
        "Mark patient as arrived?",
        title="Confirm",
        buttons=["Cancel", "Confirm"],
        on_result=_confirm_arrival,
    ).show()


confirm_btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, _show_confirm)


def _open_detail(btn, title, kind):
    def handler(_s=None, _e=None):
        parts = title.split("  ", 1)
        name_box.set_value(parts[1] if len(parts) > 1 else title)
        reason_box.set_value(kind)
        nav.push(detail)
        root_bar.set_title("Detail")
        root_bar.on_back = go_back
        if root_bar.back_button:
            root_bar.back_button.visible = True

    return handler


for btn, title, kind in appt_btns:
    btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, _open_detail(btn, title, kind))


def _do_checkin(_s=None, _e=None):
    keyboard.hide_keyboard()
    if not consent.value:
        toast.show("Consent required")
        return
    _state["queue"] += 1
    queue_badge.value = str(_state["queue"])
    queue_badge.visible = True
    queue_badge.invalidate()
    toast.show("Queue #%d" % _state["queue"])


checkin_btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, _do_checkin)

nav.push(root)
screen.visible = True