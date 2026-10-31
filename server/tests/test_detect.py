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


DUCTS = {"when": [{"facet": "class", "op": "is", "values": ["IfcDuctSegment"]}], "invert": False}


def test_a_check_on_filters_compares_what_a_filter_finds(paths):
    """docs/filters.md, "Checks": side A a filter, side B Everything or itself."""
    scene = IfcScene(paths)
    vs_all = detect.Test.from_dict({"a": {"filter": DUCTS}, "b": {}})
    run = detect.run(scene, [vs_all])
    assert vs_all.id.startswith("filter:") and vs_all.name == "DuctSegment vs Everything"
    assert ("Beam B1", "Duct D1") in names(run) and all("Duct" in a + b for a, b in names(run))
    assert all(c.a.global_id != c.b.global_id for c in run.report.clashes), "never an element with itself"
    pairs = [frozenset((c.a.global_id, c.b.global_id)) for c in run.report.clashes]
    assert len(pairs) == len(set(pairs)), "each pair once, though ducts are on both sides"
    assert run.report.title == "Coordination · DuctSegment vs Everything"
    within = detect.run(scene, [detect.Test.from_dict({"a": {"filter": DUCTS}, "b": None})])
    assert all(c.a.ifc_class == c.b.ifc_class == "IfcDuctSegment" for c in within.report.clashes)
    assert within.report.title == "Coordination · DuctSegment (within)"


def test_a_filter_colouring_by_value_is_a_side_of_what_it_colours(paths):
    """A Colour by… filter has no conditions: as a side it takes what it colours, a value ticked off left out."""
    scene = IfcScene(paths)
    by_file = {"when": [], "invert": False, "by": {"facet": "file", "off": ["Fixture-Structure.ifc"]}}
    t = detect.Test.from_dict({"a": {"filter": by_file}, "b": None})
    run = detect.run(scene, [t])
    assert run.report.clashes and all(c.a.file == c.b.file == "Fixture-MEP.ifc" for c in run.report.clashes)
    assert t.a.filter["by"] == {"facet": "file", "off": ["Fixture-Structure.ifc"]}
    assert detect.Test.from_dict({"a": {"filter": {**by_file, "by": {"facet": "file", "off": []}}}, "b": None}).id != t.id
    with pytest.raises(ValueError):
        detect.Test.from_dict({"a": {"filter": {"when": [], "by": {"off": ["x"]}}}})


def test_everything_is_what_the_full_check_covers_a_site_model_left_out(paths):
    scene = IfcScene(paths)
    ix = detect._Index(scene)
    assert detect.everything(scene, ix) == detect.Selection(), "no site model: every model"
    ix.teams = ["Site" if n == "Fixture-Structure.ifc" else t for n, t in zip(ix.names, ix.teams)]
    assert detect.everything(scene, ix) == detect.Selection(files=["Fixture-MEP.ifc"])
    ix.teams = ["Site"] * len(ix.teams)
    assert detect.everything(scene, ix) == detect.Selection(), "a site model on its own is everything there is"


def test_what_the_filters_show_is_a_side_found_on_every_run(paths):
    """docs/filters.md, "Checks": all the page's filters together, as on screen."""
    scene = IfcScene(paths)
    ducts = {**DUCTS, "action": "colour"}
    beams = {"when": [{"facet": "class", "op": "is", "values": ["IfcBeam"]}], "invert": False, "action": "colour"}
    view = {"filters": [ducts, beams], "hide_rest": True, "colours": True}
    t = detect.Test.from_dict({"a": {"view": view}, "b": None})
    run = detect.run(scene, [t])
    assert ("Beam B1", "Duct D1") in names(run)
    assert all({c.a.ifc_class, c.b.ifc_class} <= {"IfcBeam", "IfcDuctSegment"} for c in run.report.clashes)
    assert run.report.title == "Coordination · What the filters show (within)" and t.name == "What the filters show (within)"
    again = detect.Test.from_dict({"a": {"view": {**view, "filters": [beams, ducts]}}, "b": None})
    assert again.id == t.id, "what the filters show together does not depend on their order"
    nothing = detect.Test.from_dict({"a": {"view": {**view, "hide_rest": False}}, "b": None})
    assert nothing.id != t.id
    for bad in ({"filters": "x"}, {"filters": [{**ducts, "action": "explode"}]}, {"filters": [ducts] * 101}):
        with pytest.raises(ValueError):
            detect.Test.from_dict({"a": {"view": bad}})


def test_a_checks_id_comes_from_what_it_compares(paths):
    two = [{"facet": "class", "op": "is", "values": ["IfcDuctSegment", "IfcPipeSegment"]},
           {"facet": "storey", "op": "is", "values": ["Level 01"]}]
    t1 = detect.Test.from_dict({"a": {"filter": {"when": two}}, "b": {}})
    t2 = detect.Test.from_dict({"a": {"filter": {"when": [two[1], {**two[0], "values": two[0]["values"][::-1]}]}}, "b": {},
                                "name": "Mine"})
    assert t1.id == t2.id and t2.name == "Mine", "the same filter, written another way, is the same check"
    assert detect.Test.from_dict({"a": {"filter": {"when": two}}, "b": {}, "kind": "clearance", "clearance_m": 0.05}).id != t1.id
    assert detect.Test.from_dict({"a": {"filter": {"when": two}}, "b": None}).id != t1.id
    with pytest.raises(ValueError):
        detect.Test.from_dict({"a": {"filter": {"when": [{"facet": "class", "op": "explode"}]}}})
    with pytest.raises(ValueError):
        detect.Test.from_dict({"a": {"filter": {"when": [{"op": "is"}]}}})


def test_a_clash_keeps_its_id_and_number_across_the_full_check_and_a_check_on_filters(paths, tmp_path):
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    pair = lambda out: next(c for c in out["report"]["clashes"] if {c["a"]["name"], c["b"]["name"]} == {"Duct D1", "Beam B1"})
    full = ws.detect(sid)
    assert full["tests"] is None
    check = ws.detect(sid, [{"a": {"filter": DUCTS}, "b": {}}])
    assert (pair(check)["id"], pair(check)["number"]) == (pair(full)["id"], pair(full)["number"])
    assert check["report"]["title"] == "Coordination · DuctSegment vs Everything"
    assert check["diff"]["resolved"] == [] and check["diff"]["no_longer_checked"] == [], "not like with like: no noise"
    assert check["tests"][0]["id"].startswith("filter:") and ws.detections[sid]["tests"] == check["tests"]
    back = ws.detect(sid)
    assert pair(back)["id"] == pair(full)["id"] and back["diff"]["no_longer_checked"] == []
    assert back["diff"]["new"] == [], "the full check's clashes come back, not anew"
    assert {c["status"] for c in back["report"]["clashes"]} == {"active"}
    # Detect again on the same check still says what was fixed.
    ws.detect(sid, check["tests"])
    scene = ws.scene(sid)
    scene.translate([pair(full)["a"]["global_id"] if pair(full)["a"]["name"] == "Duct D1" else pair(full)["b"]["global_id"]],
                    (0.0, 0.0, -0.6))
    moved = ws.detect(sid, check["tests"])
    assert any({r["a"], r["b"]} >= {pair(full)["a"]["global_id"]} for r in moved["diff"]["resolved"])


def test_the_tests_and_their_defaults_for_a_check(paths, tmp_path):
    import json
    from fastapi.testclient import TestClient
    from sightline import app as app_module
    import pytest as _pytest

    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    mp = _pytest.MonkeyPatch()
    try:
        mp.setattr(app_module, "ws", Workspace(samples=tmp_path))
        c = TestClient(app_module.app)
        sid = c.post("/api/scenes", json={"samples": [p.name for p in paths]}).json()["id"]
        check = c.get(f"/api/scenes/{sid}/detect/tests").json()["check"]
        assert check["tolerance_m"] == 0.001 and check["clearance_m"] == 0.025 and all(check["rules"].values())
        r = c.post(f"/api/scenes/{sid}/detect/stream", json={"tests": [{"id": "", "a": {"filter": DUCTS}, "b": {}}]})
        done = [json.loads(line) for line in r.text.splitlines()][-1]
        assert done["type"] == "done" and done["tests"][0]["id"].startswith("filter:")
        assert done["report"]["title"] == "Coordination · DuctSegment vs Everything"
        bad = c.post(f"/api/scenes/{sid}/detect/stream", json={"tests": [{"a": {"filter": {"when": [{"facet": "class", "op": "x"}]}}}]})
        assert bad.status_code == 422
    finally:
        mp.undo()


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


def test_a_run_names_the_requirements_it_ran_under(paths, tmp_path):
    """The page keeps sign-offs per detection run by the models and this id (every run's title is the same)."""
    from sightline import requirements as req

    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    sid = ws.open([p.name for p in paths])
    plain = ws.detect(sid)["report"]
    assert plain["requirements_id"] is None and sorted(plain["sources"]) == sorted(p.name for p in paths)
    rid = req.register(req.default_doc(ws.scene(sid)))
    with req.using(rid):
        under = ws.detect(sid)["report"]
    assert under["requirements_id"] == rid and under["title"] == plain["title"]
    assert ws.report_summary(under["id"])["requirements_id"] == rid


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


def _workspace(paths, tmp_path):
    for p in paths:
        (tmp_path / p.name).write_bytes(p.read_bytes())
    ws = Workspace(samples=tmp_path)
    return ws, ws.open([p.name for p in paths])


class _Scripted:
    """Muse Spark's stand-in: tool calls in order, then an answer; keeps what it was sent."""

    def __init__(self, steps):
        self.steps, self.seen = list(steps), []

    def chat(self, messages, tools):
        import json
        self.seen.append(messages[-1])
        step = self.steps.pop(0)
        if isinstance(step, str):
            return {"role": "assistant", "content": step}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(step)]}


MINE = [{"id": "u1", "name": "Ducts", "when": DUCTS["when"], "invert": False, "on": True}]


def test_chat_checks_a_users_filter_by_name_or_what_it_describes(paths, tmp_path):
    import json
    from sightline.chat import Chat, Context

    ws, sid = _workspace(paths, tmp_path)
    model = _Scripted([[("detect_clashes", {"a": {"filter": "ducts"}})],
                       [("detect_clashes", {"a": {"classes": ["DuctSegment"]}, "b": {"itself": True}})], "Done."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "What do my ducts hit?", Context(sid, None, None, [], MINE), events.append)
    assert 'the user\'s filters: "Ducts"' in model.seen[0]["content"]
    opened = [e for e in events if e.get("action") == "open_report"]
    first, second = (o["detection"]["tests"][0] for o in opened)
    assert first["name"] == "Ducts vs Everything" and first["id"].startswith("filter:") and first["b"] == {
        k: [] for k in ("files", "teams", "classes", "exclude_classes", "systems", "ids")} | {"filter": None, "view": None}
    assert second["name"] == "DuctSegment (within)" and second["b"] is None
    told = json.loads(model.seen[1]["content"])
    ducts = sum(1 for g in ws.scene(sid).bounds() if ws.scene(sid).element(g).ifc_class == "IfcDuctSegment")
    assert told["check"]["a"] == {"name": "Ducts", "elements": ducts} and told["check"]["b"]["name"] == "everything"
    assert any(c["test"] == "Ducts vs Everything" and c["clashes"] >= 1 for c in told["tests"])


def test_chat_checks_the_users_colour_by_filter_what_their_filters_show_and_everything_without_site(paths, tmp_path, monkeypatch):
    """The owner's case (Oct 31): a Colour by… filter and a colour by model with the site model ticked off, the rest
    hidden; "run a clash test on the filtered items" must leave the site model out."""
    import json
    from sightline import facets, requirements
    from sightline.chat import Chat, Context

    ws, sid = _workspace(paths, tmp_path)
    real = requirements._file_teams
    monkeypatch.setattr(requirements, "_file_teams", lambda scene, domain: [
        "Site" if p.name == "Fixture-Structure.ifc" else t for p, t in zip(scene.paths, real(scene, domain))])
    idx, scene = ws.facets(sid), ws.scene(sid)
    drawn = set(scene.bounds())
    mep = {g for i, g in enumerate(idx["elements"]) if idx["files"][idx["file"][i]] == "Fixture-MEP.ifc"} & drawn
    ducts = {g for g in drawn if scene.element(g).ifc_class == "IfcDuctSegment"}
    others = [v for v in facets.facet(idx, "class")["values"] if v != "IfcDuctSegment"]
    by_class = {"id": "c", "name": "Ducts by class", "when": [], "invert": False, "on": True, "action": "byValue",
                "by": {"facet": "class", "off": others}}
    by_model = {"id": "m", "name": "By Model", "when": [], "invert": False, "on": True, "action": "byValue",
                "by": {"facet": "file", "off": ["Fixture-Structure.ifc"]}}
    model = _Scripted([[("detect_clashes", {"a": {"filter": "ducts by class"}})],
                       [("detect_clashes", {"a": {"shown": True}, "b": {"itself": True}})], "Done."])
    events = []
    chat = Chat(ws, model)
    ctx = Context(sid, None, None, [], [by_class, by_model], {"hide_rest": True, "colours": True})
    chat.turn(chat.session(None), "run a clash test on the filtered items", ctx, events.append)
    assert f"together they show {len(mep)} of {len(drawn)} elements" in model.seen[0]["content"]
    first, second = (json.loads(m["content"])["check"] for m in model.seen[1:3])
    assert first["a"] == {"name": "Ducts by class", "elements": len(ducts)}, "a Colour by… filter takes what it colours"
    assert first["b"] == {"name": "everything", "elements": len(mep)}, "everything leaves the site model out"
    assert second["a"] == {"name": "what the filters show", "elements": len(mep)}
    tests = [e["detection"]["tests"][0] for e in events if e.get("action") == "open_report"]
    assert tests[0]["name"] == "Ducts by class vs Everything" and tests[0]["b"]["files"] == ["Fixture-MEP.ifc"]
    assert tests[1]["name"] == "What the filters show (within)" and tests[1]["a"]["view"]["hide_rest"] is True
    for e in events:
        if e.get("action") == "open_report":
            clashes = ws.report(e["report_id"]).clashes
            assert all(c.a.file == c.b.file == "Fixture-MEP.ifc" for c in clashes), "no element of the site model"

    # Nothing on: the filtered items cannot be checked, and no run is spent.
    model = _Scripted([[("detect_clashes", {"a": {"shown": True}})], "Sorry."])
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "check the filtered items", Context(sid, None, None, [], [{**by_model, "on": False}]),
              lambda e: None)
    assert "no filters on" in model.seen[1]["content"]


def test_a_check_on_what_the_models_lack_is_refused_before_a_run_is_spent(paths, tmp_path):
    from sightline.chat import Chat, Context

    ws, sid = _workspace(paths, tmp_path)
    for a, said in (({"filter": "Pipes"}, "Its filters: Ducts"), ({"classes": ["Ductt"]}, "Closest: IfcDuctSegment"),
                    ({"itself": True}, "Side A cannot be itself")):
        model = _Scripted([[("detect_clashes", {"a": a})], "Sorry."])
        events = []
        chat = Chat(ws, model)
        chat.turn(chat.session(None), "Check", Context(sid, None, None, [], MINE), events.append, detect_allowed=lambda: "spent")
        assert not [e for e in events if e.get("action") == "open_report"]
        assert said in model.seen[1]["content"] and "spent" not in model.seen[1]["content"]


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
