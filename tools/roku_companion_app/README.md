# PyDevices Companion (Roku channel)

The Roku side of `lib/utils/roku_companion.py`: a small channel that speaks
text, shows a dashboard, and displays frames a PyDevices program serves.

Install it once on a Roku in developer mode (Home x3, Up x2, Right, Left,
Right, Left, Right on the remote, then set a password):

```sh
ROKU_DEV_PASSWORD=yourpassword tools/roku_companion_app/sideload.sh 192.0.2.10
```

Also turn on **Settings > System > Advanced system settings > Control by mobile
apps**. Then run any example in `lib/examples/roku/` with the TV's address as
its argument, or with `ROKU_IP` set.

Updates reach the running channel as ECP `input` events, so the screen doesn't
restart for each one; the library launches the channel only when it isn't the
active app.
