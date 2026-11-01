"""MEP hand edits (docs/editing-parity.md, Tier 2): offset a section up, down or sideways; join two free ends in line
or square with a bend; leave a joint open. Every one keeps the file valid IFC and comes back on undo."""
import ifcopenshell.validate
import numpy as np
import pytest

from sightline import edits, manual
from sightline.fixtures import build_mep_fixture, build_run_fixture
from sightline.service import Workspace


def _open(folder, builder, name):
    builder(folder / name)
    ws = Workspace(samples=folder)
    sid = ws.open([name])
    scene = ws.scene(sid)
    return ws, sid, scene, {scene.entity(g).Name: g for g in scene.bounds()}


@pytest.fixture
def mep(tmp_path):
    return _open(tmp_path, build_mep_fixture, "mep.ifc")


@pytest.fixture
def run(tmp_path):
    ws, sid, scene, _ = _open(tmp_path, build_run_fixture, "run.ifc")
    main = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    return ws, sid, scene, main


def valid(scene) -> list:
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(scene.models[0], log)
    return [s.get("message", "")[:200] for s in log.statements]


def test_an_offset_up_clears_the_beam_with_bends_and_keeps_its_joint(run):
    ws, sid, scene, main = run
    op = {"op": "offset", "element": main, "from": [2.0, 0, 2.8], "to": [4.0, 0, 2.8], "toward": "up", "by_m": 0.4}
    r = manual.check(ws, sid, op, preview=False)
    assert r["blocked"] is None and r["clashes"] == 0 and r["joints"] == []
    assert [c["name"] for c in r["cleared"]] == ["beam 'Transfer beam'"] and "offset up 400 mm" in r["summary"]
    kept = manual.apply(ws, sid, op)
    classes = [scene.entity(g).is_a() for g in kept["pieces"]]
    assert classes.count("IfcDuctFitting") == 4 and len(kept["pieces"]) == 9 and not valid(scene)
    assert scene.element(kept["pieces"][-1]).connected   # the far joint handed on to the last piece
    ws.journal(sid).undo(scene)
    assert edits.run_of(scene, main).length_m == pytest.approx(6.0) and scene.element(main).connected and not valid(scene)


def test_an_offset_goes_sideways_by_compass_or_direction_and_never_along_its_run(run):
    ws, sid, scene, main = run
    base = {"op": "offset", "element": main, "from": [2.0, 0, 2.8], "to": [4.0, 0, 2.8], "by_m": 0.6}
    north = manual.check(ws, sid, {**base, "toward": "north"}, preview=False)
    assert north["blocked"] is None and "offset north 600 mm" in north["summary"]
    assert north["op"]["toward"] == [0.0, 1.0, 0.0]
    assert manual.check(ws, sid, {**base, "toward": [0, -1, 0]}, preview=False)["op"]["toward"] == [0.0, -1.0, 0.0]
    assert "square to its run" in manual.check(ws, sid, {**base, "toward": "east"}, preview=False)["blocked"]
    assert "starts and ends along it" in manual.check(ws, sid, {**base, "toward": "up", "to": [9.0, 0, 2.8]}, preview=False)["blocked"]


def test_only_a_level_flow_segment_is_offset(run):
    ws, sid, scene, main = run
    beam = next(e for e in scene.model.by_type("IfcBeam")).GlobalId
    r = manual.check(ws, sid, {"op": "offset", "element": beam, "from": [3.0, -1, 2.8], "to": [3.0, 1, 2.8],
                               "toward": "up", "by_m": 0.2}, preview=False)
    assert "only a duct, pipe or cable tray" in r["blocked"]


def test_two_ends_on_one_line_join_by_stretching_the_first(mep):
    ws, sid, scene, g = mep
    r = manual.check(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DC"]}}, preview=False)
    assert r["blocked"] is None and "in line (1,500 mm longer)" in r["summary"]
    manual.apply(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DC"]}})
    assert edits.run_of(scene, g["DA"]).length_m == pytest.approx(4.5) and scene.element(g["DA"]).connected == [g["DC"]]
    assert not valid(scene)


def test_two_ends_square_to_each_other_join_with_a_bend_both_ways_and_undo(mep):
    ws, sid, scene, g = mep
    kept = manual.apply(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DB"]}})
    (bend,) = kept["created"]
    assert scene.entity(bend).is_a("IfcDuctFitting") and scene.entity(bend).PredefinedType == "BEND"
    assert sorted(scene.element(bend).connected) == sorted([g["DA"], g["DB"]])
    assert edits.run_of(scene, g["DA"]).length_m == pytest.approx(3.6) and edits.run_of(scene, g["DB"]).length_m == pytest.approx(3.6)
    box = scene.bounds()[bend]
    assert np.allclose(box, [[3.6, -0.2, 2.65], [4.2, 0.4, 2.95]], atol=1e-3) and not valid(scene)
    ws.journal(sid).undo(scene)
    assert not scene.has(bend) and edits.run_of(scene, g["DA"]).length_m == pytest.approx(3.0) and not valid(scene)


def test_a_join_refuses_what_it_cannot_make_in_words(mep):
    ws, sid, scene, g = mep
    assert "one kind" in manual.check(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["PA"]}}, preview=False)["blocked"]
    manual.apply(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DC"]}})
    r = manual.check(ws, sid, {"op": "join", "element": g["DB"], "to": {"element": g["DA"]}}, preview=False)
    assert "already joined" in r["blocked"] or "runs past the corner" in r["blocked"]


def test_a_joint_is_left_open_only_when_kept_with_it(mep):
    ws, sid, scene, g = mep
    manual.apply(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DC"]}})
    op = {"op": "disconnect", "element": g["DA"], "from": g["DC"]}
    r = manual.check(ws, sid, op, preview=False)
    assert r["blocked"] is None and [j["name"] for j in r["joints"]] == ["duct segment 'DC'"]
    with pytest.raises(manual.NotKept, match="1 open joint"):
        manual.apply(ws, sid, op)
    manual.apply(ws, sid, op, accept_joints=1)
    assert scene.element(g["DA"]).connected == [] and not valid(scene)
    assert "not joined to anything" in manual.check(ws, sid, op, preview=False)["blocked"]


def test_an_offset_with_45_degree_bends_climbs_a_slope_and_stays_one_joined_chain(run):
    ws, sid, scene, main = run
    op = {"op": "offset", "element": main, "from": [1.5, 0, 2.8], "to": [4.5, 0, 2.8], "toward": "up", "by_m": 0.4,
          "bend_deg": 45}
    r = manual.check(ws, sid, op, preview=False)
    assert r["blocked"] is None and r["clashes"] == 0 and "with 45° bends" in r["summary"]
    kept = manual.apply(ws, sid, op)
    pcs = kept["pieces"]
    assert [scene.entity(g).is_a() for g in pcs] == ["IfcDuctSegment", "IfcDuctFitting"] * 4 + ["IfcDuctSegment"]
    assert all(pcs[k + 1] in scene.element(pcs[k]).connected for k in range(len(pcs) - 1))
    riser, middle = scene.bounds()[pcs[2]], scene.bounds()[pcs[4]]
    assert riser[1][0] - riser[0][0] > 0.2 and riser[1][2] - riser[0][2] > 0.2        # it runs along and up: a slope
    assert (middle[0][2] + middle[1][2]) / 2 == pytest.approx(3.2, abs=1e-3)          # the middle 400 mm up
    assert sum(edits.run_of(scene, g).length_m for g in pcs if scene.entity(g).is_a("IfcDuctSegment")) < 6.0
    assert not valid(scene)


def test_muse_s_offset_can_ask_for_45_degree_bends_and_keeps_them(run):
    from sightline import agent, plans
    ws, sid, scene, main = run
    beam = scene.model.by_type("IfcBeam")[0].GlobalId
    cand = {"title": "Offset up on a slope", "split_m": [1.5, 4.5], "dz_m": 0.4, "bend_deg": 45}
    attempt, option = agent.TRIES["offset"](scene, cand, main, beam, 0.025)
    assert option is not None, attempt.reason
    assert option.edit == {"bend_deg": 45.0}
    kept = plans.apply(ws, sid, [{**agent.asdict(option), "pair": [main, beam]}])
    (run_pieces,) = kept["pieces"]
    assert len(run_pieces) == 9 and scene.entity(run_pieces[2]).is_a("IfcDuctSegment")
    riser = scene.bounds()[run_pieces[2]]
    assert riser[1][0] - riser[0][0] > 0.2   # kept as tried: up a slope, not a square riser


def test_a_side_pushed_on_its_own_warns_its_end_no_longer_matches_and_carried_adds_a_transition(run):
    from sightline import faces
    ws, sid, scene, main = run
    tail = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag != "SA-1").GlobalId
    north = next(f for f in faces.faces(scene, main) if f.kind == "side" and f.normal[1] > 0.9)
    op = {"op": "push_pull", "element": main, "face": north.id, "by_m": 0.1}
    alone = manual.check(ws, sid, op, preview=False)
    assert any("no longer matches the size of what it joins at its end" in w["text"] for w in alone["warnings"])
    carried = manual.check(ws, sid, {**op, "carry": True}, preview=False)
    assert carried["blocked"] is None and "a transition back to its old size at its end" in carried["summary"]
    kept = manual.apply(ws, sid, {**op, "carry": True})
    (tr,) = kept["created"]
    assert scene.entity(tr).is_a("IfcDuctFitting") and scene.entity(tr).PredefinedType == "TRANSITION"
    assert scene.element(main).connected == [tr] and scene.element(tail).connected == [tr]
    box = scene.bounds()[tr]   # from the new 500 mm (shifted 50 mm north) back to the old 400 mm at x = 6
    assert box[1][0] == pytest.approx(6.0, abs=1e-3) and box[1][1] == pytest.approx(0.3, abs=1e-3)
    assert edits.run_of(scene, main).length_m == pytest.approx(6.0 - 0.1 / np.tan(np.radians(30)), abs=1e-3)
    assert not valid(scene)
    ws.journal(sid).undo(scene)
    assert scene.element(tail).connected == [main] and not scene.has(tr) and not valid(scene)


def test_a_pipe_made_bigger_carried_gets_a_round_transition_to_the_pipe_it_joins(mep):
    ws, sid, scene, g = mep
    kept = manual.apply(ws, sid, {"op": "push_pull", "element": g["PA"], "face": "round side", "by_m": 0.025, "carry": True})
    (tr,) = kept["created"]
    assert scene.entity(tr).is_a("IfcPipeFitting") and scene.element(g["PB"]).connected == [tr]
    box = scene.bounds()[tr]
    assert box[1][1] - box[0][1] == pytest.approx(0.15, abs=0.005)   # 150 mm where it leaves PA, 100 mm at PB
    assert not valid(scene)


# ----------------------------------------------------------------------------------------------------- a carried move re-fits


def _corner_to_a_terminal(ws, sid, scene, g):
    """DA joined to DB with a bend, and DB's far end (4, 4, 2.8) on an air terminal that stays where it is."""
    import ifcopenshell.api
    import ifcopenshell.util.system as us
    from sightline.fixtures import _box
    manual.apply(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DB"]}})
    model = scene.models[0]
    body = next(c for c in model.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
    t = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcAirTerminal", name="AT1")
    _box(model, body, t, (0.6, 0.3, 0.6), (3.7, 4.0, 2.5))
    port = ifcopenshell.api.run("system.add_port", model, element=t)
    m = np.eye(4)
    m[:3, :3] = np.column_stack([(1.0, 0, 0), (0, 0, 1.0), (0, -1.0, 0)])
    m[:3, 3] = (4.0, 4.0, 2.8)
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=port, matrix=m, is_si=True)
    far = max(us.get_ports(scene.entity(g["DB"])), key=lambda p: scene.placement(p.GlobalId)[1, 3])
    ifcopenshell.api.run("system.connect_port", model, port1=far, port2=port, direction="NOTDEFINED")
    scene.refresh_bounds([t.GlobalId])
    return t.GlobalId, port


def test_a_carried_move_re_fits_the_neighbour_square_to_it_instead_of_pulling_the_terminal(mep):
    import ifcopenshell.util.system as us
    ws, sid, scene, g = mep
    terminal, port = _corner_to_a_terminal(ws, sid, scene, g)
    from sightline import connections
    taken = connections.plan_move(scene, [g["DA"]], [0, 0, 0.4])   # as Muse's moves still plan it: taken along
    assert not taken.ok and "AT1" in taken.refused and "stays where it is" in taken.refused
    op = {"op": "move", "element": g["DA"], "delta_m": [0, 0, 0.4], "carry": True}
    r = manual.check(ws, sid, op)
    assert r["blocked"] is None, r["blocked"]
    assert "duct segment 'DB' re-fitted at its start with a pair of bends, the rest where it is" in r["summary"]
    kept = manual.apply(ws, sid, op)
    made = kept["created"]
    assert [scene.entity(p).is_a() for p in made] == ["IfcDuctFitting", "IfcDuctSegment", "IfcDuctFitting", "IfcDuctSegment"]
    assert scene.bounds()[g["DA"]][:, 2] == pytest.approx([3.05, 3.35]), "the main went up 400 mm"
    assert scene.bounds()[g["DB"]][:, 2] == pytest.approx([3.05, 3.35]), "DB's end went with it"
    assert scene.bounds()[made[-1]][:, 2] == pytest.approx([2.65, 2.95]) and scene.bounds()[made[-1]][1][1] == pytest.approx(4.0)
    assert scene.bounds()[terminal][0][2] == pytest.approx(2.5), "the terminal stayed"
    peer = us.get_connected_port(port)
    assert peer is not None and us.get_port_element(peer).GlobalId == made[-1], "still joined, to the piece that stays"
    assert np.linalg.norm(scene.placement(peer.GlobalId)[:3, 3] - scene.placement(port.GlobalId)[:3, 3]) < 1e-6
    assert not valid(scene)
    ws.journal(sid).undo(scene)
    assert all(not scene.has(p) for p in made) and scene.bounds()[g["DB"]][:, 2] == pytest.approx([2.65, 2.95])
    assert us.get_port_element(us.get_connected_port(port)).GlobalId == g["DB"] and not valid(scene)


def test_a_carried_move_still_takes_a_free_ended_neighbour_whole(mep):
    ws, sid, scene, g = mep
    manual.apply(ws, sid, {"op": "join", "element": g["DA"], "to": {"element": g["DB"]}})
    r = manual.check(ws, sid, {"op": "move", "element": g["DA"], "delta_m": [0, 0, 0.4], "carry": True})
    assert r["blocked"] is None and "re-fitted" not in r["summary"] and r["created"] == []
    assert g["DB"] in r["changed"], "nothing beyond it: taken along, no new parts"
