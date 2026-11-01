"""What the Properties panel shows for an object (properties.py, GET /api/scenes/{id}/elements/{gid}/properties):
everything the model says, of every kind, with units, the type's values marked, and the path up to the project."""
import json

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
    ifcopenshell.api.run("pset.edit_pset", f, pset=common, properties={"LoadBearing": True, "Span": 6.0 * (1000 if millimetres else 1)})
    k = 1000.0 if millimetres else 1.0
    qto = ifcopenshell.api.run("pset.add_qto", f, product=beam, name="Qto_BeamBaseQuantities")
    ifcopenshell.api.run("pset.edit_qto", f, qto=qto, properties={"Length": 6.0 * k, "CrossSectionArea": 0.08 * k * k,
                                                                 "NetVolume": 0.48 * k ** 3})
    f.write(str(path))
    return beam.GlobalId


def _set(p, name):
    return next(s for s in p["sets"] if s["name"] == name)


def _row(rows, name):
    return next(r for r in rows if r["name"] == name)


def _values(s):
    return {r["name"]: r["value"] for r in s["props"]}


def test_an_element_shows_what_its_model_says(tmp_path):
    gid = _annotated(tmp_path / "beam.ifc")
    p = properties.properties(IfcScene(tmp_path / "beam.ifc"), gid)
    assert p["ifc_class"] == "IfcBeam" and p["name"] == "UB 406x178 beam"
    assert _row(p["attributes"], "Name")["value"] == "UB 406x178 beam"
    assert p["type"]["ifc_class"] == "IfcBeamType" and p["type"]["name"] == "UB 406x178x60"
    assert [m["name"] for m in p["materials"]] == ["Steel S355"] and p["materials"][0]["usage"] == "single"
    assert _values(_set(p, "Pset_BeamCommon")) == {"LoadBearing": True, "Span": 6.0}
    assert _row(_set(p, "Pset_BeamCommon")["props"], "Span")["unit"] == "m"
    assert _row(_set(p, "Qto_BeamBaseQuantities")["props"], "Length") == {"name": "Length", "value": 6.0, "unit": "m"}
    assert _set(p, "Qto_BeamBaseQuantities")["kind"] == "qto"
    assert p["size_m"] == [6.0, 0.2, 0.4]
    assert p["source"] == "beam.ifc" and p["file"] == 0
    assert "id" not in json.dumps([r["name"] for s in p["sets"] for r in s["props"]]), "IfcOpenShell's internal ids stay out"


def test_the_path_runs_from_the_project_to_the_storey(tmp_path):
    gid = _annotated(tmp_path / "beam.ifc")
    p = properties.properties(IfcScene(tmp_path / "beam.ifc"), gid)
    assert [(r["ifc_class"], r["name"]) for r in p["path"]] == [
        ("IfcProject", "ORCA fixture"), ("IfcSite", "Site"), ("IfcBuilding", "Building"), ("IfcBuildingStorey", "Level 03")]
    assert p["storey"]["name"] == "Level 03" and p["container"]["name"] == "Level 03"
    # A crumb opens the storey's own properties, and its path stops above it.
    storey = properties.properties(IfcScene(tmp_path / "beam.ifc"), p["storey"]["global_id"], p["storey"]["file"])
    assert storey["ifc_class"] == "IfcBuildingStorey" and storey["size_m"] is None
    assert [r["name"] for r in storey["path"]] == ["ORCA fixture", "Site", "Building"]


def test_the_demo_models_own_set_is_model_data_without_its_scripting_note(tmp_path):
    gid = _annotated(tmp_path / "beam.ifc")
    p = properties.properties(IfcScene(tmp_path / "beam.ifc"), gid)
    assert all(s["name"] != "ClashWise_Demo" for s in p["sets"])
    assert _values(_set(p, "Model data")) == {"Level": "Level 03"}
    assert "ClashRole" not in json.dumps(p) and "scripted" not in json.dumps(p)


def test_lengths_areas_and_volumes_are_si_whatever_the_file_units(tmp_path):
    gid = _annotated(tmp_path / "beam-mm.ifc", millimetres=True)
    p = properties.properties(IfcScene(tmp_path / "beam-mm.ifc"), gid)
    q = {r["name"]: r for r in _set(p, "Qto_BeamBaseQuantities")["props"]}
    assert q["Length"] == {"name": "Length", "value": 6.0, "unit": "m"}
    assert q["CrossSectionArea"] == {"name": "CrossSectionArea", "value": 0.08, "unit": "m²"}
    assert q["NetVolume"] == {"name": "NetVolume", "value": 0.48, "unit": "m³"}
    assert _row(_set(p, "Pset_BeamCommon")["props"], "Span") == {"name": "Span", "value": 6.0, "unit": "m"}


def test_an_element_with_nothing_but_geometry(tmp_path):
    build_clash_fixture(tmp_path / "plain.ifc")
    scene = IfcScene(tmp_path / "plain.ifc")
    duct = scene.models[0].by_type("IfcDuctSegment")[0].GlobalId
    p = properties.properties(scene, duct)
    assert p["type"] is None and p["materials"] == [] and p["sets"] == []
    assert p["classifications"] == [] and p["groups"] == [] and p["documents"] == []
    assert p["size_m"] == [0.4, 4.0, 0.3]


def _complete(path):
    """A beam carrying every kind of property, a type with its own sets and quantities, a wall with layers, a
    classification, a system and a document: what the reader must return, all of it."""
    build_clash_fixture(path, millimetres=True)
    f = ifcopenshell.open(str(path))
    beam, duct = f.by_type("IfcBeam")[0], f.by_type("IfcDuctSegment")[0]
    storey = f.by_type("IfcBuildingStorey")[0]
    storey.Elevation = 8000.0
    mm = f.by_type("IfcSIUnit")[0]
    celsius = f.create_entity("IfcSIUnit", UnitType="THERMODYNAMICTEMPERATUREUNIT", Name="DEGREE_CELSIUS")
    watt = f.create_entity("IfcSIUnit", UnitType="POWERUNIT", Name="WATT")
    E = f.create_entity
    single = E("IfcPropertySingleValue", Name="Depth", NominalValue=f.createIfcLengthMeasure(400.0))
    text = E("IfcPropertySingleValue", Name="Grade", NominalValue=f.createIfcLabel("S355"))
    power = E("IfcPropertySingleValue", Name="Load", NominalValue=f.createIfcPowerMeasure(1500.0), Unit=watt)
    hidden = E("IfcPropertySingleValue", Name="ClashRole", NominalValue=f.createIfcLabel("planted"))
    enum = E("IfcPropertyEnumeratedValue", Name="Finish", EnumerationValues=[f.createIfcLabel("PAINTED")])
    lst = E("IfcPropertyListValue", Name="Bolts", ListValues=[f.createIfcLengthMeasure(20.0), f.createIfcLengthMeasure(24.0)])
    bounded = E("IfcPropertyBoundedValue", Name="Service temperature", Unit=celsius,
                LowerBoundValue=f.createIfcThermodynamicTemperatureMeasure(10.0),
                UpperBoundValue=f.createIfcThermodynamicTemperatureMeasure(20.0),
                SetPointValue=f.createIfcThermodynamicTemperatureMeasure(18.0))
    table = E("IfcPropertyTableValue", Name="Deflection", DefiningValues=[f.createIfcLengthMeasure(1000.0)],
              DefinedValues=[f.createIfcLengthMeasure(2.0)])
    person = E("IfcPerson", FamilyName="Okoro")
    reference = E("IfcPropertyReferenceValue", Name="Checked by", PropertyReference=person)
    inner = E("IfcPropertySingleValue", Name="Torque", NominalValue=f.createIfcReal(210.0))
    inner_hidden = E("IfcPropertySingleValue", Name="ClashRole", NominalValue=f.createIfcLabel("planted"))
    complex_ = E("IfcComplexProperty", Name="Connection", UsageName="End plate", HasProperties=[inner, inner_hidden])
    pset = E("IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="Pset_Everything",
             HasProperties=[single, text, power, hidden, enum, lst, bounded, table, reference, complex_])
    E("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[beam], RelatingPropertyDefinition=pset)

    kind = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcBeamType", name="UB 406x178x60")
    ifcopenshell.api.run("type.assign_type", f, related_objects=[beam], relating_type=kind)
    tset = ifcopenshell.api.run("pset.add_pset", f, product=kind, name="Pset_BeamCommon")
    ifcopenshell.api.run("pset.edit_pset", f, pset=tset, properties={"Reference": "UB406", "FireRating": "R60"})
    own = ifcopenshell.api.run("pset.add_pset", f, product=beam, name="Pset_BeamCommon")
    ifcopenshell.api.run("pset.edit_pset", f, pset=own, properties={"FireRating": "R90"})
    tqto = ifcopenshell.api.run("pset.add_qto", f, product=kind, name="Qto_BeamBaseQuantities")
    ifcopenshell.api.run("pset.edit_qto", f, qto=tqto, properties={"Length": 6000.0})

    layers = ifcopenshell.api.run("material.add_material_set", f, name="Cavity wall", set_type="IfcMaterialLayerSet")
    brick = ifcopenshell.api.run("material.add_material", f, name="Brick")
    block = ifcopenshell.api.run("material.add_material", f, name="Block")
    for m, t in ((brick, 102.5), (block, 100.0)):
        layer = ifcopenshell.api.run("material.add_layer", f, layer_set=layers, material=m)
        layer.LayerThickness = t
    mprops = E("IfcMaterialProperties", Name="Pset_MaterialCommon", Material=brick,
               Properties=[E("IfcPropertySingleValue", Name="Porosity", NominalValue=f.createIfcNormalisedRatioMeasure(0.2))])
    assert mprops
    ifcopenshell.api.run("material.assign_material", f, products=[duct], type="IfcMaterialLayerSet", material=layers)

    system = ifcopenshell.api.run("classification.add_classification", f, classification="Uniclass 2015")
    ifcopenshell.api.run("classification.add_reference", f, products=[beam], classification=system,
                         identification="Ss_20_10_75_35", name="Steel beams")
    sys_ = ifcopenshell.api.run("system.add_system", f, ifc_class="IfcBuildingSystem")
    sys_.Name = "Frame"
    ifcopenshell.api.run("system.assign_system", f, products=[beam], system=sys_)
    doc = E("IfcDocumentReference", Identification="S-201", Name="Beam schedule", Location="https://example.com/s201.pdf")
    E("IfcRelAssociatesDocument", GlobalId=ifcopenshell.guid.new(), RelatedObjects=[beam], RelatingDocument=doc)
    assert mm
    f.write(str(path))
    return beam.GlobalId, duct.GlobalId, storey.GlobalId


def test_nothing_the_model_says_is_dropped(tmp_path):
    beam, _, _ = _complete(tmp_path / "all.ifc")
    p = properties.properties(IfcScene(tmp_path / "all.ifc"), beam)
    rows = {r["name"]: r for r in _set(p, "Pset_Everything")["props"]}
    assert set(rows) == {"Depth", "Grade", "Load", "Finish", "Bolts", "Service temperature", "Deflection",
                         "Checked by", "Connection"}
    assert rows["Depth"] == {"name": "Depth", "value": 0.4, "unit": "m"}, "a length in a mm file comes in metres"
    assert rows["Grade"] == {"name": "Grade", "value": "S355"}
    assert rows["Load"]["value"] == 1500.0 and rows["Load"]["unit"] == "W"
    assert rows["Finish"]["kind"] == "enumerated" and rows["Finish"]["value"] == ["PAINTED"]
    assert rows["Bolts"]["kind"] == "list" and rows["Bolts"]["value"] == [0.02, 0.024] and rows["Bolts"]["unit"] == "m"
    assert rows["Service temperature"]["kind"] == "bounded"
    assert rows["Service temperature"]["value"] == {"lower": 10.0, "upper": 20.0, "set_point": 18.0}
    assert rows["Service temperature"]["unit"] == "°C"
    assert rows["Deflection"]["kind"] == "table" and rows["Deflection"]["table"]["defining"] == [1.0]
    assert rows["Deflection"]["table"]["defined"] == [0.002] and rows["Deflection"]["table"]["defined_unit"] == "m"
    assert rows["Checked by"]["kind"] == "reference" and rows["Checked by"]["of"] == "IfcPerson"
    assert rows["Connection"]["kind"] == "complex" and rows["Connection"]["value"] == "End plate"
    assert [r["name"] for r in rows["Connection"]["rows"]] == ["Torque"], "the hidden note stays out at every depth"
    assert "ClashRole" not in json.dumps(p)
    assert properties.leaves(p) >= 9


def test_the_type_gives_what_the_element_does_not_and_says_so(tmp_path):
    beam, _, _ = _complete(tmp_path / "all.ifc")
    p = properties.properties(IfcScene(tmp_path / "all.ifc"), beam)
    common = {r["name"]: r for r in _set(p, "Pset_BeamCommon")["props"]}
    assert common["FireRating"]["value"] == "R90" and not common["FireRating"].get("from_type"), "the element's own wins"
    assert common["Reference"]["value"] == "UB406" and common["Reference"]["from_type"] is True
    qto = _set(p, "Qto_BeamBaseQuantities")
    assert qto["from_type"] is True and _row(qto["props"], "Length")["value"] == 6.0
    assert p["type"]["global_id"] and any(a["name"] == "Name" for a in p["type"]["attributes"])


def test_materials_classifications_groups_and_documents(tmp_path):
    beam, duct, _ = _complete(tmp_path / "all.ifc")
    scene = IfcScene(tmp_path / "all.ifc")
    p = properties.properties(scene, beam)
    (ref,) = scene.models[0].by_type("IfcClassificationReference")
    assert p["classifications"] == [{"id": ref.id(), "system": "Uniclass 2015", "identification": "Ss_20_10_75_35",
                                     "name": "Steel beams", "location": None}]   # its id: the panel swaps or removes it
    assert [(g["ifc_class"], g["name"]) for g in p["groups"]] == [("IfcBuildingSystem", "Frame")]
    assert p["documents"] == [{"identification": "S-201", "name": "Beam schedule", "location": "https://example.com/s201.pdf"}]
    wall = properties.properties(scene, duct)["materials"][0]
    assert wall["usage"] == "layers" and wall["name"] == "Cavity wall" and wall["total_m"] == 0.2025
    assert [(i["material"], i["thickness_m"]) for i in wall["items"]] == [("Brick", 0.1025), ("Block", 0.1)]
    assert wall["sets"][0]["material"] == "Brick" and _values(wall["sets"][0]) == {"Porosity": 0.2}


def test_every_attribute_comes_with_its_unit(tmp_path):
    _, _, storey = _complete(tmp_path / "all.ifc")
    p = properties.properties(IfcScene(tmp_path / "all.ifc"), storey)
    assert _row(p["attributes"], "Elevation") == {"name": "Elevation", "value": 8.0, "unit": "m"}
    assert not any(a["name"] in ("OwnerHistory", "ObjectPlacement", "GlobalId") for a in p["attributes"])


def test_the_route_answers_picks_a_file_and_refuses_an_unknown_element(tmp_path, monkeypatch):
    gid = _annotated(tmp_path / "beam.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc"]}).json()["id"]
    r = c.get(f"/api/scenes/{sid}/elements/{gid}/properties")
    assert r.status_code == 200 and r.json()["materials"][0]["name"] == "Steel S355"
    storey = r.json()["storey"]
    assert c.get(f"/api/scenes/{sid}/elements/{storey['global_id']}/properties?file=0").json()["ifc_class"] == "IfcBuildingStorey"
    assert c.get(f"/api/scenes/{sid}/elements/{gid}/properties?file=3").status_code == 404
    assert c.get(f"/api/scenes/{sid}/elements/0000000000000000000000/properties").status_code == 404
    assert c.get(f"/api/scenes/nope/elements/{gid}/properties").status_code == 404


def test_an_unnamed_storey_has_the_name_the_level_filter_gives_it(tmp_path):
    gid = _annotated(tmp_path / "beam.ifc")
    f = ifcopenshell.open(str(tmp_path / "beam.ifc"))
    st = f.by_type("IfcBuildingStorey")[0]
    st.Name = None
    f.write(str(tmp_path / "beam.ifc"))
    scene = IfcScene(tmp_path / "beam.ifc")
    from sightline import datums
    p = properties.properties(scene, gid)
    assert p["storey"]["name"] == p["path"][-1]["name"] == f"Storey {st.id()}" == datums.storeys(scene)[gid]
