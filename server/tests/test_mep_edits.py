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
