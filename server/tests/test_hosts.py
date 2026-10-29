"""Which hosts can take an opening (hosts.py): hard rules, Muse's reading of each kind of host, the requirements'
rules, and the actual hole checked against the reading's limits."""
import numpy as np
import pytest

from sightline import agent, edits, hosts, requirements as req, verify
from sightline.agent import Clash, resolve
from sightline.fixtures import build_penetration_fixture
from sightline.scene import IfcScene


@pytest.fixture(autouse=True)
def fresh():
    hosts.clear_cache()
    yield
    hosts.clear_cache()


@pytest.fixture
def scene(tmp_path) -> IfcScene:
    return IfcScene(build_penetration_fixture(tmp_path))


def gid(scene, name_or_tag):
    return next(e.GlobalId for m in scene.models for e in m.by_type("IfcElement")
                if name_or_tag in (e.Name, getattr(e, "Tag", None)))


class Reader:
    """Muse's stand-in for host readings: answers each kind it is asked about from `by_name` (name word → reading)."""

    def __init__(self, **by_name):
        self.by_name, self.calls = by_name, []

    def complete_json(self, system, text, images=None, schema=None):
        self.calls.append(text)
        out = []
        for line in text.splitlines()[1:]:
            kind = line.split("kind ", 1)[1].split(":", 1)[0]
            name = line.split("named '", 1)[1].split("'", 1)[0]
            r = next(v for k, v in self.by_name.items() if k in name)
            out.append({"kind": kind, "verdict": r[0], "reviewer": r[1], "fit": r[2] if len(r) > 2 else "annular",
                        "limits": {"max_depth_ratio": None, "keep_from_ends_depths": None, "keep_from_edges_m": None,
                                   "zone": "any", **(r[3] if len(r) > 3 else {})},
                        "conditions": list(r[4]) if len(r) > 4 else [], "reasoning": f"read {name}"})
        return {"readings": out}


WEB = {"max_depth_ratio": 0.4, "keep_from_ends_depths": 1.5, "zone": "middle_third"}


def test_hard_rules_need_no_model(scene):
    assert "transfer element: Column C2 on B2 stands on it" in hosts.hard_rule(scene, gid(scene, "Transfer beam B2"))
    assert "column is never cut" in hosts.hard_rule(scene, gid(scene, "Column C1"))
    assert "glazing" in hosts.hard_rule(scene, gid(scene, "Vision glazing unit G1"))
    assert "equipment is never cut" in hosts.hard_rule(scene, gid(scene, "PN-1"))
    assert hosts.hard_rule(scene, gid(scene, "Beam B1")) is None and hosts.hard_rule(scene, gid(scene, "Slab S1")) is None
    # Nothing overrides them: not Muse, not the requirements.
    d = req.default_doc(scene).to_dict()
    d["penetrations"] = [{"group": g["id"], "rule": "allowed"} for g in d["groups"]]
    assert hosts.decide(scene, gid(scene, "Transfer beam B2"), req.parse(d)).verdict == "never"


def test_muse_reads_each_kind_once_from_standard_facts_only(scene):
    reader = Reader(Beam=("with_review", "structure", "annular", WEB), Wall=("allowed", "none"))
    beam, wall = gid(scene, "Beam B1"), gid(scene, "Wall W1 partition")
    pa, pb = hosts.profile(scene, beam), hosts.profile(scene, wall)
    got = hosts.read(reader, [pa, pb, pa])
    assert set(got) == {pa["key"], pb["key"]} and len(reader.calls) == 1
    assert "FireRating=EI 60" in reader.calls[0] and "box 300 x 600 x 2000 mm" in reader.calls[0]
    hosts.read(reader, [pa])
    assert len(reader.calls) == 1                                                  # cached by kind
    r = hosts.decide(scene, beam)
    assert (r.verdict, r.reviewer, r.source, r.limits["max_depth_ratio"]) == ("with_review", "structure", "muse", 0.4)
    assert hosts.reading_text(r) == ("allowed with review, reviewed by structure (a hole at most 40% of its depth; in the "
                                     "middle third of its depth; 1.5 x its depth from its ends)")


def test_a_project_property_set_never_reaches_muse(scene):
    import ifcopenshell.api
    beam = scene.entity(gid(scene, "Beam B1"))
    model = scene.models[scene.index_of(beam.GlobalId)]
    pset = ifcopenshell.api.run("pset.add_pset", model, product=beam, name="Demo_AnswerKey")
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={"ClashRole": "Clash host for scripted #042"})
    facts = hosts.profile(scene, beam.GlobalId)["facts"]
    assert "Clash" not in str(facts) and "042" not in str(facts)


def test_the_hole_is_checked_against_the_readings_limits(scene):
    pipe, beam = gid(scene, "PN-4"), gid(scene, "Beam B1")
    reading = hosts.Reading("with_review", "structure", "annular", WEB)
    pen = edits.penetration(scene, pipe, beam)
    problems, numbers = hosts.check_hole(scene, pen, reading)
    assert not problems and numbers[0] == "hole 170 mm in 600 mm of host (28%)" and "915 mm from its nearest end" in numbers
    tight = hosts.Reading("with_review", "structure", "annular", {"max_depth_ratio": 0.25, "keep_from_ends_depths": 2})
    problems, _ = hosts.check_hole(scene, pen, tight)
    assert problems == ["the hole is 28% of the host's 600 mm depth (at most 25%)",
                        "the hole is 915 mm from the host's end (keep 1200 mm: 2 x its depth)"]


def test_a_beam_takes_an_opening_once_read_and_within_its_limits(scene):
    pipe, beam = gid(scene, "PN-4"), gid(scene, "Beam B1")
    hosts.read(Reader(Beam=("with_review", "structure", "annular", WEB, ["no hole within 1.5 depths of a support"])),
               [hosts.profile(scene, beam)])
    attempt, option = agent._try_penetration(scene, {"title": "Hole in B1's web"}, pipe, beam, 0.025)
    assert attempt.passed, attempt.reason
    assert option.review == "structure" and "no hole within 1.5 depths of a support" in option.also_needs
    assert option.edit["plain_host"] is False and option.edit["numbers"][0].startswith("hole 170 mm in 600 mm")
    assert agent.tier("penetration", option.edit) > agent.tier("penetration", {"plain_host": True})


def test_a_gland_plate_takes_a_fitted_hole_and_the_conduit_may_touch_it(scene):
    conduit, plate = gid(scene, "PN-9"), gid(scene, "Gland plate GP1")
    hosts.read(Reader(Gland=("allowed", "none", "fitted", {}, ["a cable gland to the enclosure's IP rating"])),
               [hosts.profile(scene, plate)])
    pen = edits.penetration(scene, conduit, plate, 0.025, "fitted")
    assert (pen.shape, pen.width_m, pen.fit, pen.gap_m) == ("round", 0.034, "fitted", 0.001)   # 32 mm + 1 mm round
    attempt, option = agent._try_penetration(scene, {}, conduit, plate, 0.025)
    assert attempt.passed, attempt.reason
    assert option.review is None and option.edit["fit"] == "fitted" and "cable gland" in option.also_needs
    # An annular opening would have been 32 + 2 x 30 mm, rounded up: 100 mm.
    assert edits.penetration(scene, conduit, plate, 0.025).width_m == 0.1


def test_requirements_rules_win_over_muse(scene):
    pipe, beam = gid(scene, "PN-4"), gid(scene, "Beam B1")
    hosts.read(Reader(Beam=("allowed", "none")), [hosts.profile(scene, beam)])
    d = req.default_doc(scene).to_dict()
    structure = next(g["id"] for g in d["groups"] if g["role"] == "structure")
    never = req.parse({**d, "penetrations": [{"group": structure, "rule": "never", "reason": "no holes in steel"}]})
    assert hosts.decide(scene, beam, never).verdict == "never"
    small = req.parse({**d, "penetrations": [{"group": structure, "rule": "review", "max_mm": 150, "reviewer": "structure"}]})
    r = hosts.decide(scene, beam, small)
    assert (r.verdict, r.reviewer, r.source, r.limits["max_size_m"]) == ("with_review", "structure", "requirements", 0.15)
    token = req.enter(req.register(small))
    try:
        attempt, _ = agent._try_penetration(scene, {}, pipe, beam, 0.025)
    finally:
        req.leave(token)
    assert "the hole is 170 mm (the requirements allow at most 150 mm)" in attempt.reason
    assert "Openings for services: Structure may take them, reviewed up to 150 mm by structure." in req.prompt_text(small, "fixes")


def test_a_file_without_penetration_rules_keeps_its_id(scene):
    doc = req.default_doc(scene)
    assert "penetrations" not in doc.to_dict()
    d = doc.to_dict()
    with_rules = req.parse({**d, "penetrations": [{"group": d["groups"][0]["id"], "rule": "allowed", "max_mm": 200}]})
    assert req.doc_id(with_rules) != req.doc_id(doc) and req.parse(with_rules.to_dict()) == with_rules
    assert req.doc_id(req.parse(d)) == req.doc_id(doc)


def test_the_agent_reads_the_host_before_round_one_and_muse_is_told(scene):
    pipe, beam = gid(scene, "PN-4"), gid(scene, "Beam B1")
    reader = Reader(Beam=("with_review", "structure", "annular", WEB))

    class Muse:
        calls = []

        def complete_json(self, system, text, images=None):
            self.calls.append(text)
            return {"candidates": [{"title": "Hole in the web", "kind": "penetration", "move": "A"}]}
    model = Muse()
    result = resolve(scene, Clash(pipe, beam), model, max_rounds=1, hosts_model=reader)
    assert len(reader.calls) == 1
    assert "Reading of this kind of host: allowed with review, reviewed by structure" in model.calls[0]
    assert result.options and result.options[0].kind == "penetration"


def test_the_transfer_beam_is_never_offered_and_muse_is_told_so(scene):
    pipe, beam = gid(scene, "PN-8"), gid(scene, "Transfer beam B2")
    reader = Reader(Beam=("allowed", "none"))
    text = agent._describe(scene, Clash(pipe, beam))
    assert "B may not take an opening (never: It is a transfer element: Column C2 on B2 stands on it." in text
    assert "Do not propose a penetration of B." in text
    attempt, _ = agent._try_penetration(scene, {}, pipe, beam, 0.025)
    assert not attempt.passed and "transfer element" in attempt.reason

    class Muse:
        def complete_json(self, system, text, images=None):
            return {"candidates": []}
    resolve(scene, Clash(pipe, beam), Muse(), max_rounds=1, hosts_model=reader)
    assert reader.calls == []   # a hard rule settles it: nothing to read


def test_a_failed_reading_leaves_walls_and_slabs_only(scene):
    class Broken:
        def complete_json(self, *a, **k):
            raise RuntimeError("host unreachable")
    pipe, beam = gid(scene, "PN-4"), gid(scene, "Beam B1")

    class Muse:
        def complete_json(self, system, text, images=None):
            return {"candidates": [{"title": "Hole in the web", "kind": "penetration", "move": "A"}]}
    events = []
    result = resolve(scene, Clash(pipe, beam), Muse(), max_rounds=1, hosts_model=Broken(), on_event=events.append)
    assert any(e["type"] == "note" and "host unreachable" in e["text"] for e in events)
    assert not result.options and "No reading of this kind of host" in result.attempts[0].reason
    assert hosts.decide(scene, beam).verdict == "not_advised"
    assert hosts.decide(scene, gid(scene, "Slab S1")).reviewer == "structure"


def test_a_kept_gland_hole_is_fitted_and_the_clash_clears(tmp_path):
    from sightline.service import Workspace
    paths = build_penetration_fixture(tmp_path / "samples")
    reader = Reader(Gland=("allowed", "none", "fitted"))
    ws = Workspace(paths[0].parent, hosts_model=reader)
    sid = ws.open([p.name for p in paths])
    scene = ws.scene(sid)
    conduit, plate = gid(scene, "PN-9"), gid(scene, "Gland plate GP1")
    v = ws.check_penetration(sid, conduit, plate)
    assert v["passed"] and v["host"] == "allowed; a fitted gland, no clearance round it"
    r = ws.apply_penetration(sid, conduit, plate)
    assert r["cut"] and r["fit"] == "fitted" and r["width_m"] == 0.034
    assert not [h for h in verify.check(scene, [conduit], clearance_m=0.0).hits if h.other == plate and h.distance_m < -0.001]


def test_a_rule_added_from_one_reading_covers_only_that_kind_of_host(scene):
    plate, beam = gid(scene, "Gland plate GP1"), gid(scene, "Beam B1")
    hosts.read(Reader(Gland=("allowed", "none", "fitted"), Beam=("never", "structure")),
               [hosts.profile(scene, plate), hosts.profile(scene, beam)])
    d = req.default_doc(scene).to_dict()
    structure = next(g["id"] for g in d["groups"] if g["role"] == "structure")
    rule = {"group": structure, "rule": "allowed", "source": "orca", "kind": hosts.profile(scene, plate)["key"],
            "kind_name": "gland plate gp"}
    doc = req.parse({**d, "penetrations": [rule]})
    assert doc.penetrations[0].kind == rule["kind"] and req.parse(doc.to_dict()) == doc
    assert hosts.decide(scene, plate, doc).source == "requirements"
    assert hosts.decide(scene, beam, doc).verdict == "never"     # Muse's never for beams stands
    group_wide = req.parse({**d, "penetrations": [{**rule, "kind": None}, rule]})
    assert hosts.decide(scene, beam, group_wide).verdict == "allowed"   # a person's group-wide rule still wins
    assert "Structure (gland plate gp) may take them" in req.prompt_text(doc, "fixes")


def test_the_host_model_is_resolved_for_each_request(tmp_path, monkeypatch):
    from sightline import meta_client
    from sightline.service import Workspace
    made = []
    monkeypatch.setattr(meta_client, "triage_model", lambda timeout_s=120: (made.append(timeout_s) or object(), {}))
    ws = Workspace(tmp_path)
    a, b = ws.hosts_model, ws.hosts_model
    assert a is not b and len(made) == 2      # never cached: the open-weights choice is per request

    def broken(timeout_s=120):
        raise RuntimeError("no key")
    monkeypatch.setattr(meta_client, "triage_model", broken)
    assert ws.hosts_model is None
    monkeypatch.setattr(meta_client, "triage_model", lambda timeout_s=120: (object(), {}))
    assert ws.hosts_model is not None         # a failure does not stick


def test_a_narrow_gland_plate_is_still_read_and_takes_its_fitted_hole(scene):
    import ifcopenshell.api
    plate = scene.entity(gid(scene, "Gland plate GP1"))
    model = scene.models[scene.index_of(plate.GlobalId)]
    prof = plate.Representation.Representations[0].Items[0].SweptArea
    prof.YDim, prof.Position.Location.Coordinates = 0.16, (0.3, 0.08)          # y 0.12-0.28: 160 mm wide
    m = np.eye(4)
    m[:3, 3] = (12.0, 0.12, 1.997)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=plate, matrix=m, is_si=True)
    scene._bounds = None
    conduit = gid(scene, "PN-9")
    with pytest.raises(edits.Unsupported, match="break out"):
        edits.penetration(scene, conduit, plate.GlobalId)                       # no room for an annular opening...
    assert agent.penetration_pairs(scene, Clash(conduit, plate.GlobalId))      # ...but it is read
    reader = Reader(Gland=("allowed", "none", "fitted"))

    class Muse:
        def complete_json(self, system, text, images=None):
            return {"candidates": [{"title": "Gland hole", "kind": "penetration", "move": "A"}]}
    result = resolve(scene, Clash(conduit, plate.GlobalId), Muse(), max_rounds=1, hosts_model=reader)
    assert len(reader.calls) == 1 and result.options and result.options[0].edit["fit"] == "fitted"


def test_keeping_an_opening_checks_the_hole_against_the_rules_as_they_are(tmp_path):
    from sightline.service import Workspace
    paths = build_penetration_fixture(tmp_path / "samples")
    ws = Workspace(paths[0].parent)
    sid = ws.open([p.name for p in paths])
    scene = ws.scene(sid)
    pipe, wall = gid(scene, "PN-1"), gid(scene, "Wall W1 partition")
    d = req.default_doc(scene).to_dict()
    group = req.Matcher(scene, req.parse(d)).group_of(wall).id
    small = req.parse({**d, "penetrations": [{"group": group, "rule": "review", "max_mm": 100}]})
    token = req.enter(req.register(small))
    try:
        with pytest.raises(edits.Unsupported, match="the requirements allow at most 100 mm"):
            ws.apply_penetration(sid, pipe, wall)
    finally:
        req.leave(token)


def test_a_fitted_gland_claims_no_clearance(scene):
    plate, conduit = gid(scene, "Gland plate GP1"), gid(scene, "PN-9")
    hosts.read(Reader(Gland=("allowed", "none", "fitted")), [hosts.profile(scene, plate)])
    doc = req.default_doc(scene)
    m = req.Matcher(scene, doc)

    class Muse:
        def complete_json(self, system, text, images=None):
            return {"candidates": [{"title": "Gland hole", "kind": "penetration", "move": "A"}]}
    result = resolve(scene, Clash(conduit, plate), Muse(), max_rounds=1, doc=doc,
                     policy={conduit: req.policy(doc, m, conduit), plate: req.policy(doc, m, plate)},
                     clearance_m=req.fix_clearance(doc, m, conduit, plate))
    assert result.options[0].meets[0] == "a fitted gland, sealed round the service (no clearance there)"


def test_muse_limits_are_numbers_in_range(scene):
    class Loose:
        def complete_json(self, system, text, images=None, schema=None):
            kind = text.split("kind ", 1)[1].split(":", 1)[0]
            return {"readings": [{"kind": kind, "verdict": "with_review", "reviewer": "structure", "fit": "annular",
                                  "limits": {"max_depth_ratio": "0.4", "keep_from_ends_depths": 40,
                                             "keep_from_edges_m": 50, "zone": "middle"},
                                  "conditions": ["a sleeve", 7, ""], "reasoning": "r"}]}
    beam = gid(scene, "Beam B1")
    [r] = hosts.read(Loose(), [hosts.profile(scene, beam)]).values()
    assert r.limits == {"max_depth_ratio": 0.4} and r.conditions == ["a sleeve"]
    agent._try_penetration(scene, {}, gid(scene, "PN-4"), beam, 0.025)          # no TypeError
