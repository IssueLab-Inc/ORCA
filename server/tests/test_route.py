"""Routes: a stretch of a straight run held at offsets in steps, with 90° bends (edits.apply_route), tried by the
agent, kept by plans and the fix endpoint."""
from pathlib import Path

import ifcopenshell.util.system as system
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import agent, edits, plans, verify
from sightline.agent import Clash, resolve
from sightline.fixtures import build_route_fixture, build_run_fixture
from sightline.scene import IfcScene

COMPOUND = [{"from_m": 1.5, "to_m": 2.4, "up_m": 0.35, "side_m": 0.0},
            {"from_m": 2.4, "to_m": 3.8, "up_m": 0.35, "side_m": 0.55},
            {"from_m": 3.8, "to_m": 4.6, "up_m": 0.35, "side_m": 0.0}]
TWO = [{"from_m": 1.4, "to_m": 2.6, "side_m": 0.45}, {"from_m": 3.4, "to_m": 4.6, "side_m": 0.45}]


@pytest.fixture
def scene(tmp_path) -> IfcScene:
    return IfcScene(build_route_fixture(tmp_path / "route.ifc"))


def by_tag(scene, tag):
    return next(e for e in scene.model.by_type("IfcFlowSegment") if e.Tag == tag).GlobalId


def by_name(scene, name):
    return next(e for e in scene.model.by_type("IfcProduct") if e.Name == name).GlobalId


def check(scene, pieces, obstacles):
    ignore = set(pieces) | {c for g in pieces for c in scene.element(g).connected}
    v = verify.check(scene, pieces[1:-1], ignore=ignore)
    ends = verify.check(scene, [pieces[0], pieces[-1]], ignore=ignore)
    return v.hits + [h for h in ends.hits if h.other in obstacles]


def names(scene, hits):
    return sorted({scene.entity(h.other).Name for h in hits})


def test_one_step_up_is_exactly_the_offset(tmp_path):
    path = build_run_fixture(tmp_path / "run.ifc")
    a, b = IfcScene(path), IfcScene(path)
    main = next(e for e in a.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    off = edits.apply_offset(a, main, 2.6, 3.4, 0.4)
    route = edits.apply_route(b, main, [{"from_m": 2.6, "to_m": 3.4, "up_m": 0.4}])
    assert len(route.pieces) == len(off.pieces) == 9 and route.corners == off.corners == "bends"
    for x, y in zip(edits.meshes(a, off.pieces), edits.meshes(b, route.pieces)):
        assert np.allclose(x["verts"], y["verts"], atol=1e-6) and x["faces"] == y["faces"]


def test_up_then_sideways_clears_where_either_alone_cannot(scene):
    duct, column = by_tag(scene, "RT-1"), by_name(scene, "Column A3")
    with edits.trial(scene, duct):
        up = edits.apply_offset(scene, duct, 1.5, 4.6, 0.35)
        assert names(scene, check(scene, up.pieces, {column})) == ["Column A3"]
    with edits.trial(scene, duct):
        side = edits.apply_route(scene, duct, [{"from_m": 2.4, "to_m": 3.8, "side_m": 0.55}])
        assert "Plinth" in names(scene, check(scene, side.pieces, {column}))
    with edits.trial(scene, duct):
        route = edits.apply_route(scene, duct, COMPOUND)
        assert route.corners == "bends" and not check(scene, route.pieces, {column})
        assert len(route.pieces) == 1 + 4 * 4  # first, then per change: bend, riser, bend, straight


def test_a_kept_route_is_one_chain_port_to_port_ending_on_the_far_segment(scene):
    duct, far = by_tag(scene, "RT-1"), by_tag(scene, "RT-1E")
    route = edits.apply_route(scene, duct, COMPOUND)
    chain = [scene.entity(g) for g in route.pieces]
    assert chain[0].GlobalId == duct
    for x, y in zip(chain, chain[1:]):
        ends = {system.get_connected_port(p) for p in system.get_ports(x)}
        assert ends & set(system.get_ports(y)), (x.Name, y.Name)
    last = {system.get_connected_port(p) for p in system.get_ports(chain[-1])}
    assert last & set(system.get_ports(scene.entity(far)))
    assert {e.is_a() for e in chain} == {"IfcDuctSegment", "IfcDuctFitting"}


def test_one_detour_round_each_column_clears_one_long_detour_hits_the_post(scene):
    duct = by_tag(scene, "RT-2")
    columns = {by_name(scene, "Column B2"), by_name(scene, "Column B4")}
    with edits.trial(scene, duct):
        long = edits.apply_route(scene, duct, [{"from_m": 1.4, "to_m": 4.6, "side_m": 0.45}])
        assert names(scene, check(scene, long.pieces, columns)) == ["Post P1"]
    with edits.trial(scene, duct):
        two = edits.apply_route(scene, duct, TWO)
        assert not check(scene, two.pieces, columns)
    # Muse is told the room past each column; past both at once, only further out than the post.
    room = edits.free_bands(scene, duct, [by_name(scene, "Column B2")], "side")
    assert any(b["from_m"] <= 0.45 <= b["to_m"] for b in room)
    both = edits.free_bands(scene, duct, sorted(columns), "side")
    assert not any(b["from_m"] <= 0.45 <= b["to_m"] for b in both)
    assert any(b["from_m"] >= 0.6 for b in both)  # north of the post
    text = agent._describe(scene, Clash(duct, by_name(scene, "Column B2"), others=[by_name(scene, "Column B4")]))
    assert "Room past the other element for element A: side offsets (+ is north, - south)" in text
    assert "also runs into IfcColumn 'Column B4' at 3.80-4.20 m along it" in text


def test_a_sloped_duct_keeps_its_fall_on_every_piece_along_it(scene):
    duct, column = by_tag(scene, "RT-3"), by_name(scene, "Column C3")
    d = np.asarray(edits.run_of(scene, duct).direction)
    assert d[2] < 0  # it falls
    route = edits.apply_route(scene, duct, [{"from_m": 2.4, "to_m": 3.8, "side_m": 0.45}])
    assert not check(scene, route.pieces, {column})
    along = [edits.run_of(scene, g) for g in route.pieces if scene.entity(g).is_a("IfcDuctSegment")]
    parallel = [r for r in along if abs(np.dot(r.direction, d)) > 0.5]
    assert len(parallel) == 3 and all(np.allclose(r.direction, d, atol=1e-6) for r in parallel)


def test_drainage_only_steps_sideways(scene):
    pipe, column = by_tag(scene, "RT-4"), by_name(scene, "Column D3")
    assert edits.is_gravity(scene.entity(pipe))
    with pytest.raises(edits.Unsupported, match="drainage cannot step up or down"):
        edits.apply_route(scene, pipe, [{"from_m": 2.4, "to_m": 3.8, "up_m": 0.3}])
    with edits.trial(scene, pipe):
        route = edits.apply_route(scene, pipe, [{"from_m": 2.4, "to_m": 3.8, "side_m": 0.25}])
        assert not check(scene, route.pieces, {column})


def test_a_round_pipe_takes_a_rolling_offset(scene):
    pipe, column = by_tag(scene, "RT-5"), by_name(scene, "Column E3")
    with edits.trial(scene, pipe):
        route = edits.apply_route(scene, pipe, [{"from_m": 2.4, "to_m": 3.8, "up_m": 0.2, "side_m": 0.25}])
        assert route.corners == "bends" and not check(scene, route.pieces, {column})
        assert scene.entity(route.pieces[2]).is_a("IfcPipeSegment")  # the riser runs on the diagonal
        d = edits.run_of(scene, route.pieces[2]).direction
        assert d[2] == pytest.approx(0.2 / np.hypot(0.2, 0.25)) and d[1] == pytest.approx(0.25 / np.hypot(0.2, 0.25))


@pytest.mark.parametrize("steps, why", [
    ([{"from_m": 2.4, "to_m": 3.8, "up_m": 0.35, "side_m": 0.55}], "change one axis at a time"),
    ([{"from_m": 1.0, "to_m": 3.0, "up_m": 0.4}, {"from_m": 2.5, "to_m": 4.0, "side_m": 0.5}], "overlap"),
    ([{"from_m": 2.0, "to_m": 6.5, "up_m": 0.4}], "inside the run"),
    ([{"from_m": 2.0, "to_m": 3.0}], "must go up, down or sideways"),
    ([{"from_m": 0.1, "to_m": 3.0, "up_m": 0.4}], "shorter than 50 mm"),
    ([{"from_m": 1, "to_m": 1.5, "up_m": 0.4}, {"from_m": 2, "to_m": 2.5, "up_m": 0.4},
      {"from_m": 3, "to_m": 3.5, "up_m": 0.4}, {"from_m": 4, "to_m": 4.5, "up_m": 0.4}], "at most 3 steps"),
    ("up 400", "needs steps"),
])
def test_bad_steps_are_refused_with_reasons(scene, steps, why):
    with pytest.raises(edits.Unsupported, match=why):
        with edits.trial(scene, by_tag(scene, "RT-1")):
            edits.apply_route(scene, by_tag(scene, "RT-1"), steps)


def test_a_trial_route_is_undone(scene):
    before = len(scene.model.by_type("IfcProduct"))
    with edits.trial(scene, by_tag(scene, "RT-1")):
        edits.apply_route(scene, by_tag(scene, "RT-1"), COMPOUND)
        assert len(scene.model.by_type("IfcProduct")) > before
    assert len(scene.model.by_type("IfcProduct")) == before


class Scripted:
    def __init__(self, *rounds):
        self.rounds, self.calls = list(rounds), []

    def complete_json(self, system, text, images=None):
        self.calls.append(text)
        return self.rounds[min(len(self.calls), len(self.rounds)) - 1]


def test_the_agent_offers_a_verified_route_after_offsets_fail(scene):
    duct, column = by_tag(scene, "RT-1"), by_name(scene, "Column A3")
    model = Scripted({"candidates": [{"title": "Offset up 350", "kind": "offset", "move": "A",
                                      "split_m": [1.5, 4.6], "dz_m": 0.35}]},
                     {"candidates": [{"title": "Up and over the plinth", "kind": "route", "move": "A",
                                      "steps": COMPOUND}]})
    result = resolve(scene, Clash(duct, column), model, max_rounds=2)
    assert [a.passed for a in result.attempts] == [False, True]
    o = result.options[0]
    assert o.kind == "route" and o.edit["summary"].startswith("reroute 350 mm up at 1.50-2.40 m")
    assert "550 mm north" in o.edit["summary"] and o.preview and len(o.preview) == 17
    assert o.delta_m == pytest.approx([0, 0.55, 0.35])
    assert "occupies 3.00-3.20 m along it" in model.calls[0]
    assert "Offset up 350" in model.calls[1] and "at [" in model.calls[1]  # what it hit, and where


def test_a_one_step_route_straight_up_is_tried_as_an_offset(scene):
    duct, column = by_tag(scene, "RT-1"), by_name(scene, "Column A3")
    attempt, _ = agent._try_route(scene, {"steps": [{"from_m": 1.5, "to_m": 4.6, "up_m": 0.35}]}, duct, column, 0.025)
    assert attempt.kind == "offset"


def test_the_endpoint_and_a_plan_keep_a_route(tmp_path, monkeypatch):
    from sightline import app as app_module
    from sightline.service import Workspace
    path = build_route_fixture(tmp_path / "samples" / "route.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    duct, column = by_tag(scene, "RT-2"), by_name(scene, "Column B2")
    option = {"title": "Round both columns", "kind": "route", "moved": [duct], "delta_m": [0, 0.45, 0],
              "edit": {"steps": TWO, "summary": "reroute"}, "pair": [duct, column], "others": [by_name(scene, "Column B4")]}
    item = plans.Item(f"{duct}|{column}", duct, column, "pair", [], option=option, others=[by_name(scene, "Column B4")])
    assert plans.verify_together(ws, sid, [item])["passed"]
    monkeypatch.setattr(app_module, "ws", ws)
    r = TestClient(app_module.app).post(f"/api/scenes/{sid}/fix/apply", json={"option": option})
    assert r.status_code == 200, r.text
    assert r.json()["pieces"][0] == duct and len(r.json()["pieces"]) == 17
    assert not verify.check(scene, r.json()["pieces"][1:-1], ignore=set(r.json()["pieces"])).hits


def test_a_single_proposal_hears_of_the_runs_other_clash_nearby(tmp_path):
    from sightline.service import Workspace
    path = build_route_fixture(tmp_path / "samples" / "route.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    duct, b2, b4 = by_tag(scene, "RT-2"), by_name(scene, "Column B2"), by_name(scene, "Column B4")
    report = ws.report(ws.detect(sid)["report"]["id"])
    c = next(c for c in report.clashes if {c.a.global_id, c.b.global_id} == {duct, b2})
    clash = ws.clash_for(c.a.global_id, c.b.global_id, None, None, "", report.id, c.id, sid)
    assert clash.nearby == {duct: [b4]}
    text = agent._describe(scene, clash)
    assert "also clashes nearby with IfcColumn 'Column B4' at 3.80-4.20 m along it" in text
    # The fixed side's other clashes are not this fix's: a column's other partners are never named.
    assert all(not scene.stays(g) for g in [duct]) and b2 not in clash.nearby.get(duct, [])


def test_a_single_step_on_a_sloped_run_or_drainage_keeps_the_routes_own_rules(scene):
    sloped, col = by_tag(scene, "RT-3"), by_name(scene, "Column C3")
    attempt, _ = agent._try_route(scene, {"steps": [{"from_m": 2.4, "to_m": 3.8, "up_m": -0.5}]}, sloped, col, 0.025)
    assert attempt.kind == "route" and "not horizontal" not in attempt.reason   # built by apply_route, keeping its fall
    waste, col_d = by_tag(scene, "RT-4"), by_name(scene, "Column D3")
    attempt, _ = agent._try_route(scene, {"steps": [{"from_m": 2.4, "to_m": 3.8, "up_m": 0.3}]}, waste, col_d, 0.025)
    assert attempt.kind == "route" and "drainage cannot step up or down" in attempt.reason


def test_coming_back_on_both_axes_at_once_says_how_to_come_back(scene):
    duct = by_tag(scene, "RT-1")
    with pytest.raises(edits.Unsupported, match="comes back to its line up and sideways at once"):
        edits.apply_route(scene, duct, [{"from_m": 1.5, "to_m": 2.4, "up_m": 0.35},
                                        {"from_m": 2.4, "to_m": 4.6, "up_m": 0.35, "side_m": 0.55}])


def test_the_room_beside_a_dense_mesh_is_scanned_in_time(tmp_path):
    import time
    import ifcopenshell
    import ifcopenshell.api
    path = build_route_fixture(tmp_path / "dense.ifc")
    m = ifcopenshell.open(str(path))
    body = next(c for c in m.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
    panel = ifcopenshell.api.run("root.create_entity", m, ifc_class="IfcBuildingElementProxy", name="Dense panel")
    ifcopenshell.api.run("spatial.assign_container", m, relating_structure=m.by_type("IfcBuildingStorey")[0], products=[panel])
    n = 60   # 7,200 triangles, in RT-2's stretch beside the run (the old scan took about 13 s)
    xs, zs = np.linspace(2.5, 3.5, n + 1), np.linspace(2.5, 3.1, n + 1)
    pts = [(float(x), 5.55 + 0.01 * float(np.sin(7 * x + 5 * z)), float(z)) for z in zs for x in xs]
    faces = [f for j in range(n) for i in range(n) for p in [j * (n + 1) + i + 1]
             for f in ((p, p + 1, p + n + 2), (p, p + n + 2, p + n + 1))]
    item = m.createIfcTriangulatedFaceSet(m.createIfcCartesianPointList3D(pts), None, None, faces, None)
    panel.Representation = m.createIfcProductDefinitionShape(None, None, [m.createIfcShapeRepresentation(
        body, "Body", "Tessellation", [item])])
    ifcopenshell.api.run("geometry.edit_object_placement", m, product=panel)
    m.write(str(path))
    s = IfcScene(path)
    s.bounds()
    duct, b2, b4 = by_tag(s, "RT-2"), by_name(s, "Column B2"), by_name(s, "Column B4")
    t0 = time.perf_counter()
    bands = edits.free_bands(s, duct, [b2, b4], "side")
    assert time.perf_counter() - t0 < 5
    assert not [b for b in bands if b["from_m"] <= 0.55 <= b["to_m"]]   # the panel's offset is not free


def test_nearby_clashes_are_each_sides_own_and_near_where_they_meet(tmp_path):
    from types import SimpleNamespace as NS
    from sightline.service import Workspace
    box = lambda x0, x1, y0, y1: np.array([[x0, y0, 0.0], [x1, y1, 1.0]])
    boxes = {"duct": box(0, 14, -0.2, 0.2), "pipe": box(0.9, 1.1, -3, 3), "wall": box(0.8, 1.2, 2, 2.5)}
    boxes.update({f"beam{x}": box(x - 0.1, x + 0.1, -1, 1) for x in (1, 2.5, 6, 9, 12.5)})
    fixed = {g: g.startswith(("beam", "wall")) for g in boxes}
    scene = NS(bounds=lambda: boxes, element=lambda g: NS(fixed=fixed[g]), stays=lambda g: fixed[g])
    side = lambda g, cls="IfcBeam": NS(global_id=g, ifc_class=cls)
    clashes = [NS(a=side("duct", "IfcDuctSegment"), b=side(f"beam{x}"), distance_m=-0.05) for x in (1, 2.5, 6, 9, 12.5)]
    clashes += [NS(a=side("duct", "IfcDuctSegment"), b=side("pipe", "IfcPipeSegment"), distance_m=-0.02),
                NS(a=side("pipe", "IfcPipeSegment"), b=side("wall", "IfcWall"), distance_m=-0.1)]
    ws = Workspace(tmp_path)
    ws.scenes["s"] = scene
    # On duct x beam@1: the pipe crossing right there, then beam@2.5; beams at 6, 9 and 12.5 m are too far away.
    assert ws._nearby("s", NS(clashes=clashes), "duct", "beam1") == {"duct": ["pipe", "beam2.5"]}
    # On duct x pipe (both movable): each side hears of its own partners only.
    near = ws._nearby("s", NS(clashes=clashes), "duct", "pipe")
    assert near["pipe"] == ["wall"] and "wall" not in near["duct"] and near["duct"][0] == "beam1"
