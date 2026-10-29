"""One registry of fix kinds: the agent tries only kinds it knows, ranks plain geometry fixes first, checks a split
run's end pieces against every obstacle it was told about, and one endpoint keeps a fix of any kind."""
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import pytest
from fastapi.testclient import TestClient

from sightline import agent, plans, requirements
from sightline.agent import Attempt, Clash, Option, resolve
from sightline.fixtures import _box, build_run_fixture
from sightline.scene import IfcScene


class Scripted:
    """Stands in for Muse Spark: one reply per round, from a list."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls = []

    def complete_json(self, system, text, images=None):
        self.calls.append(text)
        return self.rounds[min(len(self.calls), len(self.rounds)) - 1]


def _run_with_second_obstacle(tmp_path: Path) -> Path:
    """The offset fixture plus a column the supply main runs through 0.5 m from its start, away from the beam."""
    path = build_run_fixture(tmp_path / "run.ifc")
    model = ifcopenshell.open(str(path))
    body = next(c for c in model.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
    storey = model.by_type("IfcBuildingStorey")[0]
    column = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcColumn", name="Column C1")
    ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[column])
    _box(model, body, column, (0.2, 0.2, 2.4), (0.4, -0.1, 1.0))
    model.write(str(path))
    return path


def _ids(scene: IfcScene):
    main = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    return main, scene.model.by_type("IfcBeam")[0].GlobalId, scene.model.by_type("IfcColumn")[0].GlobalId


def test_an_unknown_kind_is_refused_not_tried_as_a_move(tmp_path):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc"))
    main = next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId
    beam = scene.model.by_type("IfcBeam")[0].GlobalId
    model = Scripted({"candidates": [{"title": "Teleport it", "kind": "teleport", "move": "A", "delta_m": [0, 0, -2]}]})
    result = resolve(scene, Clash(main, beam), model, max_rounds=1)
    assert [a.passed for a in result.attempts] == [False]
    assert "unknown kind 'teleport'" in result.attempts[0].reason
    assert not result.options


def test_split_ends_are_checked_against_every_obstacle_the_agent_was_told_about(tmp_path):
    scene = IfcScene(_run_with_second_obstacle(tmp_path))
    main, beam, column = _ids(scene)
    offset = {"title": "Offset up 400", "kind": "offset", "move": "A", "split_m": [2.6, 3.4], "dz_m": 0.4}
    # Told only about the beam, the offset clears it: its first piece still runs through the column, but a shortened
    # end piece is only checked against the obstacle.
    alone = resolve(scene, Clash(main, beam), Scripted({"candidates": [offset]}), max_rounds=1)
    assert alone.attempts[0].passed
    # Told the run also meets the column (a plan's merged item), the same offset fails on it, and Muse hears where.
    model = Scripted({"candidates": [offset]})
    told = resolve(scene, Clash(main, beam, others=[column]), model, max_rounds=1)
    assert not told.attempts[0].passed
    assert column in told.attempts[0].hit_ids
    assert told.attempts[0].where
    assert "Column C1" in model.calls[0]  # the column's place along the run is in the text


def test_feedback_names_each_kind_and_where_it_hit():
    tried = [Attempt("Up 400", [0, 0, 0.4], False, "collision with IfcColumn (-100 mm)", "offset", [2.6, 3.4],
                     where=[[0.5, 0.0, 2.8]]),
             Attempt("Trim it", [0.05, 0, 0], False, "collision with IfcWall (-10 mm)", "trim",
                     trim={"end": "start", "by_m": 0.05}),
             Attempt("Route", [0, 0.3, 0.4], True, "", "route", edit={"summary": "route up 400 then side 300 mm"})]
    text = agent._feedback(tried)
    assert "offset [2.6, 3.4] by +0.400 m" in text and "at [0.5, 0.0, 2.8]" in text
    assert "trim the start end by 50 mm" in text
    assert "route up 400 then side 300 mm): passed" in text


def test_plain_geometry_fixes_rank_before_a_resize_before_a_penetration(tmp_path, monkeypatch):
    scene = IfcScene(build_run_fixture(tmp_path / "run.ifc"))
    main, beam = _ids_two(scene)

    def fake(kind, size):
        def try_it(scene, cand, target, other, clearance_m, on_trial=None, *, others=()):
            o = Option(cand["title"], [target], [0, 0, size], "", "", 0.2, {}, kind, edit={"key": cand["title"]})
            return Attempt(cand["title"], [0, 0, size], True, "", kind), o
        return try_it
    monkeypatch.setitem(agent.TRIES, "penetration", fake("penetration", 0.0))
    monkeypatch.setitem(agent.TRIES, "resize", fake("resize", 0.05))
    monkeypatch.setitem(agent.TRIES, "move", fake("move", 0.9))
    first = {"candidates": [{"title": "Opening", "kind": "penetration"}, {"title": "Flatter", "kind": "resize"}]}
    second = {"candidates": [{"title": "Drop it", "kind": "move"}]}
    model = Scripted(first, second)
    result = resolve(scene, Clash(main, beam), model, max_rounds=3)
    # A penetration and a resize alone don't end the search: the next round found a move, which ranks first even
    # though it changes the most.
    assert len(model.calls) == 2
    assert [o.title for o in result.options] == ["Drop it", "Flatter", "Opening"]


def _ids_two(scene):
    return (next(e for e in scene.model.by_type("IfcDuctSegment") if e.Tag == "SA-1").GlobalId,
            scene.model.by_type("IfcBeam")[0].GlobalId)


def test_a_lateral_offset_is_sized_by_how_far_it_goes():
    pol = requirements.Policy("mep", "MEP", "any", 0.3, "yes")
    assert requirements.blocked(pol, None, "offset", [0, 0.45, 0], False)  # sideways 450 mm > 300 mm limit
    assert requirements.blocked(pol, None, "offset", [0, 0, 0.25], False) is None
    assert requirements.blocked(pol, None, "route", [0, 0.2, 0.4], False)


def test_plans_refuse_a_kind_they_cannot_apply(tmp_path):
    from sightline.service import Workspace
    path = build_run_fixture(tmp_path / "samples" / "run.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    main, beam = _ids_two(ws.scene(sid))
    with pytest.raises(ValueError, match="unknown kind"):
        plans.apply(ws, sid, [{"kind": "teleport", "moved": [main], "delta_m": [0, 0, 1]}])
    item = plans.Item(f"{main}|{beam}", main, beam, "pair", [], option={"kind": "teleport", "moved": [main],
                                                                        "delta_m": [0, 0, 1]})
    with pytest.raises(ValueError, match="unknown kind"):
        plans.verify_together(ws, sid, [item])


def test_one_endpoint_keeps_a_fix_of_any_kind(tmp_path, monkeypatch):
    from sightline import app as app_module
    from sightline.service import Workspace
    path = build_run_fixture(tmp_path / "samples" / "run.ifc")
    ws = Workspace(path.parent)
    monkeypatch.setattr(app_module, "ws", ws)
    client = TestClient(app_module.app)
    sid = ws.open([path.name])
    main, beam = _ids_two(ws.scene(sid))
    option = {"title": "Offset up 400", "kind": "offset", "moved": [main], "delta_m": [0, 0, 0.4],
              "split_m": [2.6, 3.4], "preview": [{"global_id": main, "verts": [], "faces": []}], "before": None}
    r = client.post(f"/api/scenes/{sid}/fix/apply", json={"option": option})
    assert r.status_code == 200, r.text
    assert r.json()["files"] == [0]
    assert r.json()["pieces"][0] == main and len(r.json()["pieces"]) == 9  # straight, bends, risers, middle, ...
    assert client.post(f"/api/scenes/{sid}/fix/apply",
                       json={"option": {**option, "kind": "teleport"}}).status_code == 400
    assert client.post(f"/api/scenes/{sid}/fix/apply", json={"option": {"kind": "move"}}).status_code == 400
