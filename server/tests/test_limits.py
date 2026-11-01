from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from sightline import app as app_module
from sightline.fixtures import build_clash_fixture
from sightline.limits import HOUR, ProposeLimit, client_id
from sightline.service import Workspace


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_per_visitor_limit_resets_after_an_hour():
    clock = Clock()
    limit = ProposeLimit(per_client_hour=2, clock=clock)
    assert limit.take("a") is None and limit.take("a") is None
    assert limit.take("a") is not None
    assert limit.take("b") is None  # another visitor is unaffected
    clock.t += HOUR + 1
    assert limit.take("a") is None


def test_daily_cap_covers_everyone_and_refusals_are_not_counted():
    limit = ProposeLimit(per_client_hour=1, per_day=2, clock=Clock())
    assert limit.take("a") is None
    assert limit.take("a") is not None  # refused by the hourly limit, not counted against the day
    assert limit.take("b") is None
    assert limit.take("c") is not None


def test_no_limits_by_default():
    limit = ProposeLimit()
    assert all(limit.take("a") is None for _ in range(100))


def test_propose_answers_429_when_limited(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "propose_limit", ProposeLimit(per_day=1))
    monkeypatch.setattr(app_module.ws, "propose", lambda *a, **k: {"understanding": "", "options": [], "attempts": []})
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["fixture-clash.ifc"]}).json()["id"]

    body = {"element_a": "a", "element_b": "b"}
    assert c.post(f"/api/scenes/{sid}/propose", json=body).status_code == 200
    r = c.post(f"/api/scenes/{sid}/propose", json=body)
    assert r.status_code == 429 and "today" in r.json()["detail"]


def test_workspace_keeps_only_the_most_recent_scenes(tmp_path):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    ws = Workspace(samples=tmp_path, max_scenes=2)
    first, second, third = (ws.open(["fixture-clash.ifc"]) for _ in range(3))
    assert list(ws.scenes) == [second, third]


def _xff(*lines: str) -> Headers:
    return Headers(raw=[(b"x-forwarded-for", line.encode()) for line in lines])


def test_a_visitor_is_the_peer_unless_proxies_are_trusted(monkeypatch):
    monkeypatch.delenv("SIGHTLINE_TRUST_FORWARDED", raising=False)
    assert client_id(_xff("1.2.3.4"), "203.0.113.9") == "203.0.113.9"   # Modal: the header is never trusted
    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "0")
    assert client_id(_xff("1.2.3.4"), "203.0.113.9") == "203.0.113.9"
    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "yes")   # not a number of proxies: none
    assert client_id(_xff("1.2.3.4"), "203.0.113.9") == "203.0.113.9"
    assert client_id(Headers(), None) == "unknown"


def test_behind_trusted_proxies_a_visitor_is_what_the_outermost_one_appended(monkeypatch):
    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "1")
    # The client wrote 1.2.3.4; the proxy appended the address it saw. The left end is the client's to choose.
    assert client_id(_xff("1.2.3.4, 198.51.100.7"), "10.0.0.1") == "198.51.100.7"
    assert client_id(_xff("9.9.9.9", "198.51.100.7"), "10.0.0.1") == "198.51.100.7"   # two header lines are one list
    assert client_id(_xff("198.51.100.7"), "10.0.0.1") == "198.51.100.7"
    assert client_id(Headers(), "10.0.0.1") == "10.0.0.1"   # no header: the proxy wrote nothing, the peer stands
    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "2")
    assert client_id(_xff("1.2.3.4, 198.51.100.7, 10.0.0.2"), "10.0.0.1") == "198.51.100.7"
    assert client_id(_xff("198.51.100.7"), "10.0.0.1") == "10.0.0.1"   # fewer entries than proxies: not theirs


def test_a_spoofed_forwarded_for_does_not_reset_a_visitors_caps(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "detect_limit", ProposeLimit(1, 0, noun="detection runs"))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["fixture-clash.ifc"]}).json()["id"]
    detect = lambda xff: c.post(f"/api/scenes/{sid}/detect/stream", json={}, headers={"x-forwarded-for": xff})

    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "1")   # a proxy that appends the visitor's address
    assert detect("1.1.1.1, 198.51.100.7").status_code == 200
    assert detect("2.2.2.2, 198.51.100.7").status_code == 429   # a new left end is the same visitor
    assert detect("198.51.100.8").status_code == 200            # another visitor is not

    monkeypatch.setenv("SIGHTLINE_TRUST_FORWARDED", "0")   # Modal: the peer, whatever the header says
    monkeypatch.setattr(app_module, "detect_limit", ProposeLimit(1, 0, noun="detection runs"))
    assert detect("3.3.3.3").status_code == 200
    assert detect("4.4.4.4").status_code == 429


def test_runs_after_hand_edits_have_their_own_cap_so_undo_and_keep_again_cannot_farm_them(tmp_path, monkeypatch):
    from sightline import manual
    from sightline.fixtures import build_edit_fixture
    build_edit_fixture(tmp_path / "edit.ifc")
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "detect_limit", ProposeLimit(1, 0, noun="detection runs"))
    monkeypatch.setattr(app_module, "edit_rerun_limit", ProposeLimit(1, 0, noun="runs after hand edits"))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["edit.ifc"]}).json()["id"]
    wall = next(e.GlobalId for e in ws.scene(sid).model.by_type("IfcWall") if e.Name == "W1")
    op = {"op": "push_pull", "element": wall, "face": "east end", "by_m": 1.2}
    manual.apply(ws, sid, op, accept_clashes=1)
    detect = lambda body: c.post(f"/api/scenes/{sid}/detect/stream", json=body)
    assert detect({"after_edit": "E1"}).status_code == 200
    ws.undo_edit(sid)
    manual.apply(ws, sid, op, accept_clashes=1)
    assert detect({"after_edit": "E2"}).status_code == 429      # farmed: its own cap is spent
    assert detect({}).status_code == 200                         # the detection cap is untouched
