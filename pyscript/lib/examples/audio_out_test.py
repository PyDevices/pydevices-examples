# gallery: skip
"""440 Hz tone smoke test for board_peripherals.audio_out (no display/app)."""

import math
import struct
import sys
import time


def main():
    print(
        "tone test (board_peripherals only, long) starting:",
        sys.implementation.name,
        sys.platform,
    )

    import board_peripherals

    out = board_peripherals.audio_out()
    fmt = out.format
    print("format:", fmt.channels, fmt.rate, fmt.bits, fmt.signed)

    rate = fmt.rate
    freq = 440
    duration_s = 6.0
    samples = int(rate * duration_s)
    amp = 0.6

    if fmt.bits != 16:
        raise RuntimeError("expected 16-bit audio format")

    buf = bytearray(samples * 2)
    for i in range(samples):
        v = int(32767 * amp * math.sin(2 * math.pi * freq * (i / rate)))
        struct.pack_into("<h", buf, i * 2, v)

    print("writing", samples, "samples")
    out.write(buf)
    print("440Hz tone write: OK")

    # Keep process alive briefly so backend drains buffered audio.
    time.sleep(2)
    out.close()
    print("audio_out closed")


if __name__ == "__main__":
    main()
