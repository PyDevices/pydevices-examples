# gallery: skip
"""Play PCM through a PCMInput into board_peripherals.audio_out (hearable).

Default (hearable on all hosts): write a 440 Hz tone via
audiodev.emulated_audio WAV devices, read it back with the same PCMInput
contract as audio_in, play on audio_out. Also opens board_peripherals.audio_in()
briefly to prove the host mic factory.

Live mic path: pass --live to record ~3 s from board_peripherals.audio_in and play
that buffer back.
"""

import math
import struct
import sys
import time


def _tone_pcm(rate, duration_s=2.0, freq=440.0, amp=0.55):
    samples = int(rate * duration_s)
    buf = bytearray(samples * 2)
    for i in range(samples):
        v = int(32767 * amp * math.sin(2 * math.pi * freq * (i / rate)))
        struct.pack_into("<h", buf, i * 2, v)
    return buf


def _play(out, pcm, label):
    out.write(pcm)
    drain = getattr(out, "drain", None)
    if drain is not None:
        drain()
    else:
        time.sleep(max(0.4, len(pcm) / (out.format.rate * out.format.frame_size) + 0.3))
    print(label, "bytes=", len(pcm))


def _wav_path():
    import os

    try:
        import tempfile

        return os.path.join(tempfile.gettempdir(), "pydevices_examples_audio_in_self_feed.wav")
    except Exception:
        return "pydevices_examples_audio_in_self_feed.wav"


def _self_feed(out, fmt):
    from audiodev.emulated_audio import audio_in as wav_in
    from audiodev.emulated_audio import audio_out as wav_out

    path = _wav_path()
    print("self-feed wav:", path)
    tone = _tone_pcm(fmt.rate, duration_s=2.0)
    wout = wav_out(fmt, path=path)
    wout.write(tone)
    wout.close()

    mic = wav_in(path=path)
    chunk = bytearray(fmt.frame_size * 1024)
    pcm = bytearray()
    while True:
        n = mic.readinto(chunk)
        if not n:
            break
        pcm.extend(chunk[:n])
    mic.close()
    _play(out, pcm, "playing emulated WAV PCMInput -> audio_out")


def _probe_audio_in():
    import board_peripherals

    try:
        import pyscript  # noqa: F401

        print("audio_in probe skipped on pyscript (needs user mic gesture)")
        return
    except Exception:
        pass

    mic = board_peripherals.audio_in()
    print(
        "audio_in opened:",
        mic.format.channels,
        mic.format.rate,
        mic.format.bits,
    )
    buf = bytearray(mic.format.frame_size * 256)
    try:
        n = mic.readinto(buf)
        print("audio_in probe readinto:", n, "bytes")
    except Exception as exc:
        print("audio_in probe readinto raised:", type(exc).__name__, exc)
    finally:
        mic.close()


def _live_capture_playback(out, mic, fmt, seconds=3.0):
    cue = _tone_pcm(fmt.rate, duration_s=0.2, freq=880.0, amp=0.35)
    _play(out, cue, "cue tone (recording starts)")
    time.sleep(0.15)

    frames = int(fmt.rate * seconds)
    need = frames * fmt.frame_size
    chunk = bytearray(fmt.frame_size * 1024)
    pcm = bytearray()
    print("recording from audio_in for", seconds, "s — make some sound")
    deadline = time.time() + seconds
    while len(pcm) < need and time.time() < deadline + 0.5:
        n = mic.readinto(chunk)
        if n:
            pcm.extend(chunk[:n])
        else:
            time.sleep(0.01)
    mic.close()
    print("captured", len(pcm), "bytes")
    if not pcm:
        raise RuntimeError("audio_in returned no samples")
    _play(out, pcm[:need] if len(pcm) > need else pcm, "playing audio_in -> audio_out")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    live = "--live" in argv
    print(
        "audio_in playback test:",
        sys.implementation.name,
        sys.platform,
        "live=" + str(live),
    )

    import board_peripherals

    backend = getattr(board_peripherals, "_select_backend", lambda: "?")()
    print("board_peripherals backend:", backend)

    out = board_peripherals.audio_out()
    fmt = out.format
    print("format:", fmt.channels, fmt.rate, fmt.bits, fmt.signed)

    try:
        if live:
            mic = board_peripherals.audio_in()
            print("audio_in format:", mic.format.channels, mic.format.rate, mic.format.bits)
            _live_capture_playback(out, mic, fmt, seconds=3.0)
        else:
            _self_feed(out, fmt)
            _probe_audio_in()
    finally:
        out.close()
        print("audio_out closed - you should have heard a 440 Hz tone")


main()
