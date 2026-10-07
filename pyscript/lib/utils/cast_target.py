"""cast_target -- where a cast board_config sends its picture.

The cast board configs (examples/roku, roku_hls, miracast) ask here for the TV's
or laptop's address, and use their own default when nothing says otherwise:

    from utils import cast_target
    TV = cast_target.get("192.0.2.10")

The address comes from, in order: ``TARGET`` below (a runner, or a board's own
boot code, sets it), the ``CAST_TARGET`` environment variable, then the default.
A board has no environment, which is why the first exists.
"""

TARGET = None


def get(default=None):
    if TARGET:
        return TARGET
    try:
        import os

        env = os.getenv("CAST_TARGET")
    except (ImportError, AttributeError):
        env = None
    return env or default
