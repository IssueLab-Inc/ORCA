"""Bigger uploads (docs/uploads.md): gzipped parts unpacked on the way in, the cap on the unpacked size and refused
early on the body's length, the open streamed with progress, the cap published, scenes held within a byte budget."""
import gzip
import json

import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline.fixtures import build_clash_fixture, build_route_fixture
from sightline.service import Workspace


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "ws", Workspace(tmp_path / "samples"))
    monkeypatch.setattr(app_module, "_classifier", lambda: None)
    return TestClient(app_module.app)


def test_a_gzipped_ifc_is_unpacked_and_opens_under_its_own_name(client, tmp_path):
    ifc = build_clash_fixture(tmp_path / "Clash.ifc").read_bytes()
    r = client.post("/api/models/upload", files=[("files", ("Clash.ifc.gz", gzip.compress(ifc)))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"] == ["Clash.ifc"] and body["step"] == {}
    assert client.get(f"/api/scenes/{body['id']}/files/0").content == ifc


def test_the_cap_counts_the_unpacked_size_and_a_long_body_is_refused_before_it_is_read(client, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "MODEL_UPLOAD_MAX_MB", 1)
    big = b"ISO-10303-21;\n" + b"/* padding */\n" * 120_000   # 1.7 MB of text, 10 kB gzipped
    r = client.post("/api/models/upload", files=[("files", ("Big.ifc.gz", gzip.compress(big)))])
    assert r.status_code == 413 and "over 1 MB" in r.json()["detail"]
    early = client.post("/api/models/upload", content=b"x", headers={"content-length": str(3 << 20),
                                                                      "content-type": "multipart/form-data; boundary=x"})
    assert early.status_code == 413
    assert client.get("/api/models").json()["model_upload_max_mb"] == 1


def test_a_broken_archive_and_a_file_given_twice_are_refused(client, tmp_path):
    assert client.post("/api/models/upload", files=[("files", ("A.ifc.gz", b"not gzip"))]).status_code == 400
    ifc = build_clash_fixture(tmp_path / "A.ifc").read_bytes()
    twice = client.post("/api/models/upload", files=[("files", ("A.ifc", ifc)), ("files", ("A.ifc.gz", gzip.compress(ifc)))])
    assert twice.status_code == 400 and "twice" in twice.json()["detail"]
    assert client.post("/api/models/upload", files=[("files", ("notes.txt.gz", gzip.compress(b"hi")))]).status_code == 400


def test_the_streamed_open_reports_what_it_received_how_far_it_got_and_the_scene(client, tmp_path):
    ifc = build_route_fixture(tmp_path / "Route.ifc").read_bytes()
    r = client.post("/api/models/upload/stream", files=[("files", ("Route.ifc.gz", gzip.compress(ifc)))])
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines()]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "received" and events[0]["bytes"] == len(ifc)
    assert "opening" in kinds and kinds[-1] == "done"
    boxes = [e for e in events if e["type"] == "boxes"]
    assert boxes and boxes[-1]["done"] == boxes[-1]["total"] > 0
    done = events[-1]
    assert done["files"] == ["Route.ifc"] and done["revision"] == 0
    assert client.get(f"/api/scenes/{done['id']}").status_code == 200


def test_a_model_that_will_not_open_ends_the_stream_with_an_error(client):
    r = client.post("/api/models/upload/stream", files=[("files", ("Bad.ifc", b"not an ifc"))])
    events = [json.loads(line) for line in r.text.splitlines()]
    assert events[-1]["type"] == "error" and events[-1]["status"] == 400 and "Could not open" in events[-1]["detail"]


def test_open_scenes_are_held_within_a_byte_budget(tmp_path):
    folder = tmp_path / "samples"
    a, b = build_clash_fixture(folder / "A.ifc"), build_route_fixture(folder / "B.ifc")
    ws = Workspace(folder, budget_mb=0)
    ws.budget = a.stat().st_size + b.stat().st_size - 1   # room for one of them at a time
    first = ws.open(["A.ifc"])
    second = ws.open(["B.ifc"])
    assert list(ws.scenes) == [second] and first not in ws.sizes
    third = ws.open(["A.ifc"])
    assert list(ws.scenes) == [third]
    ws.budget = 1                                          # a scene over the budget alone is still kept
    assert list(ws.scenes) == [third] and ws.open(["B.ifc"]) in ws.scenes and len(ws.scenes) == 1


def test_a_wider_fix_is_not_offered_on_models_too_big_to_copy(tmp_path, monkeypatch):
    from sightline import context_planner
    folder = tmp_path / "samples"
    build_clash_fixture(folder / "A.ifc")
    ws = Workspace(folder)
    sid = ws.open(["A.ifc"])
    duct, beam = sorted(ws.scene(sid).bounds())[:2]
    context_planner.validate_objective(ws, sid, {"element_a": duct, "element_b": beam})   # small: offered
    monkeypatch.setattr(context_planner, "WIDER_MAX_MB", 1)
    ws.sizes[sid] = 5 << 20
    with pytest.raises(context_planner.ContextError) as e:
        context_planner.validate_objective(ws, sid, {"element_a": duct, "element_b": beam})
    assert e.value.status == 413 and "offered up to 1 MB. Propose fixes works at any size." in str(e.value)
