"""
Text trace hooks for tower_climb debugging.

Enable with ``--trace PATH`` (JSON Lines). Each line is one JSON object with a
``kind`` field.
"""

import json

from _paths import ensure_parent_dir
import _cfg as cfg

_KIND_NAMES = (
    "bark",
    "branch_l",
    "branch_r",
    "ice",
    "leaf",
    "gem",
    "spike",
    "cloud",
    "crown",
)


def kind_name(kind):
    if 0 <= kind < len(_KIND_NAMES):
        return _KIND_NAMES[kind]
    return str(kind)


def rect_dict(r):
    return {"x": r.x, "y": r.y, "w": r.w, "h": r.h, "kind": kind_name(r.kind)}


def point_dict(p):
    return {"x": p.x, "y": p.y}


class TraceRecorder:
    __slots__ = ("_path", "_file", "frame")

    def __init__(self, path):
        self._path = path
        ensure_parent_dir(path)
        self._file = open(path, "w", encoding="utf-8")
        self.frame = 0

    def event(self, kind, **fields):
        row = {"kind": kind, "frame": self.frame}
        row.update(fields)
        self._file.write(json.dumps(row, separators=(",", ":")) + "\n")

    def log_init(self, layout, spr_w, spr_h, plats, gems, hazards, goal_y):
        self.event(
            "init",
            display={"w": layout.w, "h": layout.h},
            layout={
                "field_w": layout.field_w,
                "ox": layout.ox,
                "scale": layout.s,
                "ref": [320, 480],
            },
            sprite={"w": spr_w, "h": spr_h},
            goal_y=goal_y,
            platforms=[rect_dict(p) for p in plats],
            gems=[point_dict(g) for g in gems],
            hazards=[list(h) for h in hazards],
        )

    def log_input(self, ev_type, detail):
        self.event("input", ev_type=ev_type, **detail)

    def log_snap(self, reason, player, plat):
        self.event(
            "snap",
            reason=reason,
            player=self._player(player),
            platform=rect_dict(plat) if plat is not None else None,
        )

    def log_resolve_x(self, player, plat, dx, old_x):
        self.event(
            "resolve_x",
            dx=dx,
            old_x=old_x,
            new_x=player.x,
            player=self._player(player),
            platform=rect_dict(plat),
        )

    def log_land(self, player, prev_y, plat, result, feet):
        self.event(
            "land",
            result=result,
            prev_y=prev_y,
            feet=feet,
            player=self._player(player),
            platform=rect_dict(plat) if plat is not None else None,
        )

    def log_life(self, reason, player, camera):
        self.event("life_lost", reason=reason, camera=camera, player=self._player(player))

    def log_frame(
        self,
        player,
        camera,
        keys,
        hitbox,
        feet,
        sprite_rect,
        nearby,
        x_blocked,
        note=None,
    ):
        self.event(
            "frame",
            camera=round(camera, 2),
            keys=dict(keys),
            player=self._player(player),
            hitbox={"x": hitbox.x, "y": hitbox.y, "w": hitbox.w, "h": hitbox.h},
            feet=feet,
            sprite={"x": sprite_rect[0], "y": sprite_rect[1], "w": sprite_rect[2], "h": sprite_rect[3]},
            nearby=[rect_dict(p) for p in nearby],
            x_blocked=[rect_dict(p) for p in x_blocked],
            note=note,
        )

    def _player(self, p):
        return {
            "x": round(p.x, 2),
            "y": round(p.y, 2),
            "vx": round(p.vx, 2),
            "vy": round(p.vy, 2),
            "on_ground": p.on_ground,
            "pose": p.pose,
            "coyote": p.coyote,
            "jump_buf": p.jump_buf,
            "lives": p.lives,
            "score": p.score,
        }

    def close(self):
        if self._file is not None:
            self.event("end")
            self._file.close()
            self._file = None


def open_trace():
    path = (cfg.trace or "").strip()
    if not path:
        return None
    return TraceRecorder(path)
