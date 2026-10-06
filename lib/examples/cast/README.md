# Casting the P4's panel

The Waveshare ESP32-P4 panel can show itself, with sound, on a screen across
the room. Over Wi-Fi, it can:

- **Cast to a Windows laptop.** Open the laptop's Wireless Display app and the
  panel appears in a window. The laptop's mouse and keyboard then drive the
  panel: clicks become touches, keys become key events, and an app on the P4
  cannot tell them from its own touch screen.
- **Cast to a Roku TV, with sound, and control the TV.** The P4 powers the TV
  on, changes the volume or input, and mirrors the panel to it. Sound the P4
  plays is on the TV too, in time with the picture: the drum machine's hits
  land with its step light.
- **Run a smart-home panel.** The house panel example (`house`, beside this one)
  shows the house's sensors on the P4. One button puts the whole panel on the
  TV.

It needs P4 firmware that carries `castif`, which any micropython-pydevices
build with `--modules all` (or one naming `castif`) does; the command for each
P4 is in its [newcomer's guide](https://github.com/PyDevices/micropython-pydevices/blob/main/docs/newcomers.md#boards-we-build-for).
Anything else lacks the H.264 encoder.

## Try it

Install this example on the P4 beside `roku_remote` (for the TV control) and,
for the drum demo, `drum_machine` and `drum_seq`. Each demo has its sink's
address at the top; set it first.

| Demo | What you see |
|---|---|
| `import cast.tv_cast` | The panel on the TV for 60 s with a melody from the P4's speaker and the TV together. The TV is turned on first. |
| `import cast.laptop_input` | The panel in the laptop's Wireless Display app. Move the mouse, click, type: the P4 draws the cursor, a dot per click and the keys. |
| `import cast.drum_cast` | The drum machine, cast with its sound. Press PLAY on the panel. |

A Roku needs **Screen mirroring** on in its settings. A Windows laptop needs
the Wireless Display app open (Settings > System > Projecting to this PC).

## Measuring a cast

`pc/rtp_capture.py` records a cast on a PC, and `pc/ts_timing.py` reports what
a sink would hear: lost packets, audio gaps, the audio and picture clocks
against the PC's, and the A/V offset second by second. Run the capture with
the Windows Python, because a WSL socket does not see the LAN's UDP:

```
python.exe pc/rtp_capture.py capture.bin 5004 700
python pc/ts_timing.py capture.bin
```

then run `drum_cast.py` with `MODE = "capture"` and your PC's address.
`pc/laptop_input.ps1` drives the laptop's mouse and keyboard for
`laptop_input` with nobody at the laptop, and the house example's
`showtv_proof.py` presses SHOW-TV on a schedule with nobody at the panel. On
2026-09-27 a 10-minute drum machine cast measured about 1 ms of A/V drift,
with the audio clock within 13 ppm of the PC's and nothing dropped on the
board.

## How it works

The session with the sink is Wi-Fi Display over infrastructure (MICE, then
RTSP), in Python: `micecast.py`. Once the sink says PLAY, the stream is a C
task on the P4's core 0 (`castif`). It converts the framebuffer with the PPA,
encodes H.264 in hardware, and sends MPEG-TS over RTP, with the audio as
48 kHz LPCM on the same clock. Python only answers keepalives and draws.

Sound reaches the cast in one of two ways. `castfast.PumpFeed` produces 10 ms
blocks for the speaker and the cast at once, paced on the clock. Or castif
reads the audio pump's output itself (`castfast.TapFeed`, `Cast.set_tap`), so
whatever an app plays is what the sink gets, and nothing the interpreter does
can starve it.

`roku_cast.py` wraps both halves for an app: TV control over the Roku's ECP
(through `roku_remote`'s engine) and a cast that starts and stops in the
background.

## Known limits

- **No flash writes while casting.** A littlefs write erases a block about
  every two minutes, which parks core 0 and stalls the cast. With castif
  reading the tap it has crashed the board
  ([micropython-pydevices#26](https://github.com/PyDevices/micropython-pydevices/issues/26)).
  The demos log to the console only.
- **A whole-panel refresh flashes the P4's glass white.** Draw, then refresh
  just the rows you changed (`display_drv.flush_rect`), as the demos do.
- **Weak Wi-Fi is audible.** At -70 dBm about 0.4 % of packets were lost;
  at -80 dBm several percent. Put the P4 near the access point.
