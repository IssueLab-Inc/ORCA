"""Hand edits (manual.py, faces.py): faces named as people say them, push/pull, align and move, checked before they
are kept, refused by the requirements, warned by ORCA's own rules, logged, and undone."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import faces, manual, requirements
from sightline.fixtures import build_edit_fixture
from sightline.service import Workspace


@pytest.fixture
def ws(tmp_path):
    build_edit_fixture(tmp_path / "edit.ifc")
    return Workspace(samples=tmp_path)


@pytest.fixture
def scene(ws):
    sid = ws.open(["edit.ifc"])
    s = ws.scene(sid)
    ids = {e.Name: e.GlobalId for e in s.models[0].by_type("IfcElement") if e.Name}
    return ws, sid, s, ids


@pytest.fixture()
def using():
    tokens = []
    yield lambda doc: tokens.append(requirements.enter(requirements.register(doc)))
    for t in reversed(tokens):
        requirements.leave(t)


def names(s, gid):
    return {f.id: f.name for f in faces.faces(s, gid)}


def test_faces_are_named_as_people_say_them_and_say_what_they_allow(scene):
    ws, sid, s, g = scene
    assert names(s, g["W1"]) == {"cap:start": "north face", "cap:end": "south face", "edge:0": "bottom",
                                 "edge:1": "east end", "edge:2": "top", "edge:3": "west end"}
    assert names(s, g["C1"])["side:-x"] == "west side" and names(s, g["C1"])["cap:end"] == "top"
    assert names(s, g["B1"]) == {"cap:start": "west end", "cap:end": "east end", "flank": "sides"}
    assert names(s, g["P1"])["radial"] == "round side"
    wall = {f.id: f for f in faces.faces(s, g["W1"])}
    assert wall["cap:start"].size_m == pytest.approx(0.2) and "void" in wall["cap:start"].allows
    assert wall["edge:1"].allows == ["push_pull", "align"]
    beam = {f.id: f for f in faces.faces(s, g["B1"])}
    assert "push_pull" not in beam["flank"].allows
    # A pick is resolved to its face; Muse can say the name instead
    f = faces.resolve(s, g["W1"], [4.0, -0.1, 1.5], [1, 0, 0])
    assert (f.id, f.name) == ("edge:1", "east end")
    assert faces.resolve(s, g["C1"], [5.0, -0.1, 1.0], [-1, 0, 0]).id == "side:-x"
    assert faces.by_name(s, g["W1"], "the east end").id == "edge:1"
    with pytest.raises(KeyError):
        faces.by_name(s, g["W1"], "roof")


def test_a_wall_end_pushed_out_is_checked_kept_logged_and_undone(scene):
    ws, sid, s, g = scene
    op = {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 0.5}
    r = manual.check(ws, sid, op)
    assert r["passed"] and r["clashes"] == 0 and r["blocked"] is None
    assert "east end of wall 'W1' pushed 500 mm out" in r["summary"] and r["preview"]
    assert s.bounds()[g["W1"]][1][0] == pytest.approx(4.0)   # a check keeps nothing
    kept = manual.apply(ws, sid, op, key=r["key"])
    assert s.bounds()[g["W1"]][1][0] == pytest.approx(4.5)
    e = kept["entry"]
    assert e["source"] == "you" and e["kind"] == "push_pull" and e["elements"] == [g["W1"]]
    assert e["check"]["verified"] is False and e["check"]["accepted_clashes"] == 0 and s._edited == {0}
    ws.undo_edit(sid)
    assert s.bounds()[g["W1"]][1][0] == pytest.approx(4.0)


def test_an_edit_that_makes_a_clash_is_kept_only_when_the_person_accepts_it(scene):
    ws, sid, s, g = scene
    op = {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 1.2}
    r = manual.check(ws, sid, op)
    assert not r["passed"] and r["clashes"] == 1 and r["new"][0]["other"] == g["C1"] and r["new"][0]["name"] == "column 'C1'"
    with pytest.raises(manual.NotKept, match="keep it with 1 clash"):
        manual.apply(ws, sid, op)
    kept = manual.apply(ws, sid, op, accept_clashes=1)
    assert kept["entry"]["check"]["accepted_clashes"] == 1 and kept["entry"]["check"]["new"][0]["other"] == g["C1"]


def test_a_stale_check_is_refused(scene):
    ws, sid, s, g = scene
    op = {"op": "push_pull", "element": g["W1"], "face": "top", "by_m": 0.1}
    r = manual.check(ws, sid, op)
    manual.apply(ws, sid, {"op": "push_pull", "element": g["P1"], "face": "east end", "by_m": 0.1})
    with pytest.raises(manual.NotKept, match="changed since"):
        manual.apply(ws, sid, op, key=r["key"])


def test_a_wall_end_aligns_to_a_column_face_with_a_gap(scene):
    ws, sid, s, g = scene
    op = {"op": "align", "element": g["W1"], "face": "east end", "to": {"element": g["C1"], "face": "west side"}, "gap_m": 0.025}
    r = manual.check(ws, sid, op)
    assert r["passed"] and r["op"]["by_m"] == pytest.approx(0.975) and "25 mm off the west side of column 'C1'" in r["summary"]
    manual.apply(ws, sid, op)
    assert s.bounds()[g["W1"]][1][0] == pytest.approx(4.975)
    flush = manual.check(ws, sid, {**op, "gap_m": 0.0})
    assert flush["passed"], flush.get("new")   # flush with its target: touching it is the point
    moved = manual.check(ws, sid, {**op, "gap_m": 0.0, "how": "move"})
    assert moved["op"]["delta_m"] == pytest.approx([0.025, 0.0, 0.0]) and "moved 25 mm" in moved["summary"]


def test_faces_that_are_not_parallel_say_to_clip_instead(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "align", "element": g["W1"], "face": "east end",
                               "to": {"point": [5, 0, 0], "normal": [-0.7071, 0, 0.7071]}})
    assert "not parallel" in r["blocked"] and "clip" in r["blocked"]


def test_a_wall_end_cannot_be_pulled_through_its_window(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "west end", "by_m": -1.5})
    assert "opening" in r["blocked"]
    ok = manual.check(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "west end", "by_m": -0.5})
    assert ok["passed"], ok


def test_a_thicker_wall_keeps_its_window_cut_through(scene):
    ws, sid, s, g = scene
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "north face", "by_m": 0.3})
    wall = s.entity(g["W1"])
    assert s.bounds()[g["W1"]][1][1] == pytest.approx(0.3)
    opening = wall.HasOpenings[0].RelatedOpeningElement
    v = manual._world_verts(opening)
    assert v[:, 1].max() >= 0.3 + 0.09   # still proud of the new face
    assert v[:, 1].min() <= -0.2


def test_a_pipe_gets_bigger_and_its_designer_is_asked(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["P1"], "face": "round side", "by_m": 0.025})
    assert r["passed"] and "0.100 → 0.150 m across" in r["summary"]
    assert any(w["review"] == "services" for w in r["warnings"])
    manual.apply(ws, sid, {"op": "push_pull", "element": g["P1"], "face": "radial", "by_m": 0.025})
    box = s.bounds()[g["P1"]]
    assert box[1][1] - box[0][1] == pytest.approx(0.15, abs=0.002)


def test_a_transfer_beam_trimmed_warns_for_structure_but_is_not_refused(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["B1"], "face": "east end", "by_m": -0.2})
    assert r["passed"] and r["warnings"][0]["rule"] == "transfer" and "C2" in r["warnings"][0]["text"]
    kept = manual.apply(ws, sid, {"op": "push_pull", "element": g["B1"], "face": "east end", "by_m": -0.2})
    assert kept["entry"]["warnings"][0]["review"] == "structure"
    assert "need a pick" in manual.check(ws, sid, {"op": "push_pull", "element": g["B1"], "face": "sides", "by_m": 0.1})["blocked"]


def test_a_move_takes_the_element_and_is_logged(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "move", "element": g["C1"], "from": [5, 0, 0], "to": [5.5, 0, 0]})
    assert r["passed"] and r["op"]["delta_m"] == [0.5, 0.0, 0.0] and "moved east 500 mm" in r["summary"]
    manual.apply(ws, sid, r["op"])
    assert s.bounds()[g["C1"]][0][0] == pytest.approx(5.5)


def test_the_requirements_bind_a_hand_edit(scene, using):
    ws, sid, s, g = scene
    doc = requirements.default_doc(s)
    group = requirements.Matcher(s, doc).group_of(g["W1"])
    doc.who_moves = [requirements.Mover(group=m.group, edits="move" if m.group == group.id else m.edits)
                     for m in doc.who_moves]
    using(doc)
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 0.1})
    assert r["blocked"].startswith("blocked by requirements") and "moved whole" in r["blocked"]
    with pytest.raises(manual.NotKept):
        manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 0.1})


def test_a_hand_edit_on_a_clash_says_whether_it_resolved_it(scene):
    ws, sid, s, g = scene
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 1.2}, accept_clashes=1)
    kept = manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": -0.3},
                        clash_id="c7", pair=[g["W1"], g["C1"]])
    e = kept["entry"]
    assert e["clashes"] == [{"id": "c7", "pair": [g["W1"], g["C1"]]}] and e["follows"] == ["E1"]
    assert e["status"]["resolved"] is True and e["status"]["clash"] == "c7"


def test_the_routes(scene, monkeypatch):
    ws, sid, s, g = scene
    monkeypatch.setattr(app_module, "ws", ws)
    c = TestClient(app_module.app)
    f = c.post(f"/api/scenes/{sid}/edit/face", json={"element": g["W1"], "point": [4, -0.1, 1], "normal": [1, 0, 0]}).json()
    assert f["id"] == "edge:1" and f["name"] == "east end"
    assert len(c.get(f"/api/scenes/{sid}/elements/{g['C1']}/faces").json()["faces"]) == 6
    op = {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 1.2}
    chk = c.post(f"/api/scenes/{sid}/edit/check", json={"op": op}).json()
    assert chk["clashes"] == 1
    r = c.post(f"/api/scenes/{sid}/edit/apply", json={"op": op, "key": chk["key"]})
    assert r.status_code == 409 and "1 clash" in r.json()["detail"]
    kept = c.post(f"/api/scenes/{sid}/edit/apply", json={"op": op, "key": chk["key"], "accept_clashes": 1}).json()
    assert kept["entry"]["id"] == "E1" and kept["revision"] == 1 and [m["global_id"] for m in kept["meshes"]] == [g["W1"]]
    assert c.post(f"/api/scenes/{sid}/edit/apply", json={"op": {"op": "fly", "element": g["W1"]}}).status_code == 409
    assert c.post(f"/api/scenes/{sid}/edit/check", json={"op": {"op": "fly", "element": g["W1"]}}).json()["blocked"]
    assert c.post(f"/api/scenes/{sid}/edits/undo", json={}).json()["revision"] == 2
    assert np.allclose(s.bounds()[g["W1"]][1], [4.0, 0.0, 3.0])


def test_a_void_goes_through_the_wall_where_it_is_placed_and_is_undone(scene):
    ws, sid, s, g = scene
    op = {"op": "void", "element": g["W1"], "face": "north face", "at": [3.0, 0.0, 1.5], "shape": "rect", "width_m": 0.4, "height_m": 0.3}
    r = manual.check(ws, sid, op)
    assert r["passed"] and r["summary"] == "400 x 300 mm opening cut in the north face of wall 'W1'"
    kept = manual.apply(ws, sid, r["op"])
    wall = s.entity(g["W1"])
    assert len(wall.HasOpenings) == 2 and kept["created"] and kept["entry"]["created"] == kept["created"]
    v = manual._world_verts(s.entity(kept["created"][0]))
    assert v[:, 0].min() == pytest.approx(2.8) and v[:, 0].max() == pytest.approx(3.2)
    assert v[:, 2].min() == pytest.approx(1.35) and v[:, 2].max() == pytest.approx(1.65)
    assert v[:, 1].max() >= 0.009 and v[:, 1].min() <= -0.209   # through, and proud of both faces
    ws.undo_edit(sid)
    assert len(s.entity(g["W1"]).HasOpenings) == 1


def test_a_round_void_in_a_slab_a_recess_and_the_rules_that_warn(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "void", "element": g["S1"], "face": "top", "at": [1.5, 5.5, 3.2], "diameter_m": 0.15})
    assert r["passed"] and "Ø150 mm opening" in r["summary"] and r["warnings"][0]["review"] == "structure"
    recess = manual.check(ws, sid, {"op": "void", "element": g["S1"], "face": "top", "at": [1.5, 5.5, 3.2], "diameter_m": 0.15, "depth_m": 0.05})
    assert "50 mm recess" in recess["summary"]
    web = manual.check(ws, sid, {"op": "void", "element": g["B1"], "face": {"point": [1.0, 2.6, 2.7], "normal": [0, 1, 0]}, "diameter_m": 0.1})
    rules = {w["rule"] for w in web["warnings"]}
    assert web["passed"] and "hard_rule" in rules   # a transfer beam: ORCA would never cut it, a person may, for review
    edge = manual.check(ws, sid, {"op": "void", "element": g["W1"], "face": "north face", "at": [3.95, 0.0, 1.5], "diameter_m": 0.06})
    assert any(w["rule"] == "edge" for w in edge["warnings"])
    assert "does not take an opening" in manual.check(ws, sid, {"op": "void", "element": g["W1"], "face": "east end", "diameter_m": 0.1})["blocked"]


def test_cut_by_shape_leaves_the_gap_round_the_cutter(scene):
    ws, sid, s, g = scene
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 1.2}, accept_clashes=1)
    r = manual.check(ws, sid, {"op": "cut_by", "element": g["W1"], "cutter": g["C1"], "gap_m": 0.02})
    assert r["passed"] and r["clashes"] == 0 and r["cleared"][0]["other"] == g["C1"]
    assert r["min_clearance_m"] == pytest.approx(0.02, abs=1e-6) and "cut round column 'C1' with a 20 mm gap" in r["summary"]
    kept = manual.apply(ws, sid, r["op"])
    assert kept["entry"]["kind"] == "cut_by" and len(s.entity(g["W1"]).HasOpenings) == 2
    assert "does not reach it" in manual.check(ws, sid, {"op": "cut_by", "element": g["P1"], "cutter": g["S1"]})["blocked"]


def test_a_cut_needs_the_requirements_to_allow_any_edit(scene, using):
    ws, sid, s, g = scene
    doc = requirements.default_doc(s)
    group = requirements.Matcher(s, doc).group_of(g["S1"])
    doc.who_moves = [requirements.Mover(group=m.group, edits="move" if m.group == group.id else m.edits) for m in doc.who_moves]
    using(doc)
    r = manual.check(ws, sid, {"op": "void", "element": g["S1"], "face": "top", "at": [1.5, 5.5, 3.2], "diameter_m": 0.15})
    assert r["blocked"] and "may not be cut" in r["blocked"]


def length_x(s, gid):
    b = s.bounds()[gid]
    return b[1][0] - b[0][0]


def test_a_wall_splits_in_two_and_its_window_stays_with_the_piece_that_holds_it(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "split", "element": g["W1"], "at": [3.0, -0.1, 1.0]})
    assert r["passed"] and "split in two, 3.00 m from its west end" in r["summary"]
    kept = manual.apply(ws, sid, r["op"])
    first, second = kept["pieces"]
    assert first == g["W1"] and kept["created"] == [second] and s.entity(second).Name == "W1 (part 2)"
    assert length_x(s, first) == pytest.approx(3.0) and length_x(s, second) == pytest.approx(1.0)
    assert len(s.entity(first).HasOpenings) == 1 and not s.entity(second).HasOpenings
    through = manual.check(ws, sid, {"op": "split", "element": first, "at": [1.5, -0.1, 1.0]})
    assert "through an opening" in through["blocked"]
    ws.undo_edit(sid)
    assert length_x(s, g["W1"]) == pytest.approx(4.0) and second not in s.bounds()


def test_a_beam_and_a_pipe_split_along_their_runs(scene):
    ws, sid, s, g = scene
    kept = manual.apply(ws, sid, {"op": "split", "element": g["B1"], "at": [1.5, 2.5, 2.7]})
    a, b = kept["pieces"]
    assert length_x(s, a) == pytest.approx(1.5) and length_x(s, b) == pytest.approx(2.5)
    assert s.entity(b).is_a("IfcBeam") and not getattr(s.entity(b), "HasOpenings", None)
    assert "under 5 mm" in manual.check(ws, sid, {"op": "split", "element": g["P1"], "at": [0.003, -1, 1.5]})["blocked"]


def test_a_section_is_taken_out_and_the_rest_stays_where_it_was(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "remove_section", "element": g["P1"], "from": [2.5, -1, 1.5], "to": [1.0, -1, 1.5]})
    assert r["passed"] and "1,500 mm section taken out of pipe segment 'P1'" in r["summary"]
    kept = manual.apply(ws, sid, r["op"])
    rest = kept["created"][0]
    assert s.bounds()[g["P1"]][1][0] == pytest.approx(1.0) and s.bounds()[rest][0][0] == pytest.approx(2.5)
    assert s.bounds()[rest][1][0] == pytest.approx(4.0) and s.entity(rest).Name == "P1 (part 2)"
    assert len([e for e in s.models[0].by_type("IfcPipeSegment")]) == 2


def test_a_delete_warns_for_what_it_held_and_undo_brings_it_back(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "delete", "element": g["B1"]})
    assert r["passed"] and any(w["rule"] == "support" and "C2" in w["text"] for w in r["warnings"])
    kept = manual.apply(ws, sid, {"op": "delete", "element": g["W1"]})
    assert kept["removed"] == [g["W1"]] and g["W1"] not in s.bounds()
    assert not s.models[0].by_type("IfcOpeningElement") and kept["entry"]["names"][g["W1"]] == "IfcWall 'W1'"
    undone = ws.undo_edit(sid)
    assert g["W1"] in undone["changed"] and s.entity(g["W1"]).HasOpenings and g["W1"] in s.bounds()
    patch = ws.patch(sid, undone["changed"], 0, removed=undone["removed"])
    assert [m["global_id"] for m in patch["meshes"]] == [g["W1"]]   # its opening is not drawn as an element


def test_a_beam_end_is_clipped_to_a_sloping_face_and_its_other_end_still_pushes(scene):
    ws, sid, s, g = scene
    slope = {"point": [3.5, 2.5, 2.7], "normal": [-0.7071, 0, 0.7071]}
    r = manual.check(ws, sid, {"op": "clip", "element": g["B1"], "to": slope})
    assert r["passed"] and "clipped flush with the plane picked, 45° off square" in r["summary"]
    manual.apply(ws, sid, r["op"])
    assert s.bounds()[g["B1"]][1][0] < 4.0 - 0.1
    ends = {f.id: f for f in faces.faces(s, g["B1"])}
    assert ends["cap:end"].kind == "clip" and ends["cap:start"].allows[0] == "push_pull"
    manual.apply(ws, sid, {"op": "push_pull", "element": g["B1"], "face": "west end", "by_m": 0.2})
    assert s.bounds()[g["B1"]][0][0] == pytest.approx(-0.2)
    assert "nothing to clip" in manual.check(ws, sid, {"op": "clip", "element": g["P1"], "to": {"point": [10, 0, 0], "normal": [-1, 0, 0]}})["blocked"]


def width_along(s, gid, u):
    """The element's extent along the horizontal unit vector u (its mesh, metres)."""
    from sightline import edits
    v = edits._mesh_verts(s.entity(gid))
    return float(np.ptp(v @ np.asarray(u, float)))


def test_a_rectangle_turned_in_its_plan_pushes_along_its_own_sides(scene):
    ws, sid, s, g = scene
    u = [np.cos(np.radians(30)), np.sin(np.radians(30)), 0.0]
    side = faces.resolve(s, g["T1"], [10 + 0.2 * u[0], 0.2 * u[1], 0.5], u)
    assert side.id == "side:+x" and side.size_m == pytest.approx(0.4)
    kept = manual.apply(ws, sid, {"op": "push_pull", "element": g["T1"], "face": side.id, "by_m": 0.1})
    assert kept["entry"]["kind"] == "push_pull"
    assert width_along(s, g["T1"], u) == pytest.approx(0.5, abs=1e-6)
    assert width_along(s, g["T1"], [-u[1], u[0], 0.0]) == pytest.approx(0.2, abs=1e-6)


def test_a_shared_body_gets_its_own_copy_so_only_that_element_changes(scene):
    ws, sid, s, g = scene
    assert s.entity(g["D1"]).Representation.Representations[0] == s.entity(g["D2"]).Representation.Representations[0]
    manual.apply(ws, sid, {"op": "push_pull", "element": g["D1"], "face": "top", "by_m": 0.5})
    b1, b2 = s.bounds()[g["D1"]], s.bounds()[g["D2"]]
    assert b1[1][2] == pytest.approx(2.5) and b2[1][2] == pytest.approx(2.0)
    assert s.entity(g["D1"]).Representation.Representations[0] != s.entity(g["D2"]).Representation.Representations[0]
    ws.undo_edit(sid)
    assert s.entity(g["D1"]).Representation.Representations[0] == s.entity(g["D2"]).Representation.Representations[0]
    assert s.bounds()[g["D1"]][1][2] == pytest.approx(2.0)


def test_people_may_leave_5_mm_where_fixes_leave_50(scene):
    ws, sid, s, g = scene
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["C1"], "face": "west side", "by_m": -0.29})
    assert r["passed"] or r["blocked"] is None
    assert "at least 5 mm" in manual.check(ws, sid, {"op": "push_pull", "element": g["C1"], "face": "west side",
                                                     "by_m": -0.298})["blocked"]


def test_a_face_only_a_pick_can_place_is_refused_by_name_and_aligns_from_its_pick(scene):
    ws, sid, s, g = scene
    assert "need a pick" in manual.check(ws, sid, {"op": "align", "element": g["B1"], "face": "sides",
                                                   "to": {"element": g["C1"], "face": "west side"}})["blocked"]
    # From a pick on the beam's south flange tip (y = 2.4), not the profile's middle: moved 3.35 m to the pipe's top side.
    r = manual.check(ws, sid, {"op": "align", "element": g["B1"], "face": {"point": [1.0, 2.4, 2.7], "normal": [0, -1, 0]},
                               "to": {"element": g["P1"], "face": {"point": [1.0, -0.95, 1.5], "normal": [0, 1, 0]}}})
    assert r["blocked"] is None and r["op"]["by_m"] == pytest.approx(3.35, abs=1e-6) and r["op"]["how"] == "move"
