# deps: pdwidgets
"""
widgets_energy_panel
====================================================
Home energy / solar wall panel with live gauges, chart, and circuit controls.

Midnight palette with cyan solar, amber load, and mint battery arcs. Gauges and
chart values drift on a soft tick; slider and stepper adjust export limit and
alert threshold.
"""

import random

import board_config
import board_config
import appdev

app = appdev.App(board_config)
import pdwidgets as pd

pd.DEBUG = False

display_drv = board_config.display_drv
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

BG = pal.color565(0x1B, 0x26, 0x3B)
SURFACE = pal.color565(0x2A, 0x35, 0x48)
PRIMARY = pal.color565(0x00, 0xB4, 0xD8)
SECONDARY = pal.color565(0xFF, 0xB7, 0x03)
SUCCESS = pal.color565(0x06, 0xD6, 0xA0)
TEXT = pal.color565(0xE9, 0xEC, 0xEF)
MUTED = pal.color565(0x8D, 0x99, 0xAE)
GRID = pal.color565(0x41, 0x5A, 0x77)
WARN = pal.color565(0xEF, 0x47, 0x6F)

screen = pd.Screen(display, bg=BG, visible=False)
toast = pd.Toast(screen)

bar = pd.AppBar(screen, title="Home Energy", bg=SURFACE, fg=TEXT)
badge = pd.Badge(bar, value="", align=pd.ALIGN.RIGHT, x=-pad * 2, bg=WARN, visible=False)
pd.DigitalClock(bar, align=pd.ALIGN.RIGHT, x=-pad * 6, fg=MUTED, bg=SURFACE)

gauge_size = min(W // 3 - pad * 2, H // 5)
gauge_y = bar.height + pad
g_solar = pd.Gauge(
    screen,
    w=gauge_size,
    h=gauge_size,
    x=pad,
    y=gauge_y,
    value=0.55,
    fg=PRIMARY,
    bg=SURFACE,
    label="Solar",
)
g_load = pd.Gauge(
    screen,
    w=gauge_size,
    h=gauge_size,
    x=pad + gauge_size + pad,
    y=gauge_y,
    value=0.42,
    fg=SECONDARY,
    bg=SURFACE,
    label="Load",
)
g_batt = pd.Gauge(
    screen,
    w=gauge_size,
    h=gauge_size,
    x=pad + 2 * (gauge_size + pad),
    y=gauge_y,
    value=0.68,
    fg=SUCCESS,
    bg=SURFACE,
    label="Batt",
)

chart_h = max(48, H // 5)
chart_y = gauge_y + gauge_size + pad
_hist = [0.35, 0.42, 0.38, 0.5, 0.48, 0.55, 0.52, 0.58]
chart = pd.Chart(
    screen,
    x=pad,
    y=chart_y,
    w=W - 2 * pad,
    h=chart_h,
    mode="line",
    value=list(_hist),
    fg=PRIMARY,
    bg=SURFACE,
)

seg_y = chart_y + chart_h + pad
seg = pd.SegmentedControl(
    screen,
    labels=["Day", "Week"],
    x=pad,
    y=seg_y,
    w=W - 2 * pad,
    value=0,
    style=btn_style,
    bg=SURFACE,
    fg=TEXT,
)
chart_lbl = pd.Label(
    screen,
    value="24h production",
    x=pad,
    y=seg_y + seg.height + 2,
    fg=MUTED,
    bg=BG,
)

card = pd.Card(
    screen,
    w=W - 2 * pad,
    h=H - (seg_y + seg.height + 28) - pad,
    y=seg_y + seg.height + 20,
    align=pd.ALIGN.TOP,
    title="Circuits",
    bg=SURFACE,
    fg=TEXT,
    style=btn_style,
)

cy = 28
row_exp = pd.FormRow(card, label="Export %", y=cy, w=card.width - pad * 2, x=pad, fg=TEXT, bg=SURFACE)
export_slider = pd.Slider(row_exp, value=0.35, w=card.width // 2, step=0.05, fg=PRIMARY, bg=GRID)
cy += row_exp.height + 4

row_c1 = pd.FormRow(card, label="Kitchen", y=cy, w=card.width - pad * 2, x=pad, fg=TEXT, bg=SURFACE)
sw_kitchen = pd.Switch(row_c1, value=True)
cy += row_c1.height + 4

row_c2 = pd.FormRow(card, label="EV charger", y=cy, w=card.width - pad * 2, x=pad, fg=TEXT, bg=SURFACE)
sw_ev = pd.Switch(row_c2, value=False)
cy += row_c2.height + 4

row_thr = pd.FormRow(card, label="Alert kW", y=cy, w=card.width - pad * 2, x=pad, fg=TEXT, bg=SURFACE)
thr_step = pd.NumberStepper(row_thr, value=4, minimum=1, maximum=12, w=card.width // 3)
cy += row_thr.height + 8

budget_lbl = pd.Label(card, value="Daily budget", x=pad, y=cy, fg=MUTED, bg=SURFACE)
cy += 16
budget = pd.ProgressBar(
    card,
    x=pad,
    y=cy,
    w=card.width - 2 * pad,
    h=max(10, unit // 40),
    value=0.62,
    fg=SECONDARY,
    bg=GRID,
)
cy += budget.height + 8

status = pd.TextBox(
    card,
    x=pad,
    y=cy,
    w=card.width - 2 * pad,
    h=20,
    value="Grid: normal",
    fg=TEXT,
    bg=SURFACE,
    scale=1,
)
cy += 28

spike_btn = pd.Button(
    card,
    label="Sim spike",
    y=cy,
    align=pd.ALIGN.TOP,
    radius=radius,
    style=btn_style,
    bg=SECONDARY,
    fg=BG,
)

_state = {"solar": 0.55, "load": 0.42, "batt": 0.68, "warn": False, "budget": 0.62}


def _nudge(v, lo=0.05, hi=0.95, delta=0.04):
    return max(lo, min(hi, v + (random.random() - 0.5) * delta))


def _refresh_badges():
    thr = thr_step.value
    if _state["load"] * 10 >= thr and not _state["warn"]:
        _state["warn"] = True
        badge.value = "HIGH"
        badge.visible = True
        badge.invalidate()
        toast.show("Load above %d kW" % thr)
    elif _state["load"] * 10 < thr - 0.5:
        _state["warn"] = False
        badge.visible = False
        badge.invalidate()


def _live_tick(_=None):
    _state["solar"] = _nudge(_state["solar"], delta=0.03)
    _state["load"] = _nudge(_state["load"], delta=0.05)
    _state["batt"] = _nudge(_state["batt"], delta=0.02)
    g_solar.set_value(_state["solar"])
    g_load.set_value(_state["load"])
    g_batt.set_value(_state["batt"])
    _hist.pop(0)
    _hist.append(_state["solar"])
    chart.value = list(_hist)
    _state["budget"] = max(0.1, min(1.0, _state["budget"] + (random.random() - 0.52) * 0.02))
    budget.set_value(_state["budget"])
    status.set_value(
        "Export %.0f%%  Kitchen %s  EV %s"
        % (
            export_slider.value * 100,
            "on" if sw_kitchen.value else "off",
            "on" if sw_ev.value else "off",
        )
    )
    _refresh_badges()


def _on_seg(s):
    chart_lbl.set_value("24h production" if s.value == 0 else "7-day trend")


def _on_spike(_s=None, _e=None):
    _state["load"] = 0.92
    g_load.set_value(_state["load"])
    toast.show("Demand spike!")
    _refresh_badges()


seg.set_change_cb(_on_seg)
spike_btn.add_event_cb(pd.events.MOUSEBUTTONDOWN, _on_spike)

app.every(_live_tick, period=500, async_=app.timer_async)

screen.visible = True