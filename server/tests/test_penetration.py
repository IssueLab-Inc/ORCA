"""Penetrations: an opening asked for where a straight service crosses a wall or slab (edits.penetration), tried by
the agent with the opening cut, kept as a provision for void and, when the requirements allow, the opening itself."""
from pathlib import Path

import ifcopenshell.util.element as element_util
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import agent, detect, edits, plans, requirements as req, verify
from sightline.agent import Clash, resolve
from sightline.fixtures import build_penetration_fixture
from sightline.scene import IfcScene, is_provision
from sightline.service import Workspace


@pytest.fixture
def scene(tmp_path) -> IfcScene:
    return IfcScene(build_penetration_fixture(tmp_path))


def gid(scene, name_or_tag):
    return next(e.GlobalId for m in scene.models for e in m.by_type("IfcElement")
                if name_or_tag in (e.Name, getattr(e, "Tag", None)))


def hits_on(scene, service, host, clearance_m=0.025):
    return [h for h in verify.check(scene, [service], clearance_m=clearance_m).hits if h.other == host]


def test_the_opening_is_the_section_plus_the_clearance_and_5_mm_all_round_through_the_whole_depth(scene):
    pipe = edits.penetration(scene, gid(scene, "PN-1"), gid(scene, "Wall W1 partition"), 0.025)
    assert (pipe.shape, pipe.width_m) == ("round", 0.17)        # 110 + 2 x (25 + 5) = 170
    assert pipe.depth_m == pytest.approx(0.22) and pipe.start == pytest.approx([1.99, 0, 2.0])  # 200 + 10 proud each face
    duct = edits.penetration(scene, gid(scene, "PN-2"), gid(scene, "Wall W1 partition"), 0.05)
    assert (duct.shape, duct.width_m, duct.height_m) == ("rect", 0.51, 0.41)  # 400 x 300 + 2 x 55, to the 10 mm
    riser = edits.penetration(scene, gid(scene, "PN-3"), gid(scene, "Slab S1"), 0.025)
    assert riser.axis == pytest.approx([0, 0, 1]) and riser.start == pytest.approx([5, 5, 3.39])
    assert edits.size_text(duct) == "510 x 410 mm" and edits.size_text(pipe) == "Ø170 mm"


@pytest.mark.parametrize("tag, host, why", [
    ("PN-4", "Beam B1", "beam's openings are the structural engineer's"),
    ("PN-5", "Column C1", "column is never cut"),
    ("PN-6", "Wall W1 partition", "break out of its edge above"),
    ("PN-1", "Wall W2 core", "does not reach it"),
    ("PN-4", "Wall W1 partition", "does not pass through it"),
])
def test_beams_columns_and_holes_at_an_edge_are_refused(scene, tag, host, why):
    with pytest.raises(edits.Unsupported, match=why):
        edits.penetration(scene, gid(scene, tag), gid(scene, host))


def test_cut_in_a_trial_the_service_clears_the_wall_and_both_files_are_undone(scene):
    pipe, wall = gid(scene, "PN-1"), gid(scene, "Wall W1 partition")
    assert hits_on(scene, pipe, wall)
    counts = [len(m.by_type("IfcRoot")) for m in scene.models]
    pen = edits.penetration(scene, pipe, wall)
    with edits.trial_files(scene, {0, 1}):
        edits.apply_penetration(scene, pen, cut=True)
        assert not hits_on(scene, pipe, wall)
        pfv, opening = scene.entity(pen.provision), scene.entity(pen.opening)
        assert scene.index_of(pen.provision) == 1 and scene.index_of(pen.opening) == 0   # services, structure
        assert is_provision(pfv) and pfv.PredefinedType == "PROVISIONFORVOID"
        assert opening.VoidsElements[0].RelatingBuildingElement.GlobalId == wall
        pset = element_util.get_psets(pfv)["Pset_ProvisionForVoid"]
        assert (pset["Shape"], pset["Diameter"], pset["Depth"]) == ("Round", pytest.approx(0.17), pytest.approx(0.22))
        drawn = edits.meshes(scene, [pen.provision], render=True)[0]
        assert drawn["color"] == pytest.approx([*edits.PFV_COLOUR, edits.PFV_ALPHA])
    assert [len(m.by_type("IfcRoot")) for m in scene.models] == counts and hits_on(scene, pipe, wall)


def test_a_provision_for_void_is_never_physical(scene):
    pipe, wall = gid(scene, "PN-1"), gid(scene, "Wall W1 partition")
    pairs = lambda: sorted(tuple(sorted((c.a.global_id, c.b.global_id))) for c in detect.run(scene).report.clashes)
    found = pairs()
    pen = edits.apply_penetration(scene, edits.penetration(scene, pipe, wall), cut=False)
    assert pen.opening is None and hits_on(scene, pipe, wall)       # asked for, not cut: the clash stays
    assert pen.provision not in {p.GlobalId for p in scene.products()}
    scene.refresh_bounds([pen.provision])
    assert pen.provision not in scene.bounds()
    assert pen.provision not in {h.other for h in verify.check(scene, [pipe]).hits}
    assert pairs() == found and (min(pipe, wall), max(pipe, wall)) in found


def test_the_agent_offers_a_penetration_when_the_wall_leaves_no_way_round(scene):
    pipe, wall = gid(scene, "PN-1"), gid(scene, "Wall W1 partition")

    class Muse:
        calls = []

        def complete_json(self, system, text, images=None):
            self.calls.append(text)
            return {"candidates": [{"title": "Offset over the wall", "kind": "offset", "move": "A",
                                    "split_m": [1.6, 2.6], "dz_m": 0.5},
                                   {"title": "Opening through W1", "kind": "penetration", "move": "B"}]}
    model = Muse()
    result = resolve(scene, Clash(pipe, wall), model, max_rounds=2)
    assert 'A "penetration" (move: "A") asks for a Ø170 mm opening' in model.calls[0]
    assert "it needs fire-stopping to the host's EI 60 rating" in model.calls[0]
    assert "is a straight segment from [2.0" not in model.calls[0]   # a wall is never offered as a run to split
    o = next(o for o in result.options if o.kind == "penetration")
    assert o.moved == [wall] and o.edit["service"] == pipe and o.edit["host"] == wall    # "move": "B" named the wall
    assert o.review == "architecture" and "fire-stopping to the host's EI 60 rating" in o.also_needs
    assert o.edit["summary"] == "Ø170 mm opening through Wall 'Wall W1 partition'"
    assert len(o.preview) == 2 and o.min_clearance_m >= 0.025
    assert len(model.calls) == 2   # a penetration alone does not end the search: one more round for a plain fix


def test_a_slab_or_a_load_bearing_wall_needs_the_structural_engineer(scene):
    for tag, host in (("PN-3", "Slab S1"), ("PN-7", "Wall W2 core")):
        attempt, option = agent._try_penetration(scene, {}, gid(scene, tag), gid(scene, host), 0.025)
        assert attempt.passed and option.review == "structure", attempt.reason


def test_plain_fixes_rank_before_a_penetration(scene):
    assert agent.tier("penetration") > agent.tier("resize") > agent.tier("route") == 0


def doc_locking(scene, group_role: str):
    d = req.default_doc(scene).to_dict()
    for row in d["who_moves"]:
        group = next(g for g in d["groups"] if g["id"] == row["group"])
        if group["role"] == group_role:
            row.update(edits="none")
    return req.parse(d)


def workspace(tmp_path):
    paths = build_penetration_fixture(tmp_path / "samples")
    ws = Workspace(paths[0].parent)
    sid = ws.open([p.name for p in paths])
    return ws, sid, ws.scene(sid)


def test_kept_the_opening_is_cut_unless_the_requirements_lock_the_host(tmp_path):
    ws, sid, scene = workspace(tmp_path)
    pipe, wall, duct = gid(scene, "PN-1"), gid(scene, "Wall W1 partition"), gid(scene, "PN-2")
    r = ws.apply_penetration(sid, pipe, wall)
    assert r["cut"] and r["files"] == [0, 1] and set(r["changed"]) == {r["provision"], wall}
    assert not hits_on(scene, pipe, wall) and scene._edited == {0, 1}
    token = req.enter(req.register(doc_locking(scene, "structure")))
    try:
        settings = ws.fix_settings(sid, duct, wall)
        assert settings["policy"][wall].edits == "none" and settings["policy"][duct].edits == "any"
        r = ws.apply_penetration(sid, duct, wall)
    finally:
        req.leave(token)
    assert not r["cut"] and r["opening"] is None and r["files"] == [1] and r["changed"] == [r["provision"]]
    assert "may not be edited: its team cuts the opening" in r["blocked_by"]
    assert hits_on(scene, duct, wall)   # still clashing until that team cuts it


def test_requirements_let_a_penetration_through_where_only_moves_are_allowed(tmp_path):
    ws, sid, scene = workspace(tmp_path)
    pipe, wall = gid(scene, "PN-1"), gid(scene, "Wall W1 partition")
    d = req.default_doc(scene).to_dict()
    for row in d["who_moves"]:
        row.update(edits="move")
    doc = req.parse(d)
    m = req.Matcher(scene, doc)
    service, host = req.policy(doc, m, pipe), req.policy(doc, m, wall)
    assert req.blocked(service, host, "penetration", [0, 0, 0], False) is None
    assert "may only be moved whole" in req.blocked(service, host, "offset", [0, 0, 0.1], False)
    assert any("provision for void only" in x for x in req.meets(doc, service, host, 0.025, 0.03, [0, 0, 0], "penetration"))
    locked = req.parse({**d, "who_moves": [{**row, "edits": "none"} for row in d["who_moves"]]})
    assert "may not be edited" in req.blocked(req.policy(locked, req.Matcher(scene, locked), pipe), host, "penetration",
                                              [0, 0, 0], False)


def test_the_endpoint_a_plan_and_the_page_patch_keep_a_penetration(tmp_path, monkeypatch):
    from sightline import app as app_module
    ws, sid, scene = workspace(tmp_path)
    pipe, wall, riser, slab = gid(scene, "PN-1"), gid(scene, "Wall W1 partition"), gid(scene, "PN-3"), gid(scene, "Slab S1")
    _, option = agent._try_penetration(scene, {"title": "Opening through W1"}, pipe, wall, 0.025)
    _, through_slab = agent._try_penetration(scene, {"title": "Sleeve through S1"}, riser, slab, 0.025)
    items = [plans.Item(f"{pipe}|{wall}", pipe, wall, "pair", [], option=plans.asdict(option)),
             plans.Item(f"{riser}|{slab}", riser, slab, "pair", [], option=plans.asdict(through_slab))]
    assert plans.option_files(scene, items[0].option) == {0, 1}
    check = plans.verify_together(ws, sid, items)
    assert check["passed"], check
    monkeypatch.setattr(app_module, "ws", ws)
    body = {k: v for k, v in plans.asdict(option).items()}
    r = TestClient(app_module.app).post(f"/api/scenes/{sid}/fix/apply", json={"option": body})
    assert r.status_code == 200, r.text
    out = r.json()
    assert "cut" not in out and out["pieces"] == [] and out["revision"] == out["revision_before"] + 1
    drawn = {m["global_id"]: m for m in out["meshes"]}
    assert set(drawn) == set(out["changed"]) and wall in drawn
    provision = next(g for g in drawn if g != wall)
    assert drawn[provision]["color"][3] == pytest.approx(edits.PFV_ALPHA) and drawn[provision]["file"] == 1
    assert not hits_on(scene, pipe, wall)


def test_ifc2x3_takes_a_provision_for_void_by_its_object_type(tmp_path):
    scene = IfcScene(build_penetration_fixture(tmp_path, "IFC2X3"))
    pipe, wall = gid(scene, "PN-1"), gid(scene, "Wall W1 partition")
    pen = edits.penetration(scene, pipe, wall)
    with edits.trial_files(scene, {0, 1}):
        edits.apply_penetration(scene, pen, cut=True)
        pfv = scene.entity(pen.provision)
        assert pfv.ObjectType == "ProvisionForVoid" and is_provision(pfv) and pfv.OwnerHistory is not None
        assert not hits_on(scene, pipe, wall)
