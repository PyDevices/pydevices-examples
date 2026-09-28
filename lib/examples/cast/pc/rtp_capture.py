"""Capture the P4's RTP/MPEG-TS cast on a PC, with arrival times.

Run it with the Windows Python (the LAN reaches it; a WSL socket never sees
the P4's packets): ``python.exe rtp_capture.py OUT.bin [PORT] [SECONDS]``.
Every datagram is stored as ``<Q arrival_ns><H length>payload`` so
``ts_timing.py`` can compare the stream's own clocks with the wall clock.
"""
import socket, struct, sys, time

out = sys.argv[1]
port = int(sys.argv[2]) if len(sys.argv) > 2 else 5004
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 120
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# a deep receive buffer: the stream arrives in bursts and a default 64 KB
# socket buffer drops datagrams here, which would read as link loss
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
s.bind(("0.0.0.0", port))
print("receive buffer", s.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF), flush=True)
s.settimeout(1.0)
n = 0
first = None
with open(out, "wb") as f:
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        now = time.perf_counter_ns()
        if first is None:
            first = now
            print("first packet from", addr, flush=True)
        f.write(struct.pack("<QH", now, len(data)))
        f.write(data)
        n += 1
print("captured", n, "datagrams in", out, flush=True)
