import ifcopenshell
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import edits
from sightline.agent import Clash, resolve
from sightline.fixtures import build_clash_fixture, build_run_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace


def _ids(scene):
    m = scene.model
    main = next(e for e in m.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    return main, m.by_type("IfcBeam")[0].GlobalId


@pytest.mark.parametrize("millimetres", [False, True])
def test_offset_up_clears_beam_and_slab_and_is_undone(tmp_path, millimetres):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc", millimetres=millimetres))
    main, beam = _ids(scene)
    count = len(list(scene.model))
    ws = Workspace(samples=tmp_path)
    ws.scenes["s"] = scene

    ok = ws.check_offset("s", main, beam, [2.0, 4.0], 0.40)
    assert ok["passed"] and ok["min_clearance_m"] == pytest.approx(0.05, abs=1e-3)
    assert len(ok["preview"]) == 5

    assert "IfcSlab" in ws.check_offset("s", main, beam, [2.0, 4.0], 0.50)["reason"]   # into the slab
    assert "IfcBeam" in ws.check_offset("s", main, beam, [2.0, 4.0], 0.30)["reason"]   # still in the beam
    assert "IfcBeam" in ws.check_offset("s", main, beam, [2.0, 2.8], 0.40)["reason"]   # riser lands in the beam

    assert len(list(scene.model)) == count                      # every trial was undone
    assert edits.run_of(scene, main).length_m == pytest.approx(6.0)


def test_kept_offset_chains_ports_and_hands_on_the_far_connection(tmp_path):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc"))
    main, _ = _ids(scene)
    end = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag != "SA-1").GlobalId
    off = edits.apply_offset(scene, main, 2.0, 4.0, 0.40)

    assert off.pieces[0] == main and len(off.pieces) == 5
    assert [scene.entity(g).Tag for g in off.pieces[1:]] == ["SA-1-SL1", "SA-1-SL2", "SA-1-SL3", "SA-1-SL4"]
    for u, v in zip(off.pieces, off.pieces[1:]):
        assert v in scene.element(u).connected
    assert set(scene.element(off.pieces[-1]).connected) == {off.pieces[-2], end}   # the end segment moved over
    assert edits.run_of(scene, main).length_m == pytest.approx(2.0 - 0.15)
    middle = scene.bounds()[off.pieces[2]]
    assert middle[0][2] == pytest.approx(2.65 + 0.40) and middle[0][0] == pytest.approx(2.15)

    out = scene.write(tmp_path / "out.ifc")
    assert len(ifcopenshell.open(str(out)).by_type("IfcDuctSegment")) == 6


def test_agent_offers_a_verified_offset(tmp_path):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc"))
    main, beam = _ids(scene)

    class Model:
        def __init__(self):
            self.texts = []

        def complete_json(self, system, text, images=None):
            self.texts.append(text)
            return {"understanding": "The main runs through the beam.", "candidates": [
                {"title": "Up 500", "kind": "offset", "move": "A", "split_m": [2.0, 4.0], "dz_m": 0.5},
                {"title": "Up 400", "kind": "offset", "move": "A", "split_m": [2.0, 4.0], "dz_m": 0.4},
            ]}

    model = Model()
    result = resolve(scene, Clash(main, beam), model, max_rounds=1)
    assert "6.00 m long" in model.texts[0] and "2.90-3.10 m along it" in model.texts[0]
    assert [(a.title, a.passed) for a in result.attempts] == [("Up 500", False), ("Up 400", True)]
    [opt] = result.options
    assert opt.kind == "offset" and opt.split_m == [2.0, 4.0] and len(opt.preview) == 5
    assert edits.run_of(scene, main).length_m == pytest.approx(6.0)


def test_unsupported_shapes_fail_with_a_reason(tmp_path):
    scene = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    duct, beam = scene.model.by_type("IfcDuctSegment")[0].GlobalId, scene.model.by_type("IfcBeam")[0].GlobalId
    ws = Workspace(samples=tmp_path)
    ws.scenes["s"] = scene
    r = ws.check_offset("s", duct, beam, [1.0, 3.0], 0.4)
    assert not r["passed"] and r["reason"].startswith("cannot offset this element")


def test_api_applies_an_offset_and_serves_the_edited_file(tmp_path, monkeypatch):
    build_run_fixture(tmp_path / "run.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "EXPORTS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["run.ifc"]}).json()["id"]
    main, beam = _ids(app_module.ws.scene(sid))

    assert c.post(f"/api/scenes/{sid}/offset/check",
                  json={"element": main, "other": beam, "split_m": [2, 4], "dz_m": 0.4}).json()["passed"]
    r = c.post(f"/api/scenes/{sid}/offset/apply", json={"element": main, "split_m": [2, 4], "dz_m": 0.4}).json()
    assert len(r["pieces"]) == 5 and r["files"] == [0]
    assert b"SA-1-SL2" in c.get(f"/api/scenes/{sid}/files/0").content
    assert c.post(f"/api/scenes/{sid}/offset/apply",
                  json={"element": beam, "split_m": [1, 2], "dz_m": 0.4}).status_code == 422
    assert c.get(f"/api/scenes/{sid}/export").status_code == 200


def test_passages_find_no_opening_in_a_solid_beam(tmp_path):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc"))
    main, beam = _ids(scene)
    assert edits.passages(scene, main, beam) == []


def test_ray_hits():
    tri = np.array([[[0, -1, -1], [0, 1, -1], [0, 0, 1]]], dtype=float)
    origins = np.array([[-1, 0, 0], [-1, 0, 2], [1, 0, 0]], dtype=float)
    assert edits._hits(origins, np.array([1.0, 0, 0]), tri).tolist() == [True, False, False]  # behind the ray: no hit


def test_propose_stream_reports_progress_then_the_result(tmp_path, monkeypatch):
    import json

    class Model:
        def complete_json(self, system, text, images=None):
            return {"understanding": "Through the beam.", "candidates": [
                {"title": "Up 400", "kind": "offset", "move": "A", "split_m": [2.0, 4.0], "dz_m": 0.4}]}

    build_run_fixture(tmp_path / "run.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path, model=Model()))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["run.ifc"]}).json()["id"]
    main, beam = _ids(app_module.ws.scene(sid))
    r = c.post(f"/api/scenes/{sid}/propose/stream", json={"element_a": main, "element_b": beam})
    events = [json.loads(line) for line in r.text.splitlines()]
    assert [e["type"] for e in events] == ["thinking", "ideas", "checking", "trial", "attempt", "result"]
    assert events[1]["understanding"] == "Through the beam." and events[4]["passed"]
    assert len(events[3]["pieces"]) == 5  # the browser shows the candidate while it is checked
    [opt] = events[-1]["options"]
    assert opt["kind"] == "offset" and len(opt["before"]) == 1 and len(opt["preview"]) == 5


def test_offset_trial_sends_the_pieces_in_place(tmp_path):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc"))
    main, beam = _ids(scene)

    class Offset:
        def complete_json(self, system, text, images=None):
            return {"understanding": "", "candidates": [{"title": "Up", "kind": "offset", "move": "A",
                                                         "split_m": [2.0, 4.0], "dz_m": 0.40}]}

    events = []
    resolve(scene, Clash(main, beam), Offset(), max_rounds=1, on_event=events.append, trials=True)
    trial = next(e for e in events if e["type"] == "trial")
    assert trial["kind"] == "offset" and trial["moved"] == [main] and len(trial["pieces"]) == 5
