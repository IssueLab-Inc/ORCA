"""Keeping a fix sends the page what changed (Workspace.patch), so it updates its model in place instead of reloading
the whole file: the changed and new elements' triangles, with normals and colour, and the scene's revisions."""
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import connections, edits
from sightline.fixtures import build_route_fixture, build_run_fixture
from sightline.service import Workspace


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_run_fixture(tmp_path / "run.ifc")
    build_route_fixture(tmp_path / "route.ifc")
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    return TestClient(app_module.app), ws


def open_run(c):
    r = c.post("/api/scenes", json={"samples": ["run.ifc"]}).json()
    scene = app_module.ws.scene(r["id"])
    main = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    return r, scene, main


def whole(scene, main):
    """The duct's run: it and the segment joined to its end (a move of the duct alone would pull that joint apart)."""
    return connections.run(scene, main)


def test_opening_says_the_revision_the_page_starts_from(client):
    c, ws = client
    r, _, _ = open_run(c)
    assert r["revision"] == 0
    assert c.get(f"/api/scenes/{r['id']}").json()["revision"] == 0


def test_an_offset_comes_back_as_its_pieces_triangles(client):
    c, ws = client
    r, scene, main = open_run(c)
    kept = c.post(f"/api/scenes/{r['id']}/offset/apply", json={"element": main, "split_m": [2.6, 3.4], "dz_m": 0.4}).json()
    assert kept["scene_id"] == r["id"] and kept["revision_before"] == 0 and kept["revision"] == 1
    assert [m["global_id"] for m in kept["meshes"]] == kept["pieces"] and len(kept["pieces"]) == 9
    first = kept["meshes"][0]
    assert first["file"] == 0 and len(first["normals"]) == len(first["verts"]) and first["faces"]
    assert first["color"] is None or len(first["color"]) == 4


def test_a_move_a_route_and_a_plan_come_back_as_meshes_too(client):
    c, ws = client
    r, scene, main = open_run(c)
    run = whole(scene, main)
    moved = c.post(f"/api/scenes/{r['id']}/apply", json={"moved": run, "delta_m": [0, 0, -0.2]}).json()
    assert [m["global_id"] for m in moved["meshes"]] == run and moved["revision"] == 1
    plan = c.post(f"/api/scenes/{r['id']}/plan/apply",
                  json={"options": [{"kind": "move", "moved": run, "delta_m": [0, 0, 0.2]}]}).json()
    assert plan["revision_before"] == 1 and plan["revision"] == 2 and [m["global_id"] for m in plan["meshes"]] == run
    o = c.post("/api/scenes", json={"samples": ["route.ifc"]}).json()
    duct = next(e for e in ws.scene(o["id"]).model.by_type("IfcDuctSegment") if e.Tag == "RT-2").GlobalId
    route = c.post(f"/api/scenes/{o['id']}/fix/apply", json={"option": {
        "title": "Round both", "kind": "route", "moved": [duct], "delta_m": [0, 0.45, 0],
        "edit": {"steps": [{"from_m": 1.4, "to_m": 2.6, "side_m": 0.45}, {"from_m": 3.4, "to_m": 4.6, "side_m": 0.45}]}}}).json()
    assert [m["global_id"] for m in route["meshes"]] == route["pieces"] and len(route["pieces"]) == 17


def test_no_meshes_when_an_element_will_not_triangulate_or_there_is_too_much(client, monkeypatch):
    c, ws = client
    r, scene, main = open_run(c)
    monkeypatch.setattr(Workspace, "PATCH_MAX_VERTS", 10)
    kept = c.post(f"/api/scenes/{r['id']}/apply", json={"moved": whole(scene, main), "delta_m": [0, 0, -0.2]}).json()
    assert kept["meshes"] is None and kept["revision"] == 1  # the page reloads the file
    monkeypatch.setattr(Workspace, "PATCH_MAX_VERTS", 500_000)

    def broken(*a, **k):
        raise RuntimeError("no shape")
    monkeypatch.setattr(edits, "meshes", broken)
    kept = c.post(f"/api/scenes/{r['id']}/apply", json={"moved": whole(scene, main), "delta_m": [0, 0, 0.2]}).json()
    assert kept["meshes"] is None and kept["files"] == [0]


def test_every_reply_says_which_files_each_revision_changed(client):
    c, ws = client
    r, scene, main = open_run(c)
    c.post(f"/api/scenes/{r['id']}/apply", json={"moved": whole(scene, main), "delta_m": [0, 0, -0.2]})
    kept = c.post(f"/api/scenes/{r['id']}/offset/apply", json={"element": main, "split_m": [2.6, 3.4], "dz_m": 0.6}).json()
    # A page still at revision 0 missed the move: it reloads file 0 as well as this fix's own.
    assert kept["revision_before"] == 1 and kept["history"] == [[1, [0]], [2, [0]]]
    assert scene.snapshot().history == scene.history


def test_an_unstyled_element_keeps_no_colour_when_a_fix_is_kept(client):
    c, ws = client
    r, scene, main = open_run(c)
    assert not scene.entity(main).Representation.Representations[0].Items[0].StyledByItem   # the fixture's duct
    kept = c.post(f"/api/scenes/{r['id']}/apply", json={"moved": whole(scene, main), "delta_m": [0, 0, -0.2]}).json()
    assert kept["meshes"][0]["color"] is None   # the page keeps the colour it drew, not IfcOpenShell's class default


def test_a_move_keeps_its_joints_or_is_not_kept(client, monkeypatch):
    c, ws = client
    r, scene, main = open_run(c)
    end = next(g for g in whole(scene, main) if g != main)
    kept = c.post(f"/api/scenes/{r['id']}/apply", json={"moved": [main], "delta_m": [0, 0, -0.2]}).json()
    assert kept["changed"] == [main, end] and [m["global_id"] for m in kept["meshes"]] == [main, end]  # taken along
    monkeypatch.setenv("SIGHTLINE_CONNECTED_MOVES", "refuse")
    refused = c.post(f"/api/scenes/{r['id']}/apply", json={"moved": [main], "delta_m": [0, 0, 0.2]})
    assert refused.status_code == 422 and "would pull it apart from" in refused.json()["detail"]
    assert scene.revision == 1
