import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline.fixtures import build_clash_fixture
from sightline.service import Workspace


def test_open_verify_apply_export(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "EXPORTS", tmp_path)
    c = TestClient(app_module.app)

    assert c.get("/api/samples").json() == ["fixture-clash.ifc"]
    sid = c.post("/api/scenes", json={"samples": ["fixture-clash.ifc"]}).json()["id"]
    duct = app_module.ws.scene(sid).model.by_type("IfcDuctSegment")[0].GlobalId

    assert c.post(f"/api/scenes/{sid}/verify", json={"moved": [duct], "delta_m": [0, 0, -0.4]}).json()["passed"] is False
    assert c.post(f"/api/scenes/{sid}/verify", json={"moved": [duct], "delta_m": [0, 0, -0.8]}).json()["passed"] is True
    c.post(f"/api/scenes/{sid}/apply", json={"moved": [duct], "delta_m": [0, 0, -0.8]})
    r = c.get(f"/api/scenes/{sid}/export")
    assert r.status_code == 200 and r.content.startswith(b"ISO-10303-21")


def test_sample_names_cannot_escape_the_samples_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    assert c.post("/api/scenes", json={"samples": ["../pyproject.toml"]}).status_code == 404


def test_federated_set_exports_only_the_edited_file(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "structure.ifc", only=("beam",))
    build_clash_fixture(tmp_path / "services.ifc", only=("duct", "pipe"))
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "EXPORTS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    c = TestClient(app_module.app)

    sid = c.post("/api/scenes", json={"samples": ["structure.ifc", "services.ifc"]}).json()["id"]
    assert c.get(f"/api/scenes/{sid}/files/1").content.startswith(b"ISO-10303-21")
    assert c.get(f"/api/scenes/{sid}/export").status_code == 409  # nothing changed yet

    duct = app_module.ws.scene(sid).models[1].by_type("IfcDuctSegment")[0].GlobalId
    assert c.post(f"/api/scenes/{sid}/verify", json={"moved": [duct], "delta_m": [0, 0, 0]}).json()["passed"] is False
    assert c.get(f"/api/scenes/{sid}/export").status_code == 409  # a check moves and moves back: still nothing changed
    c.post(f"/api/scenes/{sid}/apply", json={"moved": [duct], "delta_m": [0, 0, -0.8]})
    r = c.get(f"/api/scenes/{sid}/export")
    assert r.status_code == 200 and "services.orca.ifc" in r.headers["content-disposition"]


def test_export_carries_every_accepted_fix_and_no_tried_ones(tmp_path, monkeypatch):
    """Offsets, moves and trials in one session: the exported files hold all the kept edits, and only those."""
    import io
    import zipfile

    import ifcopenshell
    import ifcopenshell.util.placement
    from sightline import agent
    from sightline.fixtures import build_run_fixture

    build_run_fixture(tmp_path / "services.ifc")
    build_clash_fixture(tmp_path / "structure.ifc", only=("beam",))
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    monkeypatch.setattr(app_module, "EXPORTS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["services.ifc", "structure.ifc"]}).json()["id"]
    scene = app_module.ws.scene(sid)
    services, structure = scene.models
    main = next(e for e in services.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    beam = services.by_type("IfcBeam")[0].GlobalId
    slab = services.by_type("IfcSlab")[0].GlobalId
    other_beam = structure.by_type("IfcBeam")[0].GlobalId

    agent._try_move(scene, {"title": "tried, not kept", "delta_m": [0, 0, -1.0]}, other_beam, 0.025)
    agent._try_offset(scene, {"split_m": [2.0, 4.0], "dz_m": 0.5}, main, beam, 0.025)
    assert c.get(f"/api/scenes/{sid}/export").status_code == 409  # trials only

    pieces = c.post(f"/api/scenes/{sid}/offset/apply", json={"element": main, "split_m": [2.0, 4.0], "dz_m": 0.4}).json()["pieces"]
    c.post(f"/api/scenes/{sid}/apply", json={"moved": [slab], "delta_m": [0, 0, 0.1]})        # same file, second fix
    c.post(f"/api/scenes/{sid}/apply", json={"moved": [other_beam], "delta_m": [0.5, 0, 0]})  # another discipline

    r = c.get(f"/api/scenes/{sid}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].endswith('filename="orca-export.zip"')  # the files share no project name
    files = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(files.namelist()) == ["services.orca.ifc", "structure.orca.ifc"]
    out = ifcopenshell.file.from_string(files.read("services.orca.ifc").decode())
    assert all(out.by_guid(g) for g in pieces)                                   # the offset's five pieces
    z = lambda m, g: ifcopenshell.util.placement.get_local_placement(m.by_guid(g).ObjectPlacement)[2, 3]
    assert z(out, slab) == pytest.approx(z(services, slab))                       # the live model, moved
    assert z(out, slab) == pytest.approx(3.5)                                     # 3.4 + 0.1
    moved = ifcopenshell.file.from_string(files.read("structure.orca.ifc").decode())
    x = ifcopenshell.util.placement.get_local_placement(moved.by_guid(other_beam).ObjectPlacement)[0, 3]
    assert x == pytest.approx(0.5)                                                # the kept move, not the tried one


def test_a_multi_file_export_is_named_for_its_project():
    northbank = ["Northbank-Structure.ifc", "Northbank-MEP.ifc", "Northbank-Architecture.ifc", "Northbank-Site.ifc"]
    assert app_module.export_zip_name(northbank) == "Northbank-orca.zip"
    assert app_module.export_zip_name(["PC-03-Palletising-Cell-RevA.step"]) == "PC-03-Palletising-Cell-RevA-orca.zip"
    assert app_module.export_zip_name(["services.ifc", "structure.ifc"]) == "orca-export.zip"
    assert app_module.export_zip_name(['Block "A"/1-MEP.ifc', 'Block "A"/1-Structure.ifc']) == "Block -A-1-orca.zip"
    assert app_module.export_zip_name([]) == "orca-export.zip"


def test_a_page_can_reopen_a_scene_the_server_still_holds(tmp_path, monkeypatch):
    build_clash_fixture(tmp_path / "fixture-clash.ifc")
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["fixture-clash.ifc"]}).json()["id"]
    info = c.get(f"/api/scenes/{sid}").json()
    assert info["files"] == ["fixture-clash.ifc"] and info["step"] == {} and info["detection"] is None
    c.post(f"/api/scenes/{sid}/detect/stream", json={}).read()
    detection = c.get(f"/api/scenes/{sid}").json()["detection"]
    assert detection["report_id"] in app_module.ws.reports and detection["coverage"]
    assert c.get("/api/scenes/nothing-here").status_code == 404


def test_eviction_spares_what_live_links_point_at(tmp_path):
    for name in ("a.ifc", "b.ifc", "c.ifc"):
        build_clash_fixture(tmp_path / name)
    kept: set[str] = set()
    ws = Workspace(samples=tmp_path, max_scenes=2, keep=lambda: kept)
    first = ws.open(["a.ifc"])
    kept.add(first)                       # an agent link points at the oldest scene
    second = ws.open(["b.ifc"])
    ws.open(["c.ifc"])                    # one too many: the unlinked one goes, not the oldest
    assert first in ws.scenes and second not in ws.scenes
