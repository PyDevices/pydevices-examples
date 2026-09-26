# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
board_voice
====================================================
The board's half of a voice turn: record from a mic, send it to the
assistant server on the PC, play the answer. No API key on the board.

On a board with a mic and a speaker (the P4)::

    import board_voice
    board_voice.turn("192.168.1.143")            # records 4 s, then speaks

It runs on desktop MicroPython and CPython too, with WAV files standing in
for the mic and speaker (``python board_voice.py HOST in.wav out.wav``).
"""

import socket
import struct
import sys

try:
    from time import ticks_diff, ticks_ms
except ImportError:
    from time import perf_counter

    def ticks_ms():
        return int(perf_counter() * 1000)

    def ticks_diff(a, b):
        return a - b


PORT = 8770
RATE = 16000  # plenty for speech, and a third of the upload at 48 kHz


def wav_header(rate, channels, bits, n):
    block = channels * bits // 8
    return (
        b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits)
        + b"data" + struct.pack("<I", n)
    )


def record(pcm_in, seconds):
    """Read ``seconds`` of audio from an audiodev PCMInput; returns a WAV."""
    fmt = pcm_in.format
    total = int(seconds * fmt.rate) * fmt.frame_size
    buf = bytearray(total)
    view = memoryview(buf)
    got = 0
    chunk = fmt.frame_size * 512
    while got < total:
        n = pcm_in.readinto(view[got : got + min(chunk, total - got)])
        if not n:
            break
        got += n
    return wav_header(fmt.rate, fmt.channels, fmt.bits, got) + bytes(buf[:got])


def post(host, path, body, ctype="audio/wav", port=PORT, timeout=60):
    """A bare HTTP/1.0 POST that any MicroPython port can make.

    Returns (status, headers dict with lower-case names, body bytes).
    """
    addr = socket.getaddrinfo(host, port)[0][-1]
    s = socket.socket()
    try:
        s.settimeout(timeout)
        s.connect(addr)
        head = "POST %s HTTP/1.0\r\nHost: %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n\r\n" % (
            path, host, ctype, len(body))
        s.sendall(head.encode())
        mv = memoryview(body)
        for i in range(0, len(body), 4096):
            s.sendall(mv[i : i + 4096])
        data = b""
        while True:
            part = s.recv(4096)
            if not part:
                break
            data += part
    finally:
        s.close()
    i = data.find(b"\r\n\r\n")
    lines = data[:i].decode().split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(":")
        headers[k.strip().lower()] = v.strip()
    return status, headers, data[i + 4 :]


def play(pcm_out, wav):
    """Play a 16-bit PCM WAV through an audiodev PCMOutput of the same format."""
    i = wav.find(b"data")
    pcm_out.write(memoryview(wav)[i + 8 :])


def ask(host, wav):
    """One voice turn over HTTP. Returns (heard, reply, reply_wav, timings)."""
    t0 = ticks_ms()
    status, h, body = post(host, "/voice", wav)
    ms = ticks_diff(ticks_ms(), t0)
    if status != 200:
        raise OSError("assistant: HTTP %d %s" % (status, body[:200]))
    return h.get("x-heard", ""), h.get("x-reply", ""), body, "%s round_trip=%.2f" % (h.get("x-timing", ""), ms / 1000)


def see(host, jpeg, question="Describe what you see in two sentences."):
    q = question.replace(" ", "%20").replace("?", "%3F")
    status, _, body = post(host, "/see?q=" + q, jpeg, "image/jpeg")
    return body.decode()


def turn(host, seconds=4, pcm_in=None, pcm_out=None):
    """Record, ask, speak. Uses the board's own mic and speaker by default."""
    if pcm_in is None or pcm_out is None:
        import boarddev
        from audiodev import AudioFormat

        pcm_in = pcm_in or boarddev.pcm_in(AudioFormat(RATE, 1, 16))
        pcm_out = pcm_out or boarddev.pcm_out(AudioFormat(24000, 1, 16))
    print("listening...")
    wav = record(pcm_in, seconds)
    heard, reply, answer, timing = ask(host, wav)
    print("heard:", heard)
    print("reply:", reply)
    print(timing)
    play(pcm_out, answer)
    return heard, reply


if __name__ == "__main__":
    # Desktop stand-in: WAV in, WAV out.
    host, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(src, "rb") as f:
        wav = f.read()
    heard, reply, answer, timing = ask(host, wav)
    with open(dst, "wb") as f:
        f.write(answer)
    print("heard:", heard)
    print("reply:", reply)
    print(timing)
