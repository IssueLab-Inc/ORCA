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
    ducts = ws.detect(sid, DUCTS)
    both = ws.report(ducts["report"]["id"])
    beam = next(c for c in both.clashes if {c.a.name, c.b.name} == {"Duct D1", "Beam B1"})
    assert beam.test == "MEP vs Structure", "the list's test: the open models' first"
    assert app_module._narrowed(both, ducts["check"]).clash(beam.id).test == "DuctSegment vs Everything", \
        "a one-check document says that check's test"
    assert [c.id for c in narrowed.clashes] == [by_pair(pipes, "Pipe P2 half a millimetre in", "Beam B1")["id"]]
    assert app_module._narrowed(report, None) is report
    with pytest.raises(KeyError):
        app_module._narrowed(report, "filter:none")
    c = TestClient(app_module.app)
    r = c.post(f"/api/reports/{report.id}/document/stream", json={"scene_id": sid, "check": "filter:none"})
    assert r.status_code == 404


# ---------------------------------------------------------------- the review of the change (PR #87)

class Gated(Reader):
    """A triage model that waits at a gate (a run kept under way), answers the rules' audit, and can fail."""

    def __init__(self, fail=False):
        super().__init__()
        self.gate, self.fail, self.audits = threading.Event(), fail, 0
        self.gate.set()

    def complete_json(self, system, text, images=None, schema=None):
        self.gate.wait(10)
        if schema and "answer" in schema.get("properties", {}):
            with self.lock:
                self.audits += 1
            return {"answer": "consistent", "note": "As the rule says."}
        if self.fail:
            raise RuntimeError("rate limited")
        return super().complete_json(system, text, images, schema)


def _done(job, wait=20.0):
    for _ in range(int(wait / 0.02)):
        if job.done:
            return job
        threading.Event().wait(0.02)
    raise AssertionError("the triage run did not end")


@pytest.fixture()
def served(opened, monkeypatch):
    from sightline import app as app_module

    ws, sid = opened
    monkeypatch.setattr(app_module, "ws", ws)
    model = Gated()
    monkeypatch.setattr(app_module, "triage_model", lambda: (model, {"model": "scripted", "open_weights": False}))
    return app_module, ws, sid, model


def test_a_failed_read_is_not_kept_and_stays_unread(served):
    app_module, ws, sid, model = served
    model.fail = True
    report = ws.union_report(sid) if ws.checks.get(sid) else ws.report(ws.detect(sid)["report"]["id"])
    charged = []
    _done(app_module._start_triage(report, sid, lambda: charged.append(1)))
    assert charged == [1] and not ws.checks[sid].readings.get("", {}), "a failed read is no reading"
    again = ws.report(ws.detect(sid, DUCTS)["report"]["id"])
    assert ws.checks[sid].carried(again, "") == {}
    state = app_module.triage_state(again.id, sid)
    assert state["unread"] == 6, "Triage N unread counts them, to be asked again"


def test_a_run_that_asks_nothing_makes_no_audit_call(served):
    from sightline import requirements as req

    app_module, ws, sid, model = served
    doc = req.default_doc(ws.scene(sid))
    doc.by_design = [req.ByDesign(["IfcDuctSegment"], ["IfcSensor"], "sensors in ducts")]
    rid = req.register(doc)
    first = ws.report(ws.detect(sid)["report"]["id"])
    with req.using(rid):
        job = _done(app_module._start_triage(first, sid, lambda: None))
    assert model.audits == 1 and job.audit, "a run that asks the model checks the rules"
    asked = len(model.asked)
    second = ws.report(ws.detect(sid, DUCTS)["report"]["id"])
    with req.using(rid):
        app_module.triage_state(second.id, sid)
        carry = _done(app_module._triage_jobs[app_module._triage_key(second, req.current())])
    assert carry.report is second and carry.only == set()
    assert model.audits == 1 and len(model.asked) == asked, "carrying readings over asks nothing, the audit neither"
    assert carry.audit == job.audit, "it keeps the last audit"


def test_a_new_list_follows_the_titling_under_way(served, monkeypatch):
    from tests.test_titles import Titler

    app_module, ws, sid, _ = served
    gate = threading.Event()

    class Slow(Titler):
        def complete_json(self, *a, **k):
            gate.wait(10)
            return super().complete_json(*a, **k)

    titler = Slow()
    monkeypatch.setattr(app_module, "triage_model", lambda: (titler, {"model": "scripted", "open_weights": True}))
    c = TestClient(app_module.app)
    first = ws.detect(sid)["report"]["id"]
    events = []
    reader = threading.Thread(target=lambda: events.append(c.post(f"/api/reports/{first}/titles/stream").text))
    reader.start()
    for _ in range(200):
        if app_module._title_jobs.get(f"scene:{sid}") is not None:
            break
        threading.Event().wait(0.02)
    job = app_module._title_jobs[f"scene:{sid}"]
    second = ws.detect(sid, NEAR_PIPES)["report"]["id"]
    follow = threading.Thread(target=lambda: events.append(c.post(f"/api/reports/{second}/titles/stream").text))
    follow.start()
    threading.Event().wait(0.2)
    assert app_module._title_jobs[f"scene:{sid}"] is job, "the new list follows the run under way"
    gate.set()
    reader.join(10); follow.join(10)
    start = json.loads(events[-1].splitlines()[0])
    assert start["report_id"] == first, "its start names the list it titles"
    titled = {n for b in titler.batches for n in b}
    assert titled == {c.number for c in ws.report(first).clashes}, "each clash titled once"
    # Asked again, the new list's own clashes (none of the first list's) are titled, its titles from the scene's.
    c.post(f"/api/reports/{second}/titles/stream").read()
    assert all(x.title for x in ws.report(second).clashes)
    again = [n for b in titler.batches for n in b]
    assert len(again) == len(set(again)), "no clash titled twice"


def test_a_reading_of_a_clash_that_moved_is_not_shown_on_the_new_list(served):
    app_module, ws, sid, _ = served
    first = ws.report(ws.detect(sid)["report"]["id"])
    job = _done(app_module._start_triage(first, sid, lambda: None))
    duct = next(x for x in first.clashes if {x.a.name, x.b.name} == {"Duct D1", "Beam B1"})
    gid = duct.a.global_id if duct.a.name == "Duct D1" else duct.b.global_id
    ws.scene(sid).translate([gid], (0.0, 0.0, 0.05))
    second = ws.report(ws.detect(sid)["report"]["id"])
    moved = second.clash(duct.id)
    assert abs(moved.distance_m - duct.distance_m) > checks.SAME_DEPTH_M
    shown = app_module._for_report(job, second)
    assert duct.id not in shown["results"] and shown["unread"] >= 1
    assert duct.id not in app_module._same_in(job, second)
    assert {x.id for x in second.clashes if x.id != duct.id and x.id in shown["results"]}, "the unchanged ones stay"


def test_a_scenes_run_is_kept_last_in_line():
    from sightline import app as app_module

    jobs = {}
    app_module._keep_job(jobs, "scene:x", "first", 16)
    for i in range(15):
        app_module._keep_job(jobs, f"r{i}", i, 16)
    app_module._keep_job(jobs, "scene:x", "again", 16)
    app_module._keep_job(jobs, "r15", 15, 16)
    assert jobs["scene:x"] == "again" and "r0" not in jobs and len(jobs) == 16


def test_a_run_under_way_is_followed_or_queued_behind(served):
    app_module, ws, sid, model = served
    first = ws.report(ws.detect(sid)["report"]["id"])
    model.gate.clear()
    running = app_module._start_triage(first, sid, lambda: None)
    ducts = ws.report(ws.detect(sid, DUCTS)["report"]["id"])
    charged = []
    key = next(k["key"] for k in ducts.checks if k["key"] != "models")
    followed = app_module._start_triage(ducts, sid, lambda: charged.append(1), scope=key)
    assert followed is running and charged == [], "the run under way reads the ducts check's clashes: followed, free"
    pipes = ws.report(ws.detect(sid, NEAR_PIPES)["report"]["id"])
    pkey = next(k["key"] for k in pipes.checks if k["name"].startswith("PipeSegment"))
    queued = app_module._start_triage(pipes, sid, lambda: charged.append(1), scope=pkey)
    assert queued is not running and queued.after is running and charged == [1]
    assert queued.events[0]["queued"] is True
    model.gate.set()
    _done(running); _done(queued)
    p3 = next(x for x in pipes.clashes if {x.a.name, x.b.name} == {"Pipe P3 under beam", "Beam B1"})
    assert queued.results[p3.id]["source"] == "model"
    assert sum("Pipe P3" in t for t in model.asked) == 1 and len(model.asked) <= 7, "only P3 is read after the first run"
    # Triage again while a run is under way is queued too, not dropped.
    model.gate.clear()
    rerun = app_module._start_triage(pipes, sid, lambda: charged.append(1), rerun=True)
    again = app_module._start_triage(pipes, sid, lambda: charged.append(1), rerun=True)
    assert again.after is rerun and charged == [1, 1, 1]
    model.gate.set()
    _done(rerun); _done(again)


def test_check_summaries_can_be_read_while_checks_come_and_go(opened):
    ws, sid = opened
    ws.detect(sid)
    errors, stop = [], threading.Event()

    def read():
        while not stop.is_set():
            try:
                register = ws.checks[sid]
                register.summaries(); register.contacts(); register.known(); register.find("models")
                ws.checks_info(sid)
            except Exception as e:  # pragma: no cover - shown by the assertion
                errors.append(e)

    t = threading.Thread(target=read)
    t.start()
    for _ in range(6):
        key = ws.detect(sid, PIPES)["check"]
        ws.remove_check(sid, key)
    stop.set(); t.join(5)
    assert not errors
