"""Script mode: keepalive holds the process until the program says stop.

No app.run(). The exit hook takes the main thread after the last line and
delivers until the timer deinits itself, then the process exits.
"""

import multimer

count = [0]


def _tick(t):
    count[0] += 1
    if count[0] % 5 == 0:
        print("[tick]", count[0])
    if count[0] >= 15:
        print("[demo] stopping at", count[0])
        t.deinit()


multimer.keepalive()
tim = multimer.every(20, _tick, name="tick")
print("[demo] strategy:", multimer.strategy())
print("-- script body ends here --")
