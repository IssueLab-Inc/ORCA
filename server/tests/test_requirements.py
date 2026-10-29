"""Coordination requirements (docs/requirements.md): the file, the numbers it resolves to, and what it compiles into."""
from pathlib import Path

import pytest

from sightline import detect, requirements as req
from sightline.fixtures import build_detection_fixtures
from sightline.reports import ReportClash, ReportElement
from sightline.scene import IfcScene


@pytest.fixture(scope="module")
def paths(tmp_path_factory) -> list[Path]:
    return build_detection_fixtures(tmp_path_factory.mktemp("requirements"))


@pytest.fixture(scope="module")
def scene(paths):
    return IfcScene(paths)


def pairs(run):
    return sorted((tuple(sorted((c.a.global_id, c.b.global_id))), round(c.distance_m, 4)) for c in run.report.clashes)


def names(run):
    return sorted(tuple(sorted((c.a.name, c.b.name))) for c in run.report.clashes)


def doc_with(scene, **over):
    d = req.default_doc(scene).to_dict()
    d.update(over)
    return req.parse(d)


# ------------------------------------------------------------------------------------------------- the file

def test_parse_drops_unknown_fields_clamps_numbers_and_needs_its_groups():
    doc = req.parse({
        "format": "orca-requirements/1", "level": 9, "strictness": "brutal", "whatever": 1,
        "groups": [{"id": "MEP", "name": "MEP", "role": "services", "select": {"teams": ["MEP"], "classes": ["IfcDuct Segment", "IfcPipeSegment"]}},
                   {"id": "everything", "name": "Everything"}],
        "checks": [{"a": "mep", "b": "nowhere"}, {"a": "mep", "b": "mep", "check": "clearance", "clearance_mm": 9000}],
        "who_moves": [{"group": "mep", "edits": "sometimes", "max_move_mm": -5}],
        "guidance": {"triage": "x" * 5000}})
    assert doc.level == 5 and doc.strictness == "balanced"
    assert [g.id for g in doc.groups] == ["mep"]                       # a group that selects nothing is dropped
    assert doc.groups[0].classes == ["IfcPipeSegment"]                  # not an IFC class name: dropped
    assert len(doc.checks) == 1 and doc.checks[0].b is None             # a group against itself
    assert doc.checks[0].clearance_mm == req.MAX_CLEARANCE_MM
    assert doc.who_moves[0].edits == "any" and doc.who_moves[0].max_move_mm is None
    assert len(doc.guidance["triage"]) == req.MAX_GUIDANCE


def test_a_file_of_another_format_is_refused():
    with pytest.raises(ValueError, match="not an ORCA requirements file"):
        req.parse({"format": "ids/1"})


def test_the_id_is_its_content_and_survives_a_round_trip(scene):
    doc = req.default_doc(scene)
    again = req.parse(doc.to_dict())
    assert req.doc_id(again) == req.doc_id(doc)
    assert req.doc_id(doc_with(scene, strictness="strict")) != req.doc_id(doc)


def test_registry_and_context(scene):
    doc = req.default_doc(scene)
    rid = req.register(doc)
    assert req.current() is None
    with req.using(rid) as d:
        assert d is not None and req.current_id() == rid
    with req.using("unknown"):
        assert req.current() is None
    assert req.current() is None


# ------------------------------------------------------------------------------------------------- numbers

def test_l3_balanced_is_todays_numbers(scene):
    p = req.resolve(req.default_doc(scene))
    assert (p.tolerance_mm, p.min_size_mm, p.fix_clearance_mm, p.max_move_mm, p.trims, p.edits, p.lean) == \
        (1, 0, 25, None, "yes", "any", None)


@pytest.mark.parametrize("level,strictness,tol,fix,move,trims", [
    (3, "lenient", 10, 10, None, "yes"), (3, "strict", 1, 40, 400, "cleanup"), (3, "exacting", 1, 50, 300, "no"),
    (1, "balanced", 50, 25, None, "yes"), (2, "relaxed", 40, 15, None, "yes")])
def test_level_and_strictness_resolve_to_numbers(scene, level, strictness, tol, fix, move, trims):
    p = req.resolve(doc_with(scene, level=level, strictness=strictness))
    assert (p.tolerance_mm, p.fix_clearance_mm, p.max_move_mm, p.trims) == (tol, fix, move, trims)


def test_scale_lists_five_levels_and_five_steps():
    s = req.scale()
    assert [l["level"] for l in s["levels"]] == [1, 2, 3, 4, 5]
    assert [x["id"] for x in s["strictness"]] == list(req.STRICTNESS_ORDER)
    assert all(l["hints"] for l in s["levels"])


# ------------------------------------------------------------------------------------------------- detection

def test_default_groups_are_the_teams_and_every_pair_is_checked(scene):
    doc = req.default_doc(scene)
    assert [(g.id, g.role) for g in doc.groups] == [("structure", "structure"), ("mep", "services")]
    assert [(c.a, c.b, c.check) for c in doc.checks] == [("structure", None, "hard"), ("structure", "mep", "hard"),
                                                         ("mep", None, "hard")]
    assert [m.group for m in doc.who_moves] == ["structure", "mep"]


def test_l3_balanced_finds_what_the_default_tests_find(scene):
    """The invariant: requirements made from the models, unchanged, check exactly what ORCA checks without them."""
    default = detect.run(scene)
    compiled = detect.run(scene, req.compile_tests(req.default_doc(scene)))
    assert pairs(compiled) == pairs(default)
    assert all(t.tolerance_m == 0.001 and t.min_size_m == 0 for t in req.compile_tests(req.default_doc(scene)))


def test_lenient_raises_the_tolerance_and_finds_fewer(scene):
    balanced = detect.run(scene, req.compile_tests(req.default_doc(scene)))
    lenient = detect.run(scene, req.compile_tests(doc_with(scene, level=2, strictness="lenient")))
    assert len(lenient.report.clashes) < len(balanced.report.clashes)
    assert ("Beam B1", "Duct D1") in names(lenient)                      # 350 mm is still a clash at 10 mm


def test_a_clearance_cell_catches_the_pipe_under_the_beam(scene):
    d = req.default_doc(scene).to_dict()
    for c in d["checks"]:
        if c["b"] == "mep":
            c.update(check="clearance", clearance_mm=25)
    doc = req.parse({**d, "strictness": "strict"})
    tests = req.compile_tests(doc)
    t = next(t for t in tests if t.id == "req:structure|mep")
    assert t.kind == "clearance" and t.clearance_m == pytest.approx(0.025)
    run = detect.run(scene, tests)
    assert ("Beam B1", "Pipe P3 under beam") in names(run)


def test_level_four_puts_clearance_between_services_and_structure(scene):
    t = next(t for t in req.compile_tests(doc_with(scene, level=4)) if t.id == "req:structure|mep")
    assert t.kind == "clearance" and t.clearance_m == pytest.approx(0.025)
    t = next(t for t in req.compile_tests(doc_with(scene, level=4, strictness="lenient")) if t.id == "req:structure|mep")
    assert t.kind == "hard"                                               # lenient: hard checks only


def test_an_off_cell_is_not_run_and_rules_reach_the_tests(scene):
    d = req.default_doc(scene).to_dict()
    d["checks"][0]["check"] = "off"
    d["rules"]["host"] = False
    tests = req.compile_tests(req.parse(d))
    assert "req:structure" not in {t.id for t in tests}
    assert all(t.rules["host"] is False for t in tests)


def test_min_size_leaves_small_elements_out(scene):
    t = detect.Test(id="t", name="t", a=detect.Selection(teams=["MEP"]), min_size_m=0.3)
    run = detect.run(scene, [t])
    assert ("Duct D1", "Sensor in duct") not in names(run)                 # the 50 mm sensor is too small to check
    assert detect.Test.from_dict({"id": "x", "min_size_m": 0.3}).min_size_m == 0.3


def test_one_model_alone_is_grouped_by_kind_of_thing(paths):
    doc = req.default_doc(IfcScene(paths[:1]))
    assert [g.id for g in doc.groups] == ["structure", "equipment"]
    assert "IfcBeam" in doc.groups[0].classes and "IfcDoor" in doc.groups[1].classes


# ------------------------------------------------------------------------------------------------- fixes

def test_policy_follows_the_level_the_strictness_and_the_movers_row(scene):
    gid = {e.Name: e.GlobalId for m in scene.models for e in m.by_type("IfcElement")}
    d = req.default_doc(scene).to_dict()
    d["who_moves"][0].update(edits="none")
    doc = req.parse(d)
    m = req.Matcher(scene, doc)
    beam, duct = req.policy(doc, m, gid["Beam B1"]), req.policy(doc, m, gid["Duct D1"])
    assert (beam.group, beam.edits) == ("structure", "none") and (duct.group, duct.edits) == ("mep", "any")
    assert req.blocked(beam, duct, "move", [0, 0, 0.1], False) == "blocked by requirements: Structure may not be edited"
    assert req.blocked(duct, beam, "move", [0, 0, 0.5], False) is None
    strict = req.parse({**d, "strictness": "strict"})
    duct = req.policy(strict, req.Matcher(scene, strict), gid["Duct D1"])
    assert "more than the 400 mm" in req.blocked(duct, beam, "move", [0, 0, 0.5], False)
    assert req.blocked(duct, beam, "trim", [0, 0, 0], False) == "blocked by requirements: trims only tidy a joint within one model"
    assert req.policy(doc_with(scene, level=5), req.Matcher(scene, doc), gid["Duct D1"]).edits == "none"


def test_fix_clearance_is_the_strictness_or_the_pairs_clearance(scene):
    gid = {e.Name: e.GlobalId for m in scene.models for e in m.by_type("IfcElement")}
    doc = req.default_doc(scene)
    assert req.fix_clearance(doc, req.Matcher(scene, doc), gid["Duct D1"], gid["Beam B1"]) == pytest.approx(0.025)
    d = doc.to_dict()
    for c in d["checks"]:
        if c["b"] == "mep":
            c.update(check="clearance", clearance_mm=60)
    doc = req.parse(d)
    assert req.fix_clearance(doc, req.Matcher(scene, doc), gid["Duct D1"], gid["Beam B1"]) == pytest.approx(0.06)


# ------------------------------------------------------------------------------------------------- triage

def _clash(a_cls, b_cls, distance=-0.05):
    e = lambda cls, n: ReportElement(global_id=n, ifc_class=cls, name=n, level="L1", file="f.ifc")
    return ReportClash(id="c1", name="x", guid="g", test="t", test_type="hard", tolerance_m=0.001, status="new",
                       distance_m=distance, point=[0, 0, 0], grid=None, a=e(a_cls, "A1"), b=e(b_cls, "B1"))


def test_a_by_design_rule_settles_either_way_round(scene):
    doc = doc_with(scene, by_design=[{"a_classes": ["IfcPipeFitting"], "b_classes": ["IfcPipeSegment"], "reason": "fittings on their pipe"}])
    v = req.settle(doc, _clash("IfcPipeSegment", "IfcPipeFitting"))
    assert v["basis"] == "requirement" and v["verdict"] == "by_design" and v["rule"] == 0
    assert "fittings on their pipe" in v["understanding"]
    assert req.settle(doc, _clash("IfcDuctSegment", "IfcBeam")) is None


def test_strict_does_not_trust_a_low_confidence_by_design(scene):
    v = {"verdict": "by_design", "confidence": 0.5, "severity": "none", "source": "model", "understanding": "u"}
    assert req.overlay(req.default_doc(scene), v) is v
    out = req.overlay(doc_with(scene, strictness="strict"), v)
    assert out["verdict"] == "real_clash" and out["basis"] == "strictness" and out["model_verdict"] == "by_design"
    assert req.overlay(doc_with(scene, strictness="strict"), {**v, "confidence": 0.9})["verdict"] == "by_design"


def test_prompt_lines_say_the_level_lean_movers_and_guidance(scene):
    doc = doc_with(scene, strictness="strict", guidance={"triage": "Ignore hangers.", "fixes": "Keep ducts level."})
    t = req.prompt_text(doc, "triage")
    assert "L3 Coordinated" in t and "call it real_clash" in t and "Ignore hangers." in t
    f = req.prompt_text(doc, "fixes")
    assert "at least 40 mm" in f and "400 mm" in f and "Keep ducts level." in f and "Structure stays put" in f


def test_model_key_ignores_rules_but_not_strictness(scene):
    base = req.default_doc(scene)
    ruled = doc_with(scene, by_design=[{"a_classes": ["IfcPlate"], "b_classes": ["IfcMember"]}])
    assert req.model_key(ruled) == req.model_key(base) and req.rules_key(ruled) != req.rules_key(base)
    assert req.model_key(doc_with(scene, strictness="strict")) != req.model_key(base)
