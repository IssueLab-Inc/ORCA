import pytest
import json

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import plans
from sightline.fixtures import build_route_fixture, build_run_fixture
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
    assert ws.last_try(sid, main, beam)["attempts"]   # what a second try on this item reads (docs/escalation.md)
    assert not item.recommended


def test_a_merged_item_is_titled_by_the_clashes_it_covers(tmp_path):
    # One duct through two columns (the route fixture's RT-2): two clashes, one element that can move, so one item.
    build_route_fixture(tmp_path / "route.ifc")
    ws = Workspace(samples=tmp_path, model=Model())
    sid = ws.open(["route.ifc"])
    m = ws.scene(sid).model
    duct = next(e for e in m.by_type("IfcDuctSegment") if e.Tag == "RT-2").GlobalId
    b2, b4 = (next(e for e in m.by_type("IfcColumn") if e.Name == n).GlobalId for n in ("Column B2", "Column B4"))
    (tmp_path / "reports" / "r").mkdir(parents=True)
    (tmp_path / "reports" / "r" / "report.xml").write_text(_report_xml([(duct, b2, -0.3), (duct, b4, -0.3)]))
    rid = ws.open_report_sample("r").id
    plan = plans.build_batch(ws, sid, rid, ["c0001", "c0002"])
    [item] = plan.items
    assert item.element_a == duct and item.others and item.clash_ids == ["c0001", "c0002"]
    assert plan.title == "Fix 2 clashes together"
    # Distinct clashes, and one for an item that stands for none (a hub's partner not in the report).
    assert plans.clashes_covered([item, plans.Item("k1", duct, b2, "", ["c0001"]), plans.Item("k2", duct, b4, "", [])]) == 3


def test_verify_together_finds_fixes_that_collide(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    end = next(e for e in ws.scene(sid).model.by_type("IfcDuctSegment") if e.Tag != "SA-1").GlobalId
    up = {"kind": "offset", "moved": [main], "split_m": [2.0, 4.0], "delta_m": [0, 0, 0.4]}
    # Move the end segment back into the main's raised middle: alone it may pass, together they collide.
    clash = {"kind": "move", "moved": [end], "delta_m": [-3.5, 0, 0.4]}
    items = [plans.Item("k1", main, beam, "", [], option=up), plans.Item("k2", end, main, "", [], option=clash)]
    check = plans.verify_together(ws, sid, items)
    assert not check["passed"] and check["conflicts"]


def test_a_combined_fix_in_a_plan_is_checked_as_a_single_proposal_checks_it(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    combined = {"kind": "combined", "moved": [main], "delta_m": [0, 0, 0.4], "title": "t",
                "edit": {"pair": [main, beam], "steps": [
                    {"kind": "offset", "target": main, "split_m": [2.0, 4.0], "delta_m": [0, 0, 0.4]}]}}
    check = plans.verify_together(ws, sid, [plans.Item("k1", main, beam, "", [], option=combined)])
    assert check["passed"] and check["items"]["k1"]["min_clearance_m"] == pytest.approx(0.05, abs=1e-3)
    low = {**combined, "edit": {**combined["edit"], "steps": [{**combined["edit"]["steps"][0], "delta_m": [0, 0, 0.3]}]}}
    check = plans.verify_together(ws, sid, [plans.Item("k1", main, beam, "", [], option=low)])
    assert not check["passed"] and "IfcBeam" in check["items"]["k1"]["reason"]


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
    assert applied["files"] == [0] and len(applied["pieces"][0]) == 9


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


def test_a_pattern_reading_is_made_and_paid_for_once(tmp_path):
    import threading
    import time

    ws, sid, rid, main, beam = _setup(tmp_path)
    pats = plans.patterns(ws, sid, rid, min_pairs=1)
    started, go = threading.Event(), threading.Event()

    class Slow:
        calls = 0

        def complete_json(self, system, text, images=None):
            Slow.calls += 1
            started.set()
            go.wait(5)
            return {"patterns": [{"id": "P1", "verdict": "modelling_error"}]}
    ws._model = Slow()
    charged, out = [], []
    read = lambda: out.append(plans.read_patterns(ws, sid, rid, pats, lambda: charged.append(1)))
    first = threading.Thread(target=read)
    first.start()
    started.wait(5)
    second = threading.Thread(target=read)   # comes while the first is being made: waits for it
    second.start()
    time.sleep(0.2)
    go.set()
    first.join(5), second.join(5)
    assert Slow.calls == 1 and charged == [1]
    assert out[0] == out[1] == ({p["id"]: {"verdict": "modelling_error", "cause": "", "action": "", "rule": ""}
                                 for p in pats}, None)
    assert plans.read_patterns(ws, sid, rid, pats, lambda: "spent") == out[0]   # kept: no charge asked
    assert plans.read_patterns(ws, sid, "other", pats, lambda: "spent") == (None, "spent")
    assert plans.read_patterns(ws, sid, rid, [], lambda: "spent") == ({}, None)   # nothing to read


def test_root_cause_charges_fixes_only_when_edits_are_needed(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    end = next(e for e in ws.scene(sid).model.by_type("IfcDuctSegment") if e.Tag != "SA-1").GlobalId
    # A second pair on the beam makes it a root cause.
    (tmp_path / "reports" / "r2").mkdir(parents=True)
    from test_plans import _report_xml
    (tmp_path / "reports" / "r2" / "report.xml").write_text(_report_xml([(main, beam, -0.15), (end, beam, -0.05)]))
    rid2 = ws.open_report_sample("r2").id
    asked = []
    plan = plans.build_root_cause(ws, sid, rid2, beam, charge=lambda n: asked.append(n) or "no allowance left")
    assert asked == [2] and plan.advice == "no allowance left" and all(it.error for it in plan.items)


def test_a_moved_hub_is_checked_against_every_partner(tmp_path):
    ws, sid, rid, main, beam = _setup(tmp_path)
    end = next(e for e in ws.scene(sid).model.by_type("IfcDuctSegment") if e.Tag != "SA-1").GlobalId
    (tmp_path / "reports" / "r3").mkdir(parents=True)
    from test_plans import _report_xml
    (tmp_path / "reports" / "r3" / "report.xml").write_text(_report_xml([(main, beam, -0.15), (end, beam, -0.05)]))
    rid3 = ws.open_report_sample("r3").id

    class Cause:
        def complete_json(self, system, text, images=None):
            return {"root_cause": "the beam is low", "strategy": "move_hub", "reason": "raise the beam"}
    ws._model = Cause()
    plan = plans.build_root_cause(ws, sid, rid3, beam, charge=lambda n: "no allowance left")
    [item] = plan.items
    assert item.element_a == beam and {item.element_b, *item.others} == {main, end} and len(item.others) == 1


def test_pairs_sharing_a_movable_element_become_one_fix():
    from types import SimpleNamespace as NS
    elements = {"pipe": NS(fixed=False, name="Air pipe", ifc_class="IfcPipeSegment"),
                "rail_n": NS(fixed=True, name="Rail north", ifc_class="IfcMember"),
                "rail_s": NS(fixed=True, name="Rail south", ifc_class="IfcMember"),
                "girder": NS(fixed=True, name="Girder", ifc_class="IfcBeam"),
                "duct": NS(fixed=False, name="Duct", ifc_class="IfcDuctSegment"),
                "tray": NS(fixed=False, name="Tray", ifc_class="IfcCableCarrierSegment")}
    ws = NS(scene=lambda sid: NS(element=lambda g: elements[g]))
    items = [plans.Item("pipe|rail_n", "pipe", "rail_n", "", ["c1"], distance_m=-0.05),
             plans.Item("pipe|rail_s", "pipe", "rail_s", "", ["c2"], distance_m=-0.06),
             plans.Item("duct|girder", "duct", "girder", "", ["c3"]),
             plans.Item("girder|tray", "girder", "tray", "", ["c4"])]
    merged = plans.merge_shared(ws, "s", items)
    one = [it for it in merged if it.element_a == "pipe"]
    assert len(one) == 1 and one[0].element_b == "rail_n" and one[0].others == ["rail_s"]
    assert one[0].clash_ids == ["c1", "c2"] and one[0].distance_m == -0.06
    assert "2 elements" in one[0].label
    # the girder stays put, so the duct and the tray each keep their own fix
    assert sorted(it.key for it in merged if not it.others) == ["duct|girder", "girder|tray"]
