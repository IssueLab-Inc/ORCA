"""The edit log (journal.py): every kept edit is an entry, undo and redo walk it, and the scene's revision only moves
forward. A trial between keeps must not break undo (edits.scratch)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline import connections, edits
from sightline.fixtures import build_run_fixture
from sightline.journal import Fenced, Journal
from sightline.service import Workspace


@pytest.fixture
def client(tmp_path, monkeypatch):
    build_run_fixture(tmp_path / "run.ifc")
    ws = Workspace(samples=tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    return TestClient(app_module.app), ws


def open_run(c):
    r = c.post("/api/scenes", json={"samples": ["run.ifc"]}).json()
    scene = app_module.ws.scene(r["id"])
    main = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    beam = scene.model.by_type("IfcBeam")[0].GlobalId
    return r["id"], scene, main, beam


def offset(c, sid, main, beam):
    return c.post(f"/api/scenes/{sid}/offset/apply",
                  json={"element": main, "other": beam, "split_m": [2.6, 3.4], "dz_m": 0.4}).json()


def test_a_kept_fix_is_an_entry_with_its_clash_and_what_it_made(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    kept = offset(c, sid, main, beam)
    assert kept["entry"]["id"] == "E1" and kept["entry"]["source"] == "fix" and kept["entry"]["kind"] == "offset"
    log = c.get(f"/api/scenes/{sid}/edits").json()
    (e,) = log["entries"]
    assert log["can_undo"] and not log["can_redo"] and log["undo"] == "E1"
    assert e["clashes"] == [{"id": None, "pair": [main, beam]}]
    assert main in e["elements"] and len(e["created"]) == 8 and e["removed"] == []
    assert e["names"][main].startswith("IfcDuctSegment") and e["when"].endswith("+00:00")
    assert e["summary"] and e["check"]["verified"] is True
    csv = c.get(f"/api/scenes/{sid}/edits?format=csv")
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[1].startswith("E1,")


def test_undo_puts_the_model_back_and_redo_makes_it_again(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    depth = scene.entity(main).Representation.Representations[0].Items[0].Depth
    box = scene.bounds()[main].copy()
    kept = offset(c, sid, main, beam)
    pieces = kept["pieces"]
    assert scene.entity(main).Representation.Representations[0].Items[0].Depth < depth
    undone = c.post(f"/api/scenes/{sid}/edits/undo", json={}).json()
    assert undone["entry"]["state"] == "undone" and undone["revision"] == 2 and undone["revision_before"] == 1
    assert sorted(undone["removed"]) == sorted(pieces[1:])
    assert [m["global_id"] for m in undone["meshes"]] == [main]
    assert scene.entity(main).Representation.Representations[0].Items[0].Depth == pytest.approx(depth)
    assert np.allclose(scene.bounds()[main], box) and not any(g in scene.bounds() for g in pieces[1:])
    assert not scene._edited and undone["can_redo"] and not undone["can_undo"]
    redone = c.post(f"/api/scenes/{sid}/edits/redo", json={}).json()
    assert redone["revision"] == 3 and redone["entry"]["state"] == "kept" and redone["removed"] == []
    assert all(g in scene.bounds() for g in pieces) and scene._edited == {0}
    assert scene.entity(main).Representation.Representations[0].Items[0].Depth < depth


def test_undo_still_works_after_trials_and_a_checked_move(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    offset(c, sid, main, beam)
    run = connections.run(scene, main)
    v = c.post(f"/api/scenes/{sid}/verify", json={"moved": run, "delta_m": [0.0, 0.0, -0.3]}).json()
    assert "passed" in v
    c.post(f"/api/scenes/{sid}/offset/check", json={"element": main, "other": beam, "split_m": [2.6, 3.4], "dz_m": 0.3})
    assert c.post(f"/api/scenes/{sid}/edits/undo", json={}).status_code == 200


def test_a_move_is_logged_and_undone(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    z = scene.placement(main)[2, 3]
    kept = c.post(f"/api/scenes/{sid}/apply", json={"moved": [main], "delta_m": [0, 0, -0.4], "obstacles": [beam]}).json()
    assert kept["entry"]["kind"] == "move" and "down" in kept["entry"]["summary"]
    c.post(f"/api/scenes/{sid}/edits/undo", json={"entry": "E1"})
    assert scene.placement(main)[2, 3] == pytest.approx(z)


def test_only_the_newest_is_undone_and_an_edit_outside_the_log_fences_it(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    kept = offset(c, sid, main, beam)
    with ws.journal(sid).record(scene, "you", "push_pull") as rec, edits.kept_files(scene, {0}):
        edits.stretch(scene, kept["pieces"][4], "end", 0.05)
    assert rec.entry.id == "E2"
    assert c.post(f"/api/scenes/{sid}/edits/undo", json={"entry": "E1"}).status_code == 409
    ws.apply(sid, [beam], [0.0, 0.0, 0.5])   # a primitive, not through the log
    r = c.post(f"/api/scenes/{sid}/edits/undo", json={})
    assert r.status_code == 409 and "outside the log" in r.json()["detail"]


def test_a_follow_up_on_what_a_fix_made_follows_it_and_carries_its_clash(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    kept = offset(c, sid, main, beam)
    middle = kept["pieces"][4]
    j = ws.journal(sid)
    with j.record(scene, "you", "push_pull", summary="middle 50 mm longer") as rec, edits.kept_files(scene, {0}):
        edits.stretch(scene, middle, "end", 0.05)
        rec.changed = [middle]
    e = rec.entry
    assert e.follows == ["E1"] and e.clashes == [{"id": None, "pair": [main, beam]}]
    assert [x.id for x in j.for_clash(None, [beam, main])] == ["E1", "E2"]
    assert middle in j.made_from(main)


def test_nothing_changed_is_no_entry_and_an_error_is_no_entry(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    j = ws.journal(sid)
    with j.record(scene, "you", "push_pull") as rec, edits.kept_files(scene, {0}):
        pass
    assert rec.entry is None and not j.entries
    with pytest.raises(edits.Unsupported):
        with j.record(scene, "you", "push_pull"), edits.kept_files(scene, {0}):
            edits.stretch(scene, main, "end", -100.0)
    assert not j.entries


def test_a_wider_fix_swap_is_undone_by_putting_the_state_back(client):
    c, ws = client
    sid, scene, main, beam = open_run(c)
    z = scene.placement(main)[2, 3]
    j = Journal()
    private = scene.snapshot()
    with edits.kept_files(private, {0}):
        private.translate([main], (0.0, 0.0, 0.2))
    private.bump([0])
    with j.record(scene, "wider", "wider") as rec:
        scene.__dict__ = private.__dict__.copy()
        rec.changed, rec.files = [main], [0]
    assert rec.entry.elements == [main] and rec.entry.files == [0]
    assert scene.placement(main)[2, 3] == pytest.approx(z + 0.2)
    rev = scene.revision
    j.undo(scene)
    assert scene.placement(main)[2, 3] == pytest.approx(z) and scene.revision == rev + 1
    j.redo(scene)
    assert scene.placement(main)[2, 3] == pytest.approx(z + 0.2) and scene.revision == rev + 2
    with pytest.raises(Fenced):
        j.redo(scene)
