# How casting works

The [cast README](https://github.com/PyDevices/pydevices-examples/blob/main/lib/examples/cast/README.md#how-it-works) covers the
Miracast session (Wi-Fi Display over infrastructure, MICE and RTSP, in
Python), and the C task that streams MPEG-TS over RTP with the audio on the
same clock. The encoders and the muxer are firmware modules of their own:
[`h264enc`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/h264enc),
[`tsmux`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/tsmux)
and the PPA's colour conversion,
[`ppa`](https://github.com/PyDevices/micropython-pydevices/tree/main/modules/ppa).
The Companion channel's BrightScript is in
[`tools/roku_companion_app`](https://github.com/PyDevices/pydevices-examples/blob/main/tools/roku_companion_app/README.md), and its
Python side in [`lib/utils/roku_companion.py`](https://github.com/PyDevices/pydevices-examples/blob/main/lib/utils/roku_companion.py).
