"""Live voice: the browser's microphone to Muse Voice Transcribe's realtime socket and its words back, as they are said.

Meta reads the API key from the first frame of the stream, so the browser cannot connect itself: this relay adds the
key and the vocabulary, keeps the audio at real time, and passes the words back in ORCA's own small protocol.

Browser → ORCA: one JSON frame `{mode: "hold" | "hands_free", report_id}`, then binary frames of 16 kHz mono 16-bit
little-endian PCM, then `{"type": "end"}` (hold: the user let go).
ORCA → browser: `ready {max_s}`, `partial {text}` (everything heard so far in this turn), `final {text, turn}` (hold:
once, at the end; hands-free: each sentence when the speaker pauses), `speech {on}`, `limit` (the time ran out),
`error {detail}`. The socket then closes.

    META_VOICE_MODEL         muse-voice-transcribe-1.0
    META_VOICE_REALTIME_URL  wss://api.meta.ai/v1/asr/realtime (else from META_API_BASE_URL's host)
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from urllib.parse import urlsplit

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState
from websockets.asyncio.client import connect  # module level so tests can swap in a fake Meta

from .meta_client import load_env

RATE_BYTES = 32_000  # 16 kHz x 16-bit mono
MAX_FRAME = 32_768  # the browser sends 80 ms (2,560 bytes); anything this size is not a microphone
# How far the audio sent may run ahead of the clock. The browser records while the socket connects (~1 s) and sends that
# at once; measured Oct 29, Meta takes a 3 s burst cleanly and garbles a 5 s one ("through the millimeters through").
AHEAD_S = 1.5
END_WAIT_S = 15  # after the end, how long to wait for the last words
MODES = {"hold": "PUSH_TO_TALK", "hands_free": "ENDPOINTING"}
CLOSED = {  # Meta's close codes, in words people can act on
    1008: "Muse Voice Transcribe refused the stream. Try again.",
    1011: "Muse Voice Transcribe had a problem. Try again.",
    1013: "Muse Voice Transcribe is busy. Wait a moment and try again.",
}


def url() -> str:
    load_env()
    if os.environ.get("META_VOICE_REALTIME_URL"):
        return os.environ["META_VOICE_REALTIME_URL"]
    host = urlsplit(os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1")).netloc or "api.meta.ai"
    return f"wss://{host}/v1/asr/realtime"


def handshake(mode: str, keywords: list[str]) -> dict:
    """The first frame Meta expects, with the key: never logged, never sent to the browser."""
    load_env()
    return {"authorization": {"accessToken": f"Bearer {os.environ['META_API_KEY']}"},
            "audioEncoding": "PCM_16KHZ", "model": os.environ.get("META_VOICE_MODEL", "muse-voice-transcribe-1.0"),
            "mode": mode, "partialMode": "CUMULATIVE", "emitAudioProgress": False,
            "languageBias": ["English"], **({"keywords": keywords} if keywords else {})}


def same_origin(headers) -> bool:
    """A browser on another site may not open the relay (it would spend our Meta budget). Non-browser clients send no
    Origin; they are held to the same caps as everyone."""
    origin = headers.get("origin")
    return not origin or urlsplit(origin).netloc.lower() == (headers.get("host") or "").lower()


async def relay(client: WebSocket, mode: str, keywords: list[str], max_s: float) -> None:
    """Run one voice session on an accepted browser socket until either side ends it, then close the browser side."""
    try:
        async with connect(url(), open_timeout=10, compression=None, max_size=2 ** 20) as meta:
            await meta.send(json.dumps(handshake(mode, keywords)))
            ack = json.loads(await asyncio.wait_for(meta.recv(), 10))
            if "sessionId" not in ack:
                raise _Refused(str(ack.get("message") or "no session"))
            await client.send_json({"type": "ready", "max_s": max_s})
            await _pump(client, meta, mode, max_s)
    except _Refused as e:
        await _say(client, {"type": "error", "detail": f"Muse Voice Transcribe refused the session: {e}"[:300]})
    except Exception as e:  # the network, the key, Meta: say what kind, never the details (they could carry the frame)
        await _say(client, {"type": "error", "detail": f"Couldn't reach Muse Voice Transcribe ({type(e).__name__})."})
    await _close(client)


class _Refused(Exception):
    pass


async def _pump(client: WebSocket, meta, mode: str, max_s: float) -> None:
    up = asyncio.create_task(_to_meta(client, meta, max_s))
    down = asyncio.create_task(_to_browser(client, meta, mode))
    try:
        done, _ = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
        if up in done and up.result() == "gone":  # the page went away: nothing left to say to it
            return
        if up in done:  # the user let go or the time ran out: wait for the last words
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(down), END_WAIT_S)
    finally:
        for t in (up, down):
            t.cancel()
        await asyncio.gather(up, down, return_exceptions=True)


async def _to_meta(client: WebSocket, meta, max_s: float) -> str:
    """Browser audio to Meta at real time. Returns "ended" (end sent to Meta) or "gone" (the browser left)."""
    sent, start, deadline = 0, None, time.monotonic() + max_s + 5
    while True:
        try:
            msg = await asyncio.wait_for(client.receive(), max(0.1, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            msg = {"type": "websocket.receive", "text": '{"type": "limit"}'}
        if msg["type"] == "websocket.disconnect":
            return "gone"
        data, text = msg.get("bytes"), msg.get("text")
        if data:
            if len(data) > MAX_FRAME or len(data) % 2:
                await _say(client, {"type": "error", "detail": "That isn't 16 kHz microphone audio."})
                return "gone"
            start = start or time.monotonic()
            ahead = (sent + len(data)) / RATE_BYTES - (time.monotonic() - start)
            if ahead > AHEAD_S:
                await asyncio.sleep(ahead - AHEAD_S)
            await meta.send(data)
            sent += len(data)
            if sent < max_s * RATE_BYTES:
                continue
            text = '{"type": "limit"}'
        try:
            kind = json.loads(text or "{}").get("type")
        except (json.JSONDecodeError, AttributeError):
            kind = None
        if kind in ("end", "limit"):
            if kind == "limit":
                await _say(client, {"type": "limit"})
            await meta.send(json.dumps({"type": "endStream"}))
            return "ended"


async def _to_browser(client: WebSocket, meta, mode: str) -> None:
    """Meta's events to the browser, in ORCA's protocol. Returns when Meta closes the stream."""
    hands_free = mode == "ENDPOINTING"
    try:
        async for raw in meta:
            if isinstance(raw, bytes):
                continue
            e = json.loads(raw)
            kind, text = e.get("type"), (e.get("transcript") or "").strip()
            if kind == "transcript" and not (hands_free and e.get("final")):
                await _say(client, {"type": "final" if e.get("final") else "partial", "text": text})
            elif kind == "speechComplete" and hands_free:
                await _say(client, {"type": "final", "text": text, "turn": e.get("turnId")})
            elif kind in ("speechStart", "speechEnd"):
                await _say(client, {"type": "speech", "on": kind == "speechStart"})
            elif kind == "error":
                await _say(client, {"type": "error", "detail": str(e.get("message") or "Transcription failed.")[:300]})
    except Exception:  # an abnormal close: the code below says which
        pass
    code, reason = getattr(meta, "close_code", None), getattr(meta, "close_reason", "") or ""
    if code not in (None, 1000):
        detail = ("That was the longest a voice session can run." if "duration" in reason.lower()
                  else CLOSED.get(code, f"Muse Voice Transcribe closed the stream ({code})."))
        await _say(client, {"type": "error", "detail": detail})


async def _say(client: WebSocket, event: dict) -> None:
    with contextlib.suppress(Exception):
        if client.application_state == WebSocketState.CONNECTED and client.client_state == WebSocketState.CONNECTED:
            await client.send_json(event)


async def _close(client: WebSocket) -> None:
    with contextlib.suppress(Exception, WebSocketDisconnect):
        if client.application_state == WebSocketState.CONNECTED:
            await client.close(1000)
