# gallery: binaries
# deps: pygraphics
"""
tower_climb.py — 1980s-style vertical scrolling platformer.

Climb a magical tree toward the canopy, inspired by Ice Climber, Nebulus,
Magical Tree, and Crazy Climber.  Uses software vertical scrolling (no
hardware ``vscsad`` / rotation tricks) so it runs on PGDisplay and SDLDisplay.

Layout scales from the 320×480 reference to taller panels (480×800, 720×720, …).
Built from the three core pydevices-examples libraries only.
"""

import sys
from collections import namedtuple


def _pkg_dir(file):
    path = str(file).replace("\\", "/")
    return path.rsplit("/", 1)[0] if "/" in path else "."


_PKG_DIR = _pkg_dir(__file__)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

from board_config import display_drv
import board_config
import appdev

app = appdev.App(board_config)
from displaydev import color565
import keys
from pygraphics import BMP565, FrameBuffer, RGB565, rect, text8
import _cfg as cfg
from _paths import asset_path
from tower_climb_trace import open_trace

try:
    from random import getrandbits, randint, seed
except ImportError:

    def getrandbits(n):
        return 0

    def randint(a, b):
        return a

    def seed(_):
        pass


try:
    from time import ticks_diff, ticks_ms
except ImportError:
    from multimer import ticks_diff, ticks_ms


# --- Scalable layout (reference 320×480) -------------------------------------------------------

REF_W, REF_H = 320, 480

# Developer difficulty tuning (1 = gentle, 10 = punishing). Not user-facing.
DIFFICULTY = 4


class Layout:
    __slots__ = ("w", "h", "sw", "sh", "s", "field_w", "ox")

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.sw = w / REF_W
        self.sh = h / REF_H
        self.s = min(self.sw, self.sh)
        self.field_w = min(w, max(self.x(REF_W), self.x(280)))
        self.ox = (w - self.field_w) // 2

    def x(self, n):
        return int(n * self.sw)

    def y(self, n):
        return int(n * self.sh)

    def u(self, n):
        return max(1, int(n * self.s))


L = Layout(display_drv.width, display_drv.height)

# Hazard pacing derived from DIFFICULTY (see DIFFICULTY above).
_HAZARD_SPEED = L.y(0.6 + DIFFICULTY * 0.10)
_HAZARD_SPAWN_PERIOD = max(180, 720 - DIFFICULTY * 50)
_HAZARD_BRANCH_INTERVAL = max(8, 24 - DIFFICULTY * 2)
_HAZARD_BRANCH_MAX_N = min(12, 4 + DIFFICULTY)

if display_drv.requires_byteswap:
    needs_swap = display_drv.disable_auto_byteswap(True)
else:
    needs_swap = False


def _c(r, g, b):
    v = color565(r, g, b)
    if needs_swap:
        v = ((v & 0xFF) << 8) | (v >> 8)
    return v


HUD_BG = _c(16, 20, 48)
HUD_INK = _c(255, 248, 200)
PARTICLE = _c(255, 200, 60)
SKY_HIGH = _c(110, 175, 255)
SKY_SUMMIT = _c(150, 210, 255)
TRUNK_WOOD = _c(72, 44, 24)
CROWN_GOLD = _c(255, 210, 50)

# --- Assets ------------------------------------------------------------------------------------

CLIMBER = BMP565(asset_path("climber.bmp"), streamed=True)
TILES = BMP565(asset_path("tower_tiles.bmp"), streamed=True)
BG = BMP565(asset_path("tower_bg.bmp"), streamed=True)

SPR_W = CLIMBER.width // 4
SPR_H = CLIMBER.height // 3
SPR_KEY = CLIMBER[0]
TILE_KEY = SPR_KEY
TILE = 16

T_BARK, T_BRANCH_L, T_BRANCH_R, T_ICE, T_LEAF, T_GEM, T_SPIKE, T_CLOUD, T_CROWN = range(9)
_TRANSPARENT_TILES = frozenset({T_LEAF, T_GEM, T_SPIKE, T_CLOUD})

BASE_Y_REF = REF_H - 80
CLIMB_REF = 560  # reference pixels; twice the original ~280 px climb
CROWN_Y = L.y(BASE_Y_REF - CLIMB_REF)
GOAL_Y = CROWN_Y - L.y(16)


def _rng(lo, hi):
    """Inclusive random int (MicroPython-safe)."""
    if lo >= hi:
        return lo
    try:
        return randint(lo, hi)
    except TypeError:
        span = hi - lo + 1
        return lo + (getrandbits(16) % span)


def _seed_rng():
    if cfg.seed is not None:
        seed(cfg.seed)
        return
    try:
        seed(ticks_ms())
    except NameError:
        pass


_seed_rng()

# --- Level helpers -----------------------------------------------------------------------------

Rect = namedtuple("Rect", "x y w h kind")
Point = namedtuple("Point", "x y")


def _tile_rect(idx):
    col = idx % 8
    row = idx // 8
    return col * TILE, row * TILE


def _blit_tile(idx, dx, dy, repeat=1):
    sx, sy = _tile_rect(idx)
    buf = TILES[sx : sx + TILE, sy : sy + TILE]
    for i in range(repeat):
        x = dx + i * TILE
        if idx in _TRANSPARENT_TILES:
            display_drv.blit_transparent(buf, x, dy, TILE, TILE, TILE_KEY)
        else:
            display_drv.blit_rect(buf, x, dy, TILE, TILE)


def _draw_sprite(pose, frame, dx, dy):
    col = frame % 4
    buf = CLIMBER[col * SPR_W : (col + 1) * SPR_W, pose * SPR_H : (pose + 1) * SPR_H]
    display_drv.blit_transparent(buf, dx, dy, SPR_W, SPR_H, SPR_KEY)


def _build_tree_crown(plats, decos, trunk, crown_y):
    """Wide leafy crown and cloud puffs at the tree top."""
    cw = L.x(_rng(96, 112))
    cx = L.ox + trunk - cw // 2
    plats.append(Rect(cx, crown_y, cw, TILE, T_CROWN))
    plats.append(Rect(cx - L.x(18), crown_y - L.y(18), L.x(40), TILE, T_LEAF))
    plats.append(Rect(cx + cw - L.x(22), crown_y - L.y(18), L.x(40), TILE, T_LEAF))
    mid = cx + cw // 2
    # Sparse cloud puffs — spread wide so the canopy is not a solid block.
    cloud_spots = (
        (-L.x(88), -L.y(34)),
        (-L.x(34), -L.y(62)),
        (L.x(78), -L.y(48)),
        (-L.x(110), -L.y(18)),
        (L.x(104), -L.y(24)),
        (-L.x(58), -L.y(78)),
        (L.x(62), -L.y(84)),
        (-L.x(18), -L.y(46)),
        (L.x(24), -L.y(70)),
    )
    for dx, dy in cloud_spots:
        if _rng(0, 99) < 88:
            jx = dx + L.x(_rng(-16, 16))
            jy = dy + L.y(_rng(-12, 12))
            decos.append((mid + jx, crown_y + jy, T_CLOUD))
    for dx, dy in ((-L.x(62), -L.y(16)), (L.x(58), -L.y(20))):
        decos.append((mid + dx + L.x(_rng(-8, 8)), crown_y + dy, T_LEAF))


def _build_level():
    """Randomized tree: branches, ice, gems, hazards, and a leafy crown."""
    plats = []
    gems = []
    hazards = []
    decos = []
    trunk = L.field_w // 2
    y = L.y(BASE_Y_REF)
    n = 0
    side = -1 if _rng(0, 1) else 1
    prev_cx = trunk
    hazard_cap = _rng(1, max(2, _HAZARD_BRANCH_MAX_N - 1))
    ice_chance = _rng(10, 18)
    gem_chance = _rng(34, 46)
    while y > CROWN_Y:
        bw = L.x(_rng(52, 84))
        reach = L.x(_rng(24, 44))
        bx = trunk + side * reach - bw // 2
        bx = max(L.ox + L.u(4), min(bx, L.ox + L.field_w - bw - L.u(4)))
        cx = bx + bw // 2
        if n > 0 and abs(cx - prev_cx) > L.x(68):
            nudge = L.x(16) if cx > prev_cx else -L.x(16)
            bx = max(L.ox + L.u(4), min(bx - nudge, L.ox + L.field_w - bw - L.u(4)))
            cx = bx + bw // 2
        prev_cx = cx
        kind = T_BRANCH_L if side < 0 else T_BRANCH_R
        if n > 3 and _rng(0, 99) < ice_chance:
            kind = T_ICE
        plats.append(Rect(bx, y, bw, TILE, kind))
        if n > 0 and _rng(0, 99) < gem_chance:
            gx = bx + _rng(max(8, bw // 5), max(9, bw - bw // 5)) - 6
            gems.append(Point(gx, y - _rng(14, 24)))
        if (
            n > 6
            and len(hazards) < hazard_cap
            and _rng(0, 99) < max(6, 90 - _HAZARD_BRANCH_INTERVAL * 4)
        ):
            hazards.append(
                [
                    bx + _rng(0, max(0, bw - 10)),
                    y - _rng(L.y(160), L.y(240)),
                    10,
                    0.0,
                    _HAZARD_SPEED,
                ]
            )
        y -= L.y(_rng(36, 44)) + L.u(_rng(2, 8))
        n += 1
        side = -side
    plats.append(Rect(L.ox + L.field_w // 2 - L.x(40), L.y(REF_H - 48), L.x(80), TILE, T_BARK))
    _build_tree_crown(plats, decos, trunk, CROWN_Y)
    return plats, gems, hazards, decos

_trace = open_trace()
_bot = cfg.bot
_record = cfg.record
_hold_win = cfg.hold_win
if _record:
    _bot = True


def _open_video_recorder():
    path = (cfg.video or "").strip()
    if not path:
        return
    if not hasattr(display_drv, "open_frame_recorder"):
        return
    display_drv.open_frame_recorder(path, fps=cfg.video_fps)


def _present():
    display_drv.show()

# --- Background draw ---------------------------------------------------------------------------


def _draw_bg(camera_y):
    """Blit a slice of the parallax strip; stretch when field width != asset width."""
    cy = max(0, min(-int(camera_y), BG.height - 1))
    slice_h = min(L.h, BG.height - cy)
    if L.field_w == BG.width:
        display_drv.blit_rect(BG[0:BG.width, cy : cy + slice_h], L.ox, 0, L.field_w, slice_h)
        if slice_h < L.h:
            display_drv.fill_rect(L.ox, slice_h, L.field_w, L.h - slice_h, _c(8, 12, 40))
    else:
        for col in range(L.field_w):
            sx = col * BG.width // L.field_w
            chunk = BG[sx : sx + 1, cy : cy + slice_h]
            display_drv.blit_rect(chunk, L.ox + col, 0, 1, slice_h)
        if slice_h < L.h:
            display_drv.fill_rect(L.ox, slice_h, L.field_w, L.h - slice_h, _c(8, 12, 40))
    if camera_y < L.y(-80):
        tint_h = min(L.h, L.u(72) + int((-camera_y - L.y(80)) // 2))
        display_drv.fill_rect(L.ox, 0, L.field_w, tint_h, SKY_HIGH)
    if camera_y < CROWN_Y - L.y(120):
        tint_h = min(L.h // 2, L.u(96))
        display_drv.fill_rect(L.ox, 0, L.field_w, tint_h, SKY_SUMMIT)
    if L.ox > 0:
        display_drv.fill_rect(0, 0, L.ox, L.h, _c(4, 8, 28))
    if L.ox + L.field_w < L.w:
        display_drv.fill_rect(L.ox + L.field_w, 0, L.w - L.ox - L.field_w, L.h, _c(4, 8, 28))


def _draw_trunk(cam):
    """Bark column through the playfield so the climb reads as a tree."""
    tx = L.ox + L.field_w // 2 - L.u(8)
    tw = L.u(16)
    y0 = max(0, int(CROWN_Y - cam) - L.u(8))
    y1 = min(L.h, int(L.y(REF_H - 36) - cam))
    if y1 <= y0:
        return
    display_drv.fill_rect(tx, y0, tw, y1 - y0, TRUNK_WOOD)
    for ty in range(y0, y1, TILE * 2):
        _blit_tile(T_BARK, tx, ty, 1)


def _draw_crown(plat, sy):
    """Summit landing: golden rim, leaf tiles, and a single cloud puff."""
    reps = max(1, plat.w // TILE)
    display_drv.fill_rect(plat.x, sy + TILE - L.u(4), plat.w, L.u(4), CROWN_GOLD)
    for i in range(reps):
        _blit_tile(T_LEAF, plat.x + i * TILE, sy, 1)
    mid = plat.x + plat.w // 2
    _blit_tile(T_CLOUD, mid - TILE // 2, sy - TILE - L.u(8), 1)


def _draw_sun(sx, sy):
    """Morning sun with rays (screen coordinates)."""
    if sy < L.u(8) or sy > L.h - L.u(24):
        return
    ray = _c(255, 196, 48)
    core = _c(255, 236, 120)
    halo = _c(255, 248, 180)
    r = L.u(9)
    cx, cy = sx, sy
    display_drv.fill_rect(cx - L.u(2), cy - L.u(16), L.u(4), L.u(32), ray)
    display_drv.fill_rect(cx - L.u(16), cy - L.u(2), L.u(32), L.u(4), ray)
    display_drv.fill_rect(cx - L.u(11), cy - L.u(11), L.u(4), L.u(14), ray)
    display_drv.fill_rect(cx + L.u(8), cy - L.u(11), L.u(4), L.u(14), ray)
    display_drv.fill_rect(cx - L.u(11), cy + L.u(4), L.u(4), L.u(14), ray)
    display_drv.fill_rect(cx + L.u(8), cy + L.u(4), L.u(4), L.u(14), ray)
    for dy in range(-r - L.u(4), r + L.u(5)):
        for dx in range(-r - L.u(4), r + L.u(5)):
            d2 = dx * dx + dy * dy
            if d2 <= (r + L.u(4)) * (r + L.u(4)):
                display_drv.pixel(cx + dx, cy + dy, halo)
            if d2 <= r * r:
                display_drv.pixel(cx + dx, cy + dy, core)


def _draw_summit_decos(cam, decos):
    for dx, dy, kind in decos:
        sy = int(dy - cam)
        if -TILE <= sy < L.h + TILE:
            _blit_tile(kind, dx, sy, 1)
    _draw_sun(L.ox + L.field_w - L.u(40), int(CROWN_Y - cam) - L.y(72))


# --- Physics -----------------------------------------------------------------------------------

GRAVITY = 0.55
JUMP_V = -10.5
MAX_FALL = 11.0
MOVE_A = 0.7
MAX_RUN = 4.5
FRICTION = 0.82
ANCHOR_Y = L.y(300)
CAM_MIN = CROWN_Y - ANCHOR_Y - L.y(56)  # stop above the leafy crown


class Player:
    __slots__ = ("x", "y", "vx", "vy", "on_ground", "coyote", "jump_buf", "lives", "score", "pose")

    def __init__(self):
        self.x = float(L.ox + L.field_w // 2 - SPR_W // 2)
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.coyote = 8
        self.jump_buf = 0
        self.lives = 3
        self.score = 0
        self.pose = 2


def _hitbox(p):
    m = 6
    return Rect(int(p.x + m), int(p.y + 10), SPR_W - m * 2, SPR_H - 12, 0)


def _overlap(a, b):
    return a.x < b.x + b.w and a.x + a.w > b.x and a.y < b.y + b.h and a.y + a.h > b.y


def _platform_supports_feet(p, plat, margin=6):
    """True when the player is standing on ``plat`` (not jumping past it)."""
    feet = p.y + SPR_H - 4
    if not p.on_ground and p.vy < 0:
        return False
    if p.vy < 0 and feet > plat.y + margin:
        return False
    return plat.y - margin <= feet <= plat.y + margin


def _resolve_x(p, plat, dx):
    if not _platform_supports_feet(p, plat):
        return None
    box = _hitbox(p)
    if not _overlap(box, plat):
        return None
    old_x = p.x
    if dx > 0:
        p.x = plat.x - (SPR_W - 6)
    elif dx < 0:
        p.x = plat.x + plat.w - 6
    else:
        return None
    if _trace is not None:
        _trace.log_resolve_x(p, plat, dx, old_x)
    return plat


def _nearby_platforms(hitbox, player_y, plats, radius=96):
    nearby = []
    for plat in plats:
        if plat.kind == T_GEM:
            continue
        if hitbox.x + hitbox.w <= plat.x or hitbox.x >= plat.x + plat.w:
            continue
        if abs(plat.y - (player_y + SPR_H)) <= radius:
            nearby.append(plat)
    return nearby


def _land(p, prev_y, plats):
    feet = int(p.y + SPR_H - 4)
    prev_feet = int(prev_y + SPR_H - 4)
    box = _hitbox(p)
    best = None
    best_plat = None

    if p.vy < 0:
        # Jumping up onto a platform from below.
        for plat in plats:
            if plat.kind == T_GEM:
                continue
            if box.x + box.w <= plat.x or box.x >= plat.x + plat.w:
                continue
            top = plat.y
            if prev_feet >= top >= feet and (best is None or top < best):
                best = top
                best_plat = plat
        if best is not None:
            new_y = best - SPR_H
            if not (p.on_ground and p.vy == 0 and abs(p.y - new_y) < 1):
                p.y = new_y
                p.vy = 0
                p.on_ground = True
                if _trace is not None:
                    _trace.log_land(p, prev_y, best_plat, "land_up", feet)
                if best_plat.kind == T_SPIKE:
                    return "hurt"
        else:
            p.on_ground = False
        return None

    if p.vy > 0 or not p.on_ground:
        tol = max(4, int(p.vy) + 2)
        for plat in plats:
            if plat.kind == T_GEM:
                continue
            if box.x + box.w <= plat.x or box.x >= plat.x + plat.w:
                continue
            top = plat.y
            crossed = prev_feet <= top <= feet
            snap = prev_feet <= top + tol and feet >= top - 2
            if (crossed or snap) and (best is None or top > best):
                best = top
                best_plat = plat
        if best is not None:
            new_y = best - SPR_H
            if not (p.on_ground and p.vy == 0 and abs(p.y - new_y) < 1):
                p.y = new_y
                p.vy = 0
                p.on_ground = True
                if _trace is not None:
                    result = "hurt" if best_plat.kind == T_SPIKE else "land"
                    _trace.log_land(p, prev_y, best_plat, result, feet)
                if best_plat.kind == T_SPIKE:
                    return "hurt"
        elif p.vy > 0:
            p.on_ground = False
    return None


def _ground_platform(plats):
    best = None
    for plat in plats:
        if plat.kind == T_GEM:
            continue
        if best is None or plat.y > best.y:
            best = plat
    return best


def _snap_to_ground(p, plats, reason="spawn"):
    plat = _ground_platform(plats)
    if plat is None:
        return
    p.y = float(plat.y - SPR_H)
    p.vx = p.vy = 0.0
    p.on_ground = True
    p.coyote = 8
    p.jump_buf = 0
    if _trace is not None:
        _trace.log_snap(reason, p, plat)


_bot_stuck = 0
_bot_last_x = None


def _bot_tick(player, plats, hazards):
    """Simple climb AI for playtesting (``--bot``)."""
    global _bot_stuck, _bot_last_x
    _keys["left"] = _keys["right"] = _keys["up"] = _keys["down"] = False
    _keys["smash"] = False
    px = player.x + SPR_W // 2

    for hz in hazards:
        hx, hy = hz[0], hz[1]
        if abs(hx - px) < L.u(28) and abs(hy - (player.y + SPR_H // 2)) < L.u(36):
            _keys["left" if px > hx else "right"] = True
            if player.on_ground or player.coyote > 0:
                _keys["up"] = True
            return

    if _bot_last_x is not None and abs(player.x - _bot_last_x) < 0.5:
        _bot_stuck += 1
    else:
        _bot_stuck = 0
    _bot_last_x = player.x

    if player.on_ground:
        box = _hitbox(player)
        for plat in plats:
            if plat.kind == T_ICE and _overlap(
                box, Rect(plat.x, plat.y - 4, plat.w, plat.h + 8, T_ICE)
            ):
                _keys["smash"] = True
                return
        support = [
            plat for plat in plats if plat.kind != T_GEM and _platform_supports_feet(player, plat)
        ]
        if support:
            plat = max(support, key=lambda p: p.y)
            edge = L.u(10)
            if px < plat.x + edge or px > plat.x + plat.w - edge:
                _keys["up"] = True

    feet = player.y + SPR_H - 4
    above = [
        plat
        for plat in plats
        if plat.kind not in (T_GEM, T_SPIKE)
        and plat.y < feet - L.u(8)
        and plat.y > GOAL_Y - L.u(30)
    ]
    if player.on_ground:
        support = [
            plat for plat in plats if plat.kind != T_GEM and _platform_supports_feet(player, plat)
        ]
        if support:
            floor_y = max(plat.y for plat in support)
            above = [plat for plat in above if plat.y < floor_y - L.u(4)]
    if not above:
        if player.y > GOAL_Y and (player.on_ground or player.coyote > 0):
            _keys["up"] = True
        return

    crowns = [plat for plat in above if plat.kind == T_CROWN]
    target = max(above, key=lambda plat: plat.y)
    if crowns and feet < CROWN_Y + L.y(72):
        target = crowns[0]
    tcx = target.x + target.w // 2
    aligned = abs(px - tcx) <= L.u(12)
    dx = abs(px - tcx)

    if aligned and (player.on_ground or player.coyote > 0):
        _keys["up"] = True
    elif _bot_stuck > 10 and (player.on_ground or player.coyote > 0):
        _keys["up"] = True
        _keys["right" if px < tcx else "left"] = True
    elif dx > L.u(8):
        _keys["right" if px < tcx else "left"] = True
        if dx < L.u(56) and (player.on_ground or player.coyote > 0):
            _keys["up"] = True
    if (player.on_ground or player.coyote > 0) and feet > target.y + L.u(6):
        _keys["up"] = True


# --- Input -------------------------------------------------------------------------------------

_keys = {"left": False, "right": False, "up": False, "down": False, "smash": False}
_awaiting_start = False
_start_received = False


def _handle_event(ev):
    global _start_received
    if _awaiting_start and _is_start_input(ev):
        _keys["left"] = _keys["right"] = _keys["up"] = _keys["down"] = False
        _keys["smash"] = False
        _start_received = True
        return
    t = ev.type
    if t == app.events.KEYDOWN:
        k = ev.key
        if k in (keys.K_LEFT, keys.K_a):
            _keys["left"] = True
        elif k in (keys.K_RIGHT, keys.K_d):
            _keys["right"] = True
        elif k in (keys.K_SPACE, keys.K_UP, keys.K_w):
            _keys["up"] = True
        elif k in (keys.K_DOWN, keys.K_s):
            _keys["down"] = True
            _keys["smash"] = True
        elif k in (keys.K_x, keys.K_z):
            _keys["smash"] = True
        if _trace is not None:
            _trace.log_input("keydown", key=int(k))
    elif t == app.events.KEYUP:
        k = ev.key
        if k in (keys.K_LEFT, keys.K_a):
            _keys["left"] = False
        elif k in (keys.K_RIGHT, keys.K_d):
            _keys["right"] = False
        elif k in (keys.K_SPACE, keys.K_UP, keys.K_w):
            _keys["up"] = False
        elif k in (keys.K_DOWN, keys.K_s):
            _keys["down"] = False
            _keys["smash"] = False
        if _trace is not None:
            _trace.log_input("keyup", key=int(k))
    elif t == app.events.MOUSEBUTTONDOWN:
        tx, ty = ev.pos
        if ty < L.h // 3:
            _keys["up"] = True
        elif ty > 2 * L.h // 3:
            _keys["smash"] = True
        elif tx < L.w // 2:
            _keys["left"] = True
        else:
            _keys["right"] = True
        if _trace is not None:
            _trace.log_input("mousedown", pos=[tx, ty], keys=dict(_keys))
    elif t == app.events.MOUSEBUTTONUP:
        _keys["left"] = _keys["right"] = _keys["up"] = _keys["smash"] = False
        if _trace is not None:
            _trace.log_input("mouseup", keys=dict(_keys))


_particles = []


def _spark(x, y, n=6):
    for _ in range(n):
        _particles.append(
            [x + randint(-6, 6), y + randint(-4, 4), randint(-3, 3), randint(6, 14)]
        )


# --- HUD & overlays ----------------------------------------------------------------------------

_hud_h = L.u(16)
_hud_buf = bytearray(L.w * _hud_h * 2)
_hud_fb = FrameBuffer(_hud_buf, L.w, _hud_h, RGB565)

_overlay_h = L.y(220)
_overlay_buf = bytearray(L.w * _overlay_h * 2)
_overlay_fb = FrameBuffer(_overlay_buf, L.w, _overlay_h, RGB565)

SPLASH_LINES = (
    "TREE CLIMB",
    "",
    "Climb the magical tree",
    "to the leafy crown!",
    "",
    "Move: arrows / A D",
    "Jump: Space / W / tap top",
    "Smash ice: Down / S",
    "",
    "Collect gems, break ice,",
    "dodge falling debris.",
    "",
    "Press any key or tap",
    "to start",
)


def _draw_hud(p, altitude):
    display_drv.fill_rect(0, 0, L.w, _hud_h, HUD_BG)
    pct = min(99, altitude * 100 // max(1, L.y(BASE_Y_REF) - GOAL_Y))
    msg = f"SCORE {p.score:04d}  M {pct:2d}%  LIVES {p.lives}"
    _hud_fb.fill(HUD_BG)
    text8(_hud_fb, msg, L.u(4), L.u(3), HUD_INK)
    display_drv.blit_rect(_hud_buf, 0, 0, L.w, _hud_h)


def _skip_ui():
    try:
        import pydevices_test_mode

        return pydevices_test_mode.ENABLED
    except ImportError:
        return False


def _draw_text_panel(lines, y0=None, at_top=False):
    line_h = L.u(12)
    pad = L.u(10)
    panel_h = pad * 2 + line_h * len(lines)
    if panel_h > _overlay_h:
        panel_h = _overlay_h
    if y0 is None:
        y0 = (_hud_h + L.u(4)) if at_top else max(0, (L.h - panel_h) // 2)
    panel_c = _c(12, 16, 40)
    border_c = _c(255, 180, 40)
    title_c = _c(255, 220, 80)
    x0 = L.u(8)
    pw = L.w - L.u(16)
    display_drv.fill_rect(x0, y0, pw, panel_h, panel_c)
    rect(display_drv, x0, y0, pw, panel_h, border_c)
    _overlay_fb.fill(panel_c)
    ty = pad
    for i, line in enumerate(lines):
        if line:
            color = title_c if i == 0 else HUD_INK
            text8(_overlay_fb, line, L.u(10), ty, color)
        ty += line_h
    display_drv.blit_rect(_overlay_buf, 0, y0, L.w, panel_h)


def _is_start_input(ev):
    if ev.type == app.events.KEYDOWN:
        return True
    if ev.type == app.events.MOUSEBUTTONDOWN:
        return True
    return False


# --- Main (on_tick state machine; no blocking sleep_ms) ----------------------------------------

PHASE_SPLASH = "splash"
PHASE_PLAY = "play"
PHASE_LIFE_LOST = "life_lost"
PHASE_END = "end"
PHASE_HOLD_WIN = "hold_win"
PHASE_DONE = "done"

_phase = PHASE_DONE
_show_splash_next = True
_wait_draw = None
_hold_left = 0
_cleaned = False

# Round state (set by _start_round)
_plats = None
_gems = None
_hazards = None
_summit_decos = None
_player = None
_camera = 0.0
_frame = 0
_won = False

_refresh_claim = None


def _take_over_display_refresh():
    global _refresh_claim
    if app is not None and _refresh_claim is None:
        _refresh_claim = app.pause_refresh()


def _restore_display_refresh():
    global _refresh_claim
    if _refresh_claim is not None:
        _refresh_claim.release()
        _refresh_claim = None


def _cleanup():
    global _phase, _cleaned, _awaiting_start
    if _cleaned:
        return
    _cleaned = True
    _phase = PHASE_DONE
    _awaiting_start = False
    try:
        CLIMBER.deinit()
        TILES.deinit()
        BG.deinit()
    except Exception:
        pass
    _restore_display_refresh()
    if _trace is not None:
        try:
            _trace.close()
        except Exception:
            pass
    if hasattr(display_drv, "close_frame_recorder"):
        try:
            display_drv.close_frame_recorder()
        except Exception:
            pass


def _respawn(p, plats):
    p.lives -= 1
    p.x = float(L.ox + L.field_w // 2 - SPR_W // 2)
    _snap_to_ground(p, plats, reason="respawn")


def _draw_splash():
    _draw_bg(0)
    _draw_text_panel(SPLASH_LINES)


def _draw_life_lost():
    lines = (
        "LIFE LOST!",
        "",
        f"Lives left: {_player.lives}",
        "",
        "Press any key or tap",
        "to continue",
    )
    _draw_bg(0)
    _draw_text_panel(lines)


def _draw_end():
    if _won:
        lines = (
            "TREE TOP!",
            "You reached the canopy!",
            "SCORE %04d" % _player.score,
            "",
            "Press any key or tap",
            "to play again",
        )
    else:
        lines = (
            "GAME OVER",
            "SCORE %04d" % _player.score,
            "",
            "Press any key or tap",
            "to play again",
        )
    _draw_bg(_camera)
    _draw_trunk(int(_camera))
    for plat in _plats:
        if plat.kind != T_CROWN:
            continue
        sy = int(plat.y - int(_camera))
        if -TILE <= sy < L.h:
            _draw_crown(plat, sy)
    _draw_summit_decos(int(_camera), _summit_decos)
    if _won:
        _draw_sprite(_player.pose, _frame // 5, int(_player.x), int(_player.y - int(_camera)))
    _draw_text_panel(lines, at_top=_won)


def _enter_wait(phase, draw_fn):
    """Non-blocking wait: redraw overlay each tick until start input (or skip_ui/bot)."""
    global _phase, _wait_draw, _awaiting_start, _start_received
    _phase = phase
    _wait_draw = draw_fn
    if _skip_ui() or (_bot and phase == PHASE_LIFE_LOST):
        _awaiting_start = False
        _start_received = True
        return
    _awaiting_start = True
    _start_received = False


def _start_round():
    global _plats, _gems, _hazards, _summit_decos, _player, _camera, _frame, _won, _phase
    _plats, gems, hazards, _summit_decos = _build_level()
    if _trace is not None:
        _trace.log_init(L, SPR_W, SPR_H, _plats, gems, hazards, GOAL_Y)
    _player = Player()
    _snap_to_ground(_player, _plats, reason="round_start")
    _gems = list(gems)
    _hazards = [list(h) for h in hazards]
    _camera = 0.0
    _frame = 0
    _won = False
    _particles.clear()
    _phase = PHASE_PLAY


def _on_round_over():
    """Win or game-over: bot exits / records; interactive waits then replays."""
    global _phase, _hold_left, _show_splash_next, _wait_draw
    if _bot and _record:
        _show_splash_next = False
        _start_round()
        return
    if _bot:
        if _hold_win and _won:
            if cfg.hold_frames is not None:
                _hold_left = int(cfg.hold_frames)
            else:
                _hold_left = (
                    48 if getattr(display_drv, "frame_recording", False) else 150
                )
            _phase = PHASE_HOLD_WIN
            _wait_draw = _draw_end
            return
        _cleanup()
        return
    _show_splash_next = False
    _enter_wait(PHASE_END, _draw_end)


def _apply_life_loss(reason):
    """Respawn or end round. Returns True if play should pause/stop this tick."""
    global _camera, _won
    if _trace is not None:
        _trace.log_life(reason, _player, _camera)
    _respawn(_player, _plats)
    _camera = 0.0
    if _player.lives <= 0:
        _won = False
        _on_round_over()
        return True
    if _bot:
        return False
    _enter_wait(PHASE_LIFE_LOST, _draw_life_lost)
    return True


def _render_play():
    altitude = int(L.y(BASE_Y_REF) - _player.y)
    _draw_bg(_camera)
    cam = int(_camera)
    _draw_trunk(cam)
    for plat in _plats:
        sy = int(plat.y - cam)
        if sy < -TILE or sy > L.h:
            continue
        if plat.kind == T_BARK:
            reps = max(1, plat.w // TILE)
            _blit_tile(T_BARK, plat.x, sy, reps)
        elif plat.kind == T_CROWN:
            _draw_crown(plat, sy)
        elif plat.kind in (T_BRANCH_L, T_BRANCH_R, T_ICE, T_LEAF):
            reps = max(1, plat.w // TILE)
            _blit_tile(plat.kind, plat.x, sy, reps)
    _draw_summit_decos(cam, _summit_decos)
    for g in _gems:
        sy = int(g.y - cam)
        if 0 <= sy < L.h:
            _blit_tile(T_GEM, g.x, sy)
    for hz in _hazards:
        sy = int(hz[1] - cam)
        if 0 <= sy < L.h:
            _blit_tile(T_SPIKE, int(hz[0]), sy)
    live = []
    for px, py, pvx, life in _particles:
        life -= 1
        if life > 0:
            px += pvx
            py += 1
            sy = int(py - cam)
            if 0 <= sy < L.h:
                display_drv.pixel(int(px), sy, PARTICLE)
            live.append([px, py, pvx, life])
    _particles[:] = live
    _draw_sprite(_player.pose, _frame // 5, int(_player.x), int(_player.y - cam))
    _draw_hud(_player, altitude)
    _present()


def _tick_play():
    global _camera, _frame, _won, _gems, _hazards
    player = _player
    plats = _plats
    gems = _gems
    hazards = _hazards

    if _bot:
        _bot_tick(player, plats, hazards)

    _frame += 1
    frame = _frame

    target_cam = player.y - ANCHOR_Y
    if target_cam < _camera:
        _camera = max(target_cam, CAM_MIN)

    if _keys["left"]:
        player.vx -= MOVE_A
        player.pose = 0
    if _keys["right"]:
        player.vx += MOVE_A
        player.pose = 0
    if not _keys["left"] and not _keys["right"] and player.on_ground:
        player.pose = 2
    if _keys["up"]:
        player.jump_buf = 8
    else:
        player.jump_buf = max(0, player.jump_buf - 1)

    if player.on_ground:
        player.coyote = 8
    else:
        player.coyote = max(0, player.coyote - 1)
        player.pose = 1

    if player.jump_buf and player.coyote:
        player.vy = JUMP_V * (L.s if L.s < 1.2 else 1.0)
        player.on_ground = False
        player.coyote = 0
        player.jump_buf = 0
        _spark(int(player.x + SPR_W // 2), int(player.y + SPR_H), 4)

    if _keys["smash"] and player.on_ground:
        box = _hitbox(player)
        for i, plat in enumerate(plats):
            if plat.kind == T_ICE and _overlap(
                box, Rect(plat.x, plat.y - 4, plat.w, plat.h + 8, T_ICE)
            ):
                plats[i] = Rect(plat.x, plat.y, plat.w, plat.h, T_BRANCH_L)
                player.score += 15
                _spark(plat.x + plat.w // 2, plat.y, 10)
                break

    player.vx = max(-MAX_RUN, min(MAX_RUN, player.vx))
    if player.on_ground:
        player.vx *= FRICTION
    else:
        player.vx *= 0.99
    if not player.on_ground:
        player.vy = min(MAX_FALL, player.vy + GRAVITY)

    ox = player.x
    player.x += player.vx
    x_blocked = []
    for plat in plats:
        blocked = _resolve_x(player, plat, player.x - ox)
        if blocked is not None:
            x_blocked.append(blocked)

    oy = player.y
    player.y += player.vy
    hurt = _land(player, oy, plats)
    if hurt:
        if _apply_life_loss("spike"):
            if _phase == PHASE_PLAY:
                _render_play()
            return
        _render_play()
        return

    if player.y > L.y(REF_H) + L.u(40):
        if _apply_life_loss("fall"):
            if _phase == PHASE_PLAY:
                _render_play()
            return
        _render_play()
        return

    box = _hitbox(player)
    got = []
    for i, g in enumerate(gems):
        gr = Rect(g.x, g.y, 12, 12, T_GEM)
        if _overlap(box, gr):
            got.append(i)
            player.score += 25
            _spark(g.x, g.y, 6)
    for i in reversed(got):
        gems.pop(i)

    if (
        frame % _HAZARD_SPAWN_PERIOD == 0
        and player.y > GOAL_Y + L.y(80)
        and player.y < L.y(REF_H - 240)
    ):
        hx = L.ox + randint(20, max(21, L.field_w - 20))
        hazards.append([hx, _camera - 20, 10, 0.0, _HAZARD_SPEED])

    for hz in hazards:
        hz[1] += hz[4]
        hz[3] += 0.05
        hr = Rect(int(hz[0]), int(hz[1]), hz[2], hz[2], T_SPIKE)
        if _overlap(box, hr):
            if _apply_life_loss("hazard"):
                if _phase == PHASE_PLAY:
                    _render_play()
                return
            _render_play()
            return
    hazards[:] = [h for h in hazards if h[1] < _camera + L.h + L.u(40)]

    if not _won:
        if player.y <= GOAL_Y:
            _won = True
            player.score += 500
        else:
            for plat in plats:
                if plat.kind == T_CROWN and _platform_supports_feet(player, plat):
                    _won = True
                    player.score += 500
                    break
        if _won and _trace is not None:
            _trace.event("win", score=player.score, y=round(player.y, 2))

    if _trace is not None:
        _trace.frame += 1
        box = _hitbox(player)
        feet = int(player.y + SPR_H - 4)
        nearby = _nearby_platforms(box, player.y, plats)
        _trace.log_frame(
            player,
            _camera,
            _keys,
            box,
            feet,
            (int(player.x), int(player.y), SPR_W, SPR_H),
            nearby,
            x_blocked,
        )

    _render_play()

    if _won:
        _on_round_over()


def _on_wait_complete():
    global _phase, _awaiting_start, _start_received, _wait_draw, _show_splash_next
    _awaiting_start = False
    _start_received = False
    _wait_draw = None
    if _phase == PHASE_SPLASH:
        _start_round()
    elif _phase == PHASE_LIFE_LOST:
        _phase = PHASE_PLAY
    elif _phase == PHASE_END:
        _show_splash_next = False
        _start_round()


def _tick(_=None):
    global _hold_left, _phase
    if app.quit_requested if app else False:
        _cleanup()
        return
    if _phase == PHASE_DONE:
        return

    if _phase in (PHASE_SPLASH, PHASE_LIFE_LOST, PHASE_END):
        if _wait_draw is not None:
            _wait_draw()
            _present()
        if _start_received or _skip_ui():
            _on_wait_complete()
        return

    if _phase == PHASE_HOLD_WIN:
        if _wait_draw is not None:
            _wait_draw()
            _present()
        _hold_left -= 1
        if _hold_left <= 0:
            _cleanup()
        return

    if _phase == PHASE_PLAY:
        _tick_play()


def main():
    global _phase, _show_splash_next
    _take_over_display_refresh()
    _open_video_recorder()
    for et in (
        app.events.KEYDOWN,
        app.events.KEYUP,
        app.events.MOUSEBUTTONDOWN,
        app.events.MOUSEBUTTONUP,
        app.events.MOUSEMOTION,
    ):
        app.on(et, _handle_event)

    show_splash = True
    if _trace is not None:
        show_splash = False
    if _bot or _record:
        show_splash = False
    _show_splash_next = show_splash

    if show_splash and not _skip_ui():
        _enter_wait(PHASE_SPLASH, _draw_splash)
    else:
        _start_round()

    app.every(_tick, period=16, async_=app.timer_async)


main()