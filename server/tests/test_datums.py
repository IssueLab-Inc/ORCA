"""Levels, grids and storeys for the drawing views (datums.py, GET /api/scenes/{id}/datums)."""
import ifcopenshell
import ifcopenshell.api
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import datums
from sightline.scene import IfcScene
from sightline.service import Workspace


def _file(path, *, mm=False, storeys=(("Level 01", 0.0), ("Level 02", 3.5)), wall_on=1, grid=False):
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="P")
    unit = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT", prefix="MILLI" if mm else None)
    ifcopenshell.api.run("unit.assign_unit", f, units=[unit])
    ifcopenshell.api.run("context.add_context", f, context_type="Model")
    site = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuilding", name="B")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[site], relating_object=project)
    ifcopenshell.api.run("aggregate.assign_object", f, products=[building], relating_object=site)
    k = 1000.0 if mm else 1.0
    made = []
    for name, z in storeys:
        st = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=name)
        ifcopenshell.api.run("aggregate.assign_object", f, products=[st], relating_object=building)
        m = np.eye(4); m[2][3] = z * k
        ifcopenshell.api.run("geometry.edit_object_placement", f, product=st, matrix=m, is_si=False)
        made.append(st)
    wall = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcWall", name="W1")
    ifcopenshell.api.run("spatial.assign_container", f, products=[wall], relating_structure=made[wall_on])
    if grid:
        g = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcGrid", name="Structural grid")
        m = np.eye(4); m[0][3] = 2 * k
        ifcopenshell.api.run("geometry.edit_object_placement", f, product=g, matrix=m, is_si=False)
        line = f.createIfcPolyline([f.createIfcCartesianPoint((0.0, -5.0 * k)), f.createIfcCartesianPoint((0.0, 5.0 * k))])
        g.UAxes = [f.createIfcGridAxis("A", line, True)]
        line2 = f.createIfcPolyline([f.createIfcCartesianPoint((-5.0 * k, 0.0)), f.createIfcCartesianPoint((5.0 * k, 0.0))])
        g.VAxes = [f.createIfcGridAxis("1", line2, True)]
    f.write(str(path))
    return wall.GlobalId


def test_levels_merge_across_files_by_name_and_height_in_metres(tmp_path):
    _file(tmp_path / "P-Structure.ifc")
    _file(tmp_path / "P-MEP.ifc", mm=True, storeys=(("Level 01", 0.0), ("Level 02", 3.5), ("Roof", 7.0)))
    s = IfcScene([tmp_path / "P-Structure.ifc", tmp_path / "P-MEP.ifc"])
    out = datums.levels(s)
    assert [(lv["name"], lv["elevation_m"], lv["height_m"]) for lv in out] == [
        ("Level 01", 0.0, 3.5), ("Level 02", 3.5, 3.5), ("Roof", 7.0, None)]


def test_storeys_name_each_elements_level(tmp_path):
    wall = _file(tmp_path / "P-Structure.ifc", wall_on=1)
    s = IfcScene([tmp_path / "P-Structure.ifc"])
    assert datums.storeys(s)[wall] == "Level 02"


def test_grid_axes_go_through_their_grids_placement_and_units(tmp_path):
    _file(tmp_path / "P-Structure.ifc", mm=True, grid=True)
    model = ifcopenshell.open(str(tmp_path / "P-Structure.ifc"))
    axes = {a["tag"]: a for a in datums.grids([(model, 0.001)])}
    assert axes["A"]["start"] == [2.0, -5.0, 0.0] and axes["A"]["end"] == [2.0, 5.0, 0.0]
    assert axes["1"]["start"] == [-3.0, 0.0, 0.0] and axes["1"]["grid"] == "Structural grid"


def test_a_sample_scene_without_a_grid_reads_its_projects_grids_file(tmp_path):
    _file(tmp_path / "P-Structure.ifc")
    _file(tmp_path / "P-Grids.ifc", grid=True)
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["P-Structure.ifc"])
    d = ws.datums(sid)
    assert d["sources"] == {"grids": "P-Grids.ifc"}
    assert sorted(a["tag"] for a in d["grids"]) == ["1", "A"]
    assert [lv["name"] for lv in d["levels"]] == ["Level 01", "Level 02"]
    # Context only: never one of the scene's files.
    assert [p.name for p in ws.scene(sid).paths] == ["P-Structure.ifc"]


def test_a_scenes_own_grid_wins_and_no_grid_is_no_grid(tmp_path):
    _file(tmp_path / "Q-Structure.ifc", grid=True)
    _file(tmp_path / "Q-Grids.ifc", grid=True)
    _file(tmp_path / "Cell.ifc")
    ws = Workspace(samples=tmp_path)
    own = ws.datums(ws.open(["Q-Structure.ifc"]))
    assert own["sources"] == {"grids": "Q-Structure.ifc"} and len(own["grids"]) == 2
    none = ws.datums(ws.open(["Cell.ifc"]))
    assert none["grids"] == [] and none["sources"] == {"grids": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    _file(tmp_path / "P-Structure.ifc")
    _file(tmp_path / "P-Grids.ifc", grid=True)
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    return TestClient(app_module.app)


def test_the_datums_route(client):
    sid = client.post("/api/scenes", json={"samples": ["P-Structure.ifc"]}).json()["id"]
    r = client.get(f"/api/scenes/{sid}/datums")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"levels", "grids", "storeys", "sources"}
    assert body["sources"]["grids"] == "P-Grids.ifc"
    assert client.get("/api/scenes/nope/datums").status_code == 404
