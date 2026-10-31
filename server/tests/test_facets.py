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
    rule, hit = facets.resolve(idx, {"classes": ["beam"], "where": [{"property": "Span", "op": "between", "min": 5, "max": 7}],
                                   "action": "isolate", "name": "Long beams"}, 3)
    assert rule == {"id": "chat3", "name": "Long beams", "on": True, "action": "isolate", "origin": "chat", "when": [
        {"facet": "class", "op": "is", "values": ["IfcBeam"]},
        {"facet": "pset:Pset_BeamCommon/Span", "op": "between", "min": 5.0, "max": 7.0}]}
    assert [idx["elements"][i] for i in hit] == [beam]
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


def test_a_test_with_no_bound_or_value_is_refused_or_takes_a_lone_number(tmp_path):
    _annotated(tmp_path / "beam.ifc")
    idx = facets.index(IfcScene(tmp_path / "beam.ifc"))
    import pytest
    for w in ({"property": "Span", "op": "more"}, {"property": "Span", "op": "less", "values": []},
              {"property": "Span", "op": "between"}, {"property": "Name", "op": "contains", "values": [""]}):
        with pytest.raises(facets.Unresolved, match="Say the"):
            facets.resolve(idx, {"where": [w], "action": "hide"})
    rule, hit = facets.resolve(idx, {"where": [{"property": "Span", "op": "more", "values": ["5"]}], "action": "hide"})
    assert rule["when"][0] == {"facet": "pset:Pset_BeamCommon/Span", "op": "gt", "min": 5.0} and len(hit) == 1
    rule, _ = facets.resolve(idx, {"where": [{"property": "Span", "op": "between", "values": [7, 5]}], "action": "hide"})
    assert (rule["when"][0]["min"], rule["when"][0]["max"]) == (5.0, 7.0)
    assert facets.found(idx, [{"facet": "pset:Pset_BeamCommon/Span", "op": "gt"}]) == set(range(len(idx["elements"]))), \
        "an unfinished condition is left out, as the page does"


def test_a_complex_propertys_part_by_its_name_or_path(tmp_path):
    beam, _, _ = _complete(tmp_path / "all.ifc")
    idx = facets.index(IfcScene(tmp_path / "all.ifc"))
    for name in ("Torque", "Connection/Torque", "Pset_Everything/Connection/Torque"):
        assert facets.property_key(idx, name) == "pset:Pset_Everything/Connection/Torque", name
    import pytest
    with pytest.raises(facets.Unresolved, match="Closest: Torque"):
        facets.property_key(idx, "Torqe")


def test_yes_and_one_stay_apart(tmp_path):
    from sightline.facets import element_facets
    read = {"source": "a.ifc", "ifc_class": "IfcWall", "type": None, "materials": [], "attributes": [],
            "classifications": [], "groups": [], "sets": [{"kind": "pset", "name": "P", "props": [
                {"name": "X", "value": True}, {"name": "X", "value": 1}]}]}
    got = [(k, v) for k, v, _ in element_facets(read, None) if k == "pset:P/X"]
    assert got == [("pset:P/X", True), ("pset:P/X", 1)] and type(got[1][1]) is int


def test_an_unreadable_element_is_skipped_not_the_whole_index(tmp_path, monkeypatch):
    _annotated(tmp_path / "beam.ifc")
    scene = IfcScene(tmp_path / "beam.ifc")
    real = facets.properties.Reader.read
    def flaky(self, e, *a, **k):
        if e.is_a("IfcBeam"):
            raise RuntimeError("unreadable")
        return real(self, e, *a, **k)
    monkeypatch.setattr(facets.properties.Reader, "read", flaky)
    idx = facets.build(scene)
    assert len(idx["elements"]) == len(scene.bounds()) - 1 and _facet(idx, "class")["values"] == ["IfcDuctSegment", "IfcPipeSegment"]


def test_a_filter_is_named_from_what_it_finds_as_the_page_names_it():
    when = [{"facet": "class", "op": "is", "values": ["IfcDuctSegment"]}, {"facet": "storey", "op": "is", "values": ["Level 02"]},
            {"facet": "pset:Model data/Length", "op": "gt", "min": 3.0}, {"facet": "pset:P/X", "op": "has"},
            {"facet": "attr:Tag", "op": "isNot", "values": ["A", "B", "C"]}, {"facet": "pset:P/Y", "op": "gt"}]
    assert facets.name_for(when) == "DuctSegment · Level 02 · Length · has X · not A, B +1"
    assert facets.name_for([]) == "Everything" and facets.name_for(when[:1], invert=True) == "everything but DuctSegment"
