"""A script that raises must surface the error and exit, not enter the loop."""

import multimer

multimer.keepalive()
multimer.every(20, lambda t: None, name="tick")
raise ValueError("boom")
