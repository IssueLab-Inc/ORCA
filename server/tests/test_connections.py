"""Joints (connections.py): what is joined to what, through ports or, for parts converted from STEP, face to face;
and moves that would pull a joint apart, refused with the joint named."""
import json
from pathlib import Path

import pytest

from sightline import agent, connections as cx, plans, step
from sightline.fixtures import build_joints_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace


@pytest.fixture
def scene(tmp_path) -> IfcScene:
    return IfcScene(build_joints_fixture(tmp_path / "joints.ifc"))


def gid(scene, tag):
    return next(e.GlobalId for e in scene.model.by_type("IfcElement") if tag in (e.Tag, e.Name))


def tags(scene, gids):
    return sorted(scene.entity(g).Tag or scene.entity(g).Name for g in gids)


def test_ports_say_what_a_segment_is_joined_to_and_at_which_end(scene):
    joints = {scene.entity(j.b).Tag or scene.entity(j.b).Name: j for j in cx.joints_of(scene, gid(scene, "S3A"))}
    assert set(joints) == {"Bend B2", "S3B"}
    assert (joints["Bend B2"].end_a, joints["Bend B2"].end_b, joints["Bend B2"].source) == ("start", None, "ports")
    assert (joints["S3B"].end_a, joints["S3B"].end_b) == ("end", "start")
    assert joints["Bend B2"].point_m == pytest.approx((0.05, 0, 0.9))
    assert len(cx.joints_of(scene, gid(scene, "Tee T1"))) == 3 and cx.joints_of(scene, gid(scene, "FP")) == []


def test_classes_and_runs(scene):
    kinds = {t: cx.classify(scene, gid(scene, t)) for t in ("S3A", "Bend B2", "Valve V1", "Tee T1", "Filter FRL1",
                                                            "Column C3")}
    assert kinds == {"S3A": "straight", "Bend B2": "rigid", "Valve V1": "rigid", "Tee T1": "rigid",
                     "Filter FRL1": "stays", "Column C3": "stays"}
    assert tags(scene, cx.run(scene, gid(scene, "S3A"))) == ["S3A", "S3B"]     # joined end to end
    assert tags(scene, cx.run(scene, gid(scene, "S2"))) == ["S2"]              # a valve and a bend stop it
    assert tags(scene, cx.run(scene, gid(scene, "M1"))) == ["M1"]              # so does a tee
    assert tags(scene, cx.run(scene, gid(scene, "Bend B2"))) == ["Bend B2"]


def test_a_move_that_would_pull_joints_apart_is_refused_with_them_named(scene, monkeypatch):
    run = cx.run(scene, gid(scene, "S3A"))
    plan = cx.plan_move(scene, run, [0, 0.25, 0])
    assert not plan.ok and tags(scene, plan.refused_at) == ["Bend B2", "Bend B3"]
    assert plan.refused.startswith("moving 'Pipe S3A' (with 1 more) north 250 mm would pull it apart from 'Bend B2' "
                                   "and 'Bend B3'")
    assert [tags(scene, (j.a, j.b)) for j in plan.kept] == [["S3A", "S3B"], ["S3A", "S3B"]]  # inside the run: kept
    assert cx.plan_move(scene, [gid(scene, "FP")], [0, 0.25, 0]).ok          # nothing joined to it
    assert cx.plan_move(scene, run, [0, 0, 0]).ok                             # not moving
    monkeypatch.setenv("SIGHTLINE_CONNECTED_MOVES", "off")                    # as before joints were known
    assert cx.plan_move(scene, run, [0, 0.25, 0]).ok
    assert tags(scene, cx.run(scene, gid(scene, "S3A"))) == ["S3A", "S3B"]


def test_the_agent_says_why_and_muse_reads_the_joints(scene):
    s3a, column = gid(scene, "S3A"), gid(scene, "Column C3")
    trials = []
    attempt, option = agent._try_move(scene, {"title": "Shift north", "delta_m": [0, 0.25, 0]}, s3a, 0.025,
                                      trials.append)
    assert option is None and attempt.reason.startswith("cannot keep its joints: moving 'Pipe S3A'")
    assert tags(scene, attempt.hit_ids) == ["Bend B2", "Bend B3"] and trials[0]["moved"] == cx.run(scene, s3a)

    class Result:
        attempts, advice = [attempt], ""
    assert "Shift north: cannot keep its joints" in plans.failure_summary(scene, Result())
    text = agent._describe(scene, agent.Clash(s3a, column))
    assert ("Element A (with the 1 straight segment(s) joined to it) is joined to pipe fitting 'Bend B2', pipe "
            "fitting 'Bend B3'.") in text
    attempt, option = agent._try_move(scene, {"title": "Lift", "delta_m": [0, 0, 0.3]}, gid(scene, "FP"), 0.025)
    assert option is not None   # a pipe joined to nothing still moves


def test_checks_endpoints_plans_and_combined_fixes_refuse_it_too(tmp_path):
    path = build_joints_fixture(tmp_path / "samples" / "joints.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    s3a, column = gid(scene, "S3A"), gid(scene, "Column C3")
    run = cx.run(scene, s3a)
    v = ws.verify_move(sid, run, [0, 0.25, 0])
    assert not v["passed"] and "would pull it apart from 'Bend B2' and 'Bend B3'" in v["reason"]
    assert tags(scene, v["joints"]["refused_at"]) == ["Bend B2", "Bend B3"]
    with pytest.raises(cx.edits.Unsupported, match="would pull it apart"):
        ws.apply(sid, run, [0, 0.25, 0])
    assert scene.revision == 0
    item = plans.Item(f"{s3a}|{column}", s3a, column, "pair", [],
                      option={"kind": "move", "moved": run, "delta_m": [0, 0.25, 0]})
    out = plans.verify_together(ws, sid, [item])
    assert not out["passed"] and out["items"][item.key]["reason"] == "breaks its joint with IfcPipeFitting x2"
    with pytest.raises(agent.Refused, match="step 1: cannot keep its joints"):
        agent.combined_steps(scene, {"steps": [{"kind": "move", "move": "A", "delta_m": [0, 0.25, 0]}]}, s3a, column)


# ------------------------------------------------------------------------------------------------- STEP parts

def write_air_step(path: Path) -> Path:
    """Parts in mm, as a machine builder's STEP has them: no ports. Group "Air": a main, a valve hanging under it, a
    vertical pipe into a box bend, a pipe on into a filter on a stand ("Frame"), a pipe touching that one side by side
    (ending short of the filter),
    a pipe ending 3 mm short of the bend; group "Spare": a pipe against the filter; group "Ladder": a riser box with a
    bend box sitting on its side."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colours = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    name = lambda label, text: TDataStd_Name.Set_s(label, TCollection_ExtendedString(text))
    box = lambda x0, y0, z0, x1, y1, z1: BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), x1 - x0, y1 - y0, z1 - z0).Shape()
    rod = lambda p, d, r, length: BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*p), gp_Dir(*d)), r, length).Shape()
    root = shapes.NewShape(); name(root, "Air test")
    groups = {g: shapes.NewShape() for g in ("Air", "Frame", "Spare", "Ladder")}
    for g, label in groups.items():
        name(label, g)
    items = [("Air", "Air main", rod((-1000, 0, 2000), (1, 0, 0), 25, 3000)),
             ("Air", "Air valve V1", box(-30, -30, 1855, 30, 30, 1975)),
             ("Air", "Air pipe 1", rod((0, 0, 1000), (0, 0, 1), 17, 855)),
             ("Air", "Air bend 1", box(-25, -25, 950, 25, 25, 1000)),
             ("Air", "Air pipe 2", rod((0, 25, 975), (0, 1, 0), 17, 1000)),
             ("Air", "Air filter F1", box(-100, 1025, 875, 100, 1225, 1075)),
             ("Frame", "Filter stand", box(-50, 1075, 0, 50, 1175, 875)),
             ("Air", "Air pipe 3", rod((34, 25, 975), (0, 1, 0), 17, 900)),
             ("Air", "Air pipe 4", rod((0, -1028, 975), (0, 1, 0), 17, 1000)),
             ("Spare", "Spare pipe", rod((100, 1125, 975), (1, 0, 0), 17, 500)),
             ("Ladder", "Ladder riser", box(2000, 0, 1000, 2300, 100, 1150)),
             ("Ladder", "Ladder bend", box(2100, 0, 1150, 2200, 100, 1250))]
    for g, n, shape in items:
        label = shapes.AddShape(shape, False); name(label, n)
        colours.SetColor(label, Quantity_Color(0.2, 0.4, 0.9, Quantity_TOC_RGB), XCAFDoc_ColorSurf)
        shapes.AddComponent(groups[g], label, TopLoc_Location())
    for g in groups.values():
        shapes.AddComponent(root, g, TopLoc_Location())
    shapes.UpdateAssemblies()
    w = STEPCAFControl_Writer(); w.SetNameMode(True); w.SetColorMode(True)
    assert w.Transfer(doc, STEPControl_AsIs) and w.Write(str(path)) == IFSelect_RetDone
    return path


class Classes:
    """The part classes Muse would give, by name."""
    WORDS = (("riser", "IfcCableCarrierSegment"), ("Ladder bend", "IfcCableCarrierFitting"), ("valve", "IfcValve"),
             ("bend", "IfcPipeFitting"), ("filter", "IfcFilter"), ("stand", "IfcMember"), ("main", "IfcPipeSegment"),
             ("pipe", "IfcPipeSegment"))

    def complete_json(self, system, text, images=None, schema=None):
        parts = []
        for line in text.splitlines():
            i, rest = line.split(": ", 1)
            cls = next(c for w, c in self.WORDS if w.lower() in rest.lower())
            parts.append({"i": int(i), "class": cls, "type": ""})
        return {"parts": parts}


@pytest.fixture
def air(tmp_path) -> IfcScene:
    ifc, _ = step.convert(write_air_step(tmp_path / "Air.step"), tmp_path / "out", classify_with=Classes())
    return IfcScene([ifc])


def named(scene, gids):
    return sorted(scene.entity(g).Name for g in gids)


def test_step_parts_are_joined_face_to_face_within_their_group(air):
    by = {air.entity(g).Name: g for g in air.bounds()}
    joined = lambda n: {air.entity(j.b).Name: (j.end_a, j.end_b, j.source) for j in cx.joints_of(air, by[n])}
    # STEP may extrude a rod either way: one joint on each of its caps
    for pipe, ends in (("Air pipe 2", {"Air bend 1", "Air filter F1"}), ("Air pipe 1", {"Air valve V1", "Air bend 1"})):
        found = joined(pipe)
        assert set(found) == ends and {v[0] for v in found.values()} == {"start", "end"}
        assert all(v[1:] == (None, "geometry") for v in found.values())
    assert joined("Air main") == {"Air valve V1": ("side", None, "geometry")}     # hanging off its side: a branch
    filt = joined("Air filter F1")    # not its stand, nor the spare pipe (another group)
    assert set(filt) == {"Air pipe 2"} and filt["Air pipe 2"][0] is None and filt["Air pipe 2"][1] in ("start", "end")
    assert joined("Air pipe 3") == {} and joined("Air pipe 4") == {}              # side by side; 3 mm short
    assert joined("Ladder riser") == {"Ladder bend": ("side", None, "geometry")}  # sat on its side
    assert named(air, cx.run(air, by["Air pipe 2"])) == ["Air pipe 2"]
    plan = cx.plan_move(air, [by["Air pipe 2"]], [0.1, 0, 0])
    assert named(air, plan.refused_at) == ["Air bend 1", "Air filter F1"]
    assert named(air, cx.run(air, by["Filter stand"])) == ["Filter stand"]        # a stand never takes the air line


def test_a_moved_part_is_joined_where_it_is_now(air):
    by = {air.entity(g).Name: g for g in air.bounds()}
    assert cx.joints_of(air, by["Air pipe 4"]) == []
    air.translate([by["Air pipe 4"]], (0, 0.003, 0))   # now against the bend's face
    air.refresh_bounds([by["Air pipe 4"]])
    assert [air.entity(j.b).Name for j in cx.joints_of(air, by["Air pipe 4"])] == ["Air bend 1"]


def test_keeping_a_move_that_would_pull_a_joint_apart_is_refused(tmp_path, monkeypatch):
    """/apply tries the move again before it keeps it (plans.apply): one that would pull a joint apart is a 409 with
    why, and nothing changes."""
    from fastapi.testclient import TestClient
    from sightline import app as app_module
    monkeypatch.setenv("SIGHTLINE_CONNECTED_MOVES", "refuse")
    path = build_joints_fixture(tmp_path / "samples" / "joints.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    monkeypatch.setattr(app_module, "ws", ws)
    r = TestClient(app_module.app).post(f"/api/scenes/{sid}/apply", json={
        "moved": [gid(scene, "S3A")], "delta_m": [0, 0.5, 0], "obstacles": [gid(scene, "Column C3")]})
    assert r.status_code == 409 and "cannot keep its joints" in r.json()["detail"]
    assert scene.revision == 0
