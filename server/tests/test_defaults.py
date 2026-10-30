"""Nothing about one project, domain, demo or vendor is fixed in code: the requirements file says whether a project is
a building or a machine and what stays in place; the demos live in demos.py with their own requirements; a check
keeps the clearance the requirements ask for; model names, prices and limits are settings."""
import json

import pytest

from sightline import demos, domains, meta_client, requirements
from sightline.fixtures import build_clash_fixture
from sightline.service import Workspace


@pytest.fixture()
def ws(tmp_path):
    build_clash_fixture(tmp_path / "f.ifc")
    return Workspace(samples=tmp_path)


def _ids(ws, sid):
    s = ws.scene(sid)
    by = {s.entity(g).is_a(): g for g in s.bounds()}
    return by["IfcBeam"], by["IfcDuctSegment"]


@pytest.fixture()
def using():
    tokens = []

    def enter(doc):
        tokens.append(requirements.enter(requirements.register(doc)))
    yield enter
    for t in reversed(tokens):
        requirements.leave(t)


def test_old_files_keep_their_id_and_new_fields_round_trip():
    old = requirements.parse({"format": requirements.FORMAT, "name": "x"})
    assert "domain" not in old.to_dict() and "stays" not in old.to_dict()
    new = requirements.parse({**old.to_dict(), "domain": "machines", "stays": ["IfcColumn", "not a class"]})
    assert (new.domain, new.stays) == ("machines", ["IfcColumn"])
    assert requirements.parse(new.to_dict()).to_dict() == new.to_dict()
    assert requirements.parse({**old.to_dict(), "domain": "spaceships"}).domain is None
    # A domain changes the triage voice, so it is part of what decides sharing a triage run; unset keeps old keys.
    assert requirements.model_key(old) != requirements.model_key(new)


def test_the_requirements_decide_the_domain_and_what_stays(ws, using):
    sid = ws.open(["f.ifc"])
    beam, duct = _ids(ws, sid)
    scene = ws.scene(sid)
    # Without requirements: a building, its frame in place.
    assert domains.of(ws, sid) == "construction" and scene.stays(beam) and not scene.stays(duct)
    # A file that says machine, with its own list: the beam may move, the duct may not.
    using(requirements.parse({"format": requirements.FORMAT, "domain": "machines", "stays": ["IfcDuctSegment"]}))
    assert domains.of(ws, sid) == "machines"
    assert not scene.stays(beam) and scene.stays(duct)
    assert scene.element(duct).fixed


def test_a_group_never_edited_stays_in_place(ws, using):
    sid = ws.open(["f.ifc"])
    beam, duct = _ids(ws, sid)
    doc = requirements.default_doc(ws.scene(sid))
    group = requirements.Matcher(ws.scene(sid), doc).group_of(duct)
    doc.who_moves = [requirements.Mover(group=m.group, edits="none" if m.group == group.id else m.edits)
                     for m in doc.who_moves]
    using(doc)
    assert ws.scene(sid).stays(duct)


def test_a_check_keeps_the_clearance_the_requirements_ask_for(ws, using):
    sid = ws.open(["f.ifc"])
    beam, duct = _ids(ws, sid)
    assert ws.clearance(sid, duct, beam) == requirements.DEFAULT_CLEARANCE_M
    strict = requirements.default_doc(ws.scene(sid))
    strict.strictness = "exacting"
    using(strict)
    assert ws.clearance(sid, duct, beam) == pytest.approx(0.05)
    assert ws.clearance(sid) == pytest.approx(0.05)   # no pair: the requirements' floor


def test_the_demos_live_in_one_place_with_their_own_requirements():
    nb = demos.find(["Northbank-MEP.ifc", "Northbank-Structure.ifc"])
    assert nb and nb.id == "northbank"
    assert demos.find(["Northbank-MEP.ifc", "Elsewhere.ifc"]) is None and demos.find([]) is None
    for d in demos.DEMOS:
        doc = requirements.parse(json.loads((demos.HERE / d.requirements).read_text()))
        assert doc.domain == d.kind and doc.stays == list(domains.STAYS[d.kind])
        assert {m.edits for m in doc.who_moves} == {"any"}   # off, they decide only the domain and what stays
    listed = demos.listing(["Northbank-Architecture.ifc", "Northbank-MEP.ifc", "Northbank-Site.ifc",
                            "Northbank-Structure.ifc", "Northbank-Grids.ifc", "Other.ifc"])
    assert [d["id"] for d in listed] == ["northbank"] and listed[0]["context"] == ["Northbank-Grids.ifc"]
    assert demos.requirements_for(["Other.ifc"]) is None


def test_model_names_and_prices_are_settings(monkeypatch):
    assert meta_client.model_label("muse-wonder-1.0") == "Muse Wonder"
    assert meta_client.model_label("muse-spark-open") == "Muse Spark Open"   # the longest prefix wins
    monkeypatch.setenv("SIGHTLINE_MODEL_LABELS", json.dumps({"acme-coder": "Acme Coder"}))
    monkeypatch.setenv("SIGHTLINE_MODEL_PRICES", json.dumps({"acme-coder": [1, 2]}))
    assert meta_client.model_label("acme-coder-7b") == "Acme Coder"
    assert meta_client.cost("acme-coder-7b", 1_000_000, 1_000_000) == pytest.approx(3.0)
    monkeypatch.setenv("META_MODEL", "acme-coder-7b")
    assert meta_client.labels()["proposal"] == "Acme Coder"
    monkeypatch.setenv("META_API_KEY", "k")
    monkeypatch.setenv("META_STREAMS_REASONING", "0")
    assert not meta_client.MetaChatModel().streams_reasoning
    monkeypatch.setenv("META_STREAMS_REASONING", "1")
    assert meta_client.MetaChatModel(base_url="https://elsewhere.example/v1").streams_reasoning


def test_the_mcp_server_names_no_deploy_unless_told(monkeypatch):
    from sightline import mcp_server
    monkeypatch.delenv("SIGHTLINE_PUBLIC_URL", raising=False)
    assert mcp_server.build(lambda: None)._lowlevel_server.website_url is None
    monkeypatch.setenv("SIGHTLINE_PUBLIC_URL", "https://orca.example")
    assert mcp_server.build(lambda: None)._lowlevel_server.website_url == "https://orca.example"


def test_voice_leans_on_the_domain_and_the_open_models_not_a_demo(ws, monkeypatch):
    from sightline import app as app_module
    monkeypatch.setattr(app_module, "ws", ws)
    sid = ws.open(["f.ifc"])
    words = app_module._voice_words(None, sid)
    assert "Northbank" not in words and "beam" in words
