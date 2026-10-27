from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline.fixtures import build_clash_fixture
from sightline.limits import HOUR, ProposeLimit
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
