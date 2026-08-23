"""Minimal itertools subset for MicroPython (used by utils/png.py)."""


class chain:
    def __new__(cls, *iterables):
        return cls._iter(*iterables)

    @staticmethod
    def _iter(*iterables):
        for it in iterables:
            for x in it:
                yield x

    @staticmethod
    def from_iterable(iterable):
        for it in iterable:
            for x in it:
                yield x


def islice(iterable, *args):
    s = slice(*args) if args else slice(None)
    start = 0 if s.start is None else s.start
    stop = s.stop if s.stop is not None else (1 << 62)
    step = 1 if s.step is None else s.step
    for n, x in enumerate(iterable):
        if n >= stop:
            break
        if n >= start and (n - start) % step == 0:
            yield x
