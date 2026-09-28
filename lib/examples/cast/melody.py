# melody.py -- a short looping arpeggio as 10 ms blocks of 48 kHz stereo s16
# little-endian PCM, the format the audio pump and the cast both take. Built
# once into RAM so a cast stays cheap.
import math

RATE = 48000
BLOCK_FRAMES = RATE // 100          # 480 frames = 10 ms
BLOCK_BYTES = BLOCK_FRAMES * 4      # 1920 bytes, stereo s16
# C5 E5 G5 C6 up and back to G4
NOTES = [(523, 250), (659, 250), (784, 250), (1047, 250),
         (784, 250), (659, 250), (523, 250), (392, 250)]


def build_melody(notes=NOTES, amp=4000):
    """(buffer, frames): the notes, padded to whole blocks."""
    frames = 0
    for _, ms in notes:
        frames += RATE * ms // 1000
    frames = ((frames + BLOCK_FRAMES - 1) // BLOCK_FRAMES) * BLOCK_FRAMES
    buf = bytearray(frames * 4)
    phase = 0.0
    idx = 0
    for hz, ms in notes:
        step = 2 * math.pi * hz / RATE
        for _ in range(RATE * ms // 1000):
            v = int(amp * math.sin(phase))
            phase += step
            lo = v & 0xFF
            hi = (v >> 8) & 0xFF
            buf[idx] = lo
            buf[idx + 1] = hi
            buf[idx + 2] = lo
            buf[idx + 3] = hi
            idx += 4
    return buf, frames


class Melody:
    """A block source: each call returns the next 10 ms, looping."""

    def __init__(self, notes=NOTES, amp=4000):
        self.buf, self.frames = build_melody(notes, amp)
        self.mv = memoryview(self.buf)
        self.total = self.frames * 4
        self.pos = 0

    def __call__(self):
        end = self.pos + BLOCK_BYTES
        if end <= self.total:
            b = bytes(self.mv[self.pos:end])
            self.pos = 0 if end == self.total else end
        else:
            rest = end - self.total
            b = bytes(self.mv[self.pos:self.total]) + bytes(self.mv[0:rest])
            self.pos = rest
        return b
