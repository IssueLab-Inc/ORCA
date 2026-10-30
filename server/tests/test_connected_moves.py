"""Moves that keep their joints (connections.plan_move, "carry"): fittings and valves beyond a run go along, a straight
segment the move runs along gets longer or shorter at the joined end (edits.stretch), and a move that can't keep
every joint is refused, naming why."""
import ifcopenshell.util.system as system
import numpy as np
import pytest

from sightline import agent, connections as cx, edits, plans, step
from sightline.fixtures import build_joints_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace
from test_connections import Classes, write_air_step


@pytest.fixture
def scene(tmp_path) -> IfcScene:
    return IfcScene(build_joints_fixture(tmp_path / "joints.ifc"))


def gid(scene, tag):
    return next(e.GlobalId for e in scene.model.by_type("IfcElement") if tag in (e.Tag, e.Name))


def tags(scene, gids):
    return sorted(scene.entity(g).Tag or scene.entity(g).Name for g in gids)


def ports_meet(scene) -> bool:
    """Every port connection in the model: both ports in the same place."""
    for rel in scene.model.by_type("IfcRelConnectsPorts"):
        a, b = (scene.placement(p.GlobalId)[:3, 3] for p in (rel.RelatingPort, rel.RelatedPort))
        if np.linalg.norm(a - b) > 0.002:
            return False
    return True


def test_a_run_moved_along_its_neighbours_takes_the_bends_and_shortens_the_legs(scene):
    run = cx.run(scene, gid(scene, "S3A"))
    plan = cx.plan_move(scene, run, [0, 0.25, 0])
    assert plan.ok and tags(scene, plan.carried) == ["Bend B2", "Bend B3"]
    stretched = {scene.entity(st.global_id).Tag: (st.face, round(st.by_m, 3), round(st.size_m, 3)) for st in plan.stretched}
    assert stretched == {"S2": ("end", -0.25, 0.7), "S4": ("start", -0.25, 0.7)}   # S2 ends, S4 starts, at the south
    assert cx.summary(scene, plan) == ("move north 250 mm; takes 'Bend B2' and 'Bend B3' along; 'Pipe S2' and "
                                       "'Pipe S4' 250 mm shorter")
    with edits.trial_files(scene, {0}):
        cx.apply_move(scene, plan)
        assert cx.check_joints(scene, plan) == [] and ports_meet(scene)
        s2 = edits.run_of(scene, gid(scene, "S2"))
        assert s2.end == pytest.approx([0, 0.3, 0.9]) and s2.length_m == pytest.approx(0.7)
        s4 = edits.run_of(scene, gid(scene, "S4"))
        assert s4.start == pytest.approx([6, 0.3, 0.9]) and s4.end == pytest.approx([6, 1.0, 0.9])
    assert ports_meet(scene) and edits.run_of(scene, gid(scene, "S2")).length_m == pytest.approx(0.95)   # undone


def test_what_a_move_cannot_keep(scene):
    run = cx.run(scene, gid(scene, "S3A"))
    up = cx.plan_move(scene, run, [0, 0, 0.25])        # S4 runs across the move, into the filter
    assert up.code == "stays" and tags(scene, up.refused_at) == ["Filter FRL1"]
    assert "would take 'Bend B3' and 'Pipe S4' along, and would pull 'Pipe S4' apart from filter 'Filter FRL1'" in up.refused
    far = cx.plan_move(scene, run, [0, 0.93, 0])       # S2 is 0.95 m: it would be 20 mm
    assert far.code == "short" and "would make 'Pipe S2' 20 mm long (it can lose at most 900 mm)" in far.refused
    ok = cx.plan_move(scene, run, [0.0004, 0.25, 0])   # 0.4 mm across: still along
    assert ok.ok and len(ok.stretched) == 2
    across = cx.plan_move(scene, run, [0.002, 0.25, 0])  # 2 mm across: S2 and S4 go along, and the filter can't
    assert across.code == "stays"
    monkey = cx.plan_move(scene, [gid(scene, "Valve V1"), gid(scene, "Bend B2")], [0, 0.1, 0])
    # S2 is joined to both: moved at both ends, it moves whole; S1 above the valve and S4 beyond B3 get shorter
    assert gid(scene, "S2") in monkey.carried and tags(scene, [st.global_id for st in monkey.stretched]) == ["S1", "S4"]


def test_a_branch_move_takes_its_tee_and_stretches_the_main(scene):
    plan = cx.plan_move(scene, [gid(scene, "BR")], [0.1, 0, 0])
    assert plan.ok and tags(scene, plan.carried) == ["Tee T1"]
    by = {scene.entity(st.global_id).Tag: round(st.by_m, 3) for st in plan.stretched}
    assert by == {"M1": 0.1, "M2": -0.1}
    with edits.trial_files(scene, {0}):
        cx.apply_move(scene, plan)
        assert cx.check_joints(scene, plan) == [] and ports_meet(scene)


def test_stretch_moves_the_face_and_its_port_without_turning_it(scene):
    s2 = gid(scene, "S2")
    port = next(p for p in system.get_ports(scene.entity(s2)) if p.FlowDirection == "SINK")   # at its start (north)
    before = scene.placement(port.GlobalId)
    with edits.trial_files(scene, {0}):
        out = edits.stretch(scene, s2, "start", 0.1)
        after = scene.placement(port.GlobalId)
        assert out.size_m == pytest.approx(1.05) and edits.run_of(scene, s2).start == pytest.approx([0, 1.1, 0.9])
        assert after[:3, 3] == pytest.approx(before[:3, 3] + [0, 0.1, 0]) and after[:3, :3] == pytest.approx(before[:3, :3])
        assert scene.bounds()[s2][1][1] == pytest.approx(1.1 + 0, abs=1e-3)
    with pytest.raises(edits.Unsupported, match="it would be 0 mm long"):
        edits.stretch(scene, s2, "end", -0.95)
    with pytest.raises(edits.Unsupported, match="only a centred rectangular segment grows sideways"):
        edits.stretch(scene, s2, "side", 0.1, normal=(0, 0, 1))


def test_the_agent_offers_it_with_what_it_takes_along(scene):
    s3a, column = gid(scene, "S3A"), gid(scene, "Column C3")
    trials = []
    attempt, option = agent._try_move(scene, {"title": "Shift north", "delta_m": [0, 0.5, 0]}, s3a, 0.025,
                                      trials.append, partners=(column,))
    assert attempt.passed and option.kind == "move" and tags(scene, option.moved) == ["Bend B2", "Bend B3", "S3A", "S3B"]
    assert option.edit["summary"].startswith("move north 500 mm; takes 'Bend B2' and 'Bend B3' along")
    assert sorted(m["global_id"] for m in option.preview) == sorted(st["global_id"] for st in option.edit["stretched"])
    assert trials[0]["pieces"] and trials[0]["summary"] == option.edit["summary"]
    attempt, option = agent._try_move(scene, {"title": "Lift", "delta_m": [0, 0, 0.3]}, s3a, 0.025)
    assert option is None and attempt.reason.startswith("cannot keep its joints: moving 'Pipe S3A' (with 1 more) up")
    text = agent._describe(scene, agent.Clash(s3a, column))
    assert "Moving A (tried at 100 mm): north: keeps its joints" in text and "up / down: cannot (filter" in text


def test_keeping_it_plans_it_again_and_refuses_a_stale_plan(tmp_path):
    path = build_joints_fixture(tmp_path / "samples" / "joints.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    s3a, column = gid(scene, "S3A"), gid(scene, "Column C3")
    v = ws.verify_move(sid, cx.run(scene, s3a), [0, 0.5, 0])
    assert v["passed"] and v["joints"]["carried"] and len(v["preview"]) == 2 and len(v["placements"]) == 4
    _, option = agent._try_move(scene, {"title": "Shift north", "delta_m": [0, 0.5, 0]}, s3a, 0.025)
    o = plans.asdict(option)
    with pytest.raises(edits.Unsupported, match="the model changed since this move was checked"):
        ws.apply(sid, o["moved"], o["delta_m"], expect={**o["edit"], "key": "something else"})
    kept, _ = plans.KEEP["move"](ws, sid, o)
    assert tags(scene, kept["changed"]) == ["Bend B2", "Bend B3", "S2", "S3A", "S3B", "S4"] and ports_meet(scene)
    assert edits.run_of(scene, gid(scene, "S2")).length_m == pytest.approx(0.45) and scene.revision == 1


def test_a_plan_checks_a_connected_move_with_its_joints(tmp_path):
    path = build_joints_fixture(tmp_path / "samples" / "joints.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    s3a, column = gid(scene, "S3A"), gid(scene, "Column C3")
    _, option = agent._try_move(scene, {"title": "Shift north", "delta_m": [0, 0.5, 0]}, s3a, 0.025)
    item = plans.Item(f"{s3a}|{column}", s3a, column, "pair", [], option=plans.asdict(option))
    assert plans.verify_together(ws, sid, [item])["passed"]
    up = {**plans.asdict(option), "delta_m": [0, 0, 0.3], "edit": None}
    out = plans.verify_together(ws, sid, [plans.Item(item.key, s3a, column, "pair", [], option=up)])
    assert out["items"][item.key]["reason"] == "breaks its joint with IfcFilter"


def test_a_step_ladder_lifted_keeps_its_riser_on_the_panel_and_exports(tmp_path):
    write_air_step(tmp_path / "Air.step")
    ws = Workspace(samples=tmp_path)
    sid = ws.open(["Air.step"], classify_with=Classes())
    scene = ws.scene(sid)
    by = {scene.entity(g).Name: g for g in scene.bounds()}
    plan = cx.plan_move(scene, cx.run(scene, by["Ladder bend"]), [0, 0, 0.05])
    assert plan.ok and [(scene.entity(st.global_id).Name, st.face, round(st.by_m, 3)) for st in plan.stretched] == \
        [("Ladder riser", "side", 0.05)]
    kept = ws.apply(sid, [by["Ladder bend"]], [0, 0, 0.05])
    assert sorted(scene.entity(g).Name for g in kept["changed"]) == ["Ladder bend", "Ladder riser"]
    lo, hi = scene.bounds()[by["Ladder riser"]]
    assert lo[2] == pytest.approx(1.0, abs=1e-4) and hi[2] == pytest.approx(1.2, abs=1e-4)   # foot where it was
    out = ws.export(sid, tmp_path / "export")
    parts = {p.name: p for p in step.parts(next(p for p in out if p.suffix == ".step"))[0]}

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    def z(p):
        box = Bnd_Box(); BRepBndLib.Add_s(p.shape, box); return box.CornerMin().Z(), box.CornerMax().Z()
    assert z(parts["Ladder riser"]) == pytest.approx((1000, 1200), abs=0.01)
    assert z(parts["Ladder bend"]) == pytest.approx((1200, 1300), abs=0.01) and parts["Ladder riser"].group == "Ladder"
    tee = cx.plan_move(scene, cx.run(scene, by["Ladder tee"]), [0, 0, 0.05])   # on a third of the stub: a branch
    assert tee.code == "branch" and "along the side of 'Ladder stub', which it branches off" in tee.refused
