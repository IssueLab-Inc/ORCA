"""Coordination requirements reaching the agent, triage and the API (docs/requirements.md). Muse stays in the loop."""
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import requirements as req
from sightline import triage
from sightline.agent import PACKS, Clash, resolve
from sightline.fixtures import build_clash_fixture, build_detection_fixtures
from sightline.scene import IfcScene
from sightline.service import Workspace
from tests.test_reports import STANDARD


class Fixer:
    """Muse Spark's stand-in for fixes: records the system prompt and what it was told; drops the duct 400 mm (hits
    the pipe), then 800 mm, then shifts it 3.5 m."""

    def __init__(self):
        self.systems, self.texts = [], []

    def complete_json(self, system, text, images=None):
        self.systems.append(system)
        self.texts.append(text)
        if len(self.texts) == 1:
            return {"understanding": "The duct passes through the beam web.", "advice": "Ask the MEP designer.",
                    "candidates": [{"title": "Drop duct 400 mm", "move": "A", "delta_m": [0, 0, -0.40]}]}
        return {"candidates": [{"title": "Drop duct 800 mm", "move": "A", "delta_m": [0, 0, -0.80]},
                               {"title": "Shift duct 3.5 m east", "move": "A", "delta_m": [3.5, 0, 0]}]}


@pytest.fixture()
def fixture(tmp_path: Path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    return s, s.model.by_type("IfcDuctSegment")[0].GlobalId, s.model.by_type("IfcBeam")[0].GlobalId


def settings_for(scene, doc, a, b):
    m = req.Matcher(scene, doc)
    return {"clearance_m": req.fix_clearance(doc, m, a, b), "doc": doc, "guidance": req.prompt_text(doc, "fixes"),
            "policy": {a: req.policy(doc, m, a), b: req.policy(doc, m, b)}}


def test_without_requirements_the_prompt_is_unchanged(fixture):
    s, duct, beam = fixture
    model = Fixer()
    result = resolve(s, Clash(duct, beam), model, max_rounds=1)
    assert model.systems[0] == (PACKS / "construction.md").read_text()
    assert result.requirements is None


def test_a_move_limit_refuses_candidates_before_they_are_tried_and_muse_hears_why(fixture):
    s, duct, beam = fixture
    doc = req.parse({**req.default_doc(s).to_dict(), "strictness": "strict"})
    model = Fixer()
    result = resolve(s, Clash(duct, beam), model, max_rounds=2, **settings_for(s, doc, duct, beam))
    assert [a.passed for a in result.attempts] == [False, False, False]
    assert "IfcPipeSegment" in result.attempts[0].reason                       # 400 mm: tried, hits the pipe
    assert all("blocked by requirements" in a.reason for a in result.attempts[1:])
    assert "Strict" in model.systems[0] and "at least 40 mm" in model.systems[0]
    assert result.requirements == "L3 Coordinated · Strict" and not result.options


def test_verified_options_say_what_they_meet(fixture):
    s, duct, beam = fixture
    doc = req.default_doc(s)
    result = resolve(s, Clash(duct, beam), Fixer(), max_rounds=2, **settings_for(s, doc, duct, beam))
    assert result.options and result.options[0].meets
    assert any("required (Balanced)" in m or "more than 25 mm" in m for m in result.options[0].meets)
    assert any("untouched" in m for m in result.options[0].meets)


def test_no_edits_allowed_still_asks_muse_for_a_recommendation(fixture):
    s, duct, beam = fixture
    doc = req.parse({**req.default_doc(s).to_dict(), "level": 5})
    model = Fixer()
    before = s.placement(duct).copy()
    result = resolve(s, Clash(duct, beam), model, recommend="L5 As-built: report only",
                     **settings_for(s, doc, duct, beam))
    assert len(model.systems) == 1 and "do not allow ORCA to edit" in model.systems[0]
    assert result.options == [] and result.attempts == []
    assert result.recommendation["title"] == "Drop duct 400 mm"
    assert result.recommendation["blocked_by"] == "L5 As-built: report only"
    assert (s.placement(duct) == before).all()


def test_workspace_fix_settings_recommend_when_neither_side_may_be_edited(tmp_path):
    paths = build_detection_fixtures(tmp_path)
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    scene = ws.scene(sid)
    beam = next(e.GlobalId for m in scene.models for e in m.by_type("IfcBeam"))
    duct = next(e.GlobalId for m in scene.models for e in m.by_type("IfcDuctSegment"))
    assert ws.fix_settings(sid, duct, beam) == {}
    with req.using(req.register(req.parse({**req.default_doc(scene).to_dict(), "level": 5}))):
        s = ws.fix_settings(sid, duct, beam)
        assert s["recommend"] == "L5 As-built: report only" and s["clearance_m"] == pytest.approx(0.025)
    with req.using(req.register(req.default_doc(scene))):
        assert ws.fix_settings(sid, duct, beam)["recommend"] is None


# ------------------------------------------------------------------------------------------------- triage

class Reader:
    """Triage and audit stand-in: every clash is real; a rule's samples look real."""

    def __init__(self, audit="looks_real"):
        self.asked, self.audits, self.systems = [], [], []
        self.audit = audit
        self.lock = threading.Lock()

    def complete_json(self, system, text, images=None, schema=None):
        with self.lock:
            if schema == triage.AUDIT_SCHEMA:
                self.audits.append(text)
                return {"answer": self.audit, "note": "Clash #2 is a wall through a beam."}
            self.asked.append(text)
            self.systems.append(system)
        return {"understanding": "u", "verdict": "by_design", "severity": "none", "responsible": "none",
                "action": "none", "fix_hint": "", "confidence": 0.5}


def _report(tmp_path):
    from sightline import reports
    (tmp_path / "a.xml").write_text(STANDARD.replace("{beam}", "0FQ9jQy2DHrgb6aZcJtSSS"))
    return reports.load("r", tmp_path, [tmp_path / "a.xml"], "t")


def _doc(**over):
    return req.parse({"format": req.FORMAT, "groups": [{"id": "all", "name": "All", "teams": ["MEP", "Structure"]}],
                      "by_design": [{"a_classes": ["IfcWall"], "b_classes": ["IfcBeam"], "reason": "walls carry beams"}],
                      **over})


def test_a_rule_settles_without_a_model_call_and_the_rest_are_read_under_the_requirements(tmp_path):
    report = _report(tmp_path)
    model = Reader()
    out = triage.triage_report(report, model, workers=1, images=False, requirements=_doc(strictness="strict"))
    wall = next(c for c in report.clashes if "IfcWall" in (c.a.ifc_class, c.b.ifc_class))
    duct = next(c for c in report.clashes if c is not wall)
    assert out[wall.id]["basis"] == "requirement" and out[wall.id]["source"] == "rule"
    assert len(model.asked) == 1 and "Project coordination requirements" in model.systems[0]
    assert out[duct.id]["verdict"] == "real_clash" and out[duct.id]["basis"] == "strictness"  # 0.5 < 0.6


def test_a_rule_over_a_known_reading_keeps_it(tmp_path):
    report = _report(tmp_path)
    wall = next(c for c in report.clashes if "IfcWall" in (c.a.ifc_class, c.b.ifc_class))
    done = {wall.id: {"verdict": "real_clash", "understanding": "A wall through the beam.", "source": "model"}}
    out = triage.triage_report(report, Reader(), workers=1, images=False, done=done, requirements=_doc())
    assert out[wall.id]["basis"] == "requirement" and "A wall through the beam." in out[wall.id]["model_reading"]


def test_muse_audits_the_rules_and_a_disputed_rule_marks_its_clashes(tmp_path):
    report = _report(tmp_path)
    model = Reader()
    job = triage.Job(report, model, {"model": "scripted", "images": False}, 1, requirements=_doc()).start()
    events = list(job.follow())
    wall = next(c for c in report.clashes if "IfcWall" in (c.a.ifc_class, c.b.ifc_class))
    assert len(model.audits) == 1 and "walls carry beams" in model.audits[0]
    assert job.results[wall.id]["audit"] == "disputed"
    assert job.state()["audit"]["0"]["answer"] == "looks_real"
    assert [e["type"] for e in events][-2:] == ["audit", "done"]


def test_a_seeded_job_keeps_readings_and_asks_only_what_the_rules_no_longer_settle(tmp_path):
    report = _report(tmp_path)
    first = Reader()
    job = triage.Job(report, first, {"model": "s", "images": False}, 1, requirements=_doc()).start()
    list(job.follow())
    second = Reader()
    again = triage.Job(report, second, {"model": "s", "images": False}, 1, requirements=_doc(by_design=[]),
                       seed=job.results).start()
    list(again.follow())
    assert len(second.asked) == 1 and len(again.results) == 2   # the wall clash: its rule is gone, read now


# ------------------------------------------------------------------------------------------------- the API

@pytest.fixture()
def client(tmp_path, monkeypatch):
    paths = build_detection_fixtures(tmp_path)
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "_triage_jobs", {})
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": [p.name for p in paths]}).json()["id"]
    return c, sid


def test_register_a_file_and_send_its_id(client):
    c, sid = client
    start = c.get(f"/api/scenes/{sid}/requirements/default").json()
    assert start["label"] == "L3 Coordinated · Balanced" and start["inventory"]["files"]
    doc = {**start["doc"], "strictness": "strict"}
    reg = c.post("/api/requirements", json=doc).json()
    assert reg["params"]["fix_clearance_mm"] == 40 and len(reg["id"]) == 16
    tests = c.get(f"/api/scenes/{sid}/detect/tests", headers={"X-Sightline-Requirements": reg["id"]}).json()
    assert all(t["id"].startswith("req:") for t in tests["tests"])
    assert tests["requirements"]["label"] == "L3 Coordinated · Strict"
    plain = c.get(f"/api/scenes/{sid}/detect/tests").json()
    assert not any(t["id"].startswith("req:") for t in plain["tests"]) and plain["requirements"] is None


def test_an_unknown_id_is_refused_so_the_page_registers_again(client):
    c, sid = client
    r = c.get(f"/api/scenes/{sid}/detect/tests", headers={"X-Sightline-Requirements": "0123456789abcdef"})
    assert r.status_code == 409 and r.json()["detail"] == "requirements_unknown"


def test_a_wrong_file_or_a_huge_one_is_refused(client):
    c, _ = client
    assert c.post("/api/requirements", json={"format": "other"}).status_code == 422
    assert c.post("/api/requirements", content=b"{" + b" " * (req.MAX_BYTES + 1) + b"}").status_code == 413


def test_detection_under_requirements_reports_them_and_reruns_compare_only_like_with_like(client):
    c, sid = client
    start = c.get(f"/api/scenes/{sid}/requirements/default").json()
    rid = c.post("/api/requirements", json=start["doc"]).json()["id"]
    plain = [json.loads(l) for l in c.post(f"/api/scenes/{sid}/detect/stream", json={}).text.splitlines()][-1]
    ruled = [json.loads(l) for l in c.post(f"/api/scenes/{sid}/detect/stream", json={},
                                           headers={"X-Sightline-Requirements": rid}).text.splitlines()][-1]
    assert ruled["type"] == "done" and ruled["requirements"]["id"] == rid
    assert len(ruled["report"]["clashes"]) == len(plain["report"]["clashes"])
    assert ruled["diff"]["first"] is True                      # other tests: not compared with the plain run


def test_preview_counts_without_opening_a_report(client):
    c, sid = client
    start = c.get(f"/api/scenes/{sid}/requirements/default").json()
    p = c.post(f"/api/scenes/{sid}/requirements/preview", json=start["doc"]).json()
    assert p["clashes"] == p["baseline"] > 0
    lenient = c.post(f"/api/scenes/{sid}/requirements/preview",
                     json={**start["doc"], "level": 2, "strictness": "lenient"}).json()
    assert lenient["clashes"] < lenient["baseline"]


def test_suggest_asks_muse_once_and_drops_invented_classes(client, monkeypatch):
    c, sid = client

    class Drafter:
        def complete_json(self, system, text, images=None, schema=None):
            assert schema == req.SUGGEST_SCHEMA and "coordination requirements" in system
            facts = json.loads(text)
            assert facts["level"]["level"] == 4 and facts["files"]
            return {"summary": "Two groups.", "groups": [
                {"id": "frame", "name": "Frame", "role": "structure", "teams": ["Structure"], "classes": [], "reason": ""},
                {"id": "services", "name": "Services", "role": "services", "teams": ["MEP"],
                 "classes": ["IfcDuctSegment", "IfcUnicornSegment"], "reason": ""}],
                "checks": [{"a": "frame", "b": "services", "check": "clearance", "clearance_mm": 30, "reason": "hangers"},
                           {"a": "services", "b": "", "check": "hard", "clearance_mm": 0, "reason": ""}],
                "who_moves": [{"group": "frame", "edits": "none", "max_move_mm": 0, "trims": False},
                              {"group": "services", "edits": "any", "max_move_mm": 600, "trims": True}],
                "by_design": [{"a_classes": ["IfcDuctSegment"], "b_classes": ["IfcSensor"], "reason": "sensors in ducts"}],
                "guidance": {"triage": "Ducts matter.", "fixes": "Keep the frame."}}

    monkeypatch.setattr(app_module.ws, "_model", Drafter())
    out = c.post(f"/api/scenes/{sid}/requirements/suggest", json={"level": 4, "strictness": "strict"}).json()
    doc = out["doc"]
    assert out["summary"] == "Two groups." and doc["level"] == 4 and doc["strictness"] == "strict"
    assert doc["groups"][1]["classes"] == ["IfcDuctSegment"]          # the invented class is gone
    assert doc["checks"][0]["clearance_mm"] == 30 and doc["checks"][1]["b"] is None
    assert doc["who_moves"][0]["edits"] == "none" and doc["who_moves"][0]["max_move_mm"] is None
    assert all(g["source"] == "orca" for g in doc["groups"])


def test_the_report_says_what_it_was_checked_against(tmp_path):
    from sightline import document
    scene = IfcScene(build_detection_fixtures(tmp_path))
    doc = req.parse({**req.default_doc(scene).to_dict(), "strictness": "strict",
                     "by_design": [{"a_classes": ["IfcPlate"], "b_classes": ["IfcMember"], "reason": "joints"}]})
    html = document.render_html("t", "s", [], {}, {"Requirements": "x"}, doc)
    assert "Coordination requirements" in html and req.doc_id(doc) in html and "at least 40 mm clear" in html
    assert "Plate with Member" in html and "L3 Coordinated · Strict" in html
    assert "at least 25 mm clear" in document.render_html("t", "s", [], {}, {})


def test_an_agent_link_works_under_the_pages_requirements(client):
    c, sid = client
    start = c.get(f"/api/scenes/{sid}/requirements/default").json()
    rid = c.post("/api/requirements", json={**start["doc"], "strictness": "strict"}).json()["id"]
    token = c.post("/api/links", json={"scene_id": sid}).json()["token"]
    link = app_module.links.get(token)
    assert link.requirements is None
    c.put(f"/api/links/{token}/context", json={"scene_id": sid}, headers={"X-Sightline-Requirements": rid})
    assert link.requirements == rid
