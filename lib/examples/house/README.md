# The house panel

The ESP32-P4 panel as a smart-home appliance:

- **On the panel:** every room's temperature, humidity, light and motion, with
  an alert when a room goes damp or warm.
- **On a phone:** the same rooms, live, at `http://<board ip>/`.
- **On the TV:** a SHOW-TV button casts the whole panel to a Roku, with the
  alert chime, and a second press stops it.

Real nodes come first. A FunHouse running the sensor hub's `funhouse_node`
posts to the panel's `/api/publish` and takes the first card; a simulated house
fills the other rooms.

## Run it

Install this example with `cast`, `roku_remote` and `sensor_hub` beside it. It
needs the P4 firmware that carries `castif` (micropython-pydevices' default
P4 build). Set `TV` in `house_panel.py` to your Roku's address, then:

```python
import house.house_app as a; a.run()
```

To boot into it, copy `main.py` to the board as `/main.py`. Ctrl-C at the REPL
stops it.

`house_server.py` serves the dashboard alone, without the panel.

The app writes nothing to flash while it runs: a flash write stalls a running
cast (see the `cast` example's README).
