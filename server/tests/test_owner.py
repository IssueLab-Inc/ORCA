import json

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import owner
from sightline.meta_client import MetaChatModel

TOKEN = "t" * 40


def _client(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_OWNER_TOKEN", TOKEN)
    return TestClient(app_module.app, base_url="https://testserver")  # the cookie is Secure


def test_unlock_sets_a_cookie_scripts_cannot_read(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/api/owner").json() == {"available": True, "owner": False}
    assert c.post("/api/owner/unlock", json={"token": "wrong"}).status_code == 403
    r = c.post("/api/owner/unlock", json={"token": TOKEN})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert TOKEN not in r.headers["set-cookie"]  # the token itself never goes back to the browser
    assert c.get("/api/owner").json()["owner"] is True
    c.post("/api/owner/lock")
    assert c.get("/api/owner").json()["owner"] is False


def test_a_new_token_logs_every_browser_out(monkeypatch):
    c = _client(monkeypatch)
    c.post("/api/owner/unlock", json={"token": TOKEN})
    monkeypatch.setenv("SIGHTLINE_OWNER_TOKEN", "u" * 40)
    assert c.get("/api/owner").json()["owner"] is False


def test_no_token_configured_means_no_owner(monkeypatch):
    monkeypatch.delenv("SIGHTLINE_OWNER_TOKEN", raising=False)
    c = TestClient(app_module.app, base_url="https://testserver")
    assert c.get("/api/owner").json() == {"available": False, "owner": False}
    assert c.post("/api/owner/unlock", json={"token": TOKEN}).status_code == 404


def test_wrong_tokens_are_capped(monkeypatch):
    monkeypatch.setattr(app_module, "unlock_limit", app_module.ProposeLimit(2, 0, noun="unlock attempts"))
    c = _client(monkeypatch)
    codes = [c.post("/api/owner/unlock", json={"token": "nope"}).status_code for _ in range(4)]
    assert codes[:2] == [403, 403] and codes[-1] == 429


def test_settings_count_only_for_the_owner():
    model = MetaChatModel("https://example/v1", "k", "m", reasoning_effort="low")
    header = json.dumps({"effort": "high", "triage_effort": "medium", "no_caps": True})
    tokens = owner.enter(False, header)  # a visitor sending the header gets nothing
    try:
        assert model.effort == "low" and not owner.no_caps()
    finally:
        owner.leave(tokens)
    tokens = owner.enter(True, header)
    try:
        assert model.effort == "high" and owner.no_caps()
        model.role = "triage"
        assert model.effort == "medium"
        seen = []
        owner.spawn(lambda: seen.append(owner.effort())).join()  # a stream's worker thread keeps the settings
        assert seen == ["high"]
    finally:
        owner.leave(tokens)
    assert owner.effort() is None


def test_unknown_settings_are_dropped():
    assert owner.settings('{"effort": "extreme", "triage_effort": "low", "no_caps": false}') == {"triage_effort": "low", "no_caps": False}
    assert owner.settings("not json") == {}


def test_the_owner_skips_the_demo_caps_and_visitors_do_not():
    from types import SimpleNamespace
    cap = app_module.ProposeLimit(1, 0)
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.7"))
    assert app_module._take(cap, request) is None
    assert app_module._take(cap, request)  # a visitor's second proposal this hour is refused
    tokens = owner.enter(False, '{"no_caps": true}')  # asking is not enough
    try:
        assert app_module._take(cap, request)
    finally:
        owner.leave(tokens)
    tokens = owner.enter(True, "{}")
    try:
        assert app_module._take(cap, request) is None
    finally:
        owner.leave(tokens)
    tokens = owner.enter(True, '{"no_caps": false}')  # the owner can switch the caps back on to try them
    try:
        assert app_module._take(cap, request)
    finally:
        owner.leave(tokens)
