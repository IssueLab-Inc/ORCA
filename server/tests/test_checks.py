"""Kept checks (docs/detection.md, "Kept checks"): each check's latest result kept per scene, one clash list of them
all, one id and #N per clash whichever check finds it, views and titles that outlive any one report."""
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sightline import checks, detect
from sightline.fixtures import build_detection_fixtures
from sightline.limits import ProposeLimit
from sightline.scene import IfcScene
from sightline.service import Workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def _filter(cls: str) -> dict:
    return {"when": [{"facet": "class", "op": "is", "values": [cls]}], "invert": False}


DUCTS = [{"a": {"filter": _filter("IfcDuctSegment")}, "b": {}}]
BEAMS = [{"a": {"filter": _filter("IfcBeam")}, "b": {}}]
# Pipes at no tolerance: pipe P2 runs 0.5 mm into the beam, a touch for the full check (1 mm), a clash for this one.
PIPES = [{"a": {"filter": _filter("IfcPipeSegment")}, "b": {}, "tolerance_m": 0.0001}]
# Pipes closer than 300 mm to anything: P1 on the beam and P2 in it only touch, P3 20 mm under it is a clash to read.
NEAR_PIPES = [{"a": {"filter": _filter("IfcPipeSegment")}, "b": {}, "kind": "clearance", "clearance_m": 0.3}]


@pytest.fixture(scope="module")
def paths(tmp_path_factory) -> list[Path]:
    return build_detection_fixtures(tmp_path_factory.mktemp("checks"))


@pytest.fixture()
def opened(paths, tmp_path):
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    return ws, ws.open([p.name for p in paths])


def by_pair(out, *names) -> dict:
    return next(c for c in out["report"]["clashes"] if {c["a"]["name"], c["b"]["name"]} == set(names))


def test_a_pair_keeps_its_id_and_number_whatever_check_finds_it_next(opened):
    """Full check, then ducts, then beams: the strut and the beam were numbered by the full check, and the beams check
    finds them again after a check that did not (it used to give them a new id and number)."""
    ws, sid = opened
    full = ws.detect(sid)
    strut = by_pair(full, "Strut S1", "Beam B1")
    ducts = ws.detect(sid, DUCTS)
    assert all(c["number"] <= len(full["report"]["clashes"]) for c in ducts["report"]["clashes"])
    beams = ws.detect(sid, BEAMS)
    assert (by_pair(beams, "Strut S1", "Beam B1")["id"], by_pair(beams, "Strut S1", "Beam B1")["number"]) == \
        (strut["id"], strut["number"])
    assert beams["diff"]["new"] == [], "nothing the list did not already hold"
    numbers = [c["number"] for c in beams["report"]["clashes"]]
    assert len(numbers) == len(set(numbers)) == len(full["report"]["clashes"])
    assert [c["key"] for c in beams["checks"]] == ["models", ducts["check"], beams["check"]]
    # Numbers no longer start again under other requirements: the pair is the same clash.
    from sightline import requirements as req
    rid = req.register(req.default_doc(ws.scene(sid)))
    with req.using(rid):
        under = ws.detect(sid)
    assert by_pair(under, "Strut S1", "Beam B1")["number"] == strut["number"]
    assert under["diff"]["first"], "its first run under these requirements"


@pytest.mark.parametrize("order", [("x", "y"), ("y", "x")])
def test_two_tests_finding_one_pair_stay_two_clashes_in_either_order(paths, order):
    scene = IfcScene(paths)
    tests = {"x": detect.Test(id="x", name="Columns (within)", a=detect.Selection(classes=["IfcColumn"])),
             "y": detect.Test(id="y", name="Structure (within)", a=detect.Selection(files=["Fixture-Structure.ifc"]))}
    first = detect.run(scene, [tests["y"]])
    column = next(c for c in first.report.clashes if "Column" in c.a.name)
    again = detect.run(scene, [tests[k] for k in order], previous=first.state)
    ids = [c.id for c in again.report.clashes]
    assert len(ids) == len(set(ids)), "no id twice in one report"
    kept = next(c for c in again.report.clashes if c.test == "Structure (within)" and "Column" in c.a.name)
    assert (kept.id, kept.number) == (column.id, column.number)


def test_two_runs_at_once_on_one_scene_lose_nothing(opened):
    ws, sid = opened
    errors = []

    def run(tests):
        try:
            ws.detect(sid, tests)
        except Exception as e:  # pragma: no cover - shown by the assertion
            errors.append(e)

    threads = [threading.Thread(target=run, args=(t,)) for t in (None, DUCTS, BEAMS)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    register = ws.checks[sid]
    assert set(register.checks) == {"models", *(detect.Test.from_dict(t[0]).id for t in (DUCTS, BEAMS))}
    numbers = list(register.numbers.values())
    assert len(numbers) == len(set(numbers))
    report = ws.union_report(sid)
    assert len({c.number for c in report.clashes}) == len(report.clashes)


def test_views_and_titles_outlive_any_one_report(paths, tmp_path):
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path, max_reports=1)
    sid = ws.open([p.name for p in paths])
    out = ws.detect(sid)
    duct = by_pair(out, "Duct D1", "Beam B1")
    assert ws.save_capture(out["report"]["id"], duct["id"], "A", PNG) == ["A"]
    ws.checks[sid].keep_titles({duct["id"]: "The duct runs through the beam"})
    # A second scene's list takes the only report place: the first is let go, and made again when asked for.
    other = ws.open([p.name for p in paths])
    ws.detect(other)
    assert out["report"]["id"] not in ws.reports
    again = ws.union_report(sid)
    assert again is not None and again.id != out["report"]["id"]
    row = again.clash(duct["id"])
    assert row.title == "The duct runs through the beam" and [label for label, _ in row.images] == ["A"]
    assert ws.report_image(again.id, duct["id"], 0).read_bytes() == PNG
    # Running a check again keeps them too, and the scene's folder goes with the scene.
    rerun = ws.detect(sid, check="models")
    assert by_pair(rerun, "Duct D1", "Beam B1")["images"] == ["A"]
    root = ws.checks[sid].root
    ws.max_scenes = 1
    ws._evict(0, other)
    assert sid not in ws.checks and not root.exists()


def test_each_check_is_kept_once_replaced_only_by_itself_and_removed_on_its_own(opened, monkeypatch):
    ws, sid = opened
    full = ws.detect(sid)
    pipes = ws.detect(sid, PIPES)
    key = pipes["check"]
    p2 = by_pair(pipes, "Pipe P2 half a millimetre in", "Beam B1")
    assert p2["checks"] == {key: pipes["checks"][1]["name"]} and p2["number"] == len(full["report"]["clashes"]) + 1
    assert pipes["diff"]["new"] == [p2["id"]] and p2["status"] == "new"
    # The full check again does not drop the pipes check's clash, nor call it anything.
    back = ws.detect(sid)
    assert by_pair(back, "Pipe P2 half a millimetre in", "Beam B1")["id"] == p2["id"] and back["diff"]["new"] == []
    with pytest.raises(ValueError):
        ws.remove_check(sid, "models")
    with pytest.raises(KeyError):
        ws.remove_check(sid, "filter:nothing")
    gone = ws.remove_check(sid, key)
    assert [c["key"] for c in gone["checks"]] == ["models"]
    assert all(c["id"] != p2["id"] for c in gone["report"]["clashes"])
    # Its number stays its own: the check run again finds it under the same id and #N.
    again = ws.detect(sid, PIPES)
    assert (by_pair(again, "Pipe P2 half a millimetre in", "Beam B1")["id"], by_pair(again, "Pipe P2 half a millimetre in", "Beam B1")["number"]) == \
        (p2["id"], p2["number"])
    # At most MAX_CHECKS: the oldest check on filters goes first, never the open models.
    monkeypatch.setattr(checks, "MAX_CHECKS", 2)
    ws.detect(sid, DUCTS)
    assert [c.key for c in ws.checks[sid].checks.values()] == ["models", detect.Test.from_dict(DUCTS[0]).id]


def test_a_kept_fix_leaves_the_checks_that_ran_before_it_stale(opened):
    ws, sid = opened
    ws.detect(sid)
    ducts = ws.detect(sid, DUCTS)
    assert not any(c["stale"] for c in ducts["checks"])
    ws.scene(sid).bump([0])
    info = ws.checks_info(sid)
    assert [c["stale"] for c in info["checks"]] == [True, True]
    assert all(c["stale"] for c in ws.report_summary(info["report_id"])["checks"])
    again = ws.detect(sid, check=ducts["check"])
    assert [c["stale"] for c in again["checks"]] == [True, False]


def test_contacts_come_from_every_kept_check(opened):
    ws, sid = opened
    ws.detect(sid, PIPES)    # pipe P1 rests on the beam: a contact this check sees
    contacts = {tuple(p) for p in ws._contacts(sid)}
    ws.detect(sid)
    assert contacts <= {tuple(p) for p in ws._contacts(sid)}


def test_the_routes_list_remove_and_run_every_check_again(paths, tmp_path, monkeypatch):
    from sightline import app as app_module

    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    limit = ProposeLimit(3, 0, noun="detection runs")
    monkeypatch.setattr(app_module, "detect_limit", limit)
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": [p.name for p in paths]}).json()["id"]
    assert c.get(f"/api/scenes/{sid}/checks").json() == {"report_id": None, "checks": []}

    def done(body):
        r = c.post(f"/api/scenes/{sid}/detect/stream", json=body)
        assert r.status_code == 200, r.text
        events = [json.loads(line) for line in r.text.splitlines()]
        assert events[-1]["type"] == "done", events[-1]
        return events

    done({})
    key = done({"tests": PIPES})[-1]["check"]
    events = done({"all": True})
    assert [e["key"] for e in events if e["type"] == "check"] == ["models", key]
    final = events[-1]
    assert final["check"] is None and final["ran"] == ["models", key] and len(final["checks"]) == 2
    assert len(limit._all) == 3, "Run all again is one detection run"
    assert c.post(f"/api/scenes/{sid}/detect/stream", json={"check": "filter:none"}).status_code == 404

    info = c.get(f"/api/scenes/{sid}").json()
    assert info["report_id"] == final["report"]["id"] and [k["key"] for k in info["checks"]] == ["models", key]
    report = c.get(f"/api/reports/{info['report_id']}").json()
    assert report["scene_id"] == sid and report["serial"] >= 3 and len(report["checks"]) == 2
    assert c.delete(f"/api/scenes/{sid}/checks/models").status_code == 409
    assert c.delete(f"/api/scenes/{sid}/checks/filter:none").status_code == 404
    left = c.delete(f"/api/scenes/{sid}/checks/{key}").json()
    assert [k["key"] for k in left["checks"]] == ["models"] and left["report"]["serial"] > report["serial"]
    # A list the server let go is made again from the checks, without a detection run.
    app_module.ws.reports.pop(left["report"]["id"])
    rebuilt = c.get(f"/api/scenes/{sid}/checks").json()
    assert rebuilt["report_id"] not in (None, left["report"]["id"]) and len(limit._all) == 3


def test_key_of_tells_a_check_on_filters_from_the_open_models():
    ducts = detect.Test.from_dict(DUCTS[0])
    assert checks.key_of([ducts]) == ducts.id and ducts.id.startswith("filter:")
    assert checks.key_of(None) == checks.key_of([]) == "models"
    pair = detect.Test(id="pair:a|b", name="A vs B", a=detect.Selection(files=["a"]), b=detect.Selection(files=["b"]))
    assert checks.key_of([pair]) == "models" and checks.key_of([pair, ducts]) == "models"


class Reader:
    """A triage model that calls everything a real clash and records what it was asked."""

    def __init__(self):
        self.asked: list[str] = []
        self.lock = threading.Lock()

    def complete_json(self, system, text, images=None, schema=None):
        with self.lock:
            self.asked.append(text)
        return {"understanding": "Real overlap.", "verdict": "real_clash", "severity": "high", "responsible": "MEP",
                "action": "move_A", "fix_hint": "Move it.", "confidence": 0.9}


def test_triage_verdicts_follow_their_clash_from_check_to_check(paths, tmp_path, monkeypatch):
    from sightline import app as app_module
    from sightline import requirements as req

    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    model = Reader()
    monkeypatch.setattr(app_module, "triage_model", lambda: (model, {"model": "scripted", "open_weights": False}))
    proposals = ProposeLimit(20, 0)
    monkeypatch.setattr(app_module, "propose_limit", proposals)
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": [p.name for p in paths]}).json()["id"]

    def triage(rid, **params):
        r = c.post(f"/api/reports/{rid}/triage/stream", params={"scene_id": sid, **params})
        assert r.status_code == 200, r.text
        return [json.loads(line) for line in r.text.splitlines()]

    def settled(rid):
        job = app_module._triage_jobs[f"scene:{sid}"]
        while not job.done:
            threading.Event().wait(0.02)
        return c.get(f"/api/reports/{rid}/triage", params={"scene_id": sid}).json()

    full = ws.detect(sid)
    rid = full["report"]["id"]
    assert c.get(f"/api/reports/{rid}/triage", params={"scene_id": sid}).json()["unread"] == 6
    triage(rid)
    asked, charged = len(model.asked), len(proposals._all)
    assert charged == 1 and 0 < asked <= 6
    assert len(settled(rid)["results"]) == 6

    # A new check: what was read follows its clashes, free; only the new clash the rules leave is unread (pipe P3,
    # 20 mm under the beam; the pipes on and 0.5 mm into it only touch).
    pipes = ws.detect(sid, NEAR_PIPES)
    rid = pipes["report"]["id"]
    state = settled(rid)
    p3 = by_pair(pipes, "Pipe P3 under beam", "Beam B1")["id"]
    assert len(state["results"]) == 8 and p3 not in state["results"] and state["unread"] == 1
    assert sum(1 for v in state["results"].values() if v.get("carried")) == 6
    assert len(proposals._all) == charged and len(model.asked) == asked, "carrying readings is free"
    # Triage in the check on screen asks about its unread clash only, for one proposal.
    start = triage(rid, scope=pipes["check"])[0]
    assert start["asking"] == 1 and start["scope"] == pipes["check"]
    assert len(model.asked) == asked + 1 and len(proposals._all) == charged + 1
    assert settled(rid)["unread"] == 0
    # Nothing unread: triage again costs nothing and asks nothing.
    triage(rid)
    assert len(model.asked) == asked + 1 and len(proposals._all) == charged + 1

    # A clash whose depth changed is read again: the reading no longer holds.
    duct = by_pair(full, "Duct D1", "Beam B1")
    gid = duct["a"]["global_id"] if duct["a"]["name"] == "Duct D1" else duct["b"]["global_id"]
    ws.scene(sid).translate([gid], (0.0, 0.0, 0.05))
    moved = ws.detect(sid)
    now = by_pair(moved, "Duct D1", "Beam B1")
    assert abs(now["distance_m"] - duct["distance_m"]) > checks.SAME_DEPTH_M
    state = settled(moved["report"]["id"])
    assert duct["id"] not in state["results"] and state["unread"] >= 1

    # Under requirements with another triage prompt nothing carries: the last run shows, marked stale.
    rid_req = req.register(req.default_doc(ws.scene(sid)))
    with req.using(rid_req):
        stale = ws.detect(sid)
        state = c.get(f"/api/reports/{stale['report']['id']}/triage", params={"scene_id": sid},
                      headers={"X-Sightline-Requirements": rid_req}).json()
    assert state.get("stale") is True


def test_a_triage_seed_keeps_only_the_reports_own_clashes():
    from sightline import reports, triage

    e = reports.ReportElement("g1", "IfcBeam", "Beam", None, None)
    f = reports.ReportElement("g2", "IfcDuctSegment", "Duct", None, None)
    clash = reports.ReportClash("s1", "Duct × Beam", None, "t", "hard", 0.001, "new", -0.1, None, None, f, e)
    report = reports.Report("r", "t", Path("."), [], [clash], origin="sightline")
    seed = {"s1": {"verdict": "real_clash", "source": "model", "alike": 3, "alike_of": "s9"},
            "s9": {"verdict": "real_clash", "source": "model"}, "s2": {"verdict": "by_design", "source": "rule"}}
    job = triage.Job(report, Reader(), {}, seed=seed)
    assert job.seed == {"s1": {"verdict": "real_clash", "source": "model"}}


def test_a_document_can_hold_one_checks_clashes(opened, monkeypatch):
    from sightline import app as app_module

    ws, sid = opened
    monkeypatch.setattr(app_module, "ws", ws)
    ws.detect(sid)
    pipes = ws.detect(sid, PIPES)
    report = ws.report(pipes["report"]["id"])
    narrowed = app_module._narrowed(report, pipes["check"])
    assert narrowed.title == "Coordination · PipeSegment vs Everything"
    assert [c.id for c in narrowed.clashes] == [by_pair(pipes, "Pipe P2 half a millimetre in", "Beam B1")["id"]]
    assert app_module._narrowed(report, None) is report
    with pytest.raises(KeyError):
        app_module._narrowed(report, "filter:none")
    c = TestClient(app_module.app)
    r = c.post(f"/api/reports/{report.id}/document/stream", json={"scene_id": sid, "check": "filter:none"})
    assert r.status_code == 404
