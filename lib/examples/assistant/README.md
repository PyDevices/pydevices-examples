# Assistant

Ask the house something, by text or by voice, and Gemini answers, calling
the other devices when it needs to: the Roku TV, the sensor hub, a camera.
It's Batch 8 of the device scenarios, a spike: on the desktop today, and on
the P4 once it's free.

```bash
cd lib/examples/assistant
python assistant.py "what's on the TV?"          # one request
python assistant.py                               # type requests
python phase_a.py OUT --image photo.jpg           # the whole proof, silent
python server.py --roku dry-run                   # the service a board talks to
```

## The key

Put your Gemini API key in `~/.pydevices/secrets/gemini.key` (or set
`GEMINI_API_KEY`). `gemini_key.load_key()` reads it and hands it to the
client, which only puts it in the request header. A board never needs it:
it talks to `server.py` on the PC.

The key in use today is on the API's free tier. That has two costs. Each
model allows only a few requests a minute (5 for Gemini 3.8 Flash), so the
client waits out the limit: the full proof spent six and a half minutes
waiting. And on the free tier, Google may use what you send, camera stills
included, to improve its products. Turning on billing for the key's Cloud
project fixes both. A Google AI subscription doesn't change the API tier.

## What it can do

| Tool | Fires on | Does |
|---|---|---|
| `roku_status` | "what's on the TV?" | power, app, playback, over ECP queries |
| `roku_press`, `roku_volume`, `roku_power`, `roku_launch` | "pause", "turn it down", "turn it off", "open YouTube" | ECP keys, from a fixed safe list |
| `hub_read` | "what's the temperature?", "how humid is it?" | the [sensor hub](../sensor_hub/README.md)'s latest readings |
| `camera_snapshot` | "what can the camera see?" | a still, described by Gemini |

The Roku tools have three modes (`--roku`):

- `dry-run`, the default: queries go to the real TV, but every keypress or
  launch is printed and held back, at the transport, so nothing can slip
  through.
- `sim`: the roku_remote simulator, with no network at all.
- `live`: keys go to the TV. Nothing has been run live yet.

## How fast it is

Measured 2026-09-26 on the desktop over Wi-Fi, with rate-limit waits taken
out. The chat model is Gemini 3.5 Flash-Lite.

| Stage | Time |
|---|---|
| One model round (a request, or a tool result back) | 0.8 to 1.7 s, typically 1.1 |
| A tool request end to end (two rounds plus the tool) | 1.9 to 3.3 s |
| Speech to text (2.6 s of speech, `gemini-3.5-transcribe`) | 1.6 to 2.4 s |
| Text to speech, whole clip (`gemini-3.8-flash-lite-tts`) | 2 to 4 s, one outlier at 35 s |
| Text to speech, streamed, to the first audio (`gemini-3.8-flash-tts`) | 1.2 to 3.6 s |
| Describing a 640-pixel still (`gemini-3.8-flash`) | 3.5 to 7 s |
| **A voice turn: speech in, the TV acts, speech out** | **6.0 s** (desktop), 9.7 s through `server.py` from MicroPython |

Streaming the answer's speech is the next saving: it starts playing about
a second after the text is ready. Streamed, the Flash-Lite speech model ran
slower than real time (13.5 s for 9 s of speech), and full Flash ran ahead
(4.1 s for 7.8 s), so `tts_stream` uses full Flash.

## What it said

From `phase_a.py`, the TV in dry-run or sim, the hub a desktop one with a
test reading of 21.4 °C and 48 %, the camera a stock photo of a banana:

```text
What's playing on the TV?          The TV is currently on and playing YouTube.
Turn the TV volume down a little.  I've turned the TV volume down.      (held back: 3 x VolumeDown)
Mute the TV.                       I've muted the TV.                   (sim)
Pause the TV.                      I've paused the TV for you.          (sim)
Turn the TV off.                   I've turned off the TV.              (sim)
Open YouTube on the TV.            I've opened YouTube on the TV.       (sim)
What's the temperature in here?    The temperature in the living room is 21.4 degrees Celsius, which is about 70.5 Fahrenheit.
How humid is the living room?      The living room humidity is 48 percent.
What can the camera see?           I can see a single yellow banana against a white background.
[till] Name the item for sale:     Banana
```

With the hub down, it says so rather than guessing: "I cannot reach the
sensor hub right now, so I'm not sure of the temperature."

## On a board (Phase B)

`board_voice.py` is the board's side, and it already runs on desktop
MicroPython against `server.py`, with WAV files for the mic and speaker:

```python
import board_voice
board_voice.turn("192.168.1.143")     # record 4 s, ask, play the answer
```

On the P4 that becomes:

1. **Mic to text.** `boarddev.pcm_in` at 16 kHz mono from the ES7210 mics
   (or the C-Media USB mic), 4 s, posted as a WAV to `/voice`: about 128 KB.
2. **The answer out loud.** The reply WAV (24 kHz mono) through
   `boarddev.pcm_out` on the panel's speaker at 85 %, or into the cast
   audio so it plays on the TV or laptop that's showing the P4's screen.
3. **The camera.** `cameraif`'s `capture_jpeg(85)` on the OV5647, posted to
   `/see?q=...`, or served on the P4 so `server.py --camera-url
   http://P4/still.jpg` fetches it when Gemini calls `camera_snapshot`.
4. **Push to talk, then a wake word.** A button (or a tap on the panel)
   starts the recording first. Voice-activity detection to end it early is
   next; a wake word is a later spike.
5. **Then shorter turns.** Stream the reply's speech to the speaker as it
   arrives, and try Gemini's Live API (`gemini-3.8-live`), which takes
   audio in and gives audio out over one WebSocket and would fold three
   calls into one.

What's needed: the P4, daytime for anything audible, and Brad at the TV
before any `--roku live` key.

## Files

| File | What |
|---|---|
| `gemini.py` | the Gemini REST client: chat with tools, vision, STT, TTS, streamed TTS |
| `gemini_key.py` | loads the key without showing it |
| `tools.py` | the tools and their declarations; the Roku modes |
| `assistant.py` | the function-calling loop, and a text prompt |
| `phase_a.py` | the silent proof: every tool, speech through files, vision |
| `server.py` | the assistant over HTTP, for boards |
| `board_voice.py` | a board's voice turn: record, post, play |

The client is new rather than taken from `ai-models`: that package's Gemini
adapters are placeholders, so its `tts_gemini` and `chat_gemini` examples
don't run. The API calls here were checked against the live model list.
