"""A drain held at its fixture tilts instead of breaking its joint (docs/connections.md, "A drain tilts"): moving the
waste arm's free end down turns it about its held end, giving it more fall, as on Snowdon Towers' #20."""
import ifcopenshell.util.system as us
import ifcopenshell.validate
import numpy as np
import pytest

from sightline import agent, connections, edits, manual, plans
from sightline.fixtures import build_drain_fixture
from sightline.service import Workspace

DOWN = [0.0, 0.0, -0.07]


def _open(folder, millimetres=False):
    build_drain_fixture(folder / "drain.ifc", millimetres=millimetres)
    ws = Workspace(samples=folder)
    sid = ws.open(["drain.ifc"])
    scene = ws.scene(sid)
    return ws, sid, scene, {(getattr(scene.entity(g), "Tag", None) or scene.entity(g).Name): g for g in scene.bounds()}


@pytest.fixture(params=[False, True], ids=["metres", "millimetres"])
def drain(tmp_path, request):
    return _open(tmp_path, request.param)


def ports_at(scene, gid):
    return sorted((tuple(np.round(scene.placement(p.GlobalId)[:3, 3], 4)) for p in us.get_ports(scene.entity(gid))))


def valid(scene) -> list:
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(scene.models[0], log)
    return [s.get("message", "")[:200] for s in log.statements]


def test_the_arm_turns_about_its_washer_end(drain):
    ws, sid, scene, g = drain
    with edits.trial(scene, g["DA"]):
        t = edits.tilt(scene, g["DA"], "start", DOWN)
        run = edits.run_of(scene, g["DA"])
        assert run.start == pytest.approx([12.1, 7.0, 0.9], abs=1e-6), "the washer end holds"
        assert run.end == pytest.approx([13.3, 7.0, 0.83], abs=1e-6), "the bend end went down 70 mm, no further along"
        assert run.length_m == pytest.approx(np.hypot(1.2, 0.07))
        assert t.turn_deg == pytest.approx(np.degrees(np.arctan2(0.07, 1.2)))
        assert t.fall == pytest.approx(0.07 / 1.2)
        assert ports_at(scene, g["DA"]) == [(12.1, 7.0, 0.9), (13.3, 7.0, 0.83)], "its ports went with its caps"
    assert edits.run_of(scene, g["DA"]).end == pytest.approx([13.3, 7.0, 0.9], abs=1e-6), "the trial put it back"


@pytest.mark.parametrize("tag, held, delta, why", [
    ("CW", "start", DOWN, "not a drain"),
    ("DA", "start", [0.0, 0.05, 0.0], "only up or down"),
    ("DA", "start", [0.0, 0.0, -0.2], "more than 5°"),
    ("DA", "start", [0.0, 0.0, 0.07], "toward its inlet"),     # the bend end up: it would drain back to the washer
    ("DA", "end", DOWN, "toward its inlet"),                   # held at the bend, the washer end down
])
def test_a_tilt_that_would_not_drain_is_refused_in_words(drain, tag, held, delta, why):
    ws, sid, scene, g = drain
    assert why in (edits.tilt_fits(scene, g[tag], held, delta) or "")
    assert edits.run_of(scene, g["DA"]).end == pytest.approx([13.3, 7.0, 0.9], abs=1e-6), "nothing was edited"


def test_moving_the_arm_down_tilts_it_and_keeps_every_joint(drain):
    ws, sid, scene, g = drain
    assert not connections.plan_move(scene, [g["DA"]], DOWN).ok, "without re-fits: refused at the washer, as before"
    plan = connections.plan_move(scene, [g["DA"]], DOWN, refit=True)
    assert plan.ok, plan.refused
    assert [(t.global_id, t.held) for t in plan.tilts] == [(g["DA"], "start")]
    assert plan.moved == [g["Bend DB"]] and plan.carried == [g["Bend DB"]], "the arm turns; the bend goes down"
    assert [(st.global_id, st.face, round(st.by_m, 4)) for st in plan.stretched] == [(g["DV"], "start", -0.07)]
    assert "'Waste arm DA' tilts about its end at 'Washer box WT'" in connections.summary(scene, plan)
    same = connections.plan_move(scene, [g["Bend DB"]], DOWN, refit=True)
    assert same.key() == plan.key(), "kept from the option's moved parts, it plans the same edit"
    t = connections.trial_move(scene, plan, 0.025, preview=True)
    assert not t.hits and t.least >= 0.025, t.hits
    assert {p["global_id"] for p in t.preview} >= {g["DA"], g["DV"]}, "the page draws the tilted arm and the stack"
    with edits.trial_files(scene, {0}):
        connections.apply_move(scene, plan)
        assert not connections.check_joints(scene, plan)


def test_up_is_refused_as_before(drain):
    ws, sid, scene, g = drain
    plan = connections.plan_move(scene, [g["DA"]], [0.0, 0.0, 0.07], refit=True)
    assert not plan.ok and "Washer box WT" in plan.refused


def test_a_drain_moved_down_at_its_bend_tilts_and_is_never_jogged(drain):
    ws, sid, scene, g = drain
    down = connections.plan_move(scene, [g["Bend DB"]], DOWN, refit=True)
    assert [t.global_id for t in down.tilts] == [g["DA"]] and not down.jogs
    up = connections.plan_move(scene, [g["Bend DB"]], [0.0, 0.0, 0.07], refit=True)
    assert not up.jogs and not up.ok, "a pair of bends up or down would trap what it carries"
    side = connections.plan_move(scene, [g["Bend DB"]], [0.0, 0.2, 0.0], refit=True)
    assert [j.global_id for j in side.jogs] == [g["DA"]], "sideways, a drain keeps its fall: re-fitted as before"


def test_muse_reads_how_far_the_arm_can_tilt(drain):
    ws, sid, scene, g = drain
    text = " ".join(connections.describe(scene, "B", g["DA"]))
    assert "Moving B down tilts it about its end at sanitary terminal 'Washer box WT'" in text
    assert "up to 104 mm" in text   # 1.2 m x tan 5°, to the millimetre below


def test_muse_s_move_down_is_verified_and_kept_as_tried(drain):
    ws, sid, scene, g = drain
    attempt, option = agent._try_move(scene, {"title": "drop the arm's bend end", "delta_m": DOWN}, g["DA"], 0.025,
                                      partners={g["CW"]})
    assert option is not None, attempt.reason
    assert option.moved == [g["Bend DB"]] and option.edit["tilts"][0]["global_id"] == g["DA"]
    assert "falls 3.3° (5.8%) toward 'Bend DB'" in option.edit["summary"]
    assert option.min_clearance_m >= 0.025
    assert edits.run_of(scene, g["DA"]).end == pytest.approx([13.3, 7.0, 0.9], abs=1e-6), "the trial put it back"
    kept = plans.apply(ws, sid, [{**agent.asdict(option), "pair": [g["DA"], g["CW"]]}])
    assert edits.run_of(scene, g["DA"]).end == pytest.approx([13.3, 7.0, 0.83], abs=1e-6)
    assert edits.run_of(scene, g["DV"]).length_m == pytest.approx(0.53)
    assert set(kept["changed"]) >= {g["DA"], g["Bend DB"], g["DV"]}
    assert not valid(scene)
    ws.journal(sid).undo(scene)
    assert edits.run_of(scene, g["DA"]).end == pytest.approx([13.3, 7.0, 0.9], abs=1e-6)


def test_a_hand_move_down_tilts_the_arm_too(drain):
    ws, sid, scene, g = drain
    plan = manual.resolve(scene, {"op": "move", "element": g["DA"], "delta_m": DOWN, "carry": True})
    assert "tilted about its end at" in plan.summary
    assert g["DA"] in plan.targets


def test_a_tail_open_at_its_far_end_tilts_and_is_kept(drain):
    # Nothing goes along: the move translates nothing, so keeping it must plan from the tilted drain itself.
    ws, sid, scene, g = drain
    attempt, option = agent._try_move(scene, {"title": "drop the tail's end", "delta_m": [0.0, 0.0, -0.03]}, g["DT"], 0.025)
    assert option is not None, attempt.reason
    assert option.moved == [] and option.edit["tilts"][0]["global_id"] == g["DT"]
    kept = plans.apply(ws, sid, [{**agent.asdict(option), "pair": [g["DT"], g["Basin WB"]]}])
    assert edits.run_of(scene, g["DT"]).end == pytest.approx([12.9, 9.0, 0.87], abs=1e-6)
    assert g["DT"] in kept["changed"]


def test_the_page_keeps_a_tilt_that_translates_nothing(tmp_path, monkeypatch):
    # The page's Accept goes through /fix/apply, which refused an option whose `moved` is empty ("names no element").
    from fastapi.testclient import TestClient
    from sightline import app as app_module
    ws, sid, scene, g = _open(tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    _, option = agent._try_move(scene, {"title": "drop the tail's end", "delta_m": [0.0, 0.0, -0.03]}, g["DT"], 0.025)
    o = {**agent.asdict(option), "preview": None, "before": None, "pair": [g["DT"], g["Basin WB"]]}
    assert o["moved"] == []
    r = TestClient(app_module.app).post(f"/api/scenes/{sid}/fix/apply", json={"option": o})
    assert r.status_code == 200, r.text
    assert g["DT"] in r.json()["changed"]
    assert edits.run_of(scene, g["DT"]).end == pytest.approx([12.9, 9.0, 0.87], abs=1e-6)
    nothing = TestClient(app_module.app).post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "edit": {}}})
    assert nothing.status_code == 400 and "names no element" in nothing.json()["detail"]
