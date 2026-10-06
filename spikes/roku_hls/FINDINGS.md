# H.264 to a Roku: step 1 findings (2026-10-06)

The question: can the PyDevices Companion channel play H.264 that we make,
for anything non-interactive, and with how much delay? Step 1 answered it from
the PC with ffmpeg, before touching the P4. Tested on a 65" TCL Roku.

**It plays.** H.264 in MPEG-TS, served as HLS, plays in the channel's new
`video` mode: `RokuCompanion.video(".../stream.m3u8")`, or any URL a Roku
`Video` node takes (`format="mp4"` and so on). The channel reports the player's state, position
and errors back to `/video` on the sending server.

**Audio must be AAC.** AAC plays. LPCM in the TS (what castif muxes for
Miracast) plays the video with no sound and no error. ffmpeg's LPCM is stream
type 0x80; castif's is 0x83; neither is an HLS audio format.

**The delay is about 7 s at the start, settling near 10 s,** with 1-second
segments (a keyframe every second) and a 3-segment playlist, read by eye
against a phone. Longer settings cost more, measured at the start of playback:

| Segments | Playlist | Behind at start |
|---|---|---|
| 1 s | 3 | 6.6–8.3 s |
| 1 s | 3, with `EXT-X-START:TIME-OFFSET=-1` | 10.1 s |
| 2 s | 3 | 13.1 s |
| 1 s | 6 | 17.8 s |

The Roku starts at the oldest segment in the playlist and keeps its own buffer
on top. No stalls in 2½ minutes; one brief hiccup near 2 minutes, after which
it held at about 10 s.

**What step 2 needs from castif:** cut its TS into 1-second segments at
keyframes (its default GOP of 30 is a second at 30 fps), keep the last three,
serve a playlist and the segments over HTTP, and encode audio as AAC (the P4
has no AAC hardware; Espressif's `esp_audio_codec` has a software AAC-LC
encoder) or send video only.

**Step 2 is parked (Brad, 2026-10-06).** esp-vision's H.264 encoder is
expected to come into micropython-pydevices beside castif; step 2 starts after
that, on whichever encoder the P4 then has, video only first.

## Traps found on the way

- **This PC's WSL clock runs about 5% fast** (monotonic: 61.95 s against 59.0 s
  of internet time), with Windows stepping the wall clock back about 1.5 s every
  ~30 s. Switching the clock source to `hyperv_clocksource_tsc_page` did not
  change it. ffmpeg's `-re` paces by that clock, so a live stream from WSL runs
  fast and a TV falls ever further behind (it read 15 s behind after 2½
  minutes). `hls_probe.py --rate 0.952` compensates. Any rate or duration
  measured with the monotonic clock under WSL reads about 5% high.
- **Only port 8090 reaches WSL from the TV.** A server on 8095 never saw a request.
- **The developer screenshot captures graphics, not video:** a playing `Video`
  node is black in it, so delay has to be read by eye or from the player.
- **The player's `position` counts from where playback began**, not from the
  stream's start.
- **Give each run its own URL.** A player from the previous run keeps polling
  the old playlist and errors out ("no valid bitrates") when segment numbers go
  backwards.

## The tools

`hls_probe.py` runs ffmpeg live with the stream time and the PC clock burned in,
serves the HLS on 8090, puts the channel in video mode, and logs every request
and player report. `hls_report.py RUN_DIR` summarises one run.
