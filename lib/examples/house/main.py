# Copy to the board as /main.py to boot into the house appliance: the house
# panel on the display, the dashboard at http://<board ip>/, and a SHOW-TV
# button that casts to the TV. Ctrl-C at the REPL stops it.
import house  # noqa: F401  puts the example's modules on the path
import house_app

try:
    house_app.run(port=80)
except KeyboardInterrupt:
    print("house app stopped")
