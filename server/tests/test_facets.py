"""The filters' index (facets.py, GET /api/scenes/{id}/facets): what a filter can match, value by value."""
import json

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import datums, facets
from sightline.scene import IfcScene
from sightline.service import Workspace
from tests.test_properties import _annotated, _complete


def _facet(idx, key):
    f = facets.facet(idx, key)
    assert f is not None, key
    return f


def _who(idx, key, value):
    f = _facet(idx, key)
    return {idx["elements"][i] for i in f["items"][f["values"].index(value)]}


def test_every_element_with_its_file_class_storey_type_and_material(tmp_path):
    beam = _annotated(tmp_path / "beam.ifc")
    scene = IfcScene(tmp_path / "beam.ifc")
    idx = facets.index(scene)
    assert sorted(idx["elements"]) == sorted(scene.bounds()) and idx["files"] == ["beam.ifc"]
    assert idx["file"] == [0] * len(idx["elements"])
    assert _facet(idx, "file")["values"] == ["beam.ifc"]
    assert _facet(idx, "class")["values"] == ["IfcBeam", "IfcDuctSegment", "IfcPipeSegment"]
    assert _who(idx, "class", "IfcBeam") == {beam}
    storeys = datums.storeys(scene)
    assert _facet(idx, "storey")["values"] == sorted(set(storeys.values())) == ["Level 03"]
    assert _who(idx, "type", "UB 406x178x60") == {beam}
    assert _who(idx, "material", "Steel S355") == {beam}
    assert [f["key"] for f in idx["facets"]][:5] == ["file", "class", "storey", "type", "material"]


def test_properties_and_quantities_keep_numbers_as_numbers_in_si(tmp_path):
    beam = _annotated(tmp_path / "beam-mm.ifc", millimetres=True)
    idx = facets.index(IfcScene(tmp_path / "beam-mm.ifc"))
    span = _facet(idx, "pset:Pset_BeamCommon/Span")
    assert span["kind"] == "number" and span["values"] == [6.0] and span["unit"] == "m"
    assert _facet(idx, "pset:Pset_BeamCommon/LoadBearing")["kind"] == "bool"
    assert _facet(idx, "qto:Qto_BeamBaseQuantities/NetVolume")["values"] == [0.48]
    assert _who(idx, "pset:Model data/Level", "Level 03") == {beam}
    assert _facet(idx, "attr:Name")["kind"] == "text"


def test_the_hidden_note_never_reaches_a_filter(tmp_path):
    _annotated(tmp_path / "beam.ifc")
    text = json.dumps(facets.index(IfcScene(tmp_path / "beam.ifc")))
    assert "ClashRole" not in text and "scripted" not in text


def test_every_kind_of_value_a_filter_can_match(tmp_path):
    beam, duct, _ = _complete(tmp_path / "all.ifc")
    idx = facets.index(IfcScene(tmp_path / "all.ifc"))
    assert _who(idx, "classif:Uniclass 2015", "Ss_20_10_75_35") == {beam}
    assert _who(idx, "group:IfcBuildingSystem", "Frame") == {beam}
    assert _who(idx, "material", "Brick") == {duct}
    assert _who(idx, "pset:Pset_Everything/Finish", "PAINTED") == {beam}
    assert _facet(idx, "pset:Pset_Everything/Bolts")["values"] == [0.02, 0.024]
    assert _who(idx, "pset:Pset_Everything/Connection/Torque", 210.0) == {beam}
    assert _who(idx, "pset:Pset_BeamCommon/Reference", "UB406") == {beam}, "what the type gives counts"
    assert facets.facet(idx, "pset:Pset_Everything/Service temperature") is None, "a range is not one value"
    assert facets.facet(idx, "pset:Pset_Everything/Deflection") is None, "nor a table"


def test_conditions_match_as_the_page_does(tmp_path):
    beam = _annotated(tmp_path / "beam.ifc")
    idx = facets.index(IfcScene(tmp_path / "beam.ifc"))
    n = len(idx["elements"])
    beam_i = idx["elements"].index(beam)
    assert facets.matching(idx, "class", "is", ["ifcbeam"]) == {beam_i}
    assert len(facets.matching(idx, "class", "isNot", ["IfcBeam"])) == n - 1
    assert len(facets.matching(idx, "attr:Name", "contains", ["duct"])) == 1
    assert facets.matching(idx, "pset:Pset_BeamCommon/Span", "has") == {beam_i}
    assert len(facets.matching(idx, "pset:Pset_BeamCommon/Span", "missing")) == n - 1
    assert facets.matching(idx, "pset:Pset_BeamCommon/Span", "between", lo=5.0, hi=7.0) == {beam_i}
    assert facets.matching(idx, "pset:Pset_BeamCommon/Span", "gt", lo=6.5) == set()
    assert facets.matching(idx, "pset:Pset_BeamCommon/Span", "is", ["6"]) == {beam_i}
    assert facets.matching(idx, "no such facet", "is", ["x"]) == set()
    assert facets.suggest(idx, "pset:Pset_BeamCommon/Spam")[0] == "pset:Pset_BeamCommon/Span"


def test_kept_on_the_scene_until_an_edit(tmp_path):
    _annotated(tmp_path / "beam.ifc")
    scene = IfcScene(tmp_path / "beam.ifc")
    first = facets.index(scene)
    assert facets.index(scene) is first
    scene.bump([0])
    again = facets.index(scene)
    assert again is not first and again["revision"] == scene.revision


def test_the_route(tmp_path, monkeypatch):
    _annotated(tmp_path / "beam.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc"]}).json()["id"]
    r = c.get(f"/api/scenes/{sid}/facets")
    assert r.status_code == 200 and r.json()["facets"][0]["key"] == "file"
    assert c.get("/api/scenes/nope/facets").status_code == 404


def test_what_chat_asks_for_resolves_to_the_pages_rule(tmp_path):
    beam = _annotated(tmp_path / "beam.ifc")
    idx = facets.index(IfcScene(tmp_path / "beam.ifc"))
    rule, n = facets.resolve(idx, {"classes": ["beam"], "where": [{"property": "Span", "op": "between", "min": 5, "max": 7}],
                                   "action": "isolate", "name": "Long beams"}, 3)
    assert rule == {"id": "chat3", "name": "Long beams", "on": True, "action": "isolate", "origin": "chat", "when": [
        {"facet": "class", "op": "is", "values": ["IfcBeam"]},
        {"facet": "pset:Pset_BeamCommon/Span", "op": "between", "min": 5.0, "max": 7.0}]}
    assert n == 1 and beam in idx["elements"]
    assert facets.property_key(idx, "level") == "storey"
    assert facets.property_key(idx, "Model data/Level") == "pset:Model data/Level"
    assert facets.property_key(idx, "loadbearing") == "pset:Pset_BeamCommon/LoadBearing"
    rule, _ = facets.resolve(idx, {"models": ["beam"], "action": "colour_by_value", "by": "Level"})
    assert rule["when"] == [{"facet": "file", "op": "is", "values": ["beam.ifc"]}] and rule["by"] == {"facet": "storey"}, "a level is the storey"


def test_what_the_models_lack_fails_with_the_closest_and_never_the_hidden_note(tmp_path):
    _annotated(tmp_path / "beam.ifc")
    idx = facets.index(IfcScene(tmp_path / "beam.ifc"))
    import pytest
    with pytest.raises(facets.Unresolved, match="Closest: Span"):
        facets.property_key(idx, "Spam")
    with pytest.raises(facets.Unresolved) as e:
        facets.property_key(idx, "ClashRol")
    assert "ClashRole" not in str(e.value).split("Closest")[-1]
    with pytest.raises(facets.Unresolved, match="IfcBeam"):
        facets.resolve(idx, {"classes": ["Beem"], "action": "hide"})
    with pytest.raises(facets.Unresolved, match="#rrggbb"):
        facets.resolve(idx, {"action": "colour", "colour": "teal"})
    with pytest.raises(facets.Unresolved, match="colour by"):
        facets.resolve(idx, {"action": "colour_by_value"})
