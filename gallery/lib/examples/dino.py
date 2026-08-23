# deps: pygraphics
# utils: pixel_sim
"""
dino.py — a self-contained, color pixel-matrix endless runner.

Gameplay follows the familiar offline dinosaur runner: Space/Up or a tap starts
and jumps, Down ducks on the ground and accelerates a fall in the air. The pace
increases until the dinosaur hits a cactus or pterosaur; the next jump input
restarts the game.

All game art is stored below as one-bit-per-pixel ``bytes`` masks. ``MonoSprite``
wraps each mask in a ``pygraphics.FrameBuffer`` and colors its on-pixels when
compositing onto the RGB565 scene. The silhouettes are original pixel art
created for this example.
"""

from random import getrandbits

import board_config as _host_board

from displaydev import color565
import keys
from multimer import ticks_diff, ticks_ms
from pygraphics import MONO_HLSB, RGB565, FrameBuffer

# Rotate the simulator's output surface before pixel_sim sizes its LED blocks.
if _host_board.display_drv.width < _host_board.display_drv.height:
    _host_board.display_drv.rotation = (_host_board.display_drv.rotation + 90) % 360

# For real PixelDisplay hardware, replace this import with:
# from board_config import display_drv
# app = appdev.App(board_config)
from pixel_sim import display_drv, app

WIDTH = display_drv.width
HEIGHT = display_drv.height
GROUND_Y = HEIGHT - 2
FRAME_MS = 16
FP = 256
JUMP_VELOCITY = -320
JUMP_RELEASE_VELOCITY = -260
GRAVITY = 10
FAST_FALL_GRAVITY = 75

BLACK = color565(0, 0, 0)
WHITE = color565(245, 245, 245)
DINO_DAY = color565(72, 220, 96)
DINO_NIGHT = color565(116, 245, 156)
CACTUS_DAY = color565(238, 174, 48)
CACTUS_NIGHT = color565(255, 206, 92)
BIRD_DAY = color565(238, 76, 178)
BIRD_NIGHT = color565(255, 132, 216)
GROUND_DAY = color565(188, 174, 146)
GROUND_NIGHT = color565(100, 148, 190)
CLOUD_DAY = color565(68, 154, 224)
CLOUD_NIGHT = color565(72, 92, 150)
MOON = color565(224, 224, 176)
SCORE_DAY = color565(180, 180, 180)
SCORE_NIGHT = color565(132, 176, 220)


def _randint(low, high):
    span = high - low + 1
    if span <= 1:
        return low
    bits = 0
    value = span - 1
    while value:
        bits += 1
        value >>= 1
    return low + getrandbits(bits) % span


def _bitmap(*rows):
    """Pack left-to-right strings into MicroPython MONO_HLSB bytes."""
    width = len(rows[0])
    height = len(rows)
    stride = (width + 7) // 8
    data = bytearray(stride * height)
    for y, row in enumerate(rows):
        if len(row) != width:
            raise ValueError("sprite rows must have equal width")
        for x, pixel in enumerate(row):
            if pixel != ".":
                data[y * stride + (x >> 3)] |= 1 << (7 - (x & 7))
    return bytes(data)


class MonoSprite:
    """A bytes-backed one-bit sprite with a per-instance RGB565 color."""

    def __init__(self, width, height, data, color):
        self.width = width
        self.height = height
        self.stride = (width + 7) // 8
        self.data = data
        self.color = color
        self.mask = FrameBuffer(bytearray(data), width, height, MONO_HLSB)

    def draw(self, dest, x, y, color=None):
        ink = self.color if color is None else color
        pixel = dest.pixel
        for sy in range(self.height):
            dy = y + sy
            if not 0 <= dy < HEIGHT:
                continue
            for sx in range(self.width):
                dx = x + sx
                if 0 <= dx < WIDTH and self.mask.pixel(sx, sy):
                    pixel(dx, dy, ink)

    def hits(self, x, y, other, ox, oy):
        left = max(x, ox)
        top = max(y, oy)
        right = min(x + self.width, ox + other.width)
        bottom = min(y + self.height, oy + other.height)
        if left >= right or top >= bottom:
            return False
        for py in range(top, bottom):
            for px in range(left, right):
                if self.mask.pixel(px - x, py - y) and other.mask.pixel(px - ox, py - oy):
                    return True
        return False


# Original one-bit artwork. Every non-dot character is an on-pixel.
DINO_RUN_1_BITS = _bitmap(
    "......###.",
    ".....#####",
    ".....##.#.",
    "#...#####.",
    "##.####...",
    ".#####....",
    "..##.##...",
)
DINO_RUN_2_BITS = _bitmap(
    "......###.",
    ".....#####",
    ".....##.#.",
    "#...#####.",
    "##.####...",
    ".#####....",
    "..###.#...",
)
DINO_JUMP_BITS = _bitmap(
    "......###.",
    ".....#####",
    ".....##.#.",
    "#...#####.",
    "##.####...",
    ".#####....",
    "..##.##...",
)
DINO_DUCK_1_BITS = _bitmap(
    "......####",
    "##########",
    ".#######.#",
    "..##..##..",
)
DINO_DUCK_2_BITS = _bitmap(
    "......####",
    "##########",
    ".#######.#",
    "..###..#..",
)
DINO_DEAD_BITS = _bitmap(
    "......###.",
    ".....#####",
    ".....##X#.",
    "#...#####.",
    "##.####...",
    ".#####....",
    "..##.##...",
)

CACTUS_SMALL_BITS = _bitmap(
    "..#..",
    "#.#..",
    "###.#",
    "..###",
    "..#..",
)
CACTUS_TALL_BITS = _bitmap(
    "...#..",
    "#..#..",
    "#.##.#",
    "###..#",
    "...###",
    "...#..",
    "...#..",
)
CACTUS_CLUSTER_BITS = _bitmap(
    "..#....#.",
    "#.#.#..#.",
    "###.##.#.",
    "..#.#####",
    "..#...#..",
    "..#...#..",
)

BIRD_UP_BITS = _bitmap(
    "#.......#",
    ".##...##.",
    "..#####..",
    "...###...",
)
BIRD_DOWN_BITS = _bitmap(
    "...###...",
    "..#####..",
    ".##...##.",
    "#.......#",
)

CLOUD_BITS = _bitmap(
    "...##....",
    ".######..",
    "#########",
)
MOON_BITS = _bitmap(
    ".###.",
    "#####",
    "####.",
    ".###.",
)
RESTART_BITS = _bitmap(
    ".###.",
    "#...#",
    "#.###",
    "#....",
    ".####",
)

DIGIT_ROWS = {
    "0": ("###", "#.#", "#.#", "#.#", "###"),
    "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", "###", "#..", "###"),
    "3": ("###", "..#", ".##", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"),
    "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"),
    "7": ("###", "..#", "..#", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"),
    "9": ("###", "#.#", "###", "..#", "###"),
}


def _sprite(width, height, data, color):
    return MonoSprite(width, height, data, color)


DINO_RUN = (
    _sprite(10, 7, DINO_RUN_1_BITS, DINO_DAY),
    _sprite(10, 7, DINO_RUN_2_BITS, DINO_DAY),
)
DINO_JUMP = _sprite(10, 7, DINO_JUMP_BITS, DINO_DAY)
DINO_DUCK = (
    _sprite(10, 4, DINO_DUCK_1_BITS, DINO_DAY),
    _sprite(10, 4, DINO_DUCK_2_BITS, DINO_DAY),
)
DINO_DEAD = _sprite(10, 7, DINO_DEAD_BITS, DINO_DAY)
CACTUS_SMALL = _sprite(5, 5, CACTUS_SMALL_BITS, CACTUS_DAY)
CACTUS_TALL = _sprite(6, 7, CACTUS_TALL_BITS, CACTUS_DAY)
CACTUS_CLUSTER = _sprite(9, 6, CACTUS_CLUSTER_BITS, CACTUS_DAY)
BIRD_UP = _sprite(9, 4, BIRD_UP_BITS, BIRD_DAY)
BIRD_DOWN = _sprite(9, 4, BIRD_DOWN_BITS, BIRD_DAY)
CLOUD = _sprite(9, 3, CLOUD_BITS, CLOUD_DAY)
MOON_SPRITE = _sprite(5, 4, MOON_BITS, MOON)
RESTART = _sprite(5, 5, RESTART_BITS, WHITE)
DIGITS = {value: _sprite(3, 5, _bitmap(*rows), SCORE_DAY) for value, rows in DIGIT_ROWS.items()}


class Obstacle:
    def __init__(self, sprite, x, y, kind):
        self.sprite = sprite
        self.x = x * FP
        self.y = y
        self.kind = kind
        self.frame = 0

    def current_sprite(self):
        if self.kind == "bird":
            return BIRD_UP if (self.frame // 8) & 1 else BIRD_DOWN
        return self.sprite


class DinoGame:
    WAITING = 0
    RUNNING = 1
    OVER = 2

    def __init__(self):
        self.canvas = FrameBuffer(bytearray(WIDTH * HEIGHT * 2), WIDTH, HEIGHT, RGB565)
        self.high_score = 0
        self.keys = {"jump": False, "down": False}
        self.state = self.WAITING
        self.last_ms = ticks_ms()
        self.accumulator = 0
        self.blink = 0
        self.reset()

    def reset(self):
        self.state = self.WAITING
        self.score = 0
        self.distance = 0
        self.speed = 116  # 0.45 pixels/frame in 8.8 fixed point.
        self.dino_x = 4
        self.dino_y = (GROUND_Y - DINO_JUMP.height) * FP
        self.velocity_y = 0
        self.on_ground = True
        self.ducking = False
        self.obstacles = []
        self.spawn_distance = 30 * FP
        self.ground_offset = 0
        self.cloud_x = WIDTH - 10
        self.cloud_y = 2
        self.night = False
        self.flash_frames = 0
        self.anim_frame = 0

    def start_or_jump(self):
        if self.state == self.OVER:
            self.reset()
            self.state = self.RUNNING
        elif self.state == self.WAITING:
            self.state = self.RUNNING
        if self.state == self.RUNNING and self.on_ground:
            self.ducking = False
            self.on_ground = False
            self.velocity_y = JUMP_VELOCITY

    def release_jump(self):
        self.velocity_y = max(self.velocity_y, JUMP_RELEASE_VELOCITY)

    def set_down(self, pressed):
        self.keys["down"] = pressed
        if self.on_ground:
            self.ducking = pressed

    def _dino_sprite(self):
        if self.state == self.OVER:
            return DINO_DEAD
        if not self.on_ground:
            return DINO_JUMP
        if self.ducking:
            return DINO_DUCK[(self.anim_frame // 5) & 1]
        return DINO_RUN[(self.anim_frame // 5) & 1]

    def _dino_top(self):
        sprite = self._dino_sprite()
        if self.on_ground:
            return GROUND_Y - sprite.height
        return self.dino_y // FP

    def _spawn(self):
        can_fly = self.score >= 180
        roll = _randint(0, 9)
        if can_fly and roll < 3:
            # Low birds require a jump; middle birds require a duck; high birds
            # can be ignored, matching the three-height Chrome obstacle.
            level = _randint(0, 2)
            y = (GROUND_Y - 4, GROUND_Y - 7, GROUND_Y - 10)[level]
            self.obstacles.append(Obstacle(BIRD_UP, WIDTH + 2, y, "bird"))
        else:
            choice = _randint(0, 9)
            if choice < 4:
                sprite = CACTUS_SMALL
            elif choice < 8:
                sprite = CACTUS_TALL
            else:
                sprite = CACTUS_CLUSTER
            self.obstacles.append(Obstacle(sprite, WIDTH + 2, GROUND_Y - sprite.height, "cactus"))
        speed_px = max(1, self.speed // FP)
        self.spawn_distance = _randint(26, 42) * FP + speed_px * 3 * FP

    def _physics(self):
        if self.on_ground:
            self.ducking = self.keys["down"]
            return
        gravity = FAST_FALL_GRAVITY if self.keys["down"] else GRAVITY
        self.velocity_y += gravity
        self.dino_y += self.velocity_y
        ground = (GROUND_Y - DINO_JUMP.height) * FP
        if self.dino_y >= ground:
            self.dino_y = ground
            self.velocity_y = 0
            self.on_ground = True
            self.ducking = self.keys["down"]

    def _move_world(self):
        self.distance += self.speed
        self.score = self.distance // (FP * 5)
        self.speed = min(310, 116 + self.score // 5)
        self.ground_offset = (self.ground_offset + self.speed) % (8 * FP)
        self.spawn_distance -= self.speed
        if self.spawn_distance <= 0:
            self._spawn()

        alive = []
        for obstacle in self.obstacles:
            obstacle.x -= self.speed
            obstacle.frame += 1
            if obstacle.x // FP + obstacle.current_sprite().width >= 0:
                alive.append(obstacle)
        self.obstacles = alive

        self.cloud_x -= max(1, self.speed // (FP * 3))
        if self.cloud_x + CLOUD.width < 0:
            self.cloud_x = WIDTH + _randint(4, 18)
            self.cloud_y = _randint(1, max(1, GROUND_Y - 10))

        new_night = (self.score // 700) & 1
        self.night = bool(new_night)
        if self.score and self.score % 100 == 0 and self.flash_frames == 0:
            self.flash_frames = 34
        if self.flash_frames:
            self.flash_frames -= 1

    def _collided(self):
        dino = self._dino_sprite()
        dx = self.dino_x
        dy = self._dino_top()
        for obstacle in self.obstacles:
            sprite = obstacle.current_sprite()
            ox = obstacle.x // FP
            if dino.hits(dx, dy, sprite, ox, obstacle.y):
                return True
        return False

    def step(self):
        self.anim_frame += 1
        self.blink += 1
        if self.state != self.RUNNING:
            return
        self._physics()
        self._move_world()
        if self._collided():
            self.state = self.OVER
            self.high_score = max(self.high_score, self.score)
            self.keys["down"] = False
            self.ducking = False

    def _draw_number(self, value, right, color):
        text = ("00000" + str(max(0, min(99999, int(value)))))[-5:]
        x = right - len(text) * 4
        for char in text:
            DIGITS[char].draw(self.canvas, x, 0, color)
            x += 4

    def draw(self):
        self.canvas.fill(BLACK)
        ground_color = GROUND_NIGHT if self.night else GROUND_DAY
        cloud_color = CLOUD_NIGHT if self.night else CLOUD_DAY
        score_color = SCORE_NIGHT if self.night else SCORE_DAY
        dino_color = DINO_NIGHT if self.night else DINO_DAY
        cactus_color = CACTUS_NIGHT if self.night else CACTUS_DAY
        bird_color = BIRD_NIGHT if self.night else BIRD_DAY

        if self.night:
            MOON_SPRITE.draw(self.canvas, WIDTH - 7, 1)
        else:
            CLOUD.draw(self.canvas, self.cloud_x, self.cloud_y, cloud_color)

        offset = self.ground_offset // FP
        for x in range(-offset, WIDTH, 8):
            self.canvas.pixel(x, GROUND_Y, ground_color)
            if x + 2 < WIDTH:
                self.canvas.pixel(x + 2, GROUND_Y + 1, ground_color)

        for obstacle in self.obstacles:
            sprite = obstacle.current_sprite()
            color = bird_color if obstacle.kind == "bird" else cactus_color
            sprite.draw(self.canvas, obstacle.x // FP, obstacle.y, color)

        dino = self._dino_sprite()
        dino.draw(self.canvas, self.dino_x, self._dino_top(), dino_color)

        if self.state == self.RUNNING:
            if not self.flash_frames or (self.flash_frames // 4) & 1:
                self._draw_number(self.score, WIDTH, score_color)
        elif self.state == self.WAITING:
            # A pulsing start marker keeps the idle screen readable at 64x16.
            if (self.blink // 24) & 1:
                RESTART.draw(self.canvas, WIDTH - 7, 1, score_color)
            self._draw_number(self.high_score, WIDTH - 8, score_color)
        else:
            RESTART.draw(self.canvas, WIDTH // 2 - 2, 1, score_color)
            self._draw_number(self.score, WIDTH, score_color)
            if self.high_score:
                self._draw_number(self.high_score, WIDTH - 24, score_color)

        display_drv.blit_rect(self.canvas.buffer, 0, 0, WIDTH, HEIGHT)
        display_drv.show()

    def tick(self, _timer=None):
        app.poll()
        if app.quit_requested:
            return
        now = ticks_ms()
        elapsed = ticks_diff(now, self.last_ms)
        self.last_ms = now
        if elapsed < 0:
            elapsed = FRAME_MS
        self.accumulator += min(80, elapsed)
        while self.accumulator >= FRAME_MS:
            self.step()
            self.accumulator -= FRAME_MS
        self.draw()


game = DinoGame()


def _on_input(event):
    if event.type == app.events.KEYDOWN:
        if event.key in (keys.K_SPACE, keys.K_UP, keys.K_w):
            game.keys["jump"] = True
            game.start_or_jump()
        elif event.key in (keys.K_DOWN, keys.K_s):
            game.set_down(True)
    elif event.type == app.events.KEYUP:
        if event.key in (keys.K_SPACE, keys.K_UP, keys.K_w):
            game.keys["jump"] = False
            game.release_jump()
        elif event.key in (keys.K_DOWN, keys.K_s):
            game.set_down(False)
    elif event.type in (app.events.MOUSEBUTTONDOWN, app.events.FINGERDOWN):
        game.start_or_jump()
    elif event.type in (app.events.MOUSEBUTTONUP, app.events.FINGERUP):
        game.release_jump()


for _event_type in (
    app.events.KEYDOWN,
    app.events.KEYUP,
    app.events.MOUSEBUTTONDOWN,
    app.events.MOUSEBUTTONUP,
    app.events.FINGERDOWN,
    app.events.FINGERUP,
):
    app.on(_event_type, _on_input)


def _tick(timer=None):
    game.tick(timer)


_tick_subscription = app.every(_tick, period=FRAME_MS, async_=app.timer_async)
game.draw()