"""Hosts with no prompt to fall through to: multimer.repl() is the prompt.

CircuitPython's supervisor resets the board when code.py returns, so the
program holds the main thread itself and reads lines between deliveries.
"""

import multimer

ticks = []
fast = multimer.every(10, lambda t: ticks.append(multimer.ticks_ms()), name="fast")
print("[demo] armed; source:", multimer.info()["source"])
multimer.repl()
print("[demo] repl returned with", len(ticks), "ticks")
