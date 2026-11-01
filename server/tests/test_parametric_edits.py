"""Every hand edit on every construct real exports carry (docs/editing-parity.md, "Test matrix").

Each cell is either kept consistent (no block, the warnings named) or refused in words: never a model that says two
things. Tier 1 turns refusals into consistent edits; flip the cell when it does.
"""
import pytest

from sightline import manual
from sightline.fixtures import build_parametric_fixture
from sightline.service import Workspace


@pytest.fixture(scope="module")
def param(tmp_path_factory):
    folder = tmp_path_factory.mktemp("param")
    build_parametric_fixture(folder / "param.ifc")
    ws = Workspace(samples=folder)
    sid = ws.open(["param.ifc"])
    scene = ws.scene(sid)
    return ws, sid, {scene.entity(g).Name: g for g in scene.bounds()}


OK, LAYERS, PROFILE, AXIS, JOINS, MAPPED = "ok", "material layers", "material profile", "axis of", "path join", "comes from its type"

MATRIX = [
    # (cell, op without its element, element, expected: OK or the words of the refusal, warnings expected when OK)
    ("wall height", {"op": "push_pull", "face": "top", "by_m": 0.2}, "W1", OK, {"quantities"}),
    ("wall thickness", {"op": "push_pull", "face": "north face", "by_m": 0.05}, "W1", LAYERS, None),
    ("wall length", {"op": "push_pull", "face": "west end", "by_m": 0.3}, "W1", AXIS, None),
    ("wall moved up", {"op": "move", "delta_m": [0, 0, 0.1]}, "W1", OK, set()),
    ("wall moved off its join", {"op": "move", "delta_m": [-0.2, 0, 0]}, "W1", JOINS, None),
    ("wall void", {"op": "void", "face": "north face", "at": [2.0, 0.25, 1.5], "shape": "rect", "width_m": 0.4,
                   "height_m": 0.4}, "W1", OK, {"quantities"}),
    ("wall split", {"op": "split", "at": [2.0, 0.1, 1.5]}, "W1", AXIS, None),
    ("wall deleted", {"op": "delete"}, "W1", OK, set()),
    ("slab thickness", {"op": "push_pull", "face": "top", "by_m": 0.05}, "SL1", LAYERS, None),
    ("slab size", {"op": "push_pull", "face": "east end", "by_m": 0.5}, "SL1", OK, {"quantities"}),
    ("slab moved", {"op": "move", "delta_m": [0, 0, 0.1]}, "SL1", OK, set()),
    ("slab split", {"op": "split", "at": [3.0, 7.0, 3.1]}, "SL1", OK, {"quantities"}),
    ("beam length", {"op": "push_pull", "face": "east end", "by_m": 0.5}, "BM1", AXIS, None),
    ("beam section", {"op": "push_pull", "face": "top", "by_m": 0.05}, "BM1", PROFILE, None),
    ("beam moved", {"op": "move", "delta_m": [0, 0, 0.1]}, "BM1", OK, set()),
    ("beam split", {"op": "split", "at": [2.5, 12.0, 3.0]}, "BM1", AXIS, None),
    ("beam section removed", {"op": "remove_section", "from": [1.0, 12.0, 3.0], "to": [2.0, 12.0, 3.0]}, "BM1", AXIS, None),
    ("mapped fitting moved", {"op": "move", "delta_m": [0, 0, 0.1]}, "F1", OK, set()),
    ("mapped fitting clipped", {"op": "clip", "to": {"point": [10.3, 0.2, 1.15], "normal": [1, 0, 0]}, "gap_m": 0.0},
     "F1", MAPPED, None),
    ("mapped fitting split", {"op": "split", "at": [10.3, 0.2, 1.15]}, "F1", MAPPED, None),
    ("mapped fitting deleted", {"op": "delete"}, "F1", OK, set()),
]


@pytest.mark.parametrize("cell,op,name,expected,warned", MATRIX, ids=[m[0] for m in MATRIX])
def test_every_edit_keeps_the_model_consistent_or_says_why_not(param, cell, op, name, expected, warned):
    ws, sid, g = param
    r = manual.check(ws, sid, {**op, "element": g[name]}, preview=False)
    if expected == OK:
        assert r["blocked"] is None, r["blocked"]
        rules = {w["rule"] for w in r["warnings"]} & {"quantities", "layers", "profile", "axis", "joins", "type"}
        assert rules == warned
    else:
        assert r["blocked"] and expected in r["blocked"], r["blocked"]


def test_a_refused_edit_names_what_it_would_break_in_numbers(param):
    ws, sid, g = param
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["W1"], "face": "north face", "by_m": 0.05}, preview=False)
    assert "250 mm" in r["blocked"] and "300 mm" in r["blocked"] and r["consistency"][0]["rule"] == "layers"
    r = manual.check(ws, sid, {"op": "push_pull", "element": g["BM1"], "face": "east end", "by_m": 0.5}, preview=False)
    assert "5.000 m" in r["blocked"] and "5.500 m" in r["blocked"]


def test_a_refused_edit_cannot_be_kept_and_leaves_the_model_as_it_was(param):
    ws, sid, g = param
    scene = ws.scene(sid)
    revision = scene.revision
    with pytest.raises(manual.NotKept, match="material layers"):
        manual.apply(ws, sid, {"op": "push_pull", "element": g["SL1"], "face": "top", "by_m": 0.05})
    assert scene.revision == revision and not ws.journal(sid).entries
