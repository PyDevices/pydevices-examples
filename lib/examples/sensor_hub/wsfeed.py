"""A one-way WebSocket feed for an asyncio HTTP server (MicroPython and CPython).

The server pushes text frames to every browser that connects; what the
browser sends is read only to notice pings and a close. That is all a live
dashboard needs, and it keeps the code small enough for an ESP32.

    feed = Feed()
    # in your HTTP handler, once you have the request headers:
    if headers.get("upgrade", "").lower() == "websocket":
        await feed.serve(reader, writer, headers, hello='{"type":"hello"}')
    # anywhere, synchronously:
    feed.send('{"type":"reading", ...}')

A slow browser can't hold up the others: each client has its own short
queue, and when it overflows the oldest message is dropped.
"""

import asyncio
import binascii
import hashlib

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
QUEUE_MAX = 32


def accept_key(key):
    """The Sec-WebSocket-Accept value for a client's Sec-WebSocket-Key."""
    digest = hashlib.sha1(key.encode() + _GUID).digest()
    return binascii.b2a_base64(digest).strip().decode()


def frame(payload, opcode=0x1):
    """One unmasked, final server frame (text by default)."""
    if isinstance(payload, str):
        payload = payload.encode()
    n = len(payload)
    if n < 126:
        head = bytes((0x80 | opcode, n))
    elif n < 65536:
        head = bytes((0x80 | opcode, 126, n >> 8, n & 0xFF))
    else:
        head = bytes((0x80 | opcode, 127)) + n.to_bytes(8, "big")
    return head + payload


class _Client:
    def __init__(self, writer):
        self.writer = writer
        self.queue = []
        self.ready = asyncio.Event()
        self.open = True

    def push(self, data):
        if len(self.queue) >= QUEUE_MAX:
            self.queue.pop(0)
        self.queue.append(data)
        self.ready.set()


class Feed:
    def __init__(self):
        self.clients = []
        self.sent = 0

    def __len__(self):
        return len(self.clients)

    def send(self, text):
        """Queue ``text`` for every connected browser. Safe to call from sync code."""
        if not self.clients:
            return
        data = frame(text)
        for c in self.clients:
            c.push(data)
        self.sent += 1

    async def serve(self, reader, writer, headers, hello=None):
        """Finish the handshake and serve one browser until it goes away."""
        key = headers.get("sec-websocket-key")
        if not key:
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return
        writer.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept_key(key).encode() + b"\r\n\r\n"
        )
        await writer.drain()
        client = _Client(writer)
        if hello is not None:
            client.push(frame(hello))
        self.clients.append(client)
        sender = asyncio.create_task(self._sender(client))
        try:
            await self._reader(reader, client)
        except Exception:
            pass
        finally:
            client.open = False
            client.ready.set()
            if client in self.clients:
                self.clients.remove(client)
            try:
                await sender
            except Exception:
                pass

    async def _sender(self, client):
        w = client.writer
        try:
            while client.open:
                await client.ready.wait()
                client.ready.clear()
                while client.queue and client.open:
                    w.write(client.queue.pop(0))
                    await w.drain()
        except Exception:
            client.open = False

    async def _reader(self, reader, client):
        while client.open:
            head = await reader.readexactly(2)
            opcode = head[0] & 0x0F
            n = head[1] & 0x7F
            if n == 126:
                n = int.from_bytes(await reader.readexactly(2), "big")
            elif n == 127:
                n = int.from_bytes(await reader.readexactly(8), "big")
            mask = await reader.readexactly(4) if head[1] & 0x80 else None
            data = await reader.readexactly(n) if n else b""
            if mask:
                data = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
            if opcode == 0x8:  # close: answer it, then stop
                client.push(frame(data[:2], 0x8))
                return
            if opcode == 0x9:  # ping
                client.push(frame(data, 0xA))
