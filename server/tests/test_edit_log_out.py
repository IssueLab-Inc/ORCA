"""The edit log leaves the server (docs/manual-edits.md): in the report (a timeline per clash, "Changes to the model",
BCF comments), in the exported IFC (ORCA_Edit on what each entry changed) and STEP (deleted parts gone), and as the
log itself beside the models. Exporting never touches the log's undo."""
import io
import zipfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import document, manual, step
from sightline.fixtures import build_edit_fixture
from sightline.journal import Journal
from sightline.reports import Report, ReportClash, ReportElement
from sightline.service import Workspace

from test_document import Writer, _jpeg


@pytest.fixture
def scene(tmp_path):
    build_edit_fixture(tmp_path / "edit.ifc")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["edit.ifc"])
    s = ws.scene(sid)
    return ws, sid, s, {e.Name: e.GlobalId for e in s.models[0].by_type("IfcElement") if e.Name}


def _report(g) -> Report:
    a = ReportElement(g["W1"], "IfcWall", "W1", "Level 01", "edit.ifc")
    b = ReportElement(g["C1"], "IfcColumn", "C1", "Level 01", "edit.ifc")
    c = ReportClash("c1", "W1 x C1", None, "Walls vs columns", None, None, "new", -0.2, None, None, a, b, number=7)
    return Report("r", "Edits", Path("."), [], [c])


def test_a_fix_then_a_hand_edit_show_as_a_timeline_in_the_report(scene):
    ws, sid, s, g = scene
    j = ws.journal(sid)
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 1.2}, accept_clashes=1)
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": -0.3},
                 clash_id="c1", pair=[g["W1"], g["C1"]])
    j.attach_picture("E2", _jpeg())
    rows = document.build_rows(_report(g), {}, {}, {"c1": {"a": g["W1"], "b": g["C1"]}}, s, {}, {}, {}, journal=j)
    (r,) = rows
    assert r.section == "page" and [e["id"] for e in r.edits] == ["E2"]
    assert document.edit_state(r) == "Edited by hand, still resolved"
    html = document.render_html("Report", "Edits", rows, {}, {}, changes=[e.to_dict() for e in j.kept()])
    assert "What was done" in html and "east end of wall &#x27;W1&#x27; pushed 300 mm in" in html
    assert "Changes to the model" in html and "<td>E1</td>" in html and "<td>#7</td>" in html
    assert "After the edits" in html and "checked, kept with 1 clash" in html
    assert "What was done (Edited by hand, still resolved)" in document._facts(r)
    bcf = zipfile.ZipFile(io.BytesIO(document.bcf_zip(rows, {"c1": {"a": g["W1"], "b": g["C1"]}}, s,
                                                     changes=[e.to_dict() for e in j.kept()])))
    markups = [bcf.read(n).decode() for n in bcf.namelist() if n.endswith("markup.bcf")]
    assert any("ORCA edit log" in m and "E2 (by hand" in m for m in markups)
    assert any("TopicType=\"Request\"" in m and "E1:" in m for m in markups)   # kept with a clash, on no page: its own topic


def test_a_kept_fix_followed_by_hand_reads_fix_applied_then_edited(scene):
    ws, sid, s, g = scene
    row = document.Row(_report(g).clashes[0], "edit.ifc", "edit.ifc", "A", "S", "A", ["A", "S"], None, {}, "page",
                       edits=[{"id": "E1", "params": {"options": []}, "source": "fix", "summary": "offset", "check": {"verified": True}},
                              {"id": "E2", "params": {"op": "push_pull"}, "source": "you", "summary": "pushed",
                               "check": {"accepted_clashes": 0}, "status": {"resolved": False, "depth_m": -0.012}}])
    assert document.edit_state(row) == "Fix applied, then edited by hand, clash back (-12 mm)"


def test_the_export_names_the_edits_on_the_elements_and_the_log_survives_it(scene, tmp_path):
    ws, sid, s, g = scene
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "east end", "by_m": 0.5}, clash_id="c1")
    kept = manual.apply(ws, sid, {"op": "void", "element": g["W1"], "face": "north face", "at": [3.0, 0, 1.5], "diameter_m": 0.2})
    out = ws.export(sid, tmp_path / "out")
    assert [p.name for p in out] == ["edit.orca.ifc"]   # one file: the bare IFC, no zip, no log beside it
    m = ifcopenshell.open(str(out[0]))
    pset = ifcopenshell.util.element.get_pset(m.by_guid(g["W1"]), "ORCA_Edit")
    assert pset["EntryIds"] == "E1, E2" and pset["Clashes"] == "c1" and "pushed 500 mm out" in pset["Summary"]
    assert ifcopenshell.util.element.get_pset(m.by_guid(kept["created"][0]), "ORCA_Edit")["Ops"] == "void"
    assert ifcopenshell.util.element.get_pset(s.entity(g["W1"]), "ORCA_Edit") is None   # only in the file written
    ws.undo_edit(sid)
    ws.undo_edit(sid)
    assert s.bounds()[g["W1"]][1][0] == pytest.approx(4.0)


def test_a_zip_carries_the_log(tmp_path, monkeypatch):
    from sightline.fixtures import build_clash_fixture
    build_clash_fixture(tmp_path / "s.ifc", only=("beam",))
    build_clash_fixture(tmp_path / "m.ifc", only=("duct",))
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["s.ifc", "m.ifc"])
    s = ws.scene(sid)
    beam = s.models[0].by_type("IfcBeam")[0].GlobalId
    duct = s.models[1].by_type("IfcDuctSegment")[0].GlobalId
    manual.apply(ws, sid, {"op": "move", "element": beam, "delta_m": [0, 0, 0.5]}, accept_clashes=5)
    manual.apply(ws, sid, {"op": "move", "element": duct, "delta_m": [0, 0, -0.5]}, accept_clashes=5)
    names = sorted(p.name for p in ws.export(sid, tmp_path / "out"))
    assert names == ["m.orca.ifc", "orca-edits.csv", "orca-edits.json", "s.orca.ifc"]


def test_the_picture_route(scene, monkeypatch):
    ws, sid, s, g = scene
    monkeypatch.setattr(app_module, "ws", ws)
    c = TestClient(app_module.app)
    manual.apply(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "top", "by_m": 0.1})
    assert c.post(f"/api/scenes/{sid}/edits/E1/picture", json={"png": _jpeg()}).json() == {"ok": True}
    assert c.get(f"/api/scenes/{sid}/edits").json()["entries"][0]["has_picture"] is True
    assert c.post(f"/api/scenes/{sid}/edits/E9/picture", json={"png": _jpeg()}).status_code == 404
    assert c.post(f"/api/scenes/{sid}/edits/E1/picture", json={"png": "nope"}).status_code == 400
