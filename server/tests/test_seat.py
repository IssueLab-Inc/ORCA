"""Seats (docs/edits.md, "Seat"): an element that comes down into what carries it is cut where it is inside, below the
support's top, so what is left bears on it. Decided from the geometry, for any pair: the fixture has a wall and a
column landing in a base, and what is not a seat (a wall through a slab, a support wider below its top, a pipe, a
block mostly inside)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import agent, detect, edits, plans, verify
from sightline import app as app_module
from sightline import requirements as req
from sightline.fixtures import build_seat_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace


class Scripted:
    """Stands in for Muse Spark: the same reply every round."""

    def __init__(self, reply):
        self.reply = reply

    def complete_json(self, system, text, images=None):
        return self.reply


@pytest.fixture(params=[False, True], ids=["metres", "millimetres"])
def scene(tmp_path, request) -> IfcScene:
    s = IfcScene(build_seat_fixture(tmp_path / "seat.ifc", millimetres=request.param))
    s.bounds()
    return s


def gid(scene, name):
    return next(g for g in scene.bounds() if scene.entity(g).Name == name)


def volume(scene, g):
    m = edits.meshes(scene, [g])[0]
    v = np.asarray(m["verts"], float).reshape(-1, 3)
    f = np.asarray(m["faces"], int).reshape(-1, 3)
    return abs(float(np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])).sum()) / 6)


def test_what_comes_down_into_its_support_is_cut_there_and_bears_on_the_top(scene):
    u1, b1, k1 = gid(scene, "Upstand U1"), gid(scene, "Base B1"), gid(scene, "Column K1")
    st = agent.seat_of(scene, u1, b1)
    assert st.cut == [[0.8, 0.0, -0.65], [1.0, 0.5, 0.0]] and st.size_m == [0.2, 0.5, 0.65] and st.top_m == 0.0
    assert st.share == pytest.approx(0.103, abs=0.001)
    assert sorted(map(tuple, st.footprint)) == [(0.0, 0.0), (0.0, 1.8), (1.8, 0.0), (1.8, 1.8)]
    assert agent.seat_of(scene, k1, b1).size_m == [0.2, 0.2, 0.3]   # a column standing in it: shortened to its top
    with pytest.raises(edits.Unsupported, match="does not stand above"):   # the support is never the one seated
        agent.seat_of(scene, b1, u1)
    before = volume(scene, u1)
    with edits.trial(scene, u1):
        edits.apply_seat(scene, st)
        recess = scene.entity(st.recess)
        assert recess.is_a("IfcOpeningElement") and recess.PredefinedType == "RECESS"
        assert recess.VoidsElements[0].RelatingBuildingElement.GlobalId == u1
        j = edits.SEAT_JOINT_M   # the recess clears the base by a bedding joint
        assert volume(scene, u1) == pytest.approx(before - 0.2 * (0.5 + j) * (0.65 + j), abs=1e-5)
        v = np.asarray(edits.meshes(scene, [u1])[0]["verts"], float).reshape(-1, 3)
        inside = (v[:, 0] > 0.001) & (v[:, 0] < 1.799) & (v[:, 1] > 0.001) & (v[:, 1] < 1.799) & (v[:, 2] < -0.001)
        assert not inside.any()   # nothing of it below the base's top inside its footprint
        assert detect.measure_pair(scene, u1, b1) is None   # re-measured: it bears on the base, no overlap
        assert v[:, 2].max() == pytest.approx(0.4) and v[:, 1].max() == pytest.approx(0.5)   # its end stays put
    assert volume(scene, u1) == pytest.approx(before) and scene.entity(u1).HasOpenings == ()


@pytest.mark.parametrize("element, support, why", [
    ("Wall W2", "Slab S1", "passes the element"),
    ("Upstand U2", "Stepped base B2", "not as wide below its top"),
    ("Riser R1", "Base B1", "never seated"),
    ("Block K2", "Base B1", "mostly inside"),
])
def test_what_is_not_a_seat_is_refused_saying_why(scene, element, support, why):
    with pytest.raises(edits.Unsupported, match=why):
        agent.seat_of(scene, gid(scene, element), gid(scene, support))


def test_the_agent_offers_it_reviewed_and_muse_is_told_when_it_applies(scene):
    u1, b1 = gid(scene, "Upstand U1"), gid(scene, "Base B1")
    trials = []
    attempt, option = agent._try_seat(scene, {"title": "Seat the upstand"}, u1, b1, 0.025, trials.append)
    assert attempt.passed and option.kind == "seat" and option.moved == [u1] and option.delta_m == [0, 0, 0]
    assert option.review == "structure" and option.edit["support"] == b1 and option.preview[0]["global_id"] == u1
    assert option.edit["summary"].startswith("seat 'Upstand U1' on 'Base B1': its foot cut where it is inside (0.20 x 0.50")
    assert trials[0]["kind"] == "seat" and trials[0]["summary"] == option.edit["summary"]
    assert scene.entity(u1).HasOpenings == ()   # tried and undone
    wrong, _ = agent._try_seat(scene, {}, b1, u1, 0.025)
    assert not wrong.passed and "seat Upstand U1 on it instead" in wrong.reason
    text = agent._describe(scene, agent.Clash(u1, b1, -0.5))
    assert 'Bearing: element A comes down into element B and stands 400 mm above its top' in text
    assert 'A "seat" of A on B cuts A' in text and "seat\" of B" not in text


def test_a_seat_is_a_trim_to_the_requirements():
    pol = req.Policy(group="g", group_name="Structure", edits="any", max_move_m=None, trims="no")
    assert req.blocked(pol, None, "seat", [0, 0, 0], True) == "blocked by requirements: no trims or seats on Structure"
    moving = req.Policy(group="g", group_name="Structure", edits="move", max_move_m=None, trims="yes")
    assert "may only be moved whole" in req.blocked(moving, None, "seat", [0, 0, 0], True)
    free = req.Policy(group="g", group_name="Structure", edits="any", max_move_m=0.1, trims="yes")
    assert req.blocked(free, None, "seat", [0, 0, 0], True) is None


@pytest.fixture
def served(tmp_path, monkeypatch):
    build_seat_fixture(tmp_path / "seat.ifc")
    ws = Workspace(samples=tmp_path, model=Scripted({"candidates": [
        {"title": "Seat the upstand on the base", "kind": "seat", "move": "A"}]}))
    monkeypatch.setattr(app_module, "ws", ws)
    c = TestClient(app_module.app)
    sid = c.post("/api/scenes", json={"samples": ["seat.ifc"]}).json()["id"]
    s = ws.scene(sid)
    return c, ws, sid, s, gid(s, "Upstand U1"), gid(s, "Base B1")


def test_proposed_kept_in_place_and_refused_once_the_model_changed(served):
    c, ws, sid, s, u1, b1 = served
    o = ws.propose(sid, u1, b1)["options"][0]
    assert o["kind"] == "seat" and o["pair"] == [u1, b1]
    stale = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "preview": None, "before": None,
                                                                    "edit": {**o["edit"], "key": "another cut"}}})
    assert stale.status_code == 409 and s.revision == 0
    kept = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "preview": None, "before": None}})
    assert kept.status_code == 200, kept.text
    r = kept.json()
    assert r["changed"] == [u1] and r["revision"] == 1 and [m["global_id"] for m in r["meshes"]] == [u1]
    assert len(s.entity(u1).HasOpenings) == 1 and s.index_of(u1) in s._edited
    seated = verify.check(s, [u1], clearance_m=0.0, ignore={b1})
    assert all(h.distance_m >= -0.002 for h in seated.hits)
    again = c.post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "preview": None, "before": None}})
    assert again.status_code == 409 and len(s.entity(u1).HasOpenings) == 1   # seated already: nothing to cut


def test_a_plan_checks_a_seat_with_the_other_fixes(served):
    c, ws, sid, s, u1, b1 = served
    o = ws.propose(sid, u1, b1)["options"][0]
    item = plans.Item("k", u1, b1, "Upstand U1 x Base B1", [], option=o)
    check = plans.verify_together(ws, sid, [item])
    assert check["passed"], check
    assert s.entity(u1).HasOpenings == ()
