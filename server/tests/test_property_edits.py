"""Editing what the model says about an element (property_edits.py, docs/editing-parity.md, Tier 3): through the
routes the Properties panel uses, kept in the edit log, undone like any edit, and refused in words where the change
would leave the model saying two things."""
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.util.element as ue
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline.fixtures import build_parametric_fixture
from sightline.service import Workspace


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_parametric_fixture(tmp_path / "param.ifc")
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["param.ifc"]}).json()["id"]
    scene = ws.scene(sid)
    return c, ws, sid, scene, {scene.entity(g).Name: g for g in scene.bounds()}


def change(c, sid, gid, **kw):
    return c.post(f"/api/scenes/{sid}/elements/{gid}/properties", json={"change": kw})


def test_the_choices_come_from_the_element_s_own_model(client):
    c, ws, sid, scene, g = client
    ch = c.get(f"/api/scenes/{sid}/elements/{g['W1']}/property-choices").json()
    assert ch["attributes"] == ["Name", "Description", "ObjectType", "Tag", "PredefinedType"]
    assert "PARTITIONING" in ch["predefined"] and [t["name"] for t in ch["types"]] == ["WT-250"]
    assert ch["material"] is None and "layers" in ch["material_fixed"] and ch["containers"][0]["name"] == "Level 01"


def test_an_attribute_and_a_property_are_kept_in_the_log_and_come_back_on_undo(client):
    c, ws, sid, scene, g = client
    r = change(c, sid, g["W1"], kind="attribute", name="Name", value="W1-A")
    assert r.status_code == 200 and r.json()["entry"]["summary"] == "wall 'W1': Name 'W1' → 'W1-A'"
    assert r.json()["properties"]["name"] == "W1-A"
    r = change(c, sid, g["W1"], kind="property", pset="Pset_WallCommon", name="FireRating", value="60")
    assert r.status_code == 200 and ue.get_pset(scene.entity(g["W1"]), "Pset_WallCommon", "FireRating") == "60"
    log = ws.journal(sid)
    assert [(e.kind, e.source, e.elements) for e in log.entries] == [("property", "you", [g["W1"]])] * 2
    c.post(f"/api/scenes/{sid}/edits/undo", json={})
    c.post(f"/api/scenes/{sid}/edits/undo", json={})
    assert scene.entity(g["W1"]).Name == "W1" and ue.get_pset(scene.entity(g["W1"]), "Pset_WallCommon") is None


def test_a_number_stays_a_number_and_yes_stays_yes(client):
    c, ws, sid, scene, g = client
    change(c, sid, g["BM1"], kind="property", pset="Pset_BeamCommon", name="Span", value=5.0)
    change(c, sid, g["BM1"], kind="property", pset="Pset_BeamCommon", name="LoadBearing", value=True)
    assert change(c, sid, g["BM1"], kind="property", pset="Pset_BeamCommon", name="Span", value="5.5").status_code == 200
    change(c, sid, g["BM1"], kind="property", pset="Pset_BeamCommon", name="LoadBearing", value="no")
    pset = ue.get_pset(scene.entity(g["BM1"]), "Pset_BeamCommon")
    assert pset["Span"] == 5.5 and pset["LoadBearing"] is False


def test_what_would_make_the_model_say_two_things_is_refused_in_words(client):
    c, ws, sid, scene, g = client
    r = change(c, sid, g["W1"], kind="property", pset="Qto_WallBaseQuantities", name="Width", value=1)
    assert r.status_code == 422 and "base quantities follow its body" in r.json()["detail"]
    types = c.get(f"/api/scenes/{sid}/elements/{g['W1']}/property-choices").json()["types"]
    r = change(c, sid, g["W1"], kind="type", type=types[0]["global_id"])
    assert r.status_code == 422 and ("layers or profile come from its type" in r.json()["detail"] or "already" in r.json()["detail"])
    steel = ue.get_material(scene.entity(g["BM1"]), should_skip_usage=True).MaterialProfiles[0].Material
    r = change(c, sid, g["BM1"], kind="material", material=steel.id())
    assert r.status_code == 422 and "layers or profile" in r.json()["detail"]
    assert change(c, sid, g["W1"], kind="attribute", name="GlobalId", value="x").status_code == 400
    assert not ws.journal(sid).entries


def test_a_type_given_property_belongs_to_every_element_of_the_type(client):
    c, ws, sid, scene, g = client
    model = scene.models[0]
    wt = ue.get_type(scene.entity(g["W1"]))
    pset = ifcopenshell.api.run("pset.add_pset", model, product=wt, name="Pset_WallCommon")
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={"AcousticRating": "45 dB"})
    r = change(c, sid, g["W1"], kind="property", pset="Pset_WallCommon", name="AcousticRating", value="50 dB")
    assert r.status_code == 422 and "comes from its type" in r.json()["detail"]


def test_a_fitting_moves_to_another_type_keeping_its_shape_and_a_classification_comes_and_goes(client):
    c, ws, sid, scene, g = client
    model = scene.models[0]
    other = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcDuctFittingType", name="FT-OTHER")
    box = scene.bounds()[g["F1"]].copy()
    r = change(c, sid, g["F1"], kind="type", type=other.GlobalId)
    assert r.status_code == 200 and "now of type 'FT-OTHER' (was 'FT-BOX')" in r.json()["entry"]["summary"]
    assert ue.get_type(scene.entity(g["F1"])).Name == "FT-OTHER" and (scene.bounds()[g["F1"]] == box).all()
    assert [i.is_a() for i in scene.entity(g["F1"]).Representation.Representations[0].Items] == ["IfcExtrudedAreaSolid"]
    cl = ifcopenshell.api.run("classification.add_classification", model, classification="Uniclass")
    ifcopenshell.api.run("classification.add_reference", model, products=[scene.entity(g["W2"])], identification="Ss_25_10",
                         name="Walls", classification=cl)
    (ref,) = c.get(f"/api/scenes/{sid}/elements/{g['W1']}/property-choices").json()["classifications"]
    assert change(c, sid, g["W1"], kind="classification", reference=ref["id"]).status_code == 200
    assert c.get(f"/api/scenes/{sid}/elements/{g['W1']}/property-choices").json()["classifications"][0]["on"]
    assert change(c, sid, g["W1"], kind="classification", reference=ref["id"], remove=True).status_code == 200


def test_a_classification_is_swapped_in_one_change_and_never_given_twice(client):
    c, ws, sid, scene, g = client
    model = scene.models[0]
    cl = ifcopenshell.api.run("classification.add_classification", model, classification="Uniclass")
    walls = ifcopenshell.api.run("classification.add_reference", model, products=[scene.entity(g["W1"])],
                                 identification="Ss_25_10", name="Walls", classification=cl)
    beams = ifcopenshell.api.run("classification.add_reference", model, products=[scene.entity(g["W2"])],
                                 identification="Ss_20_10", name="Beams", classification=cl)
    # The panel reads which reference a row is, to swap or take it off.
    (row,) = c.get(f"/api/scenes/{sid}/elements/{g['W1']}/properties").json()["classifications"]
    assert row["id"] == walls.id() and row["identification"] == "Ss_25_10"
    r = change(c, sid, g["W1"], kind="classification", reference=walls.id())
    assert r.status_code == 422 and "already classified Ss_25_10 Walls" in r.json()["detail"]
    r = change(c, sid, g["W1"], kind="classification", reference=beams.id(), remove=True)
    assert r.status_code == 422 and "not classified Ss_20_10 Beams" in r.json()["detail"]
    r = change(c, sid, g["W1"], kind="classification", reference=beams.id(), replace=walls.id())
    assert r.status_code == 200
    assert r.json()["entry"]["summary"] == "wall 'W1' classified Ss_20_10 Beams (was Ss_25_10 Walls)"
    assert [x["identification"] for x in r.json()["properties"]["classifications"]] == ["Ss_20_10"]
    assert len(ws.journal(sid).entries) == 1, "one change, one entry"
    c.post(f"/api/scenes/{sid}/edits/undo", json={})
    import ifcopenshell.util.classification as uc
    assert [x.Identification for x in uc.get_references(scene.entity(g["W1"]))] == ["Ss_25_10"]
    assert [x.Identification for x in uc.get_references(scene.entity(g["W2"]))] == ["Ss_20_10"], "W2 keeps its own"


def test_muse_changes_a_property_only_when_the_person_said_the_new_value(client):
    from test_chat_edits import Scripted
    from sightline.chat import Chat, Context
    c, ws, sid, scene, g = client
    change = {"kind": "attribute", "name": "Tag", "value": "W-01"}
    model = Scripted([[("edit_property", {"element": g["W1"], "change": change})], "It needs your word.",
                      [("edit_property", {"element": g["W1"], "change": change})], "Done."])
    chat = Chat(ws, model)
    s = chat.session(None)
    chat.turn(s, "tag this wall properly", Context(sid), lambda e: None)
    assert scene.entity(g["W1"]).Tag is None and not ws.journal(sid).entries
    events = []
    chat.turn(s, "set its tag to W-01", Context(sid), events.append)
    (e,) = ws.journal(sid).entries
    assert scene.entity(g["W1"]).Tag == "W-01" and e.source == "muse" and e.kind == "property"
    assert any(ev.get("action") == "edit_kept" for ev in events if ev.get("type") == "ui")


def test_an_export_carries_the_change_and_its_stamp(client, tmp_path):
    c, ws, sid, scene, g = client
    change(c, sid, g["W2"], kind="attribute", name="Tag", value="W-02")
    out = ws.export(sid, tmp_path / "out")
    m = ifcopenshell.open(str(next(p for p in out if p.suffix == ".ifc")))
    w2 = next(e for e in m.by_type("IfcWall") if e.Name == "W2")
    assert w2.Tag == "W-02" and "ORCA_Edit" in ue.get_psets(w2)
