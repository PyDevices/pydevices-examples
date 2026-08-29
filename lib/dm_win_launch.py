# Untracked dev launcher: run the drum machine on micropython.exe from WSL.
# cwd must be pydevices-examples/lib; env cannot cross into a Windows PE,
# so all paths are set up in-process (same approach as example_test_wrapper).
import sys

sys.path[:0] = [
    "examples",
    "../../audioif/lib",
    "../../pydevices/lib",
    "../../pydevices/utils",
]
with open("examples/drum_machine/drum_machine.py") as f:
    exec(f.read(), {"__name__": "__main__"})
