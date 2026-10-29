"""ORCA detection (docs/detection.md) on small synthetic models: one case per rule and measure."""
from pathlib import Path

import pytest

from sightline import detect, plans, triage
from sightline.fixtures import build_detection_fixtures
from sightline.scene import IfcScene
from sightline.service import Workspace


def names(run, test=None):
    return sorted(tuple(sorted((c.a.name, c.b.name))) for c in run.report.clashes if test is None or c.test == test)


def cov(run, name):
    return next(c for c in run.coverage if c.name == name)


@pytest.fixture(scope="module")
def paths(tmp_path_factory) -> list[Path]:
    return build_detection_fixtures(tmp_path_factory.mktemp("detect"))


@pytest.fixture(scope="module")
def result(paths):
    return detect.run(IfcScene(paths))


def test_default_tests_pair_every_model_and_check_each_against_itself(paths):
    tests = detect.default_tests(IfcScene(paths))
    assert [t.name for t in tests] == ["MEP vs Structure", "MEP (within)", "Structure (within)", "Duplicates (all models)"]
    assert all(t.tolerance_m == 0.001 for t in tests)
    assert [t.kind for t in tests] == ["hard", "hard", "hard", "duplicate"]


def test_a_site_model_is_context_its_tests_are_offered_but_off(paths):
    scene = IfcScene(paths)
    ix = detect._Index(scene)
    ix.teams = ["Site" if n == "Fixture-Structure.ifc" else t for n, t in zip(ix.names, ix.teams)]
    tests = {t.name: t for t in detect.default_tests(scene, ix)}
    assert [n for n, t in tests.items() if t.enabled] == ["MEP (within)", "Duplicates (building models)"]
    assert tests["Duplicates (building models)"].a.files == ["Fixture-MEP.ifc"]
    assert not tests["MEP vs Site"].enabled and not tests["Site (within)"].enabled


def test_the_crossing_duct_is_the_only_clash_between_the_models(result):
    assert names(result, "MEP vs Structure") == [("Beam B1", "Duct D1")]
    c = next(c for c in result.report.clashes if c.test == "MEP vs Structure")
    assert c.a.name == "Duct D1" and c.a.file == "Fixture-MEP.ifc" and c.b.file == "Fixture-Structure.ifc"
    assert c.distance_m == pytest.approx(-0.35, abs=1e-3)   # up 350 mm clears the beam's top: exact for two boxes
    assert c.point == pytest.approx([3.0, 0.1, 2.8], abs=0.06)
    assert c.a.level == "Level 01" and c.a.ifc_class == "IfcDuctSegment"


def test_a_touch_and_half_a_millimetre_are_not_clashes(result):
    """Pipe P1 sits on the beam (0 mm), P2 runs 0.5 mm into it: at 1 mm both are touches, and only P2 overlaps at all."""
    assert cov(result, "MEP vs Structure").touching == 1
    assert not [c for c in result.report.clashes if "Pipe" in c.a.name + c.b.name]


def test_flush_faced_overlap_found_with_its_exact_depth(result):
    """The strut runs 30 mm into the beam's end with every side flush: the triangle queries miss it."""
    c = next(c for c in result.report.clashes if {c.a.name, c.b.name} == {"Beam B1", "Strut S1"})
    assert c.distance_m == pytest.approx(-0.03, abs=1e-4)


def test_an_element_wholly_inside_another_is_a_clash(result):
    assert ("Duct D1", "Sensor in duct") in names(result, "MEP (within)")


def test_pairs_meant_to_meet_are_counted_not_reported(result):
    s = cov(result, "Structure (within)")
    assert s.excluded == {"host": 1, "assembly": 1}           # door in its wall; two panels of one curtain wall
    assert cov(result, "MEP (within)").excluded == {"connected": 1}
    reported = {n for pair in names(result) for n in pair}
    assert not reported & {"Door D1", "Wall W1", "CW1 panel 0", "CW1 panel 1", "Duct run 0", "Duct run 1"}


def test_rules_can_be_switched_off(paths):
    t = detect.Test(id="s", name="Structure (within)", a=detect.Selection(files=["Fixture-Structure.ifc"]),
                    rules={"host": False})
    run = detect.run(IfcScene(paths), [t])
    assert ("Door D1", "Wall W1") in names(run)
    assert cov(run, "Structure (within)").excluded == {"assembly": 1}


def test_duplicates_are_copies_not_crossing_braces_with_the_same_box(result):
    assert names(result, "Duplicates (all models)") == [("Column C1 copy 1", "Column C1 copy 2")]
    assert ("Brace X1", "Brace X2") in names(result, "Structure (within)")


def test_clearance_reports_the_gap(paths):
    t = detect.Test(id="c", name="clear", kind="clearance", clearance_m=0.025, a=detect.Selection(teams=["MEP"]),
                    b=detect.Selection(teams=["Structure"]))
    run = detect.run(IfcScene(paths), [t])
    gaps = {c.a.name: c.distance_m for c in run.report.clashes}
    assert gaps["Pipe P3 under beam"] == pytest.approx(0.02, abs=1e-3)
    assert gaps["Duct D1"] == pytest.approx(-0.35, abs=1e-3)


def test_models_far_from_the_origin_give_the_same_clashes(tmp_path, result):
    """The triangle tree drops real overlaps far from its origin; the run shifts the models nearer first."""
    far = detect.run(IfcScene(build_detection_fixtures(tmp_path, (100_000.0, 250_000.0, 30.0))))
    assert far.offset != [0.0, 0.0, 0.0]
    assert names(far) == names(result)
    duct = next(c for c in far.report.clashes if c.test == "MEP vs Structure")
    assert duct.point == pytest.approx([100_003.0, 250_000.1, 32.8], abs=0.06)


def test_self_tests_count_each_pair_once(result):
    within = [c for c in result.report.clashes if c.test.endswith("(within)")]
    pairs = [frozenset((c.a.global_id, c.b.global_id)) for c in within]
    assert len(pairs) == len(set(pairs))
    assert all(c.a.global_id != c.b.global_id for c in within)


def test_ids_are_stable_and_a_rerun_tells_new_from_resolved(paths):
    scene = IfcScene(paths)
    first = detect.run(scene)
    assert first.diff["first"] and all(c.status == "new" for c in first.report.clashes)
    numbers = {c.id: c.number for c in first.report.clashes}
    assert sorted(numbers.values()) == list(range(1, len(numbers) + 1))   # #1..#n across the whole set, not per test
    assert all(c.name == f"{c.a.name} × {c.b.name}" and c.label == f"#{c.number} {c.name}" for c in first.report.clashes)
    again = detect.run(scene, previous=first.state)
    assert [c.id for c in again.report.clashes] == [c.id for c in first.report.clashes]
    assert {c.id: c.number for c in again.report.clashes} == numbers
    assert again.diff["new"] == [] and again.diff["resolved"] == []
    assert all(c.status == "active" for c in again.report.clashes)

    duct = next(c for c in first.report.clashes if c.test == "MEP vs Structure").a.global_id
    scene.translate([duct], (0.0, 0.0, -0.6))                 # under the beam, and away from the sensor it held
    moved = detect.run(scene, previous=first.state)
    assert sorted(r["test"] for r in moved.diff["resolved"]) == ["MEP (within)", "MEP vs Structure"]
    # A resolved clash's number is not reused: anything new later takes the next one.
    scene.translate([duct], (0.0, 0.0, 0.6))
    back = detect.run(scene, previous=moved.state)
    assert {c.id: c.number for c in back.report.clashes} == numbers

    # A test that no longer selects the structure model cannot call its clashes resolved.
    narrow = [detect.Test(id="pair:Fixture-MEP.ifc|Fixture-Structure.ifc", name="MEP vs Structure",
                          a=detect.Selection(files=["Fixture-MEP.ifc"]), b=detect.Selection(classes=["IfcWall"]))]
    unchecked = detect.run(scene, narrow, previous=first.state)
    assert unchecked.diff["resolved"] == []
    assert any(r["test"] == "MEP vs Structure" for r in unchecked.diff["no_longer_checked"])


def test_a_test_over_the_cap_is_partial(paths):
    run = detect.run(IfcScene(paths), cap=1)
    s = cov(run, "Structure (within)")
    assert s.partial and s.clashes == 1
    assert run.state["selections"][s.test]["complete"] is False


def test_selections_by_class_and_exclusion(paths):
    t = detect.Test(id="t", name="Columns vs structure", a=detect.Selection(classes=["IfcColumn"]),
                    b=detect.Selection(files=["Fixture-Structure.ifc"], exclude_classes=["IfcColumn"]))
    assert detect.run(IfcScene(paths), [t]).report.clashes == []


def test_bad_tests_are_refused():
    with pytest.raises(ValueError):
        detect.Test.from_dict({"id": "x", "kind": "soft"})
    t = detect.Test.from_dict({"id": "x", "a": {"files": ["A.ifc"]}, "b": None, "rules": {"connected": False}})
    assert t.b is None and t.rules["connected"] is False and t.rules["host"] is True


def test_a_run_is_a_report_the_rest_of_sightline_reads(paths, tmp_path):
    """Detection opens as a clash report: matching by GlobalId, triage's rules, patterns and captured views work."""
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    out = ws.detect(sid)
    rid = out["report"]["id"]
    report = ws.report(rid)
    assert out["report"]["origin"] == "sightline" and report.temporary
    matches = ws.match(rid, sid)
    assert all(m["how"] == ["globalid", "globalid"] for m in matches.values())
    assert all(triage.by_rule(c) is None for c in report.clashes)   # real overlaps, not touches or non-physical
    assert isinstance(plans.patterns(ws, sid, rid), list)
    duct = next(c for c in report.clashes if c.test == "MEP vs Structure")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    assert ws.save_capture(rid, duct.id, "A", png) == ["A"]
    assert ws.clash_for(duct.a.global_id, duct.b.global_id, report_id=rid, clash_id=duct.id).images
    assert "Found by ORCA" in ws.clash_for(duct.a.global_id, duct.b.global_id, report_id=rid,
                                                clash_id=duct.id).notes
    # The next run on the same scene compares with this one, and keeps the views taken of clashes still there.
    again = ws.detect(sid)
    assert again["diff"]["first"] is False and again["diff"]["new"] == []
    kept = next(c for c in again["report"]["clashes"] if c["id"] == duct.id)
    assert kept["images"] == ["A"]
    assert ws.report_image(again["report"]["id"], duct.id, 0).read_bytes() == png


def test_detect_api_streams_progress_then_opens_the_report(paths, tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from sightline import app as app_module

    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": [p.name for p in paths]}).json()["id"]

    tests = c.get(f"/api/scenes/{sid}/detect/tests").json()
    assert [t["name"] for t in tests["tests"]][:2] == ["MEP vs Structure", "MEP (within)"]
    assert tests["teams"] == {"Fixture-Structure.ifc": "Structure", "Fixture-MEP.ifc": "MEP"}

    r = c.post(f"/api/scenes/{sid}/detect/stream", json={})
    assert r.headers["content-encoding"] == "identity"
    events = [json.loads(line) for line in r.text.splitlines()]
    assert [e["type"] for e in events][:2] == ["phase", "start"]
    done = events[-1]
    assert done["type"] == "done" and done["report"]["origin"] == "sightline"
    rid = done["report"]["id"]
    clash = next(x for x in done["report"]["clashes"] if x["test"] == "MEP vs Structure")
    assert c.get(f"/api/reports/{rid}").json()["clashes"]

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    up = c.post(f"/api/reports/{rid}/clashes/{clash['id']}/images", data={"label": "A"},
                files={"image": ("a.png", png, "image/png")})
    assert up.json() == {"images": ["A"]}
    assert c.get(f"/api/reports/{rid}/clashes/{clash['id']}/images/0").content == png
    assert c.post(f"/api/reports/{rid}/clashes/{clash['id']}/images", data={"label": "A"},
                  files={"image": ("a.txt", b"not a png", "text/plain")}).status_code == 415
    assert c.post(f"/api/scenes/{sid}/detect/stream", json={"tests": [{"id": "x", "kind": "soft"}]}).status_code == 422


def test_chat_can_run_detection_and_then_work_on_its_report(paths, tmp_path):
    import json
    from sightline.chat import Chat, Context

    class Scripted:
        def __init__(self, steps):
            self.steps = list(steps)

        def chat(self, messages, tools):
            step = self.steps.pop(0)
            if isinstance(step, str):
                return {"role": "assistant", "content": step}
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                for i, (n, a) in enumerate(step)]}

    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    events = []
    chat = Chat(ws, Scripted([[("detect_clashes", {"tolerance_mm": 1})], [("report_summary", {})], "Five clashes."]))
    answer = chat.turn(chat.session(None), "Find the clashes", Context(sid, None, None), events.append)
    assert answer == "Five clashes."
    opened = next(e for e in events if e.get("action") == "open_report")
    assert ws.report(opened["report_id"]).origin == "sightline"
    assert opened["detection"]["coverage"] and any(e["type"] == "detect_event" for e in events)


def test_one_model_on_its_own_is_named_after_its_file(paths):
    names = [t.name for t in detect.default_tests(IfcScene(paths[0]))]
    assert names == ["Fixture-Structure (within)", "Duplicates (all models)"]


def test_now_measures_a_detected_clash_as_the_run_did(paths, tmp_path):
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    out = ws.detect(sid)
    duct = next(c for c in out["report"]["clashes"] if c["test"] == "MEP vs Structure")
    now = ws.measure(out["report"]["id"], duct["id"], sid)
    assert now["distance_m"] == pytest.approx(duct["distance_m"], abs=1e-6)
    ws.scene(sid).translate([duct["a"]["global_id"]], (0.0, 0.0, -0.6))
    assert detect.measure_pair(ws.scene(sid), duct["a"]["global_id"], duct["b"]["global_id"]) is None
