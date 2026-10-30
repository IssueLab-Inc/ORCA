"""What the Properties panel shows for an element (properties.py, GET /api/scenes/{id}/elements/{gid}/properties)."""
import ifcopenshell
import ifcopenshell.api
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import properties
from sightline.fixtures import build_clash_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace


def _annotated(path, millimetres=False):
    """The clash fixture's beam with a type, a material, the demo models' own property set, a common set and quantities."""
    build_clash_fixture(path, millimetres=millimetres)
    f = ifcopenshell.open(str(path))
    beam = f.by_type("IfcBeam")[0]
    kind = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBeamType", name="UB 406x178x60")
    ifcopenshell.api.run("type.assign_type", f, related_objects=[beam], relating_type=kind)
    steel = ifcopenshell.api.run("material.add_material", f, name="Steel S355")
    ifcopenshell.api.run("material.assign_material", f, products=[beam], material=steel)
    demo = ifcopenshell.api.run("pset.add_pset", f, product=beam, name="ClashWise_Demo")
    ifcopenshell.api.run("pset.edit_pset", f, pset=demo, properties={"Level": "Level 03", "ClashRole": "Clash host for scripted #1"})
    common = ifcopenshell.api.run("pset.add_pset", f, product=beam, name="Pset_BeamCommon")
    ifcopenshell.api.run("pset.edit_pset", f, pset=common, properties={"LoadBearing": True, "Span": 6.0})
    k = 1000.0 if millimetres else 1.0
    qto = ifcopenshell.api.run("pset.add_qto", f, product=beam, name="Qto_BeamBaseQuantities")
    ifcopenshell.api.run("pset.edit_qto", f, qto=qto, properties={"Length": 6.0 * k, "CrossSectionArea": 0.08 * k * k,
                                                                 "NetVolume": 0.48 * k ** 3})
    f.write(str(path))
    return beam.GlobalId


def test_an_element_shows_what_its_model_says(tmp_path):
    gid = _annotated(tmp_path / "beam.ifc")
    p = properties.properties(IfcScene(tmp_path / "beam.ifc"), gid)
    assert p["ifc_class"] == "IfcBeam" and p["attributes"]["Name"] == "UB 406x178 beam"
    assert p["type"] == {"ifc_class": "IfcBeamType", "name": "UB 406x178x60"}
    assert p["materials"] == ["Steel S355"]
    assert p["psets"]["Pset_BeamCommon"] == {"LoadBearing": True, "Span": 6.0}
    assert p["quantities"]["Qto_BeamBaseQuantities"]["Length"] == {"value": 6.0, "unit": "m"}
    assert p["size_m"] == [6.0, 0.2, 0.4]
    assert p["source"] == "beam.ifc"
    assert all("id" not in s for s in p["psets"].values()), "IfcOpenShell's internal ids stay out"


def test_the_demo_models_own_set_is_model_data_without_its_scripting_note(tmp_path):
    gid = _annotated(tmp_path / "beam.ifc")
    p = properties.properties(IfcScene(tmp_path / "beam.ifc"), gid)
    assert "ClashWise_Demo" not in p["psets"]
    assert p["psets"]["Model data"] == {"Level": "Level 03"}


def test_quantities_are_si_whatever_the_file_units(tmp_path):
    gid = _annotated(tmp_path / "beam-mm.ifc", millimetres=True)
    q = properties.properties(IfcScene(tmp_path / "beam-mm.ifc"), gid)["quantities"]["Qto_BeamBaseQuantities"]
    assert q["Length"] == {"value": 6.0, "unit": "m"}
    assert q["CrossSectionArea"] == {"value": 0.08, "unit": "m²"}
    assert q["NetVolume"] == {"value": 0.48, "unit": "m³"}


def test_an_element_with_nothing_but_geometry(tmp_path):
    build_clash_fixture(tmp_path / "plain.ifc")
    scene = IfcScene(tmp_path / "plain.ifc")
    duct = scene.models[0].by_type("IfcDuctSegment")[0].GlobalId
    p = properties.properties(scene, duct)
    assert p["type"] is None and p["materials"] == [] and p["psets"] == {} and p["quantities"] == {}
    assert p["size_m"] == [0.4, 4.0, 0.3]


def test_the_route_answers_and_refuses_an_unknown_element(tmp_path, monkeypatch):
    gid = _annotated(tmp_path / "beam.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc"]}).json()["id"]
    r = c.get(f"/api/scenes/{sid}/elements/{gid}/properties")
    assert r.status_code == 200 and r.json()["materials"] == ["Steel S355"]
    assert c.get(f"/api/scenes/{sid}/elements/0000000000000000000000/properties").status_code == 404
    assert c.get(f"/api/scenes/nope/elements/{gid}/properties").status_code == 404
