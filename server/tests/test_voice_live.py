"""Live voice (voice_live.py): the relay between the browser's microphone and Muse Voice Transcribe's realtime socket,
against a fake Meta that answers like the real one did (Oct 28)."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from sightline import app as app_module
from sightline import voice_live
from sightline.limits import ProposeLimit
from sightline.service import Workspace

from test_reports import STANDARD

KEY = "meta-key-that-must-stay-on-the-server"
FRAME = b"\x01\x00" * 1280  # 80 ms of 16 kHz audio


class FakeMeta:
    """Meta's realtime socket: acks the handshake, answers audio with partials and the end with a final."""

    def __init__(self, mode_events=None, close_code=1000, close_reason="", ack=None):
        self.sent: list = []
        self.close_code, self.close_reason = close_code, close_reason
        self.ack = ack or {"sessionId": "s-1"}
        self.mode_events = mode_events

    async def __aenter__(self):
        self.out: asyncio.Queue = asyncio.Queue()
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, data):
        self.sent.append(data)
        if isinstance(data, bytes):
            heard = sum(isinstance(d, bytes) for d in self.sent)
            await self.out.put(json.dumps({"type": "transcript", "transcript": f" raise the duct {heard} ",
                                           "final": False, "audioProcessedMs": 80 * heard}))
        elif json.loads(data).get("type") == "endStream":
            for e in self.mode_events or [{"type": "transcript", "transcript": " Raise the duct. ", "final": True}]:
                await self.out.put(json.dumps(e))
            await self.out.put(None)

    async def recv(self):
        return json.dumps(self.ack)

    def __aiter__(self):
        return self

    async def __anext__(self):
        e = await self.out.get()
        if e is None:
            raise StopAsyncIteration
        return e


@pytest.fixture
def meta(monkeypatch):
    monkeypatch.setenv("META_API_KEY", KEY)
    box = {"fake": FakeMeta()}
    monkeypatch.setattr(voice_live, "connect", lambda *a, **k: box["fake"])
    monkeypatch.setattr(app_module, "voice_limit", ProposeLimit(per_client_hour=5))
    return box


def _events(sock):
    """Everything the server says until it closes the socket."""
    out = []
    try:
        while True:
            out.append(sock.receive_json())
    except WebSocketDisconnect:
        return out


def test_hold_to_talk_streams_partials_and_sends_the_final_on_release(tmp_path, monkeypatch, meta):
    (tmp_path / "report.xml").write_text(STANDARD)
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    report = ws.open_report_folder(tmp_path, "t")
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold", "report_id": report.id})
        assert sock.receive_json() == {"type": "ready", "max_s": 60}
        sock.send_bytes(FRAME)
        sock.send_bytes(FRAME)
        assert sock.receive_json() == {"type": "partial", "text": "raise the duct 1"}
        assert sock.receive_json() == {"type": "partial", "text": "raise the duct 2"}
        sock.send_json({"type": "end"})
        assert _events(sock) == [{"type": "final", "text": "Raise the duct."}]
    first = json.loads(meta["fake"].sent[0])
    assert first["authorization"] == {"accessToken": f"Bearer {KEY}"}
    assert first["audioEncoding"] == "PCM_16KHZ" and first["mode"] == "PUSH_TO_TALK" and first["model"]
    assert "transom" in first["keywords"] and "Supply duct 400x300" in first["keywords"]  # BIM words + the report's
    assert meta["fake"].sent[1:] == [FRAME, FRAME, json.dumps({"type": "endStream"})]


def test_hands_free_sends_each_sentence_when_the_speaker_pauses(meta):
    meta["fake"] = FakeMeta(mode_events=[
        {"type": "speechStart", "turnId": 0, "audioProcessedMs": 0},
        {"type": "speechEnd", "turnId": 0, "audioProcessedMs": 900},
        {"type": "speechComplete", "turnId": 0, "transcript": " Propose a fix. ", "audioProcessedMs": 900},
        {"type": "speaker", "label": "A", "audioProcessedMs": 900},
        {"type": "transcript", "transcript": "", "final": True, "audioProcessedMs": 960},  # the end: not a sentence
    ])
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hands_free"})
        assert sock.receive_json() == {"type": "ready", "max_s": app_module.VOICE_HANDS_FREE_MAX_S}
        sock.send_json({"type": "end"})
        assert _events(sock) == [{"type": "speech", "on": True}, {"type": "speech", "on": False},
                                 {"type": "final", "text": "Propose a fix.", "turn": 0}]
    assert json.loads(meta["fake"].sent[0])["mode"] == "ENDPOINTING"


def test_the_time_limit_ends_the_stream(monkeypatch, meta):
    monkeypatch.setattr(app_module, "VOICE_HOLD_MAX_S", 0.1)  # 3,200 bytes: the second frame reaches it
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        sock.receive_json()
        sock.send_bytes(FRAME)
        sock.send_bytes(FRAME)
        events = _events(sock)
    assert {"type": "limit"} in events and events[-1] == {"type": "final", "text": "Raise the duct."}
    assert meta["fake"].sent[-1] == json.dumps({"type": "endStream"})


def test_what_is_not_microphone_audio_is_refused(meta):
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        sock.receive_json()
        sock.send_bytes(b"\0" * 40_000)
        assert _events(sock) == [{"type": "error", "detail": "That isn't 16 kHz microphone audio."}]
    assert not any(isinstance(d, bytes) for d in meta["fake"].sent)


def test_meta_closing_badly_is_said_in_words_and_never_shows_the_key(meta):
    meta["fake"] = FakeMeta(mode_events=[{"type": "error", "message": "Backlog exceeded"}], close_code=1008)
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        sock.receive_json()
        sock.send_json({"type": "end"})
        events = _events(sock)
    assert events == [{"type": "error", "detail": "Backlog exceeded"},
                      {"type": "error", "detail": voice_live.CLOSED[1008]}]
    assert KEY not in json.dumps(events)


def test_meta_unreachable_or_refusing_the_session(monkeypatch, meta):
    def unreachable(*a, **k):
        raise OSError(f"cannot connect with {KEY}")
    monkeypatch.setattr(voice_live, "connect", unreachable)
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        events = _events(sock)
    assert events == [{"type": "error", "detail": "Couldn't reach Muse Voice Transcribe (OSError)."}]

    monkeypatch.setattr(voice_live, "connect", lambda *a, **k: FakeMeta(ack={"type": "error", "message": "bad model"}))
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        assert _events(sock) == [{"type": "error", "detail": "Muse Voice Transcribe refused the session: bad model"}]


def test_a_session_counts_once_against_the_voice_cap(monkeypatch, meta):
    monkeypatch.setattr(app_module, "voice_limit", ProposeLimit(per_client_hour=1, noun="voice messages"))
    c = TestClient(app_module.app)
    with c.websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hands_free"})
        assert sock.receive_json()["type"] == "ready"
        sock.send_json({"type": "end"})
        _events(sock)
    with c.websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        events = _events(sock)
    assert len(events) == 1 and events[0]["type"] == "error" and "voice messages" in events[0]["detail"]


def test_the_owner_has_no_voice_cap(monkeypatch, meta):
    monkeypatch.setenv("SIGHTLINE_OWNER_TOKEN", "t" * 40)
    monkeypatch.setattr(app_module, "voice_limit", ProposeLimit(per_client_hour=1))
    c = TestClient(app_module.app, base_url="https://testserver")
    assert c.post("/api/owner/unlock", json={"token": "t" * 40}).status_code == 200
    for _ in range(3):
        meta["fake"] = FakeMeta()
        with c.websocket_connect("wss://testserver/api/voice/live") as sock:  # the cookie is Secure
            sock.send_json({"mode": "hold"})
            assert sock.receive_json()["type"] == "ready"
            sock.send_json({"type": "end"})
            _events(sock)


def test_another_site_cannot_open_the_relay(meta):
    c = TestClient(app_module.app)
    with pytest.raises(WebSocketDisconnect) as refused:
        with c.websocket_connect("/api/voice/live", headers={"origin": "https://elsewhere.example"}):
            pass
    assert refused.value.code == 1008
    with c.websocket_connect("/api/voice/live", headers={"origin": "http://testserver"}) as sock:  # same origin
        sock.send_json({"mode": "hold"})
        assert sock.receive_json()["type"] == "ready"
        sock.send_json({"type": "end"})
        _events(sock)


def test_the_page_leaving_ends_the_session(meta):
    with TestClient(app_module.app).websocket_connect("/api/voice/live") as sock:
        sock.send_json({"mode": "hold"})
        sock.receive_json()
        sock.send_bytes(FRAME)
        sock.receive_json()
    assert meta["fake"].sent[-1] == FRAME  # nothing more was sent for a page that is gone
