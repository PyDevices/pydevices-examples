# audiolive — an effect rack you can play

Four examples that put a guitar pedalboard on a dev board. A riff (or the
microphone, or a note you play from a DAW) runs through a chain of effects and
out of the speaker, and you change the sound while it plays — with your
fingers on a touchscreen, with a knob, or with a MIDI controller.

The audio never touches the interpreter. A C task pulls the effect graph on
the core the interpreter is not on and writes each block straight into I2S, so
the screen redraws, USB runs and Python loops while the sound keeps its exact
clock. `audiolive/__init__.py` is the surface over that: one object owning the
codec, the graph and the pump, and nothing in an example opens I2S or touches
a codec register.

| | board | what it shows |
|---|---|---|
| [`rack_gui.py`](rack_gui.py) | Waveshare ESP32-P4-WIFI6-Touch-LCD-4B | A touch pedalboard: patch buttons, a slider per macro, BYPASS, MIC, and a live readout of what the audio costs |
| [`rack_midi.py`](rack_midi.py) | the same P4 | The board is a USB MIDI instrument. Play it from a DAW; CCs move the pedals; a program change swaps the whole board |
| [`rack_all.py`](rack_all.py) | the same P4 | All three at once — screen, USB MIDI and the microphone through the pedals — with STARVED on screen in numbers you can read across the room |
| [`rack_knob.py`](rack_knob.py) | LilyGO T-Embed S3 | The same pedalboard for a board with one encoder and no touchscreen |

## Putting one on a board

Copy the package and the example beside it, then start it **without** a soft
reset so the REPL stays alive next to the audio:

```bash
mpftp mkdir -d COM4 /lib/audiolive
mpftp put -d COM4 lib/examples/audiolive/__init__.py /lib/audiolive/__init__.py
mpftp put -d COM4 lib/examples/audiolive/rack_gui.py /lib/audiolive/rack_gui.py
python.exe -m mpremote connect COM4 exec "import audiolive.rack_gui" repl
```

`exec` soft-resets on the way in, which is fine — nothing is playing yet.
`repl` does not: it sends Ctrl-B only, so the pump keeps running and you land
at a prompt with the app still live. Ctrl-] leaves the terminal and the audio
keeps playing.

`rack_all.py` and `rack_knob.py` start the same way (`rack_knob` on the
T-Embed, `-d COM12`). **`rack_midi.py` is the exception**: its MIDI loop is
the foreground, so it is run rather than imported and left.

```bash
mpftp run lib/examples/audiolive/rack_midi.py -d COM4 --follow --timeout 300
```

The firmware needs the pump in it. On a build without the platform driver the
examples say so instead of failing on the import line, and
`audiopump.driver()` tells you which driver bound — `'esp32'` on a board,
`'none'` if it did not link.

## What you should see, hear and touch

**`rack_gui`** — a dark screen with patch names across the top and a stack of
labelled sliders beneath. The speaker plays a six-note plucked phrase, round
and round, with some grit on it. Drag DRIVE right and the phrase gets dirtier
and louder the way a guitar amp does when you turn it up; drag it back and it
cleans up. Tap a different patch name and the sound changes character on the
next note. Tap BYPASS for the bare, clean pluck. Tap MIC and the riff stops
and the room comes through the speaker with the same pedals on it — **put on
headphones first or it will howl**. Along the bottom, `load` is how much of
each block the effects use (under 100 is fine) and `starved` is the one that
matters: milliseconds of silence the speaker had to invent.

**`rack_midi`** — plug the board into a computer with a data cable and it
turns up as a MIDI device. Play a note and a plucked string sounds, in tune,
with overdrive and a tape echo on it. Hold a chord and you get a chord. Move
the mod wheel and the note you are *already holding* gets dirtier, not the
next one. CC 74 — the one most controllers label "filter" or "brightness" —
drags the echo out longer. Program change 1, 2 or 3 swaps the pedalboard and
the note you were holding carries on through the new pedals. Every ten seconds
a line prints what has arrived and what the audio cost, ending in `starved`.

**`rack_all`** — the room comes out of the speaker with overdrive and a tape
echo on it: talk, and you hear yourself, dirty and echoing, about a hundredth
of a second behind. A bar sweeps across the screen the whole time. Play your
MIDI controller and a plucked string joins the room through the same pedals.
Tap a patch name and the whole sound changes. Tap SOURCE to swap the
microphone for the looped riff, which is the fair comparison — same chain,
same load, no acoustic feedback. The four numbers along the bottom are LOAD,
WORST (the slowest single block, against the block length printed beside it),
MIDI (messages arrived) and STARVED, which should be `0 ms` and stay there
while you drag, play and talk at once. Headphones again.

**`rack_knob`** — the patch name at the top, one row per macro, then a line of
numbers. One row is orange; that is the one the knob moves. **Turn** the knob
and that row's value moves — on PATCH it steps through the pedalboards, on a
macro row it moves that macro 0–127 and you hear it immediately. **Press** the
knob and the highlight moves down one row, wrapping at the end. So the knob is
the value and the button is the cursor, which is the one idiom a single
encoder carries without inventing modifiers.

The T-Embed runs the same code 1.6–2.3x slower than the P4, so `rack_knob`
ships its own patch list, `audiolive.LIGHT_PATCHES` — five chains at 64–73 %
of a block, three of them a single pedal. Two classes are out of it entirely:
`ShimmerHall` takes 92 % of its own block there and starves with nothing else
running, and `Reverb` at 52 % leaves no room for a delay behind it.

## Four lessons these paid for

**Draw meters small and slow.** On MicroPython, LVGL's tick is delivered
through `micropython.schedule`, so `lv.task_handler()` runs between the
interpreter's bytecodes — it *is* your app's thread. One repaint of
`rack_all`'s 696 × 240 bar cost **67.8 ms** against a 10 ms tick, and the gate
resynchronises to *now* after an overrun, so repaints ran back to back and the
app had no time left at all: a 300-iteration Python loop took **20.3 s**, and
tapping SOURCE took 73 s. The audio never stopped, which is the point of the
pump, but the app looked hung. With the same bar drawn as a 696 × 40 strip at
8 Hz the same loop is **0.50 ms**. Drawing *often* is dearer than drawing
*big*: on the T-Embed an eight-row moving bar at 237 blits a second costs the
pump 27 points of a block where whole-screen repaints at 31 a second cost 12.
Filed as [lvgl-bindings#15](https://github.com/PyDevices/lvgl-bindings/issues/15).

**Pick the ring for the board.** The DMA ring is the latency and it is also
the only thing that absorbs a slow block, so it is a per-board number rather
than a constant. On the **P4 with its panel lit**, a 190-second run with
pedalboard changes, three thousand slider moves and forced repaints: 4 × 128
was silent all the way through, 6 × 128 lost 381 ms (all of it at patch
changes), and **12 × 128** — 32 ms — read zero on seven readings of nine.
Lighting that 720 × 720 panel alone costs about eleven points of a block,
because a megabyte of framebuffer is read out of PSRAM for every frame it
clocks and the graph is in PSRAM too; no amount of priority reaches a
bandwidth tax. On the **T-Embed's SPI panel** a lit screen costs nothing
measurable, but `rack_knob` needs a *deeper* ring than the P4 does, not a
shallower one: 4 × 128 leaks 426 ms in twenty seconds and 16 × 128 still
leaks 18 ms, while **12 × 256** — 64 ms — reads zero for as long as you turn
a macro (changing pedalboard is another matter, below). What decides it is the
worst block, 8.4–8.7 ms against a 5333 µs block, and a ring in 128-frame
pieces cannot hold one however many of them there are.
`audiolive.DMA_DESC_GUI` is the P4 number and an app opts into it;
32 ms is inaudible for a pedalboard and far too much for playing an
instrument.

**Never write flash while it plays.** A flash erase IPCs the pump's core into
`vTaskSuspendAll()` until it finishes, so no priority, no `IRAM_ATTR` and no
internal RAM protects it. A 512-byte write costs **27–37 ms of stopped audio
on the P4 and 43–48 ms on the T-Embed** against a 5.3 ms block; a 4 KB write
cost the T-Embed 661 ms of silence. A **read is free** — worst block 5.9 ms,
zero starved bytes — and a first `import` is a read. So: no `print()`
redirected to a file, no saved preset, no `mip install` and no log while
something is playing. That is why these examples hold their lines and write
their results once, after teardown.

**A timer tick re-enters your Python between its own bytecodes.** LVGL's tick
and MicroPython's soft timers both arrive through `micropython.schedule`, so a
callback does not wait for the function you are in to finish — it lands
between two of its bytecodes and runs on the same thread. Anything both of
them touch has to be guarded, and the tell is a symptom with no cause in the
code you are reading: a kit change that asked for an I2S peripheral its own
re-entrant copy was already holding and got "Peripheral in use"; a full
pattern that raised `AttributeError` out of a press and read exactly like an
exhausted voice pool, when it was a top-up tick re-arming the keyboard while
the bar was still being laid. Pause the timer across anything that rearranges
state, as `drum_machine._load_machine` does, or hold a flag the callback
checks. A desktop cannot show you this without injecting the interrupt, so it
is a board bug you will meet for the first time on a board.

## Not finished

- **Driving the board's MIDI from WSL needs one policy set once per host.**
  The wire itself is proven: on the Waveshare ESP32-P4, notes, CC 1 and two
  program changes reached a live `rack_all` — `patch: LO-FI`, then
  `patch: CRUNCH` — with `err=0 fault=0`. What it took was `usbipd`'s
  **AutoBind** policy on the board's busid, because the identity it wears with
  MIDI on is a different device from the one a CDC+MSC bind covers. With that
  in place the attach needs no elevation, the kernel autoloads
  `snd-usb-audio`, and raw bytes written to `/dev/snd/midiC0D0` (group
  `audio`) are enough — no `amidi`, no `sudo`, no winmm.
- **`rack_knob` has been heard on the LilyGO T-Embed S3** (2026-09-21, at
  the 12 × 256 ring): patch and macros changed by hand, no clicks and no
  gaps. The hole at a pedalboard change, below, is there if you listen for
  it and was judged very short — acceptable even for playing live.
- **A patch change builds a whole Rack on the UI thread.** One `app.poll()` in
  ten minutes on the P4 hit 222 ms at a patch change. It is a hitch, not a
  hang. On the T-Embed it is a hole you can hear: 395–1036 ms of interpreter
  building the new Rack, and up to 176 ms of silence that no ring depth
  covers — a 190-second run that keeps changing pedalboard reads 3749 ms
  starved at the same 12 × 256 that reads zero under the knob
  ([#126](https://github.com/PyDevices/pydevices-examples/issues/126)).
