# SPDX-License-Identifier: MIT
"""TPMS tire pressure / temperature."""

import lvgl as lv

import theme
from screens._common import content_size, prep_page, zero_pad


def _scale_2x(lbl):
    w = max(1, lbl.get_width())
    h = max(1, lbl.get_height())
    lbl.set_style_transform_pivot_x(w // 2, 0)
    lbl.set_style_transform_pivot_y(h // 2, 0)
    try:
        lbl.set_style_transform_scale(512, 0)
    except Exception:
        lbl.set_style_transform_scale_x(512, 0)
        lbl.set_style_transform_scale_y(512, 0)


def _scale_2x_bottom_right(lbl):
    """2× scale with BR pivot so growth stays inside the card."""
    w = max(1, lbl.get_width())
    h = max(1, lbl.get_height())
    lbl.set_style_transform_pivot_x(w, 0)
    lbl.set_style_transform_pivot_y(h, 0)
    try:
        lbl.set_style_transform_scale(512, 0)
    except Exception:
        lbl.set_style_transform_scale_x(512, 0)
        lbl.set_style_transform_scale_y(512, 0)


def _scale_2x_top_left(lbl):
    """2× scale with TL pivot — opposite of bottom-right temps."""
    lbl.set_style_transform_pivot_x(0, 0)
    lbl.set_style_transform_pivot_y(0, 0)
    try:
        lbl.set_style_transform_scale(512, 0)
    except Exception:
        lbl.set_style_transform_scale_x(512, 0)
        lbl.set_style_transform_scale_y(512, 0)


class TiresScreen:
    def __init__(self, page, vehicle, group, w=0, h=0):
        self.vehicle = vehicle
        w, h = content_size(prep_page(page, w, h), w, h)

        self.cards = []
        font = theme.pick_font(220, page)
        font_sm = theme.pick_font(180, page)
        gap = 8
        spare_h = 44
        cw = (w - gap * 3) // 2
        ch = (h - gap * 3 - spare_h) // 2
        positions = (
            (gap, gap),
            (gap + cw + gap, gap),
            (gap, gap + ch + gap),
            (gap + cw + gap, gap + ch + gap),
        )
        for i, tire in enumerate(vehicle.tires[:4]):
            x, y = positions[i]
            card = lv.obj(page)
            card.set_size(cw, ch)
            card.set_pos(x, y)
            zero_pad(card)
            theme.style_bg(
                card, theme.panel_raised(), radius=10, border_w=1, border_color=theme.accent_dim()
            )
            zero_pad(card)
            try:
                card.add_flag(lv.obj.FLAG.OVERFLOW_VISIBLE)
            except Exception:
                pass
            name = lv.label(card)
            name.set_text(tire["name"])
            name.set_style_text_color(theme.accent_lite(), 0)
            theme.apply_font(name, font_sm)
            zero_pad(name)
            name.align(lv.ALIGN.TOP_LEFT, 8, 8)
            psi = lv.label(card)
            psi.set_text("")
            psi.set_style_text_color(theme.text(), 0)
            theme.apply_font(psi, font)
            zero_pad(psi)
            psi.align(lv.ALIGN.CENTER, 0, -4)
            temp = lv.label(card)
            temp.set_text("")
            temp.set_style_text_color(theme.text_dim(), 0)
            theme.apply_font(temp, font_sm)
            zero_pad(temp)
            # Bottom-right of card, inset a little up and left.
            temp.align(lv.ALIGN.BOTTOM_RIGHT, -8, -8)
            self.cards.append((card, name, psi, temp))

        # Spare: single compact row — no large centered psi that looks like a stray
        spare = vehicle.tires[4]
        card = lv.obj(page)
        card.set_size(w - 2 * gap, spare_h)
        card.set_pos(gap, h - spare_h - gap)
        zero_pad(card)
        theme.style_bg(card, theme.panel(), radius=8, border_w=1, border_color=theme.chrome_mid())
        zero_pad(card)

        name = lv.label(card)
        name.set_text(spare["name"])
        name.set_style_text_color(theme.text_dim(), 0)
        theme.apply_font(name, font_sm)
        zero_pad(name)
        name.align(lv.ALIGN.LEFT_MID, 12, 0)

        psi = lv.label(card)
        psi.set_text("")
        psi.set_style_text_color(theme.text(), 0)
        theme.apply_font(psi, font_sm)
        zero_pad(psi)
        psi.align(lv.ALIGN.CENTER, 0, 0)

        temp = lv.label(card)
        temp.set_text("")
        temp.set_style_text_color(theme.text_dim(), 0)
        theme.apply_font(temp, font_sm)
        zero_pad(temp)
        temp.align(lv.ALIGN.RIGHT_MID, -12, 0)
        self.cards.append((card, name, psi, temp))
        self.update()

    def update(self):
        for i, (tire, entry) in enumerate(zip(self.vehicle.tires, self.cards)):
            _card, name_lbl, psi_lbl, temp_lbl = entry
            psi = tire["psi"]
            psi_lbl.set_text("%.1f psi" % psi)
            temp_lbl.set_text("%.0f °F" % tire["temp_f"])
            if psi < 30 or psi > 42:
                psi_lbl.set_style_text_color(theme.danger(), 0)
            elif psi < 32 or psi > 38:
                psi_lbl.set_style_text_color(theme.warn(), 0)
            else:
                psi_lbl.set_style_text_color(theme.ok(), 0)
            # Corner cards: keep all three lines at 2× after text changes.
            if i < 4:
                name_lbl.align(lv.ALIGN.TOP_LEFT, 8, 8)
                temp_lbl.align(lv.ALIGN.BOTTOM_RIGHT, -8, -8)
                _scale_2x_top_left(name_lbl)
                _scale_2x(psi_lbl)
                _scale_2x_bottom_right(temp_lbl)

    def apply_theme(self):
        for i, (card, name_lbl, psi_lbl, temp_lbl) in enumerate(self.cards):
            card.set_style_bg_color(theme.panel_raised() if i < 4 else theme.panel(), 0)
            card.set_style_border_color(theme.accent_dim() if i < 4 else theme.chrome_mid(), 0)
            name_lbl.set_style_text_color(theme.accent_lite() if i < 4 else theme.text_dim(), 0)
            temp_lbl.set_style_text_color(theme.text_dim(), 0)
        self.update()


def build(page, vehicle, group, w=0, h=0):
    return TiresScreen(page, vehicle, group, w, h)
