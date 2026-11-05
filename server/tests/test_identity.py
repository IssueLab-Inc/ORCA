"""Who is asking (identity.py): the same visitor `limits.client_id` names, set once per request by the middleware and
carried into the work a request starts (owner.spawn, owner.submit)."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from starlette.requests import Request

from sightline import app as app_module
from sightline import identity, owner
from sightline.identity import Identity
from sightline.limits import client_id


def _request(client=("203.0.113.9", 5000), xff: list[str] | None = None) -> Request:
    headers = [(b"x-forwarded-for", v.encode()) for v in (xff or [])]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": client,
                    "query_string": b""})


def _old(request: Request) -> str:
    """What app.py asked before identity.py, at each of its nine call sites."""
    return client_id(request.headers, request.client.host if request.client else None)


def test_who_names_the_visitor_client_id_named(monkeypatch):
    cases = [_request(), _request(xff=["1.2.3.4"]), _request(client=None), _request(client=None, xff=["1.2.3.4"]),
             _request(xff=["1.1.1.1, 198.51.100.7"]), _request(xff=["9.9.9.9", "198.51.100.7"]),
             _request(xff=["1.2.3.4, 198.51.100.7, 10.0.0.2"])]
    for hops in (None, "0", "1", "2", "yes", ""):
        if hops is None:
            monkeypatch.delenv("SIGHTLINE_TRUST_FORWARDED", raising=False)
        else:
            monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", hops)
        for r in cases:
            assert identity.who(r) == _old(r)
            assert identity.of_scope(r.scope) == identity.of(r) == Identity(_old(r))
    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "1")
    assert identity.who(_request(xff=["1.1.1.1, 198.51.100.7"])) == "198.51.100.7"
    assert identity.who(_request(client=None)) == "unknown"


def test_without_a_request_nobody_is_asking():
    assert identity.current() is None
    assert identity.who() is None


def test_the_identity_in_force_wins_and_a_person_is_their_user_id():
    token = identity.enter(Identity("198.51.100.7"))
    try:
        assert identity.who() == "198.51.100.7"
        assert identity.who(_request(client=("10.0.0.1", 1))) == "198.51.100.7"   # the request's, set by the middleware
    finally:
        identity.leave(token)
    token = identity.enter(Identity("198.51.100.7", user_id="42"))
    try:
        assert identity.who() == "u:42"
    finally:
        identity.leave(token)
    assert identity.current() is None


def _recording_app(seen: dict):
    """An ASGI app behind the real middleware: it notes who is asking in the request, in a thread started with
    owner.spawn, and in a pool through owner.submit, as streams and model calls are run."""
    pool = ThreadPoolExecutor(1)

    async def inner(scope, receive, send):
        seen["request"] = identity.current()
        done = threading.Event()

        def work():
            seen["spawn"] = identity.current()
            done.set()
        owner.spawn(work)
        done.wait(5)
        seen["submit"] = owner.submit(pool, identity.current).result(5)
        seen["outside"] = pool.submit(identity.current).result(5)   # a plain submit does not carry it
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})
            return
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"ok"})
    return app_module._OwnerContext(inner)


def test_the_middleware_sets_the_identity_and_workers_keep_it(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "1")
    seen: dict = {}
    c = TestClient(_recording_app(seen))
    assert c.get("/api/anything", headers={"x-forwarded-for": "1.1.1.1, 198.51.100.7"}).status_code == 200
    want = Identity("198.51.100.7")
    assert seen["request"] == seen["spawn"] == seen["submit"] == want
    assert seen["outside"] is None


def test_the_middleware_sets_the_identity_on_a_websocket():
    seen: dict = {}
    c = TestClient(_recording_app(seen))
    with c.websocket_connect("/api/voice/live"):
        pass
    assert seen["request"] == seen["spawn"] == seen["submit"] == Identity("testclient")


def _after(mw, headers: list[tuple[bytes, bytes]]) -> tuple[Identity | None, list[dict]]:
    """Run one request through the middleware in this task, and say who is asking once it has returned."""
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    async def go():
        await mw({"type": "http", "method": "GET", "path": "/api/anything", "headers": headers,
                  "client": ("203.0.113.9", 5000), "query_string": b""}, receive, send)
        return identity.current()
    return asyncio.run(go()), sent


def test_the_identity_is_left_when_the_request_ends_even_when_refused():
    seen: dict = {}
    mw = _recording_app(seen)
    after, sent = _after(mw, [])
    assert seen["request"] == Identity("203.0.113.9") and after is None
    seen.clear()
    after, sent = _after(mw, [(b"x-sightline-requirements", b"0" * 16)])   # unknown: 409 before the route
    assert sent[0]["status"] == 409 and "request" not in seen and after is None


def test_caps_count_the_same_visitor_through_the_app(tmp_path, monkeypatch):
    """A route that takes a cap counts it under the visitor who asked (app._take → identity.who)."""
    from sightline.limits import ProposeLimit
    monkeypatch.delenv("SIGHTLINE_TRUST_FORWARDED", raising=False)
    limit = ProposeLimit(1, 0, noun="agent links")
    monkeypatch.setattr(app_module, "link_limit", limit)
    c = TestClient(app_module.app)
    assert c.post("/api/links", json={}).status_code == 200
    assert c.post("/api/links", json={}).status_code == 429
    assert set(limit._clients) == {"testclient"}
