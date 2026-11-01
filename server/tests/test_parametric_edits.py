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


def test_a_section_grown_on_one_side_keeps_its_body_where_pushed_and_its_axis_at_the_cardinal_point(param):
    ws, sid, scene, g = param
    r = manual.apply(ws, sid, {"op": "push_pull", "element": g["BM1"], "face": "top", "by_m": 0.05})
    assert "the axis of beam 'BM1' back at its section's cardinal point (5)" in r["check"]["summary"]
    box = scene.bounds()[g["BM1"]]
    assert box[:, 2] == pytest.approx([2.8, 3.25]), "the body grew up only, as pushed"
    assert scene.placement(g["BM1"])[2, 3] == pytest.approx(3.025), "its axis is the new section's middle"
    axis = consistency._world_axis(scene, scene.entity(g["BM1"]))
    assert axis[:, 2] == pytest.approx([3.025, 3.025])
    off, *_ = consistency.cardinal_offset(scene.entity(g["BM1"]), 1.0)
    assert off == pytest.approx([0.0, 0.0], abs=1e-6)
    assert_consistent(scene)
    ws.journal(sid).undo(scene)
    assert scene.placement(g["BM1"])[2, 3] == pytest.approx(3.0)


def test_a_bottom_centred_beam_moves_its_axis_only_when_its_bottom_moves(param):
    ws, sid, scene, g = param
    b = scene.entity(g["BM2"])
    ue.get_material(b).CardinalPoint = 2    # its axis on its bottom flange: the body hangs 200 mm below the axis's middle
    off0, *_ = consistency.cardinal_offset(b, 1.0)
    manual.apply(ws, sid, {"op": "push_pull", "element": g["BM2"], "face": "top", "by_m": 0.05})
    assert scene.placement(g["BM2"])[2, 3] == pytest.approx(3.0), "its bottom stayed: so does its axis"
    manual.apply(ws, sid, {"op": "push_pull", "element": g["BM2"], "face": "bottom", "by_m": 0.05})
    assert scene.placement(g["BM2"])[2, 3] == pytest.approx(2.95), "its bottom went down 50 mm: so did its axis"
    off, *_ = consistency.cardinal_offset(scene.entity(g["BM2"]), 1.0)
    assert off == pytest.approx(off0, abs=1e-6)


def test_undo_puts_type_set_axis_and_quantities_back(param):
    ws, sid, scene, g = param
    before = untouched(scene, g, "")
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "north face", "by_m": 0.05})
    manual.apply(ws, sid, {"op": "push_pull", "element": g["BM1"], "face": "east end", "by_m": 0.5})
    log = ws.journal(sid)
    log.undo(scene)
    log.undo(scene)
    assert untouched(scene, g, "") == before


# ----------------------------------------------------------------------------------------------------- Apply to the type


def _mapped(e):
    (item,) = e.Representation.Representations[0].Items
    assert item.is_a("IfcMappedItem")
    return item.MappingSource


def test_applied_to_its_type_a_mapped_fitting_changes_every_fitting_of_it(param):
    ws, sid, scene, g = param
    before = untouched(scene, g, "")
    f2 = scene.bounds()[g["F2"]].copy()
    op = {"op": "push_pull", "element": g["F1"], "face": "top", "by_m": 0.1, "scope": "type"}
    r = manual.check(ws, sid, op)
    assert r["blocked"] is None and g["F2"] in r["changed"] and g["F2"] in r["targets"]
    assert "its type FT-BOX too, and the 1 other element of it" in r["summary"]
    manual.apply(ws, sid, op)
    f1e, f2e = scene.entity(g["F1"]), scene.entity(g["F2"])
    rmap = ue.get_type(f1e).RepresentationMaps[0]
    assert _mapped(f1e) == _mapped(f2e) == rmap, "both still draw their type's shape"
    assert rmap.MappedRepresentation.Items[0].Depth == pytest.approx(0.4)
    assert scene.bounds()[g["F1"]][1][2] == pytest.approx(1.4)
    assert scene.bounds()[g["F2"]][1][2] == pytest.approx(f2[1][2] + 0.1)
    assert scene.bounds()[g["F2"]][:, :2] == pytest.approx(f2[:, :2]), "only its height changed"
    assert ue.get_type(f1e).Name == "FT-BOX" and not [t for t in scene.models[0].by_type("IfcTypeObject")
                                                       if t.Name and t.Name.endswith("(ORCA)")]
    assert_consistent(scene)
    ws.journal(sid).undo(scene)
    assert untouched(scene, g, "") == before


def test_applied_to_its_type_a_turned_fitting_s_end_moves_the_others_in_their_own_frame(param):
    ws, sid, scene, g = param
    f1 = scene.bounds()[g["F1"]].copy()
    f2 = scene.bounds()[g["F2"]].copy()
    manual.apply(ws, sid, {"op": "push_pull", "element": g["F2"], "face": "north end", "by_m": 0.1, "scope": "type"})
    assert scene.bounds()[g["F2"]][1][1] == pytest.approx(f2[1][1] + 0.1)
    # F2's map is turned 90 degrees: what is north in it is along x in F1
    size = lambda b: b[1] - b[0]
    assert size(scene.bounds()[g["F1"]]) == pytest.approx(size(f1) + [0.1, 0.0, 0.0])
    assert _mapped(scene.entity(g["F1"])) == _mapped(scene.entity(g["F2"]))
    assert_consistent(scene)


def test_applied_to_its_type_a_deeper_section_deepens_every_beam_of_it_about_its_own_axis(param):
    ws, sid, scene, g = param
    bm2 = scene.bounds()[g["BM2"]].copy()
    r = manual.apply(ws, sid, {"op": "push_pull", "element": g["BM1"], "face": "top", "by_m": 0.05, "scope": "type"})
    assert g["BM2"] in r["changed"]
    b1, b2 = scene.entity(g["BM1"]), scene.entity(g["BM2"])
    u1, u2 = ue.get_material(b1), ue.get_material(b2)
    assert u1.ForProfileSet == u2.ForProfileSet and u1.ForProfileSet.MaterialProfiles[0].Profile.OverallDepth == pytest.approx(0.45)
    assert ue.get_type(b1).Name == ue.get_type(b2).Name == "BT-UB", "the type itself, not a copy"
    assert u2.CardinalPoint == 5 and consistency._swept_area(b2).OverallDepth == pytest.approx(0.45)
    assert scene.bounds()[g["BM2"]][:, 2] == pytest.approx(bm2[:, 2] + [-0.025, 0.025]), "about its own axis"
    assert scene.bounds()[g["BM1"]][1][2] == pytest.approx(3.25), "the face pushed"
    assert_consistent(scene)


@pytest.mark.parametrize("name,op,words", [
    ("W1", {"op": "push_pull", "face": "north face", "by_m": 0.05}, "layers of WT-250 are changed for every element"),
    ("SL1", {"op": "push_pull", "face": "top", "by_m": 0.05}, "has no type"),
    ("BM1", {"op": "push_pull", "face": "east end", "by_m": 0.5}, "changes nothing its type BT-UB gives"),
    ("F1", {"op": "move", "delta_m": [0, 0, 0.1]}, "only a push, pull or align changes what its type gives"),
], ids=["layered type", "no type", "a length", "a move"])
def test_applied_to_its_type_what_the_type_does_not_give_is_refused_in_words(param, name, op, words):
    ws, sid, scene, g = param
    r = manual.check(ws, sid, {**op, "element": g[name], "scope": "type"})
    assert r["blocked"] and words in r["blocked"], r["blocked"]


# ----------------------------------------------------------------------------------------------------- a carried wall end


def _axis_length(scene, gid):
    a = consistency._world_axis(scene, scene.entity(gid))
    return float(((a[1] - a[0]) ** 2).sum() ** 0.5)


def test_a_wall_moved_with_joined_parts_brings_the_joined_wall_s_end_along(param):
    ws, sid, scene, g = param
    before = untouched(scene, g, "")
    op = {"op": "move", "element": g["W2"], "delta_m": [0.5, 0, 0], "carry": True}
    r = manual.check(ws, sid, op)
    assert r["blocked"] is None and r["joints"] == [] and r["passed"]
    assert "the east end of wall 'W1' follows it (500 mm longer)" in r["summary"]
    manual.apply(ws, sid, op)
    assert _axis_length(scene, g["W1"]) == pytest.approx(4.5)
    assert scene.bounds()[g["W1"]][1][0] == pytest.approx(4.5)
    assert ue.get_pset(scene.entity(g["W1"]), "Qto_WallBaseQuantities", "Length") == pytest.approx(4.5)
    (rel,) = [x for x in scene.entity(g["W1"]).ConnectedTo if x.is_a("IfcRelConnectsPathElements")]
    assert consistency._join_gap(scene, rel) == pytest.approx(0.0, abs=1e-6), "the join holds"
    assert_consistent(scene)
    after = untouched(scene, g, "")
    assert {k for k in before if before[k] != after[k]} == {"W1"}, "W2 only moved (its placement): nothing else changed"
    ws.journal(sid).undo(scene)
    assert untouched(scene, g, "") == before


def test_a_wall_moved_across_the_joined_wall_s_line_shortens_it(param):
    ws, sid, scene, g = param
    manual.apply(ws, sid, {"op": "move", "element": g["W1"], "delta_m": [0, 0.5, 0], "carry": True})
    assert _axis_length(scene, g["W2"]) == pytest.approx(2.5)
    assert scene.bounds()[g["W2"]][0][1] == pytest.approx(0.5)
    assert_consistent(scene)


def test_a_wall_moved_along_its_own_line_leaves_its_join_open_even_with_joined_parts(param):
    ws, sid, scene, g = param
    r = manual.check(ws, sid, {"op": "move", "element": g["W1"], "delta_m": [-0.2, 0, 0], "carry": True})
    assert [j["name"] for j in r["joints"]] == ["wall 'W2'"] and "follows" not in r["summary"]
