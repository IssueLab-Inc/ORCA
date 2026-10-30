"""Resize: a stretch of a rectangular duct or tray made flatter where an obstacle leaves too little depth, keeping what
it carries (edits.apply_resize), tried by the agent, kept by plans and the fix endpoint."""
import ifcopenshell.util.system as system
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sightline import agent, edits, plans, verify
from sightline.agent import Clash, resolve
from sightline.fixtures import build_resize_fixture
from sightline.scene import IfcScene


@pytest.fixture
def scene(tmp_path) -> IfcScene:
    return IfcScene(build_resize_fixture(tmp_path / "resize.ifc"))


def by_tag(scene, tag):
    return next(e for e in scene.model.by_type("IfcFlowSegment") if e.Tag == tag).GlobalId


def by_name(scene, name):
    return next(e for e in scene.model.by_type("IfcProduct") if e.Name == name).GlobalId


def test_a_duct_keeps_its_equivalent_diameter_and_a_tray_its_cross_section(scene):
    duct = edits.resize_size(scene, by_tag(scene, "RS-1"), 0.22)
    assert (duct["width_m"], duct["depth_m"], duct["before"]) == (0.735, 0.22, [0.5, 0.3])
    assert duct["performance"] == "equivalent diameter 100% of before, 3.3:1"
    assert edits.equivalent_diameter(0.735, 0.22) == pytest.approx(edits.equivalent_diameter(0.5, 0.3), rel=0.01)
    tray = edits.resize_size(scene, by_tag(scene, "RS-2"), 0.06)
    assert (tray["width_m"], tray["performance"]) == (0.5, "cross-section 100% of before")


@pytest.mark.parametrize("tag, depth, why", [
    ("RS-1", 0.2, "830 x 200 mm would be 4.1:1, flatter than 4:1 (no shallower than about 205 mm)"),
    ("RS-1", 0.35, "a resize makes it shallower"),
    ("RS-2", 0.04, "a tray keeps sides at least 50 mm high"),
    ("RS-3", 0.08, "a pipe's size is set by its flow"),
    ("RS-4", 0.2, "a round duct keeps its size"),
])
def test_what_a_resize_refuses(scene, tag, depth, why):
    with pytest.raises(edits.Unsupported, match=why.replace("(", r"\(").replace(")", r"\)")):
        edits.resize_size(scene, by_tag(scene, tag), depth)


def test_flatter_with_its_bottom_kept_it_clears_the_beam_and_stays_one_chain(scene):
    duct, beam = by_tag(scene, "RS-1"), by_name(scene, "Beam B1")
    end = by_tag(scene, "RS-1E")
    r = edits.apply_resize(scene, duct, [2.5, 3.5], 0.22, "bottom")
    assert len(r.pieces) == 5 and r.pieces[0] == duct
    kinds = [(scene.entity(g).is_a(), getattr(scene.entity(g), "PredefinedType", None)) for g in r.pieces]
    assert kinds[1] == kinds[3] == ("IfcDuctFitting", "TRANSITION") and kinds[2][0] == "IfcDuctSegment"
    b = scene.bounds()
    assert b[r.pieces[2]][0][2] == pytest.approx(2.45, abs=1e-3) and b[r.pieces[2]][1][2] == pytest.approx(2.67, abs=1e-3)
    assert b[r.pieces[2]][1][1] - b[r.pieces[2]][0][1] == pytest.approx(0.735, abs=1e-3)
    assert b[r.pieces[1]][1][0] - b[r.pieces[1]][0][0] == pytest.approx(np.tan(np.radians(60)) * 0.1175, abs=2e-3)  # 30°
    # The middle's profile is its own: the original's is untouched.
    assert scene.entity(duct).Representation.Representations[0].Items[0].SweptArea.XDim == 0.5
    own = set(r.pieces) | {c for g in r.pieces for c in scene.element(g).connected}
    v = verify.check(scene, r.pieces[1:-1], ignore=own)
    assert v.passed and v.min_clearance_m == pytest.approx(0.03, abs=1e-3)
    # Port to port in order, the last piece on the far segment, ports at the lifted centre of the resized middle.
    chain = [duct, *r.pieces[1:], end]
    for x, y in zip(chain, chain[1:]):
        assert y in scene.element(x).connected, (scene.entity(x).Tag, scene.entity(y).Tag)
    mid_ports = [scene.placement(p.GlobalId)[:3, 3] for p in system.get_ports(scene.entity(r.pieces[2]))]
    assert all(abs(p[2] - 2.56) < 1e-3 for p in mid_ports)


def test_split_points_must_leave_room_for_the_transitions(scene):
    with pytest.raises(edits.Unsupported, match="leaves too little run"):
        edits.apply_resize(scene, by_tag(scene, "RS-1"), [0.1, 3.5], 0.22, "bottom")


def test_a_trial_resize_is_undone(scene):
    duct = by_tag(scene, "RS-1")
    before = len(scene.model.by_type("IfcRoot"))
    with edits.trial(scene, duct):
        edits.apply_resize(scene, duct, [2.5, 3.5], 0.22, "bottom")
    assert len(scene.model.by_type("IfcRoot")) == before


class Scripted:
    def __init__(self, *rounds):
        self.rounds, self.calls = list(rounds), []

    def complete_json(self, system, text, images=None):
        self.calls.append(text)
        return self.rounds[min(len(self.calls), len(self.rounds)) - 1]


def test_the_agent_offers_a_resize_when_offsets_fail_and_muse_is_told_what_fits(scene):
    duct, beam = by_tag(scene, "RS-1"), by_name(scene, "Beam B1")
    model = Scripted({"candidates": [{"title": "Drop under the beam", "kind": "offset", "move": "A",
                                      "split_m": [2.3, 3.7], "dz_m": -0.1},
                                     {"title": "Flatten under the beam", "kind": "resize", "move": "A",
                                      "split_m": [2.5, 3.5], "depth_m": 0.22, "keep": "bottom"}]})
    result = resolve(scene, Clash(duct, beam), model, max_rounds=2)
    assert "keeping its bottom level, 225 mm deep passes under the other element" in model.calls[0]
    assert [a.passed for a in result.attempts[:2]] == [False, True]
    o = result.options[0]
    assert o.kind == "resize" and o.review == "services" and o.delta_m == pytest.approx([0, 0, -0.08])
    assert o.edit["summary"] == "resize 2.50-3.50 m to 735 x 220 mm (bottom kept level)"
    assert "equivalent diameter 100% of before, 3.3:1" in o.also_needs and len(o.preview) == 5
    assert len(model.calls) == 2   # a resize alone does not end the search: one more round for a plain fix


def test_the_endpoint_and_a_plan_keep_a_resize(tmp_path, monkeypatch):
    from sightline import app as app_module
    from sightline.service import Workspace
    path = build_resize_fixture(tmp_path / "samples" / "resize.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    duct, beam = by_tag(scene, "RS-1"), by_name(scene, "Beam B1")
    _, option = agent._try_resize(scene, {"title": "Flatten", "split_m": [2.5, 3.5], "depth_m": 0.22, "keep": "bottom"},
                                  duct, beam, 0.025)
    o = plans.asdict(option)
    assert plans.verify_together(ws, sid, [plans.Item(f"{duct}|{beam}", duct, beam, "pair", [], option=o)])["passed"]
    monkeypatch.setattr(app_module, "ws", ws)
    r = TestClient(app_module.app).post(f"/api/scenes/{sid}/fix/apply", json={"option": {**o, "preview": None}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["pieces"][0] == duct and len(out["pieces"]) == 5 and {m["global_id"] for m in out["meshes"]} == set(out["pieces"])
    assert not [h for h in verify.check(scene, out["pieces"][1:-1], ignore=set(out["pieces"])).hits if h.other == beam]


@pytest.mark.parametrize("profile, why", [("IfcRectangleHollowProfileDef", "a hollow section would lose its wall"),
                                          ("IfcRoundedRectangleProfileDef", "a rounded or flat-oval section")])
def test_only_a_plain_rectangle_is_resized(scene, profile, why):
    duct = by_tag(scene, "RS-1")
    item = scene.entity(duct).Representation.Representations[0].Items[0]
    old = item.SweptArea
    extra = {"WallThickness": 0.001} if "Hollow" in profile else {"RoundingRadius": 0.15}
    item.SweptArea = scene.model.create_entity(profile, ProfileType="AREA", Position=old.Position,
                                               XDim=old.XDim, YDim=old.YDim, **extra)
    with pytest.raises(edits.Unsupported, match=why):
        edits.apply_resize(scene, duct, [2.5, 3.5], 0.22, "bottom")


def test_a_split_that_is_not_a_number_is_refused_before_anything_changes(tmp_path, monkeypatch):
    from sightline import app as app_module
    from sightline.service import Workspace
    path = build_resize_fixture(tmp_path / "samples" / "resize.ifc")
    ws = Workspace(path.parent)
    sid = ws.open([path.name])
    scene = ws.scene(sid)
    duct = by_tag(scene, "RS-1")
    connected = lambda: [system.get_connected_port(p) is not None for p in system.get_ports(scene.entity(duct))]
    before = connected()
    with pytest.raises(edits.Unsupported, match="finite"):
        edits.apply_resize(scene, duct, [float("nan"), 3.5], 0.22)
    monkeypatch.setattr(app_module, "ws", ws)
    r = TestClient(app_module.app).post(f"/api/scenes/{sid}/fix/apply", content=(
        '{"option": {"kind": "resize", "moved": ["%s"], "delta_m": [0, 0, 0], '
        '"edit": {"split_m": [NaN, 3.5], "depth_m": 0.22}}}' % duct).encode(), headers={"content-type": "application/json"})
    assert r.status_code in (400, 409, 422) and connected() == before and scene.revision == 0


def test_a_centre_kept_resize_moves_each_face_half_the_change(scene):
    duct, beam = by_tag(scene, "RS-1"), by_name(scene, "Beam B1")
    cand = {"kind": "resize", "split_m": [2.5, 3.5], "depth_m": 0.22, "keep": "centre"}
    assert agent._candidate_delta(cand, scene, duct) == ("resize", [0.0, 0.0, -0.04])
    attempt, _ = agent._try_resize(scene, cand, duct, beam, 0.025)
    assert attempt.delta_m == [0.0, 0.0, -0.04]
    assert agent._candidate_delta({**cand, "keep": "bottom"}, scene, duct)[1] == [0.0, 0.0, -0.08]


def test_the_resized_pieces_say_their_new_size(scene):
    import ifcopenshell.util.element as ue
    duct = by_tag(scene, "RS-1")
    name = scene.entity(duct).Name
    r = edits.apply_resize(scene, duct, [2.5, 3.5], 0.22, "bottom")
    middle = scene.entity(r.pieces[2])
    assert "735x220" in middle.Name and "500x300" not in middle.Name
    assert middle.Representation.Representations[0].Items[0].SweptArea.ProfileName == "735x220"
    resize = ue.get_psets(middle)["ORCA_Resize"]
    assert (resize["ResizedFrom"], resize["Size"], resize["KeepLevel"]) == ("500x300", "735x220", "bottom")
    assert [scene.entity(g).Name for g in (r.pieces[1], r.pieces[3])] == [f"{name} transition to 735x220"] * 2
    assert scene.entity(duct).Name == name and "ORCA_Resize" not in ue.get_psets(scene.entity(duct))
    assert edits._resized_name("Supply air main L02 600x300", (0.6, 0.3), "795x240") == "Supply air main L02 795x240"
    assert edits._resized_name("Main 300 x 600 duct", (0.6, 0.3), "795x240") == "Main 795x240 duct"
    assert edits._resized_name("Main", (0.6, 0.3), "795x240") == "Main 795x240"
