import json

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import plans
from sightline.fixtures import build_run_fixture
from sightline.limits import ProposeLimit
from sightline.service import Workspace


class Model:
    """Muse Spark stand-in: offsets whichever segment is element A by +0.40 m; root cause says fix the partners."""

    def complete_json(self, system, text, images=None):
        if "hub" in text:
            return {"root_cause": "Services ignore the beam.", "strategy": "fix_partners", "reason": "Offset each."}
        return {"understanding": "Through the beam.", "candidates": [
            {"title": "Up 400", "kind": "offset", "move": "A", "split_m": [2.0, 4.0], "dz_m": 0.4},
            {"title": "Up 380", "kind": "offset", "move": "A", "split_m": [2.0, 4.0], "dz_m": 0.38}]}


def _report_xml(pairs):
    results = ""
    for n, (a, b, d) in enumerate(pairs, 1):
        obj = lambda g: (f"<clashobject><smarttags><smarttag><name>X / Element / IfcClass</name><value>IfcElement</value></smarttag>"
                         f"<smarttag><name>X / Element / GlobalId</name><value>{g}</value></smarttag></smarttags></clashobject>")
        results += f'<clashresult name="Clash{n}" guid="g{n}" distance="{d}"><clashobjects>{obj(a)}{obj(b)}</clashobjects></clashresult>'
    return f'<exchange><batchtest><clashtests><clashtest name="T" tolerance="0"><clashresults>{results}</clashresults></clashtest></clashtests></batchtest></exchange>'


def _setup(tmp_path):
    build_run_fixture(tmp_path / "run.ifc")
    ws = Workspace(samples=tmp_path, model=Model())
    sid = ws.open(["run.ifc"])
    m = ws.scene(sid).model
    main = next(e for e in m.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    beam, slab = m.by_type("IfcBeam")[0].GlobalId, m.by_type("IfcSlab")[0].GlobalId
    (tmp_path / "reports" / "r").mkdir(parents=True)
    # The same pair twice (two tests reporting it) and the beam against the slab (not a real overlap here).
    (tmp_path / "reports" / "r" / "report.xml").write_text(_report_xml([(main, beam, -0.15), (beam, main, -0.15)]))
    return ws, sid, ws.open_report_sample("r").id, main, beam


def test_batch_dedupes_pairs_and_checks_the_plan_as_a_whole(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    events = []
    plan = plans.build_batch(ws, sid, rid, ["c0001", "c0002"], events.append)
    [item] = plan.items
    assert item.clash_ids == ["c0001", "c0002"] and item.option["kind"] == "offset"
    assert plan.check["passed"] and plan.check["items"][item.key]["min_clearance_m"] > 0.04
    assert [e["status"] for e in events if e["type"] == "item"][-1] == "done"
    assert len(list(ws.scene(sid).model.by_type("IfcDuctSegment"))) == 2      # trials were all undone


def test_verify_together_finds_fixes_that_collide(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    end = next(e for e in ws.scene(sid).model.by_type("IfcDuctSegment") if e.Tag != "SA-1").GlobalId
    up = {"kind": "offset", "moved": [main], "split_m": [2.0, 4.0], "delta_m": [0, 0, 0.4]}
    # Move the end segment back into the main's raised middle: alone it may pass, together they collide.
    clash = {"kind": "move", "moved": [end], "delta_m": [-3.5, 0, 0.4]}
    items = [plans.Item("k1", main, beam, "", [], option=up), plans.Item("k2", end, main, "", [], option=clash)]
    check = plans.verify_together(ws, sid, items)
    assert not check["passed"] and check["conflicts"]


def test_root_causes_and_plan_endpoints(tmp_path, monkeypatch):
    ws, sid, rid, main, beam = _setup(tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "propose_limit", ProposeLimit(per_client_hour=1))
    c = TestClient(app_module.app)
    assert c.get(f"/api/reports/{rid}/root_causes/{sid}").json() == []        # one pair is not a cluster
    r = c.post(f"/api/scenes/{sid}/plan/stream", json={"report_id": rid, "clash_ids": ["c0001", "c0002"]})
    events = [json.loads(line) for line in r.text.splitlines()]
    plan = events[-1]
    assert plan["type"] == "plan" and plan["check"]["passed"] and len(plan["items"]) == 1
    # The allowance is per pair: a second plan this hour is refused before any work starts.
    assert c.post(f"/api/scenes/{sid}/plan/stream", json={"report_id": rid, "clash_ids": ["c0001"]}).status_code == 429
    applied = c.post(f"/api/scenes/{sid}/plan/apply", json={"options": [plan["items"][0]["option"]]}).json()
    assert applied["files"] == [0] and len(applied["pieces"][0]) == 5


def test_patterns_group_same_kind_clashes_and_triage_maps_back(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    pats = plans.patterns(ws, sid, rid, min_pairs=1)
    [p] = pats
    assert p["classes"] == sorted(["IfcBeam", "IfcDuctSegment"]) and p["clashes"] == 2 and p["pairs"] == 1 and p["constant"]

    class Triage:
        def complete_json(self, system, text, images=None):
            assert "P1:" in text
            return {"patterns": [{"id": "P1", "verdict": "by_design", "cause": "c", "action": "a", "rule": "r"}]}
    ws._model = Triage()
    assert plans.triage_patterns(ws, pats)[p["id"]]["verdict"] == "by_design"
    assert plans.patterns(ws, sid, rid, fixed=["c0001", "c0002"], min_pairs=1) == []   # resolved clashes drop out
