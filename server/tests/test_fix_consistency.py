"""Muse's fixes keep the model true too (docs/editing-parity.md, "AI fixes"): each fix kind's trial brings what the
model says besides the shape along with the body (parametric.sync) and is refused with why when it still disagrees, so
Muse hears it; keeping a fix (plans.apply) does the same, all or nothing."""
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element as ue
import numpy as np
import pytest

from sightline import agent, consistency, edits, parametric, plans, quantities
from sightline.fixtures import _box, build_parametric_fixture
from sightline.service import Workspace


@pytest.fixture
def param(tmp_path):
    path = build_parametric_fixture(tmp_path / "param.ifc")
    model = ifcopenshell.open(str(path))   # a column the beam BM1 runs into at its east end (x 4.8 to 5.2)
    body = next(c for c in model.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
    col = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcColumn", name="C9")
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=model.by_type("IfcBuildingStorey")[0], products=[col])
    _box(model, body, col, (0.4, 0.4, 2.0), (4.8, 11.8, 2.0))
    model.write(str(path))
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["param.ifc"])
    scene = ws.scene(sid)
    return ws, sid, scene, {scene.entity(g).Name: g for g in scene.bounds()}


def test_a_fix_trial_keeps_the_axis_true_and_puts_everything_back(param):
    ws, sid, scene, g = param
    before = consistency._axis_points(scene.entity(g["BM1"]), 1.0).tolist()
    was = parametric.snapshot(scene, [g["BM1"]])
    readings = consistency.measure(scene, [g["BM1"]])
    with edits.trial(scene, g["BM1"]):
        edits.stretch(scene, g["BM1"], "end", -0.4)
        assert agent._keeps_true(scene, was, readings, [g["BM1"]], g["BM1"]) is None
        assert consistency._axis_points(scene.entity(g["BM1"]), 1.0).tolist() == [[0.0, 0.0, 0.0], [0.0, 0.0, 4.6]]
    with agent._fix_trial(scene, g["BM1"]) as ft:   # the wrapper the fix kinds use: nothing to refuse here
        edits.stretch(scene, g["BM1"], "end", -0.4)
        ft.made = [g["BM1"]]
    assert ft.why is None and consistency._axis_points(scene.entity(g["BM1"]), 1.0).tolist() == before


def test_a_fix_that_moves_a_joined_wall_off_its_join_is_refused_with_why(param):
    ws, sid, scene, g = param
    attempt, option = agent._try_move(scene, {"title": "slide it west", "delta_m": [-0.3, 0, 0]}, g["W1"], 0.025)
    assert option is None and "join with 'W2' open" in attempt.reason
    attempt, option = agent._try_move(scene, {"title": "lift it", "delta_m": [0, 0, 0.1]}, g["BM2"], 0.025)
    assert option is not None   # a beam with an axis moved whole: nothing to bring along, nothing refused
    with pytest.raises(plans.NotVerified, match="join with 'W2' open"):
        plans.apply(ws, sid, [dict(kind="move", moved=[g["W1"]], delta_m=[-0.3, 0, 0], pair=[g["W1"], g["W2"]])])
    assert not ws.journal(sid).entries


def test_a_kept_trim_of_a_typed_beam_brings_its_axis_and_quantities_along(param):
    ws, sid, scene, g = param
    attempt, option = agent.TRIES["trim"](scene, {"title": "trim the beam to the column"}, g["BM1"], g["C9"], 0.025)
    assert option is not None, attempt.reason
    kept = plans.apply(ws, sid, [{**agent.asdict(option), "pair": [g["BM1"], g["C9"]]}])
    assert kept["entry"] is not None
    beam = scene.entity(g["BM1"])
    axis = consistency._axis_points(beam, 1.0)
    assert np.allclose(axis[1], [0, 0, 4.8], atol=1e-3)      # the beam now stops at the column's west face
    q = ue.get_pset(beam, "Qto_BeamBaseQuantities")
    assert q["Length"] == pytest.approx(quantities.measured(scene, g["BM1"])["Length"], abs=1e-6) == pytest.approx(4.8, abs=1e-3)
    assert ue.get_pset(scene.entity(g["BM2"]), "Qto_BeamBaseQuantities") is None and \
        consistency._axis_points(scene.entity(g["BM2"]), 1.0)[1][2] == pytest.approx(5.0)
