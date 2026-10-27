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
    c.post(f"/api/scenes/{sid}/apply", json={"moved": [duct], "delta_m": [0, 0, -0.8]})
    r = c.get(f"/api/scenes/{sid}/export")
    assert r.status_code == 200 and "services.sightline.ifc" in r.headers["content-disposition"]
