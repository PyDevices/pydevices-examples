"""No app.run(), no App: two timers, then the script ends.

Under ``-i`` the prompt must come back with both timers still firing and
inspectable; without ``-i`` the process may exit (no keepalive was asked
for), like a daemon thread.
"""

import multimer

ticks = []
slow = []


def _fast(t):
    ticks.append(multimer.ticks_ms())


def _slow(t):
    slow.append(multimer.ticks_ms())


fast = multimer.every(10, _fast, name="fast")
slower = multimer.every(100, _slow, name="slower")
print("[demo] armed; source:", multimer.info()["source"], "strategy:", multimer.strategy())
print("-- script body ends here --")
