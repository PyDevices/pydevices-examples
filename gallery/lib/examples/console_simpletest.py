# deps: pygraphics
# utils: console
"""
console_simpletest.py
=====================

The smallest useful `Console`: hand it a display and write to it.

`Console` is a text stream, so `print(..., file=console)` works, and it
understands the ANSI escapes a terminal emits, so colors come from either the
`fg` / `bg` arguments or from escape sequences in the text itself.

Nothing here refreshes the display by hand: with no `appdev.App` to own
refresh, the console calls `display_drv.show()` after every write.

Call `console.hide()` to hand the display back to something else, and
`console.show()` to bring the text back.
"""

from board_config import display_drv
from console import Console


console = Console(display_drv, title="console_simpletest")

console.write("Console is a stream, so print() works too.\n")
print("...this line came from print(file=console).", file=console)
console.write("\n")

for i in range(60):
    console.write("line {:02d}  ".format(i))
    console.write("fg/bg arguments\n", fg=Console.BRIGHT_CYAN if i % 2 else Console.GREEN)

console.write("\n\x1b[1;33mANSI escapes\x1b[0m work as well: ")
console.write("\x1b[7mreverse\x1b[27m, \x1b[44;97mwhite on blue\x1b[0m.\n")
console.write("Text older than the last {} lines has scrolled away.\n".format(console.rows))
