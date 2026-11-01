"""Adding and removing models in an open scene (docs/add-and-remove-models.md): the scene's own file list first."""
from pathlib import Path

import pytest

from sightline import manual
from sightline.fixtures import build_clash_fixture, build_detection_fixtures
from sightline.journal import Fenced
from sightline.scene import IfcScene
from sightline.service import StaleLayout, Workspace


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> list[Path]:
    """Structure, MEP, and a second structure model with its own GlobalIds (another build of the fixture)."""
    first = build_detection_fixtures(tmp_path_factory.mktemp("first"))
    second = build_detection_fixtures(tmp_path_factory.mktemp("second"))
    extra = first[0].parent / "Fixture-Extra.ifc"
    extra.write_bytes(second[0].read_bytes())
    return [*first, extra]


def ids(scene: IfcScene, index: int) -> set[str]:
    return {e.GlobalId for e in scene.models[index].by_type("IfcElement")}


def test_an_added_file_is_measured_alone_and_found(files, monkeypatch):
    scene = IfcScene(files[:2])
    before = dict(scene.bounds())
    measured = []
    real = IfcScene._measure

    def spy(self, indexes, progress=None):
        measured.append(list(indexes))
        return real(self, indexes, progress)

    monkeypatch.setattr(IfcScene, "_measure", spy)
    seen = []
    assert scene.add_files([files[2]], progress=lambda done, total: seen.append((done, total))) == [2]
    assert measured == [[2]], "only the new file's elements are measured"
    assert seen and seen[-1][0] == seen[-1][1]
    assert [p.name for p in scene.paths] == ["Fixture-Structure.ifc", "Fixture-MEP.ifc", "Fixture-Extra.ifc"]
    assert len(scene.models) == len(scene.unit_scales) == 3
    new = ids(scene, 2) & set(scene.bounds())
    assert new and all(scene.index_of(g) == 2 for g in new)
    for g, box in before.items():   # the boxes already there are kept as they were
        assert (scene.bounds()[g] == box).all()
    assert (scene.revision, scene.layout) == (1, 1)


def test_adding_before_any_box_is_measured_measures_nothing_yet(files, monkeypatch):
    scene = IfcScene(files[:1])
    monkeypatch.setattr(IfcScene, "_measure", lambda *a, **k: pytest.fail("measured too early"))
    assert scene.add_files(files[1:]) == [1, 2]
    assert scene._bounds is None and scene.layout == 1


def test_a_file_that_will_not_open_leaves_the_scene_as_it_was(files, tmp_path):
    scene = IfcScene(files[:2])
    scene.bounds()
    bad = tmp_path / "Broken.ifc"
    bad.write_text("not an IFC file")
    with pytest.raises(Exception):
        scene.add_files([files[2], bad])
    assert len(scene.models) == len(scene.paths) == len(scene.unit_scales) == 2
    assert (scene.revision, scene.layout) == (0, 0)


def test_removing_the_middle_file_drops_its_boxes_and_shifts_what_comes_after(files):
    scene = IfcScene(files)
    scene.bounds()
    middle, last = ids(scene, 1), ids(scene, 2)
    scene._edited = {0, 1, 2}
    scene.history = [(1, [0, 2]), (2, [1])]
    scene.revision = 2
    assert scene.remove_file(1) == files[1]
    assert [p.name for p in scene.paths] == ["Fixture-Structure.ifc", "Fixture-Extra.ifc"]
    assert len(scene.models) == len(scene.unit_scales) == 2
    assert not middle & set(scene.bounds()), "the removed file's boxes go"
    assert last & set(scene.bounds()) and all(scene.index_of(g) == 1 for g in last & set(scene.bounds()))
    assert scene._edited == {0, 1}, "the last file's mark moves down with it"
    assert scene.history == [(1, [0, 1]), (2, [])]
    assert (scene.revision, scene.layout) == (3, 1)
    assert not any(scene.has(g) for g in middle)


def test_removing_by_a_position_that_is_not_there_is_refused(files):
    scene = IfcScene(files[:2])
    with pytest.raises(IndexError):
        scene.remove_file(2)
    with pytest.raises(IndexError):
        scene.remove_file(-1)


def test_what_was_worked_out_from_the_file_list_is_worked_out_again(files):
    scene = IfcScene(files[:2])
    scene._req_teams = {"construction": ["structure", "services"]}
    scene._facets = ((0, 1), {})
    scene.add_files([files[2]])
    assert not hasattr(scene, "_req_teams") and not hasattr(scene, "_facets")


def test_a_copy_carries_the_layout(files):
    scene = IfcScene(files[:2])
    scene.add_files([files[2]])
    assert scene.snapshot().layout == 1


# ------------------------------------------------------------------------------------------------- adding


@pytest.fixture
def ws(tmp_path):
    build_clash_fixture(tmp_path / "beam.ifc", only=("beam",))
    build_clash_fixture(tmp_path / "duct.ifc", only=("duct",))
    build_clash_fixture(tmp_path / "pipe.ifc", only=("pipe",))
    return Workspace(samples=tmp_path)


def gid(ws, sid, ifc_class):
    return next(e.GlobalId for m in ws.scene(sid).models for e in m.by_type(ifc_class))


def files_of(clash: dict) -> set[str]:
    return {clash["a"]["file"], clash["b"]["file"]}


def test_a_sample_joins_an_open_scene_and_the_check_finds_its_clash(ws):
    sid = ws.open(["beam.ifc"])
    assert ws.detect_all(sid)["report"]["clashes"] == []
    size = ws.sizes[sid]
    events = []
    assert ws.add_samples(sid, ["duct.ifc"], on_event=events.append) == [1]
    assert ws.names[sid] == ["beam.ifc", "duct.ifc"] and ws.sizes[sid] > size
    assert ws.step_files(sid) == {} and ws.scene(sid).layout == 1
    assert {e["type"] for e in events} >= {"opening", "boxes"}
    (clash,) = ws.detect_all(sid)["report"]["clashes"]
    assert files_of(clash) == {"beam.ifc", "duct.ifc"} and clash["number"] == 1
    info = ws.scene_info(sid)
    assert info["files"] == ["beam.ifc", "duct.ifc"] and info["layout"] == 1


def test_adding_refuses_a_name_already_open_and_one_given_twice(ws):
    sid = ws.open(["beam.ifc", "duct.ifc"])
    with pytest.raises(ValueError, match=r"^duct\.ifc is already open\.$"):
        ws.add_samples(sid, ["pipe.ifc", "duct.ifc"])
    with pytest.raises(ValueError, match="twice"):
        ws.add_samples(sid, ["pipe.ifc", "pipe.ifc"])
    with pytest.raises(FileNotFoundError):
        ws.add_samples(sid, ["nothing.ifc"])
    assert ws.names[sid] == ["beam.ifc", "duct.ifc"] and ws.scene(sid).layout == 0


def test_adding_past_the_scene_budget_is_refused_with_the_new_total(ws):
    sid = ws.open(["beam.ifc"])
    ws.budget = ws.sizes[sid] + 10
    with pytest.raises(ValueError, match=r"over this server's .* MB"):
        ws.add_samples(sid, ["duct.ifc"])
    assert ws.names[sid] == ["beam.ifc"] and ws.scene(sid).layout == 0


def test_adding_makes_room_by_dropping_older_scenes_never_this_one(ws):
    old = ws.open(["pipe.ifc"])
    sid = ws.open(["beam.ifc"])
    ws.budget = ws.sizes[old] + ws.sizes[sid] + (ws.samples / "duct.ifc").stat().st_size - 1
    ws.add_samples(sid, ["duct.ifc"])
    assert old not in ws.scenes and sid in ws.scenes


def test_adding_clears_what_was_worked_out_from_the_files(ws):
    sid = ws.open(["beam.ifc"])
    ws._stays[sid] = ("doc", "rule")
    ws._matches[("r1", sid)] = {}
    ws._matches[("r1", "other")] = {}
    ws._patterns[("r1", sid, (), "")] = {}
    ws.add_samples(sid, ["duct.ifc"])
    assert sid not in ws._stays and ("r1", sid) not in ws._matches and ("r1", "other") in ws._matches
    assert not ws._patterns


def test_step_and_ifc_do_not_mix(ws, tmp_path):
    from test_step import write_step
    write_step(tmp_path / "Cell-A.step")
    write_step(tmp_path / "Cell-B.step", ladder_z=1500.0)
    building = ws.open(["beam.ifc"])
    with pytest.raises(ValueError, match=r"^A STEP machine can't join building models yet: open it on its own\.$"):
        ws.add_samples(building, ["Cell-A.step"])
    machine = ws.open(["Cell-A.step"])
    with pytest.raises(ValueError, match=r"^A building model can't join a STEP machine yet: open it on its own\.$"):
        ws.add_samples(machine, ["duct.ifc"])
    assert ws.add_samples(machine, ["Cell-B.step"]) == [1]
    assert ws.step_files(machine) == {0: "Cell-A.step", 1: "Cell-B.step"}
    assert ws.scene(machine).domain == "machines" and len(ws._roots[machine]) == 2
    out = ws.remove_model(machine, 0, "Cell-A.step")
    assert ws.step_files(machine) == {0: "Cell-B.step"} and out["step"] == {0: "Cell-B.step"}
    assert len(ws._roots[machine]) == 1, "the folder of the STEP removed goes with it"


# ------------------------------------------------------------------------------------------------- removing


def test_removing_refuses_a_stale_position_and_the_only_model(ws):
    sid = ws.open(["beam.ifc", "duct.ifc"])
    with pytest.raises(StaleLayout, match="The models changed: reload them."):
        ws.remove_model(sid, 0, "duct.ifc")
    with pytest.raises(StaleLayout):
        ws.remove_model(sid, 2, "pipe.ifc")
    ws.remove_model(sid, 0, "beam.ifc")
    with pytest.raises(ValueError, match=r"^This is the only model: open others instead\.$"):
        ws.remove_model(sid, 0, "duct.ifc")


def test_removing_takes_its_clashes_out_of_every_check_and_keeps_the_numbers(ws):
    sid = ws.open(["beam.ifc", "duct.ifc", "pipe.ifc"])
    beam = gid(ws, sid, "IfcBeam")
    full = ws.detect_all(sid)["report"]["clashes"]
    assert any(files_of(c) == {"beam.ifc", "duct.ifc"} for c in full)
    ws.detect(sid, [{"a": {"filter": {"when": [{"facet": "class", "op": "is", "values": ["IfcDuctSegment"]}],
                                      "invert": False}}, "b": {}}])
    revision = ws.scene(sid).revision
    out = ws.remove_model(sid, 0, "beam.ifc")
    assert out["files"] == ["duct.ifc", "pipe.ifc"] and out["layout"] == 1 and out["revision"] == revision + 1
    assert out["removed"]["clashes"] == sum("beam.ifc" in files_of(c) for c in full) > 0
    assert all("beam.ifc" not in files_of(c) for c in out["report"]["clashes"])
    for check in ws.checks[sid].checks.values():
        assert all("beam.ifc" not in (c.a.file, c.b.file) for c in check.clashes)
        assert all(beam not in (was["a"], was["b"]) for was in check.state["clashes"].values())
        assert all(beam not in pair for pair in check.state["contacts"])
    assert len(out["checks"]) == 2 and not any(c["stale"] for c in out["checks"]), \
        "removing a model makes no clash: the checks still hold"
    again = ws.detect_all(sid)["report"]["clashes"]   # run again: what was left keeps its number, nothing comes back
    assert {c["id"]: c["number"] for c in again} == \
        {c["id"]: c["number"] for c in full if "beam.ifc" not in files_of(c)}


def test_an_uploaded_model_removed_leaves_its_folder(ws, tmp_path):
    folder = tmp_path / "upload"
    folder.mkdir()
    for n in ("beam.ifc", "duct.ifc"):
        (folder / n).write_bytes((ws.samples / n).read_bytes())
    sid = ws.open_paths([folder / "beam.ifc", folder / "duct.ifc"], folder)
    ws.remove_model(sid, 1, "duct.ifc")
    assert not (folder / "duct.ifc").exists() and (folder / "beam.ifc").exists()
    assert ws.sizes[sid] == (folder / "beam.ifc").stat().st_size
    assert ws._roots[sid] == [folder]


def test_a_sample_removed_is_never_deleted(ws):
    sid = ws.open(["beam.ifc", "duct.ifc"])
    ws.remove_model(sid, 1, "duct.ifc")
    assert (ws.samples / "duct.ifc").exists()


def test_edits_in_a_removed_model_stay_in_the_log_and_are_never_undone(ws, tmp_path):
    sid = ws.open(["beam.ifc", "duct.ifc", "pipe.ifc"])
    s = ws.scene(sid)
    beam, duct, pipe = gid(ws, sid, "IfcBeam"), gid(ws, sid, "IfcDuctSegment"), gid(ws, sid, "IfcPipeSegment")
    manual.apply(ws, sid, {"op": "move", "element": duct, "delta_m": [0, 0, -0.1]}, accept_clashes=5)    # E1: duct
    manual.apply(ws, sid, {"op": "move", "element": beam, "delta_m": [0, 0, 0.05]}, accept_clashes=5)   # E2: beam
    manual.apply(ws, sid, {"op": "move", "element": pipe, "delta_m": [0, 0, -0.05]}, accept_clashes=5)  # E3: pipe
    ws.undo_edit(sid)   # E3 undone, waiting to be redone
    pipe_z = s.bounds()[pipe][0][2]
    duct_z = s.placement(duct)[2, 3]
    out = ws.remove_model(sid, 0, "beam.ifc")
    assert out["removed"]["edits"] == 1
    log = ws.journal(sid)
    e1, e2, e3 = log.entries
    assert (e1.model_removed, e2.model_removed, e3.model_removed) == (None, "beam.ifc", None)
    assert (e1.files, e3.files) == ([0], [1]), "file indexes move down with the files"
    assert s._edited == {0}, "the duct's file is still marked edited, now at index 0"
    summary = log.summary()
    assert (summary["undo"], summary["redo"]) == ("E1", "E3")
    assert summary["entries"][1]["model_removed"] == "beam.ifc"
    with pytest.raises(Fenced, match="beam.ifc, which was removed"):
        ws.undo_edit(sid, "E2")
    ws.redo_edit(sid)   # E3 again, in the pipe's file at its new index
    assert s.bounds()[pipe][0][2] == pytest.approx(pipe_z - 0.05) and s._edited == {0, 1}
    names = sorted(p.name for p in ws.export(sid, tmp_path / "out"))
    assert names == ["duct.orca.ifc", "orca-edits.csv", "orca-edits.json", "pipe.orca.ifc"]
    ws.undo_edit(sid)
    ws.undo_edit(sid)   # E1: the duct goes back up; E2 is skipped, never undone
    assert s.placement(duct)[2, 3] == pytest.approx(duct_z + 0.1)
    assert e2.state == "kept" and not log.summary()["can_undo"]


def test_an_undone_edit_in_a_removed_model_is_never_redone(ws):
    sid = ws.open(["beam.ifc", "duct.ifc"])
    beam = gid(ws, sid, "IfcBeam")
    manual.apply(ws, sid, {"op": "move", "element": beam, "delta_m": [0, 0, 0.05]}, accept_clashes=5)
    ws.undo_edit(sid)
    ws.remove_model(sid, 0, "beam.ifc")
    assert not ws.journal(sid).summary()["can_redo"]
    with pytest.raises(Fenced, match="beam.ifc, which was removed"):
        ws.redo_edit(sid, "E1")


def test_a_wider_fix_is_not_undone_once_the_models_changed(ws):
    sid = ws.open(["beam.ifc", "duct.ifc"])
    s = ws.scene(sid)
    duct = gid(ws, sid, "IfcDuctSegment")
    private = s.snapshot()
    private.translate([duct], (0, 0, -0.1))
    with ws.journal(sid).record(s, "wider", "wider", title="Wider fix") as rec:
        s.__dict__ = private.__dict__.copy()
        rec.changed, rec.files = [duct], [1]
    ws.add_samples(sid, ["pipe.ifc"])
    with pytest.raises(Fenced, match="added or removed"):
        ws.undo_edit(sid)
    assert len(ws.scene(sid).models) == 3


# ------------------------------------------------------------------------------------------------- routes


@pytest.fixture
def client(ws, monkeypatch):
    from fastapi.testclient import TestClient
    from sightline import app as app_module
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "_classifier", lambda: None)
    return TestClient(app_module.app), app_module


def events(response) -> list[dict]:
    import json
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def upload(c, sid, *files):
    return c.post(f"/api/scenes/{sid}/models/upload/stream", files=[("files", (n, data)) for n, data in files])


def test_the_routes_add_samples_and_then_the_check_finds_the_new_pair(client, ws):
    c, _ = client
    opened = c.post("/api/scenes", json={"samples": ["beam.ifc"]}).json()
    sid = opened["id"]
    assert opened["layout"] == 0 and opened["files"] == ["beam.ifc"]
    first = events(c.post(f"/api/scenes/{sid}/detect/stream", json={"all": True}))[-1]
    assert first["type"] == "done" and first["report"]["clashes"] == []
    r = c.post(f"/api/scenes/{sid}/models", json={"samples": ["duct.ifc"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["files"], body["added"], body["layout"], body["step"]) == (["beam.ifc", "duct.ifc"], [1], 1, {})
    assert body["revision"] == ws.scene(sid).revision
    assert c.get(f"/api/scenes/{sid}").json()["layout"] == 1
    done = events(c.post(f"/api/scenes/{sid}/detect/stream", json={"all": True}))[-1]
    (clash,) = done["report"]["clashes"]
    assert files_of(clash) == {"beam.ifc", "duct.ifc"} and clash["number"] == 1
    assert c.get(f"/api/scenes/{sid}/files/1").content == (ws.samples / "duct.ifc").read_bytes()


def test_the_routes_refuse_in_words(client, ws, tmp_path):
    c, _ = client
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc", "duct.ifc"]}).json()["id"]
    r = c.post(f"/api/scenes/{sid}/models", json={"samples": ["duct.ifc"]})
    assert (r.status_code, r.json()["detail"]) == (400, "duct.ifc is already open.")
    assert c.post(f"/api/scenes/{sid}/models", json={"samples": ["nothing.ifc"]}).status_code == 404
    assert c.post(f"/api/scenes/{sid}/models", json={"samples": []}).status_code == 400
    assert c.post("/api/scenes/nope/models", json={"samples": ["pipe.ifc"]}).status_code == 404
    from test_step import write_step
    step_file = write_step(tmp_path / "Cell.step")
    r = upload(c, sid, ("Cell.step", step_file.read_bytes()))
    assert (r.status_code, r.json()["detail"]) == \
        (400, "A STEP machine can't join building models yet: open it on its own.")


def test_adding_an_upload_is_one_model_upload_and_a_refusal_is_not(client, ws, monkeypatch):
    c, app_module = client
    monkeypatch.setattr(app_module, "model_upload_limit", app_module.ProposeLimit(1, 0, noun="model uploads"))
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc"]}).json()["id"]   # samples are free
    assert upload(c, sid, ("beam.ifc", b"x")).status_code == 400, "refused before it is charged"
    r = upload(c, sid, ("Mine.ifc", (ws.samples / "duct.ifc").read_bytes()))
    assert r.status_code == 200
    seen = events(r)
    assert seen[0]["type"] == "received" and {"opening", "boxes"} <= {e["type"] for e in seen}
    done = seen[-1]
    assert done["type"] == "done" and done["files"] == ["beam.ifc", "Mine.ifc"] and done["added"] == [1]
    assert done["layout"] == 1
    assert upload(c, sid, ("Other.ifc", (ws.samples / "pipe.ifc").read_bytes())).status_code == 429


def test_a_broken_upload_added_says_why_and_changes_nothing(client, ws):
    c, _ = client
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc"]}).json()["id"]
    done = events(upload(c, sid, ("Broken.ifc", b"not an IFC file")))[-1]
    assert done["type"] == "error" and done["status"] == 400 and "Could not add the models" in done["detail"]
    assert ws.names[sid] == ["beam.ifc"] and ws.scene(sid).layout == 0 and not ws._roots.get(sid)


def test_the_delete_route_guards_the_position_and_answers_what_is_left(client, ws):
    c, _ = client
    sid = c.post("/api/scenes", json={"samples": ["beam.ifc", "duct.ifc", "pipe.ifc"]}).json()["id"]
    events(c.post(f"/api/scenes/{sid}/detect/stream", json={"all": True}))
    stale = c.delete(f"/api/scenes/{sid}/models/0", params={"name": "duct.ifc"})
    assert (stale.status_code, stale.json()["detail"]) == (409, "The models changed: reload them.")
    r = c.delete(f"/api/scenes/{sid}/models/0", params={"name": "beam.ifc"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"] == ["duct.ifc", "pipe.ifc"] and body["layout"] == 1 and body["removed"]["name"] == "beam.ifc"
    assert body["removed"]["clashes"] >= 1 and body["removed"]["edits"] == 0
    assert all("beam.ifc" not in files_of(x) for x in body["report"]["clashes"])
    assert body["report"]["id"] == c.get(f"/api/scenes/{sid}/checks").json()["report_id"]
    c.delete(f"/api/scenes/{sid}/models/1", params={"name": "pipe.ifc"})
    only = c.delete(f"/api/scenes/{sid}/models/0", params={"name": "duct.ifc"})
    assert (only.status_code, only.json()["detail"]) == (400, "This is the only model: open others instead.")
    assert c.delete(f"/api/scenes/{sid}/models/0").status_code == 422, "the name is required"


# ------------------------------------------------------------------------------------------------- Northbank

STRUCTURE, MEP, ARCHITECTURE = "Northbank-Structure.ifc", "Northbank-MEP.ifc", "Northbank-Architecture.ifc"
GIRDER, SUPPLY_MAIN = "1eVHoPtl1IhAbbhivqVqb0", "2AbvqKF25LGeR0M34N_jld"   # TB-L02-01 and #042's duct (CLAUDE.md)


@pytest.fixture(scope="module")
def northbank():
    return Workspace()   # the shipped samples


def test_architecture_added_to_northbank_joins_the_list_numbers_carry_on_and_readings_follow(northbank):
    ws = northbank
    sid = ws.open([STRUCTURE, MEP])
    before = ws.detect_all(sid)["report"]["clashes"]
    assert before and all(files_of(c) <= {STRUCTURE, MEP} for c in before)
    girder = next(c for c in before if GIRDER in (c["a"]["global_id"], c["b"]["global_id"])
                  and SUPPLY_MAIN in (c["a"]["global_id"], c["b"]["global_id"]))
    register = ws.checks[sid]
    report = ws.report(register.report_id)
    read = next(c for c in report.clashes if c.id == girder["id"])
    register.keep_reading("", read, {"source": "model", "verdict": "real", "reason": "a girder"})
    ws.add_samples(sid, [ARCHITECTURE])
    after = ws.detect_all(sid)["report"]["clashes"]
    numbers = {c["id"]: c["number"] for c in before}
    assert {c["id"]: c["number"] for c in after if c["id"] in numbers} == \
        {i: n for i, n in numbers.items() if i in {c["id"] for c in after}}, "every clash there before keeps its #N"
    new = [c for c in after if c["id"] not in numbers]
    assert new and any(ARCHITECTURE in files_of(c) for c in new)
    assert min(c["number"] for c in new) > max(numbers.values()), "numbering carries on"
    carried = register.carried(ws.report(register.report_id), "")
    assert carried[girder["id"]]["verdict"] == "real", "the reading follows the clash, unchanged"


def test_structure_removed_from_northbank_takes_its_clashes_and_leaves_the_mep_edit(northbank, tmp_path):
    ws = northbank
    sid = ws.open([STRUCTURE, MEP, ARCHITECTURE])
    s = ws.scene(sid)
    ws.detect_all(sid)
    duct_z = s.placement(SUPPLY_MAIN)[2, 3]
    manual.apply(ws, sid, {"op": "move", "element": SUPPLY_MAIN, "delta_m": [0, 0, 0.4]},
                 accept_clashes=50, accept_joints=50)                                             # E1: MEP
    manual.apply(ws, sid, {"op": "move", "element": GIRDER, "delta_m": [0, 0, -0.01]},
                 accept_clashes=50, accept_joints=50)                                             # E2: Structure
    out = ws.remove_model(sid, 0, STRUCTURE)
    assert out["files"] == [MEP, ARCHITECTURE] and out["removed"]["edits"] == 1 and out["removed"]["clashes"] > 0
    structure = lambda c: STRUCTURE in files_of(c)
    assert not any(structure(c) for c in out["report"]["clashes"])
    for check in ws.checks[sid].checks.values():
        assert not any(STRUCTURE in (c.a.file, c.b.file) for c in check.clashes)
    assert s.placement(SUPPLY_MAIN)[2, 3] == pytest.approx(duct_z + 0.4), "the MEP edit stays"
    e1, e2 = ws.journal(sid).entries
    assert e2.model_removed == STRUCTURE and e1.model_removed is None
    with pytest.raises(Fenced, match="Northbank-Structure.ifc, which was removed"):
        ws.undo_edit(sid, e2.id)
    written = [p.name for p in s.write_edited(tmp_path)]
    assert written == ["Northbank-MEP.orca.ifc"], "only the files left are written"
