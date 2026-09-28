# drum_cast.py -- the drum machine example on the P4, its sound on the cast.
# The cast takes the audio pump's OUTPUT: castif reads the pump's tap from its
# own task on core 0 (Cast.set_tap), so what the P4 plays is what the sink gets,
# whatever the interpreter is doing. Press PLAY on the panel.
#
#   import cast.drum_cast
#
#   MODE = "tv":      cast to a Roku TV (set TV) for a listen.
#   MODE = "capture": castif straight to a PC running pc/rtp_capture.py (set
#                     PC), for a measured run; PLAY is pressed for you.
#                     Analyse the capture with pc/ts_timing.py.
#
# Nothing here writes to flash while the cast runs: a littlefs block erase
# parks core 0 and stalls the cast.
import sys
import time
from _common import log, wifi_up
from board_config import fb
import castfast

MODE = "tv"
TV = "192.168.1.129"      # your Roku's IP address
PC = "192.168.1.143"      # the PC running pc/rtp_capture.py
SECONDS = 150 if MODE == "tv" else 630

w = wifi_up()
# The drum machine opens board_peripherals.audio_out(latency="low"), which on
# the P4 is 24 kHz mono; the cast carries 48 kHz stereo and converts.
feed = castfast.TapFeed(rate=24000, channels=1, log=log)

if MODE == "tv":
    from roku_cast import RokuScreen
    tv = RokuScreen(TV, name="PyDevices Drums", log=log)
    tv.on()
    ok = tv.start_cast(fb, audio=feed, seconds=SECONDS, skip_ms=0)   # every frame: the step light is small
    log("cast thread started:", ok)
else:
    import _thread
    import micropython
    # a scheduled LVGL callback can run on whichever thread is sleeping, and
    # the default thread stack is too small for it
    _thread.stack_size(32 * 1024)
    cast = castfast.make_caster(720, 720, fps=30, bitrate=3_000_000, audio=True)
    feed.cast = cast
    cast.start(fb, PC, 5004, 15550)
    cast.set_skip(0)
    log("castif -> %s:5004 with the pump tap, %d s" % (PC, SECONDS))

    def reporter():
        t0 = time.ticks_ms()
        beat = 0
        try:
            while time.ticks_diff(time.ticks_ms(), t0) < SECONDS * 1000:
                feed.pump()          # hands the tap to castif on the first call
                el = time.ticks_diff(time.ticks_ms(), t0)
                if el // 5000 > beat:
                    beat = el // 5000
                    s = cast.stats()
                    log("castif: %d f %.1f fps | fed %d muxed %d level %d under %d drift %d ms ins %d drop %d rejoin %d | tap %d lapped %d" % (
                        s["frames"], s["fps"] / 1000.0, s["audio_fed"], s["audio_muxed"], s["audio_level"],
                        s["audio_underruns"], s["audio_drift_ms"], s["audio_inserted"], s["audio_dropped"],
                        s["audio_rejoins"], s["tap_bytes"], s["tap_lapped"]))
                time.sleep_ms(25)
        finally:
            cast.stop()
            log("capture run done")

    _thread.start_new_thread(reporter, ())

    # nobody is at the panel: press PLAY once the app exists, on the main
    # thread (LVGL is not thread-safe)
    def press_play(_):
        import lvgl as lv
        dm = sys.modules["drum_machine.drum_machine"].machine
        dm.play_btn.add_state(lv.STATE.CHECKED)
        dm._on_play(None)
        log("PLAY pressed")

    def autoplay():
        while getattr(sys.modules.get("drum_machine.drum_machine"), "machine", None) is None:
            time.sleep_ms(200)
        time.sleep_ms(3000)
        micropython.schedule(press_play, None)

    _thread.start_new_thread(autoplay, ())

log("starting the drum machine")
import drum_machine  # noqa: E402,F401  runs the app; it owns the main thread from here
