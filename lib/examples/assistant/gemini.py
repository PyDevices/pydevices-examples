# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
gemini
====================================================
A small Gemini REST client: chat with function calling, vision, speech
to text and text to speech, all through ``generateContent``.

Written for CPython first, with nothing a MicroPython board lacks except
the HTTP transport: it uses ``urllib`` on CPython and ``requests`` on a
board. The key is passed in by the caller and only ever goes into the
``x-goog-api-key`` header.
"""

import json

try:
    import binascii

    def _b64e(data):
        return binascii.b2a_base64(data).strip().decode()

    def _b64d(text):
        return binascii.a2b_base64(text)
except ImportError:  # pragma: no cover
    import base64

    def _b64e(data):
        return base64.b64encode(data).decode()

    def _b64d(text):
        return base64.b64decode(text)

try:
    import urllib.request as _urlreq
    import urllib.error as _urlerr
except ImportError:  # MicroPython
    _urlreq = None
    import requests as _requests

try:
    from time import perf_counter as _now
except ImportError:  # MicroPython
    from time import ticks_ms as _tms

    def _now():
        return _tms() / 1000

BASE = "https://generativelanguage.googleapis.com/v1beta/models/"

# Checked against the live model list on 2026-09-26.
# On the API's free tier, each model has its own per-minute budget (3.8
# Flash allows 5 requests a minute), so chat and vision use different ones.
CHAT_MODEL = "gemini-3.5-flash-lite"
SMART_MODEL = "gemini-3.8-flash"
VISION_MODEL = "gemini-3.8-flash"
TTS_MODEL = "gemini-3.8-flash-lite-tts"
# Streamed, the lite model came in slower than real time (13.5 s for 9 s of
# speech) while the full one ran ahead of it (4.1 s for 7.8 s).
STREAM_TTS_MODEL = "gemini-3.8-flash-tts"
STT_MODEL = "gemini-3.5-transcribe"
TTS_RATE = 24000


class GeminiError(Exception):
    pass


class Gemini:
    def __init__(self, api_key, timeout=60):
        self._key = api_key
        self.timeout = timeout
        self.last_latency = 0.0
        self.waited = 0.0  # seconds spent waiting out rate limits

    # -- transport ---------------------------------------------------------
    def _post(self, model, body, retries=3):
        """POST, waiting out a 429 (the free tier's per-minute cap) or a 503 up to ``retries`` times."""
        for attempt in range(retries + 1):
            try:
                return self._post_once(model, body)
            except GeminiError as e:
                wait = _retry_delay(str(e))
                if attempt == retries or wait is None:
                    raise
                self.waited += wait
                _sleep(wait)

    def _post_once(self, model, body):
        url = BASE + model + ":generateContent"
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        t0 = _now()
        if _urlreq is not None:
            req = _urlreq.Request(url, data=data, headers=headers, method="POST")
            try:
                with _urlreq.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read())
            except _urlerr.HTTPError as e:
                raise GeminiError("HTTP %d: %s" % (e.code, e.read()[:2000].decode("utf-8", "replace")))
        else:
            r = _requests.post(url, data=data, headers=headers)
            try:
                if r.status_code >= 400:
                    raise GeminiError("HTTP %d: %s" % (r.status_code, r.text[:2000]))
                out = r.json()
            finally:
                r.close()
        self.last_latency = _now() - t0
        return out

    @staticmethod
    def _parts(resp):
        try:
            return resp["candidates"][0]["content"].get("parts", [])
        except (KeyError, IndexError):
            raise GeminiError("no candidate: " + json.dumps(resp)[:300])

    @classmethod
    def _text(cls, resp):
        return "".join(p.get("text", "") for p in cls._parts(resp) if not p.get("thought")).strip()

    # -- chat with tools ---------------------------------------------------
    def chat(self, contents, tools=None, system=None, model=CHAT_MODEL):
        """One turn. Returns the model's ``content`` dict (role + parts)."""
        body = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]
        resp = self._post(model, body)
        try:
            return resp["candidates"][0]["content"]
        except (KeyError, IndexError):
            raise GeminiError("no candidate: " + json.dumps(resp)[:300])

    # -- vision ------------------------------------------------------------
    def describe(self, jpeg, prompt="Describe what you see in two sentences.", model=VISION_MODEL):
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inlineData": {"mimeType": "image/jpeg", "data": _b64e(jpeg)}},
                        {"text": prompt},
                    ],
                }
            ]
        }
        return self._text(self._post(model, body))

    # -- speech ------------------------------------------------------------
    def tts(self, text, voice="Kore", model=TTS_MODEL):
        """Text to speech. Returns (pcm_bytes, sample_rate): 16-bit mono."""
        body = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        for p in self._parts(self._post(model, body)):
            inline = p.get("inlineData")
            if inline:
                raw = _b64d(inline["data"])
                mime = inline.get("mimeType", "")
                if raw[:4] == b"RIFF":
                    return _wav_pcm(raw)
                rate = TTS_RATE
                if "rate=" in mime:
                    rate = int(mime.split("rate=")[1].split(";")[0])
                return raw, rate
        raise GeminiError("no audio in TTS response")

    def tts_stream(self, text, voice="Kore", model=STREAM_TTS_MODEL):
        """Text to speech as it's made: yields 16-bit mono PCM chunks at TTS_RATE.

        The first chunk arrives in about 1.2-1.5 s, against 3-4 s for the whole
        clip from ``tts``. CPython only for now (it reads server-sent events).
        """
        body = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        url = BASE + model + ":streamGenerateContent?alt=sse"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self._key}
        req = _urlreq.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with _urlreq.urlopen(req, timeout=self.timeout) as r:
            for line in r:
                if not line.startswith(b"data:"):
                    continue
                for p in json.loads(line[5:])["candidates"][0]["content"].get("parts", []):
                    if "inlineData" in p:
                        yield _b64d(p["inlineData"]["data"])

    def stt(self, wav, model=STT_MODEL, prompt="Transcribe this audio exactly. Reply with the words only."):
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inlineData": {"mimeType": "audio/wav", "data": _b64e(wav)}},
                        {"text": prompt},
                    ],
                }
            ]
        }
        parts = self._parts(self._post(model, body))
        # The transcribe model answers in an audioTranscription part; chat models in text.
        said = " ".join(p["audioTranscription"].get("text", "") for p in parts if "audioTranscription" in p)
        return (said or "".join(p.get("text", "") for p in parts if not p.get("thought"))).strip()


def _retry_delay(msg):
    """Seconds to wait before retrying: a 429's retryDelay, a few for a
    503 ("high demand"), or None when a retry won't help."""
    if msg.startswith("HTTP 503") or msg.startswith("HTTP 500"):
        return 5.0
    if not msg.startswith("HTTP 429"):
        return None
    i = msg.find('"retryDelay": "')
    if i < 0:
        return 30.0
    j = msg.find("s", i + 15)
    try:
        return float(msg[i + 15 : j]) + 1
    except ValueError:
        return 30.0


def _sleep(s):
    import time

    time.sleep(s)


def wav_bytes(pcm, rate, channels=1, bits=16):
    import struct

    block = channels * bits // 8
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def _wav_pcm(wav):
    import struct

    rate = struct.unpack("<I", wav[24:28])[0]
    i = wav.find(b"data")
    return wav[i + 8 :], rate
