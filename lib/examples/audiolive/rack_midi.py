# deps: audioeffects, audioinstruments
# gallery: skip
"""rack_midi.py - the board is a USB MIDI instrument you play from a DAW.

Plug the board into a computer with a data cable and it turns up as a MIDI
device. Play it and you hear a plucked string come out of the board's own
speaker, through the same pedalboard the touchscreen example uses. Turn a
knob on your controller and the pedals move. Send a program change and the
whole pedalboard changes.

Nothing is needed on the computer but something that sends MIDI - a DAW
track, a MIDI monitor, a USB keyboard routed through either.

The costume
-----------
usbif calls the set of USB functions a board presents its "costume". This
example wears **CDC + MIDI**::

    _usbif.dev_functions(_usbif.FN_CDC | _usbif.FN_MIDI)

MIDI because that is the point, and CDC because dropping it would take the
REPL down with it - and the REPL is how you start and stop this. The
costume is only re-applied when it is not already right, because changing
it drops the host's connection and costs a fresh enumeration. So the first
run makes the serial port disappear and come back once; later runs do not.

If your firmware was built without the MIDI function the example says so
and stops: ``_usbif.dev_functions_built() & _usbif.FN_MIDI``.

Run it on the Waveshare ESP32-P4-WIFI6-Touch-LCD-4B
--------------------------------------------------
::

    mpftp mkdir -d COM4 /lib/audiolive
    mpftp put -d COM4 lib/examples/audiolive/__init__.py /lib/audiolive/__init__.py
    mpftp run lib/examples/audiolive/rack_midi.py -d COM4 --follow --timeout 300

This one owns the terminal, unlike the two LVGL examples here: its MIDI
loop is the foreground, so it is run rather than imported-and-left. The
soft reset ``run`` does on the way in is harmless - nothing is playing yet
- and the pump is torn down when the run ends, whether you stop it or it
times out. (The P4's USB host controller detects nothing at high speed, so
the P4 is always the device in a pairing - see usbif#3.)

``MidiRack`` below is the reusable half - it turns parsed MIDI into sound
and knows nothing about how the bytes arrived. ``rack_all.py`` drives the
same idea from an LVGL timer instead of a loop, which is what an app with
a screen wants.

What you should see and hear
----------------------------
Play a note on your controller and a plucked string sounds, in tune with
what you played, with overdrive and a tape echo on it. Hold a chord and you
get a chord. Move the mod wheel and the drive comes up - the note you are
already holding gets dirtier as you move it, not on the next note.
CC 74 (the one most controllers label "filter" or "brightness") moves the
second pedal's first knob, so on the CRUNCH board it drags the echo out
longer. Send program change 1, 2 or 3 and the pedalboard changes to DIRT,
CLEAN or LO-FI; the note you were holding carries on through the new
pedals.

Every ten seconds a line prints saying what has arrived and what the audio
cost, ending in ``starved``. That number is how many milliseconds of
silence the speaker had to invent because the effects were late while USB
was busy. It should stay at zero.
"""

import time

import _usbif
import usbif

import audiolive
from audiolive import PATCHES

INSTRUMENT = "karplus"
MOUNT_TIMEOUT_MS = 10000
REPORT_MS = 10000
BUF = bytearray(256)

# Controller number -> (which pedal in the chain, which of its macros).
# These are the CCs a general-purpose controller already sends: 1 is the
# mod wheel, 74 and 71 are the two knobs the MIDI spec calls brightness and
# harmonic content, 91 is the reverb send. Nothing here is magic - it is a
# dict, and a user's own controller wants their own numbers in it.
CC_MAP = {
    1: (0, 0),          # mod wheel   -> first pedal, first knob (usually Drive)
    74: (1, 0),         # brightness  -> second pedal, first knob
    71: (0, 1),         # harmonics   -> first pedal, second knob
    91: (1, 2),         # reverb send -> second pedal, third knob (usually Mix)
}


def wait_for_mount(timeout_ms=MOUNT_TIMEOUT_MS):
    """Wait for the host to configure us, so we do not read into the void."""
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        connected, mounted, _ = _usbif.dev_state()
        if mounted:
            return True
        time.sleep_ms(50)
    print("the host never configured us.")
    print("  check the cable is a data cable and is in the native USB jack,")
    print("  not only the UART bridge.")
    return False


class MidiRack:
    def __init__(self, patch=0):
        self.live = audiolive.LiveAudio(volume=audiolive.VOLUME)
        self.patch = patch
        # An instrument rather than the looped riff: this one is played.
        self.live.play(PATCHES[patch][1], source=INSTRUMENT)
        self.synth = self.live.synth
        self.parser = usbif.MidiParser()
        self.counts = {}
        self.held = set()

    def program_change(self, index):
        index %= len(PATCHES)
        if index == self.patch:
            return
        self.patch = index
        # The new pedals are built while the old ones are still playing, and
        # the pump is pointed at the finished chain in one locked move. The
        # instrument underneath is untouched, so a held note carries through.
        self.live.play(PATCHES[index][1])
        print("patch:", PATCHES[index][0],
              [type(f).NAME for f in self.live.effects])

    def control_change(self, controller, value):
        where = CC_MAP.get(controller)
        if where is None:
            return
        slot, macro = where
        try:
            self.live.knob(slot, macro, value)
        except (IndexError, KeyError):
            pass        # this pedal has no such knob; a CC is a wire message

    def note_on(self, pitch, velocity):
        # press() "now". There is no timestamped event queue in the pump
        # yet, so a note lands at the next block boundary rather than at a
        # frame you chose - fine for playing, not enough for a sequencer.
        self.synth.note_on(pitch, velocity)
        self.held.add(pitch)

    def note_off(self, pitch):
        self.synth.note_off(pitch)
        self.held.discard(pitch)

    def feed(self, buf, n):
        """One USB packet's worth of MIDI, turned into sound."""
        self.parser.feed(buf, n)
        for status, data in self.parser.drain():
            kind = status >> 4
            self.counts[kind] = self.counts.get(kind, 0) + 1
            if kind == 0x9 and len(data) == 2 and data[1]:
                self.note_on(data[0], data[1])
            elif kind == 0x8 or (kind == 0x9 and len(data) == 2):
                self.note_off(data[0])
            elif kind == 0xB and len(data) == 2:
                self.control_change(data[0], data[1])
            elif kind == 0xC and len(data) >= 1:
                self.program_change(data[0])

    def report(self):
        s = self.live.status()
        seen = ", ".join("%s %d" % (NAMES.get(k, "?"), v)
                         for k, v in sorted(self.counts.items()))
        print("%s | held %d | load %d%% worst %d/%d us starved %d ms"
              % (seen or "nothing yet", len(self.held), s["load_pct"],
                 s["worst_us"], s["block_us"], s["starved_ms"]))

    def stop(self):
        for pitch in tuple(self.held):
            self.note_off(pitch)
        self.live.stop()


NAMES = {0x8: "note-off", 0x9: "note-on", 0xB: "cc", 0xC: "program",
         0xE: "bend"}


def main():
    built = _usbif.dev_functions_built()
    if not (built & _usbif.FN_MIDI):
        print("this firmware has no MIDI device function built in")
        return False

    restore = _usbif.dev_functions()
    want = _usbif.FN_CDC | _usbif.FN_MIDI
    if restore != want:
        # Re-enumerating costs the host's connection, so only do it when the
        # costume is actually wrong. CDC stays on so the REPL survives.
        _usbif.dev_functions(want)
        print("costume: cdc+midi -- the serial port re-enumerates once")
    else:
        print("costume: already cdc+midi, left alone")

    rack = MidiRack()
    print("pedalboard:", PATCHES[0][0],
          [type(f).NAME for f in rack.live.effects])
    print("play into it. program change 0-3 picks the pedalboard.")
    if not wait_for_mount():
        rack.stop()
        return False

    next_report = time.ticks_add(time.ticks_ms(), REPORT_MS)
    try:
        while True:
            n = _usbif.midi_read(BUF)
            if n:
                rack.feed(BUF, n)
            else:
                # The audio is pulled by a C task on the other core, so
                # sleeping here costs it nothing at all.
                time.sleep_ms(2)
            if time.ticks_diff(next_report, time.ticks_ms()) <= 0:
                rack.report()
                next_report = time.ticks_add(time.ticks_ms(), REPORT_MS)
    except KeyboardInterrupt:
        print("stopping")
    finally:
        rack.report()
        rack.stop()
        if restore != want:
            _usbif.dev_functions(restore)
    return True


# `mpftp run` and `mpremote exec` both execute a file as `__main__`, so the
# documented way in still starts the loop. Importing the module does not, so
# `MidiRack` is reusable - rack_all.py does the same job from an LVGL timer.
if __name__ == "__main__":
    main()
