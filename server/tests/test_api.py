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
    sid = c.post("/api/scenes", json={"sample": "fixture-clash.ifc"}).json()["id"]
    duct = app_module.ws.scene(sid).model.by_type("IfcDuctSegment")[0].GlobalId

    assert c.post(f"/api/scenes/{sid}/verify", json={"moved": [duct], "delta_m": [0, 0, -0.4]}).json()["passed"] is False
    assert c.post(f"/api/scenes/{sid}/verify", json={"moved": [duct], "delta_m": [0, 0, -0.8]}).json()["passed"] is True
    c.post(f"/api/scenes/{sid}/apply", json={"moved": [duct], "delta_m": [0, 0, -0.8]})
    r = c.get(f"/api/scenes/{sid}/export")
    assert r.status_code == 200 and r.content.startswith(b"ISO-10303-21")


def test_sample_names_cannot_escape_the_samples_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ws", Workspace(samples=tmp_path))
    c = TestClient(app_module.app)
    assert c.post("/api/scenes", json={"sample": "../pyproject.toml"}).status_code == 404
