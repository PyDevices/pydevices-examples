# gallery: skip
import board_config
import appdev

app = appdev.App(board_config)


def _heartbeat(_=None):
    print("appdev_simpletest: polling… (click the canvas)")


def _on_event(e):
    print(e)


print("appdev_simpletest: started — click the canvas to see pointer events")
app.every(_heartbeat, period=2000, async_=app.timer_async)

# Subscribe broadly via device type so any pointer/key event prints.
for et in (
    app.events.MOUSEBUTTONDOWN,
    app.events.MOUSEBUTTONUP,
    app.events.MOUSEMOTION,
    app.events.KEYDOWN,
    app.events.KEYUP,
):
    app.on(et, _on_event)