"""Every hand edit on every construct real exports carry (docs/editing-parity.md, "Test matrix").

Each cell is kept and then the whole model is read again: what it says besides the shape still matches every body (layer
sets, material profiles, axes, path joins, base quantities), and nothing but the edited element changed (the other
wall, beam and fitting of its type, the type's maps, the sets they share).
"""
import ifcopenshell.util.element as ue
import ifcopenshell.validate
import pytest

from sightline import consistency, manual, quantities
from sightline.fixtures import build_parametric_fixture
from sightline.service import Workspace


def open_fixture(folder):
    build_parametric_fixture(folder / "param.ifc")
    ws = Workspace(samples=folder)
    sid = ws.open(["param.ifc"])
    scene = ws.scene(sid)
    return ws, sid, scene, {scene.entity(g).Name: g for g in scene.bounds()}


@pytest.fixture
def param(tmp_path):
    return open_fixture(tmp_path)


def untouched(scene, g, edited: str) -> dict:
    """What every element but the edited one says about itself (its type, its set, its body), to compare after."""
    out = {}
    for name, gid in g.items():
        if name == edited or not scene.has(gid):
            continue
        e = scene.entity(gid)
        rtype, mat = ue.get_type(e), ue.get_material(e, should_skip_usage=False)
        out[name] = (rtype.Name if rtype else None, str(consistency._material_set(mat)) if mat else None,
                     [str(x) for x in scene.models[0].traverse(e.Representation)] if e.Representation else None,
                     [str(x) for m in (rtype.RepresentationMaps or []) for x in scene.models[0].traverse(m)] if rtype else None)
    return out


def assert_consistent(scene):
    """Every element's data matches its body: layers, profiles and axes read zero; joins meet; quantities measured;
    and the file is valid IFC (no shape left without its product, every inverse the schema asks for)."""
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(scene.models[0], log)
    assert not log.statements, [s.get("message", "")[:200] for s in log.statements[:3]]
    readings = consistency.measure(scene, list(scene.bounds()))
    for (gid, rule, *_), r in readings.items():
        name = scene.entity(gid).Name
        if rule == "layers":
            assert abs(r.values[0]) <= consistency.LENGTH_TOL_M, (name, r.words)
        elif rule == "profile":
            assert all(abs(x) <= consistency.LENGTH_TOL_M for x in r.values), (name, r.values)
        elif rule == "axis":
            assert all(abs(x) <= consistency.LENGTH_TOL_M for x in r.values), (name, r.words)
        elif rule == "joins":
            assert r.values[0] <= consistency.JOIN_TOL_M, (name, r.values)
    for gid in scene.bounds():
        got = quantities.measured(scene, gid)
        for q, values in quantities.base_sets(scene.entity(gid)).items():
            for n, v in values.items():
                if n != "id" and got and n in got:
                    assert v == pytest.approx(got[n], rel=1e-6, abs=1e-9), (scene.entity(gid).Name, q, n)


OPEN = "open"
MATRIX = [
    # (cell, op without its element, element, the joints it leaves open)
    ("wall height", {"op": "push_pull", "face": "top", "by_m": 0.2}, "W1", 0),
    ("wall thickness, north", {"op": "push_pull", "face": "north face", "by_m": 0.05}, "W1", 0),
    ("wall thickness, south", {"op": "push_pull", "face": "south face", "by_m": 0.02}, "W1", 0),
    ("wall length", {"op": "push_pull", "face": "west end", "by_m": 0.3}, "W1", 0),
    ("wall moved up", {"op": "move", "delta_m": [0, 0, 0.1]}, "W1", 0),
    ("wall moved off its join", {"op": "move", "delta_m": [-0.2, 0, 0]}, "W1", 1),
    ("wall void", {"op": "void", "face": "north face", "at": [2.0, 0.25, 1.5], "shape": "rect", "width_m": 0.4,
                   "height_m": 0.4}, "W1", 0),
    ("wall split", {"op": "split", "at": [2.0, 0.1, 1.5]}, "W1", 0),
    ("wall deleted", {"op": "delete"}, "W1", 0),
    ("slab thickness", {"op": "push_pull", "face": "top", "by_m": 0.05}, "SL1", 0),
    ("slab size", {"op": "push_pull", "face": "east end", "by_m": 0.5}, "SL1", 0),
    ("slab moved", {"op": "move", "delta_m": [0, 0, 0.1]}, "SL1", 0),
    ("slab split", {"op": "split", "at": [3.0, 7.0, 3.1]}, "SL1", 0),
    ("beam length", {"op": "push_pull", "face": "east end", "by_m": 0.5}, "BM1", 0),
    ("beam section", {"op": "push_pull", "face": "top", "by_m": 0.05}, "BM1", 0),
    ("beam moved", {"op": "move", "delta_m": [0, 0, 0.1]}, "BM1", 0),
    ("beam split", {"op": "split", "at": [2.5, 12.0, 3.0]}, "BM1", 0),
    ("beam section removed", {"op": "remove_section", "from": [1.0, 12.0, 3.0], "to": [2.0, 12.0, 3.0]}, "BM1", 0),
    ("mapped fitting pushed", {"op": "push_pull", "face": "top", "by_m": 0.1}, "F1", 0),
    ("turned mapped fitting pushed", {"op": "push_pull", "face": "north end", "by_m": 0.1}, "F2", 0),
    ("mapped fitting moved", {"op": "move", "delta_m": [0, 0, 0.1]}, "F1", 0),
    ("mapped fitting clipped", {"op": "clip", "to": {"point": [10.3, 0.2, 1.15], "normal": [1, 0, 0]}, "gap_m": 0.0},
     "F1", 0),
    ("mapped fitting split", {"op": "split", "at": [10.3, 0.2, 1.15]}, "F1", 0),
    ("mapped fitting deleted", {"op": "delete"}, "F1", 0),
]


@pytest.mark.parametrize("cell,op,name,joints", MATRIX, ids=[m[0] for m in MATRIX])
def test_every_kept_edit_leaves_the_model_consistent_and_the_rest_as_it_was(param, cell, op, name, joints):
    ws, sid, scene, g = param
    others = untouched(scene, g, name)
    r = manual.check(ws, sid, {**op, "element": g[name]}, preview=False)
    assert r["blocked"] is None, r["blocked"]
    assert len(r["joints"]) == joints and not [w for w in r["warnings"] if w["rule"] in ("quantities", "layers")]
    manual.apply(ws, sid, {**op, "element": g[name]}, accept_joints=joints)
    assert_consistent(scene)
    assert untouched(scene, g, name) == others


def test_a_thicker_wall_gets_its_own_type_and_the_layer_on_the_pushed_face_grows(param):
    ws, sid, scene, g = param
    kept = manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "north face", "by_m": 0.05})
    assert "own type WT-250 (ORCA)" in kept["entry"]["summary"] and "layers of wall 'W1'" in kept["entry"]["summary"]
    usage = ue.get_material(scene.entity(g["W1"]))
    assert [round(l.LayerThickness, 3) for l in usage.ForLayerSet.MaterialLayers] == [0.015, 0.2, 0.085]
    assert ue.get_type(scene.entity(g["W2"])).Name == "WT-250"
    assert [round(l.LayerThickness, 3) for l in ue.get_material(scene.entity(g["W2"])).ForLayerSet.MaterialLayers] == [0.015, 0.2, 0.035]
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "south face", "by_m": 0.02})
    usage = ue.get_material(scene.entity(g["W1"]))   # pushed out on the other side: the first layer, and the reference line held
    assert [round(l.LayerThickness, 3) for l in usage.ForLayerSet.MaterialLayers] == [0.035, 0.2, 0.085]
    assert usage.OffsetFromReferenceLine == pytest.approx(-0.02) and ue.get_type(scene.entity(g["W1"])).Name == "WT-250 (ORCA)"
    with pytest.raises(manual.NotKept, match="Plaster layer"):
        manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "south face", "by_m": -0.04})


def test_a_split_wall_hands_its_join_to_the_piece_that_holds_its_end(param):
    ws, sid, scene, g = param
    kept = manual.apply(ws, sid, {"op": "split", "element": g["W1"], "at": [2.0, 0.1, 1.5]})
    (rel,) = scene.models[0].by_type("IfcRelConnectsPathElements")
    assert rel.RelatingElement.Name == "W1 (part 2)" and rel.RelatedElement.Name == "W2" and "its join now at" in kept["entry"]["summary"]
    assert consistency._axis_points(rel.RelatingElement, 1.0).tolist() == [[2.0, 0.0, 0.0], [4.0, 0.0, 0.0]]


def test_a_wall_moved_off_its_join_leaves_it_open_only_when_said_and_undo_brings_it_back(param):
    ws, sid, scene, g = param
    op = {"op": "move", "element": g["W2"], "delta_m": [0.5, 0, 0]}
    with pytest.raises(manual.NotKept, match="1 open joint"):
        manual.apply(ws, sid, op)
    kept = manual.apply(ws, sid, op, accept_joints=1)
    assert not scene.models[0].by_type("IfcRelConnectsPathElements")
    assert kept["entry"]["check"]["open_joints"][0]["name"] == "wall 'W1'"
    ws.journal(sid).undo(scene)
    assert len(scene.models[0].by_type("IfcRelConnectsPathElements")) == 1


def test_a_mapped_fitting_edited_keeps_its_type_and_the_others_their_shape(param):
    ws, sid, scene, g = param
    manual.apply(ws, sid, {"op": "push_pull", "element": g["F1"], "face": "top", "by_m": 0.1})
    f1, f2 = scene.entity(g["F1"]), scene.entity(g["F2"])
    assert [i.is_a() for i in f1.Representation.Representations[0].Items] == ["IfcExtrudedAreaSolid"]
    assert [i.is_a() for i in f2.Representation.Representations[0].Items] == ["IfcMappedItem"]
    assert ue.get_type(f1).Name == "FT-BOX" and ue.get_type(f1).RepresentationMaps[0].MappedRepresentation.Items[0].Depth == 0.3
    assert scene.bounds()[g["F1"]][1][2] == pytest.approx(1.4)


def test_a_beam_given_a_deeper_section_keeps_its_cardinal_point_and_its_twin_its_own(param):
    ws, sid, scene, g = param
    manual.apply(ws, sid, {"op": "push_pull", "element": g["BM1"], "face": "top", "by_m": 0.05})
    u1, u2 = ue.get_material(scene.entity(g["BM1"])), ue.get_material(scene.entity(g["BM2"]))
    assert u1.ForProfileSet.MaterialProfiles[0].Profile.OverallDepth == pytest.approx(0.45) and u1.CardinalPoint == 5
    assert u2.ForProfileSet.MaterialProfiles[0].Profile.OverallDepth == pytest.approx(0.4)
    assert ue.get_type(scene.entity(g["BM1"])).Name == "BT-UB (ORCA)" and ue.get_type(scene.entity(g["BM2"])).Name == "BT-UB"


def test_undo_puts_type_set_axis_and_quantities_back(param):
    ws, sid, scene, g = param
    before = untouched(scene, g, "")
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "north face", "by_m": 0.05})
    manual.apply(ws, sid, {"op": "push_pull", "element": g["BM1"], "face": "east end", "by_m": 0.5})
    log = ws.journal(sid)
    log.undo(scene)
    log.undo(scene)
    assert untouched(scene, g, "") == before
