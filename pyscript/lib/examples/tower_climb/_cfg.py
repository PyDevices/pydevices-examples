"""tower_climb launch flags (argv only — no getenv).

Interactive MCU/desktop: run with no flags.
Host tools (playtest, record_*.sh) pass ``--bot``, ``--trace``, etc.

Unknown argv tokens are ignored so the example_test_wrapper's flags are safe.
"""

import sys

# Mutated once by ``parse()``; game code reads these module attributes.
seed = None  # None → ticks_ms() in game
bot = False
record = False
hold_win = False
trace = ""
video = ""
video_fps = 12
hold_frames = None  # None → 48 when recording, else 150


def parse(argv=None):
    """Parse known flags from *argv* (default ``sys.argv[1:]``). Idempotent."""
    global seed, bot, record, hold_win, trace, video, video_fps, hold_frames
    if argv is None:
        try:
            argv = list(sys.argv[1:])
        except Exception:
            argv = []

    seed = None
    bot = False
    record = False
    hold_win = False
    trace = ""
    video = ""
    video_fps = 12
    hold_frames = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--bot":
            bot = True
            i += 1
        elif arg == "--record":
            record = True
            bot = True
            i += 1
        elif arg == "--hold-win":
            hold_win = True
            i += 1
        elif arg == "--seed" and i + 1 < len(argv):
            try:
                seed = int(argv[i + 1], 0)
            except ValueError:
                seed = None
            i += 2
        elif arg == "--trace" and i + 1 < len(argv):
            trace = str(argv[i + 1])
            i += 2
        elif arg == "--video" and i + 1 < len(argv):
            video = str(argv[i + 1])
            i += 2
        elif arg == "--video-fps" and i + 1 < len(argv):
            try:
                video_fps = int(argv[i + 1])
            except ValueError:
                video_fps = 12
            i += 2
        elif arg == "--hold-frames" and i + 1 < len(argv):
            try:
                hold_frames = int(argv[i + 1])
            except ValueError:
                hold_frames = None
            i += 2
        else:
            i += 1


parse()
