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


def beam_of(scene):
    return scene.model.by_type("IfcBeam")[0].GlobalId


def drop(c, r, scene, main, dz=-0.4):
    """Keep a move of the supply main's run down past the beam (-0.4 m leaves 50 mm under it)."""
    return c.post(f"/api/scenes/{r['id']}/apply", json={"moved": [main], "delta_m": [0, 0, dz],
                                                         "obstacles": [beam_of(scene)]}).json()


def test_opening_says_the_revision_the_page_starts_from(client):
    c, ws = client
    r, _, _ = open_run(c)
    assert r["revision"] == 0
    assert c.get(f"/api/scenes/{r['id']}").json()["revision"] == 0


def test_an_offset_comes_back_as_its_pieces_triangles(client):
    c, ws = client
    r, scene, main = open_run(c)
    kept = c.post(f"/api/scenes/{r['id']}/offset/apply",
                  json={"element": main, "other": beam_of(scene), "split_m": [2.6, 3.4], "dz_m": 0.4}).json()
    assert kept["scene_id"] == r["id"] and kept["revision_before"] == 0 and kept["revision"] == 1
    assert [m["global_id"] for m in kept["meshes"]] == kept["pieces"] and len(kept["pieces"]) == 9
    first = kept["meshes"][0]
    assert first["file"] == 0 and len(first["normals"]) == len(first["verts"]) and first["faces"]
    assert first["color"] is None or len(first["color"]) == 4


def test_a_move_a_route_and_a_plan_come_back_as_meshes_too(client):
    c, ws = client
    r, scene, main = open_run(c)
    run = connections.run(scene, main)   # the supply main and its end segment: a move takes the whole run
    moved = drop(c, r, scene, main)
    assert {m["global_id"] for m in moved["meshes"]} == set(run) and moved["revision"] == 1
    plan = c.post(f"/api/scenes/{r['id']}/plan/apply", json={"options": [
        {"kind": "move", "moved": [main], "delta_m": [0, 0, -0.1], "pair": [main, beam_of(scene)]}]}).json()
    assert plan["revision_before"] == 1 and plan["revision"] == 2 and [m["global_id"] for m in plan["meshes"]] == run
    o = c.post("/api/scenes", json={"samples": ["route.ifc"]}).json()
    route_scene = ws.scene(o["id"])
    duct = next(e for e in route_scene.model.by_type("IfcDuctSegment") if e.Tag == "RT-2").GlobalId
    b2, b4 = (next(e.GlobalId for e in route_scene.model.by_type("IfcColumn") if e.Name == n) for n in ("Column B2", "Column B4"))
    route = c.post(f"/api/scenes/{o['id']}/fix/apply", json={"option": {
        "title": "Round both", "kind": "route", "moved": [duct], "delta_m": [0, 0.45, 0], "pair": [duct, b2], "others": [b4],
        "edit": {"steps": [{"from_m": 1.4, "to_m": 2.6, "side_m": 0.45}, {"from_m": 3.4, "to_m": 4.6, "side_m": 0.45}]}}}).json()
    assert [m["global_id"] for m in route["meshes"]] == route["pieces"] and len(route["pieces"]) == 17


def test_no_meshes_when_an_element_will_not_triangulate_or_there_is_too_much(client, monkeypatch):
    c, ws = client
    r, scene, main = open_run(c)
    monkeypatch.setattr(Workspace, "PATCH_MAX_VERTS", 10)
    kept = drop(c, r, scene, main)
    assert kept["meshes"] is None and kept["revision"] == 1  # the page reloads the file
    monkeypatch.setattr(Workspace, "PATCH_MAX_VERTS", 500_000)

    def broken(*a, **k):
        raise RuntimeError("no shape")
    monkeypatch.setattr(edits, "meshes", broken)
    kept = drop(c, r, scene, main, -0.1)
    assert kept["meshes"] is None and kept["files"] == [0]


def test_every_reply_says_which_files_each_revision_changed(client):
    c, ws = client
    r, scene, main = open_run(c)
    drop(c, r, scene, main)
    kept = drop(c, r, scene, main, -0.1)
    # A page still at revision 0 missed the first move: it reloads file 0 as well as this fix's own.
    assert kept["revision_before"] == 1 and kept["history"] == [[1, [0]], [2, [0]]]
    assert scene.snapshot().history == scene.history


def test_an_unstyled_element_keeps_no_colour_when_a_fix_is_kept(client):
    c, ws = client
    r, scene, main = open_run(c)
    assert not scene.entity(main).Representation.Representations[0].Items[0].StyledByItem   # the fixture's duct
    kept = drop(c, r, scene, main)
    # the page keeps the colour it drew, not IfcOpenShell's class default
    assert kept["meshes"] and all(m["color"] is None for m in kept["meshes"])


def test_a_move_keeps_its_whole_run(client):
    """Asked to move the main alone, the server keeps its run: the segment joined to its end comes too, patched in
    place (a move that would pull a joint apart is refused: test_connections)."""
    c, ws = client
    r, scene, main = open_run(c)
    run = connections.run(scene, main)
    kept = drop(c, r, scene, main)
    assert len(run) == 2 and set(kept["changed"]) == set(run) and {m["global_id"] for m in kept["meshes"]} == set(run)
