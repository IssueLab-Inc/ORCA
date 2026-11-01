"""STEP models (step.py): convert, check, move as groups, export back to STEP, upload."""
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import ifcopenshell.guid
import ifcopenshell.util.element
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import detect, step
from sightline.scene import IfcScene, step_source
from sightline.service import Workspace


def write_step(path: Path, ladder_z: float = 1000.0) -> Path:
    """A tiny machine in mm: group "Frame" with a post (green) and a beam on it; group "Ladder" with two touching runs
    (one see-through), the first through the post when ladder_z is low."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_ColorRGBA, Quantity_TOC_RGB
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
    box = lambda x, y, z, dx, dy, dz: BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()
    root = shapes.NewShape(); name(root, "Test cell")
    groups = {}
    for g in ("Frame", "Ladder", "Air"):
        groups[g] = shapes.NewShape(); name(groups[g], g)
    items = [("Frame", "Post P1", box(0, 0, 0, 100, 100, 2000), (0.1, 0.6, 0.2), 1.0),
             ("Frame", "Beam B1", box(-500, 0, 2000, 1100, 100, 200), (0.1, 0.6, 0.2), 1.0),
             ("Ladder", "Ladder run 1", box(-1000, 20, ladder_z, 1050, 60, 50), (0.8, 0.5, 0.1), 1.0),
             ("Ladder", "Ladder run 2", box(50, 20, ladder_z, 1000, 60, 50), (0.8, 0.5, 0.1), 0.5),
             # a 40 mm rod along X through a 300 mm block: the case a local offset fixes
             ("Air", "Air pipe 1", BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-1000, 3000, 1550), gp_Dir(1, 0, 0)), 20, 3000).Shape(),
              (0.2, 0.4, 0.9), 1.0),
             ("Frame", "Block K1", box(300, 2900, 1400, 300, 200, 300), (0.1, 0.6, 0.2), 1.0)]
    for g, n, shape, rgb, alpha in items:
        label = shapes.AddShape(shape, False); name(label, n)
        if alpha < 1:
            colours.SetColor(label, Quantity_ColorRGBA(*rgb, alpha), XCAFDoc_ColorSurf)
        else:
            colours.SetColor(label, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorSurf)
        shapes.AddComponent(groups[g], label, TopLoc_Location())
    for g in groups.values():
        shapes.AddComponent(root, g, TopLoc_Location())
    shapes.UpdateAssemblies()
    w = STEPCAFControl_Writer(); w.SetNameMode(True); w.SetColorMode(True)
    assert w.Transfer(doc, STEPControl_AsIs) and w.Write(str(path)) == IFSelect_RetDone
    return path


@pytest.fixture()
def cell(tmp_path):
    src = write_step(tmp_path / "Test-cell.step")
    ifc, manifest = step.convert(src, tmp_path / "out")
    return src, ifc, json.loads(manifest.read_text())


def test_conversion_keeps_names_groups_colours_and_metres(cell):
    src, ifc, manifest = cell
    scene = IfcScene([ifc])
    b = scene.bounds()
    by_name = {scene.entity(g).Name: g for g in b}
    assert set(by_name) == {"Post P1", "Beam B1", "Ladder run 1", "Ladder run 2", "Air pipe 1", "Block K1"}
    assert b[by_name["Post P1"]][1][2] == pytest.approx(2.0, abs=1e-3)       # mm → m
    assert scene.step_group(by_name["Ladder run 2"]) == "Ladder"
    run2 = scene.entity(by_name["Ladder run 2"])
    styles = [s for s in scene.model.by_type("IfcSurfaceStyleRendering") if s.Transparency]
    assert any(s.Transparency == pytest.approx(0.5, abs=0.01) for s in styles)
    assert run2.is_a("IfcBuildingElementProxy") and run2.ObjectType == "Ladder"   # no classifier: proxy, group name
    assert step_source(run2)["Group"] == "Ladder" and "ORCA_STEP" in ifcopenshell.util.element.get_psets(run2)
    again, _ = step.convert(src, src.parent / "again")
    assert sorted(g.GlobalId for g in IfcScene([again]).model.by_type("IfcBuildingElementProxy")) == sorted(b)
    assert {p["name"] for p in manifest["parts"].values()} == set(by_name)
    # Rods and bars become exact extrusions, so offsets and trims work on them; the rest would stay meshes.
    pipe = scene.entity(by_name["Air pipe 1"]).Representation.Representations[0].Items[0]
    assert pipe.is_a("IfcExtrudedAreaSolid") and pipe.SweptArea.Radius == pytest.approx(0.02)
    assert pipe.Depth == pytest.approx(3.0)
    post = scene.entity(by_name["Post P1"]).Representation.Representations[0].Items[0]
    assert post.is_a("IfcExtrudedAreaSolid") and post.Depth == pytest.approx(2.0)


def test_detection_finds_the_ladder_through_the_post(cell):
    _, ifc, _ = cell
    run = detect.run(IfcScene([ifc]))
    pairs = {frozenset((c.a.name, c.b.name)) for c in run.report.clashes}
    assert frozenset(("Ladder run 1", "Post P1")) in pairs
    assert frozenset(("Ladder run 1", "Ladder run 2")) not in pairs   # they touch end to end: not a clash


def test_a_ladder_run_moves_with_the_runs_it_touches_and_a_post_alone(cell):
    _, ifc, _ = cell
    scene = IfcScene([ifc])
    by_name = {scene.entity(g).Name: g for g in scene.bounds()}
    assert [scene.entity(g).Name for g in scene.connected_run(by_name["Ladder run 1"])] in (
        ["Ladder run 1", "Ladder run 2"], ["Ladder run 2", "Ladder run 1"])
    assert scene.connected_run(by_name["Post P1"]) == sorted([by_name["Post P1"], by_name["Beam B1"]])  # touching


def test_export_writes_the_moves_back_into_the_step(tmp_path):
    src = write_step(tmp_path / "Test-cell.step")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["Test-cell.step"])
    scene = ws.scene(sid)
    run = scene.connected_run({scene.entity(g).Name: g for g in scene.bounds()}["Ladder run 1"])
    ws.apply(sid, run, (0.0, 0.0, 1.5))
    pipe = {scene.entity(g).Name: g for g in scene.bounds()}["Air pipe 1"]
    ws.apply_offset(sid, pipe, [1.15, 1.75], -0.3)   # under the block (x 0.3-0.6 m from the pipe's start at -1 m)
    out = ws.export(sid, tmp_path / "export")
    assert sorted(p.name for p in out) == ["Test-cell.orca.ifc", "Test-cell.orca.step"]
    moved = {p.name: p for p in step.parts(next(p for p in out if p.suffix == ".step"))[0]}
    before = {p.name: p for p in step.parts(src)[0]}

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    def zmin(p):
        box = Bnd_Box(); BRepBndLib.Add_s(p.shape, box); return box.CornerMin().Z()
    assert zmin(moved["Ladder run 1"]) - zmin(before["Ladder run 1"]) == pytest.approx(1500, abs=0.01)
    assert zmin(moved["Ladder run 2"]) - zmin(before["Ladder run 2"]) == pytest.approx(1500, abs=0.01)
    assert zmin(moved["Post P1"]) == pytest.approx(zmin(before["Post P1"]))
    assert moved["Ladder run 2"].alpha == pytest.approx(0.5, abs=0.01) and moved["Post P1"].group == "Frame"

    def box_of(p):
        box = Bnd_Box(); BRepBndLib.Add_s(p.shape, box); lo, hi = box.CornerMin(), box.CornerMax()
        return (lo.X(), lo.Y(), lo.Z()), (hi.X(), hi.Y(), hi.Z())
    after = step.parts(next(p for p in out if p.suffix == ".step"))[0]
    pieces = [p for p in after if p.group == "Air"]
    assert len(pieces) >= 5                                          # the pipe split: ends, risers, middle
    assert 100 < box_of(moved["Air pipe 1"])[1][0] < 300            # its first piece now stops short of the block
    lowest = min(box_of(p)[0][2] for p in pieces)
    assert lowest == pytest.approx(1550 - 20 - 300, abs=1)          # the middle runs 300 mm lower
    assert all(p.colour == pytest.approx((0.2, 0.4, 0.9), abs=0.01) for p in pieces)
    assert sum(box_of(moved["Block K1"]), ()) == pytest.approx(sum(box_of(before["Block K1"]), ()))


def test_classes_come_from_the_model_and_unknown_ones_stay_proxies(tmp_path):
    src = write_step(tmp_path / "Test-cell.step")

    class Classes:
        def complete_json(self, system, user, images, schema=None):
            return {"parts": [{"i": 0, "class": "IfcMember", "type": "POST"},
                              {"i": 3, "class": "IfcCableCarrierSegment", "type": "CABLELADDERSEGMENT"},
                              {"i": 4, "class": "IfcNotAClass", "type": "x"}]}
    ifc, _ = step.convert(src, tmp_path / "out", Classes())
    scene = IfcScene([ifc])
    by_name = {scene.entity(g).Name: scene.entity(g) for g in scene.bounds()}
    assert by_name["Post P1"].is_a("IfcMember") and by_name["Post P1"].PredefinedType == "POST"
    assert by_name["Ladder run 1"].is_a("IfcCableCarrierSegment")
    assert by_name["Ladder run 2"].is_a("IfcBuildingElementProxy")


def test_upload_opens_step_and_ifc_and_refuses_the_rest(tmp_path, monkeypatch):
    src = write_step(tmp_path / "Test-cell.step")
    monkeypatch.setattr(app_module, "_classifier", lambda: None)
    c = TestClient(app_module.app)
    r = c.post("/api/models/upload", files=[("files", ("Test-cell.step", src.read_bytes()))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"] == ["Test-cell.step"] and body["step"] == {"0": "Test-cell.step"}
    assert c.get(f"/api/scenes/{body['id']}/files/0").content.startswith(b"ISO-10303-21")
    assert c.post("/api/models/upload", files=[("files", ("notes.txt", b"hi"))]).status_code == 400
    bad = c.post("/api/models/upload", files=[("files", ("broken.step", b"not a step file"))])
    assert bad.status_code == 400


def test_uploads_are_capped_per_visitor(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "model_upload_limit", app_module.ProposeLimit(1, 0, noun="model uploads"))
    monkeypatch.setattr(app_module, "_classifier", lambda: None)
    src = write_step(tmp_path / "Test-cell.step")
    c = TestClient(app_module.app)
    assert c.post("/api/models/upload", files=[("files", ("Test-cell.step", src.read_bytes()))]).status_code == 200
    assert c.post("/api/models/upload", files=[("files", ("Test-cell.step", src.read_bytes()))]).status_code == 429


def test_parts_from_older_conversions_still_read_their_group():
    """Caches written before the rename carry the pset as Sightline_STEP."""
    model = ifcopenshell.file(schema="IFC4")
    part = model.createIfcBuildingElementProxy(ifcopenshell.guid.new(), Name="Old part")
    pset = ifcopenshell.api.run("pset.add_pset", model, product=part, name="Sightline_STEP")
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={"Group": "Frame", "Label": "0:1:1:2"})
    assert step_source(part) == {"Group": "Frame", "Label": "0:1:1:2", "id": pset.id()}


def test_a_part_deleted_by_hand_leaves_the_step_and_a_pushed_box_changes_shape(tmp_path):
    from sightline import manual
    write_step(tmp_path / "Test-cell.step")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["Test-cell.step"])
    scene = ws.scene(sid)
    ids = {scene.entity(g).Name: g for g in scene.bounds()}
    kept = manual.apply(ws, sid, {"op": "delete", "element": ids["Block K1"]})
    assert kept["removed"][0] == ids["Block K1"]
    post = next(f for f in manual.faces.faces(scene, ids["Post P1"]) if f.kind == "cap" and f.name == "top")
    manual.apply(ws, sid, {"op": "push_pull", "element": ids["Post P1"], "face": post.id, "by_m": 0.2}, accept_clashes=9)
    out = ws.export(sid, tmp_path / "export")
    after = {p.name: p for p in step.parts(next(p for p in out if p.suffix == ".step"))[0]}
    assert "Block K1" not in after and "Post P1" in after

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box(); BRepBndLib.Add_s(after["Post P1"].shape, box)
    before = {p.name: p for p in step.parts(tmp_path / "Test-cell.step")[0]}
    box0 = Bnd_Box(); BRepBndLib.Add_s(before["Post P1"].shape, box0)
    assert box.CornerMax().Z() - box0.CornerMax().Z() == pytest.approx(200, abs=0.5)
