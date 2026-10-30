"""A move keeps what it stands on (verify.supports / keep_supports): a post slid along its slab, still cast into it,
is not a new clash; a post lifted off it, or sunk deeper, is refused. Runs (ducts, pipes) stand on nothing."""
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import pytest

from sightline import agent, plans
from sightline.fixtures import _box
from sightline.scene import IfcScene
from sightline.service import Workspace


def build(path: Path) -> Path:
    """A 200 mm slab (top at z 0), a post cast 70 mm into it, a restricted zone the post stands in, a cabinet 1 m east
    of the post standing on the slab, and a duct crossing the zone 2.5 m up."""
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="supports")
    ifcopenshell.api.run("unit.assign_unit", model, units=[ifcopenshell.api.run("unit.add_si_unit", model,
                                                                              unit_type="LENGTHUNIT")])
    ctx = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model", context_identifier="Body",
                                target_view="MODEL_VIEW", parent=ctx)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Floor")
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, products=[storey])

    def element(cls, name, size, origin):
        e = ifcopenshell.api.run("root.create_entity", model, ifc_class=cls, name=name)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, products=[e])
        _box(model, body, e, size, origin)
        return e
    element("IfcSlab", "Floor slab", (8.0, 8.0, 0.2), (-4.0, -4.0, -0.2))
    element("IfcMember", "Fence post", (0.08, 0.08, 2.07), (0.0, 0.0, -0.07))
    element("IfcBuildingElementProxy", "Robot zone", (1.0, 1.0, 2.5), (-0.9, -0.5, 0.0))
    element("IfcFurnishingElement", "Cabinet", (0.6, 0.6, 1.8), (1.0, -0.3, 0.0))
    element("IfcDuctSegment", "Duct", (6.0, 0.3, 0.3), (-3.0, -0.15, 2.4))
    model.write(str(path))
    return path


@pytest.fixture
def cell(tmp_path):
    s = IfcScene(build(tmp_path / "s.ifc"))
    ids = {p.Name: p.GlobalId for p in s.products()}
    return s, ids


def test_a_post_slid_along_its_slab_keeps_its_footing(cell):
    s, ids = cell
    post, zone = ids["Fence post"], ids["Robot zone"]
    out, option = agent._try_move_fix(s, {"title": "west 0.3", "delta_m": [0.3, 0, 0]}, post, zone, 0.025)
    assert out.passed and option.min_clearance_m > 0.025   # its clearance is to what is near it, not the slab
    # the same move without knowing the clash is checked as before: the embedment counts
    out, _ = agent._try_move(s, {"title": "west 0.3", "delta_m": [0.3, 0, 0]}, post, 0.025)
    assert not out.passed and "IfcSlab" in out.reason


@pytest.mark.parametrize("delta,why", [
    ([0.3, 0, 0.15], "standing on nothing"),    # lifted off its slab: not buildable as drawn
    ([0.3, 0, -0.05], "sinks deeper"),          # pushed further into it
    ([1.2, 0, 0], "IfcFurnishingElement"),       # onto the cabinet: a clash like any other
])
def test_a_post_lifted_sunk_or_pushed_into_something_is_refused(cell, delta, why):
    s, ids = cell
    out, option = agent._try_move_fix(s, {"title": "t", "delta_m": delta}, ids["Fence post"], ids["Robot zone"], 0.025)
    assert not out.passed and option is None and why in out.reason


def test_the_clash_itself_is_never_what_it_stands_on(cell):
    s, ids = cell
    # a post-against-slab clash is not cleared by sliding the post along the slab
    out, _ = agent._try_move_fix(s, {"title": "west 0.3", "delta_m": [0.3, 0, 0]}, ids["Fence post"], ids["Floor slab"], 0.025)
    assert not out.passed and "IfcSlab" in out.reason


def test_runs_stand_on_nothing_and_the_plan_check_agrees(cell, tmp_path):
    s, ids = cell
    from sightline import verify
    assert verify.supports(s, [ids["Duct"]], {ids["Robot zone"]}, 0.025).standers == set()
    ws = Workspace(samples=tmp_path)
    ws.scenes["s"] = s
    post, zone = ids["Fence post"], ids["Robot zone"]
    ok = {"kind": "move", "moved": [post], "delta_m": [0.3, 0, 0]}
    lifted = {"kind": "move", "moved": [post], "delta_m": [0.3, 0, 0.15]}
    check = plans.verify_together(ws, "s", [plans.Item("k", post, zone, "", [], option=ok)])
    assert check["passed"]
    check = plans.verify_together(ws, "s", [plans.Item("k", post, zone, "", [], option=lifted)])
    assert not check["passed"] and "standing on nothing" in check["items"]["k"]["reason"]


def test_a_checked_move_keeps_its_footing_only_when_told_what_it_must_clear(cell, tmp_path):
    s, ids = cell
    ws = Workspace(samples=tmp_path)
    ws.scenes["s"] = s
    post, zone = ids["Fence post"], ids["Robot zone"]
    assert not ws.verify_move("s", [post], [0.3, 0, 0])["passed"]                       # every contact counts
    assert ws.verify_move("s", [post], [0.3, 0, 0], obstacles=[zone])["passed"]          # as a proposal checks it
    lifted = ws.verify_move("s", [post], [0.3, 0, 0.15], obstacles=[zone])
    assert not lifted["passed"] and "standing on nothing" in lifted["reason"]


def test_a_stand_touching_the_floor_keeps_touching_it_when_slid(cell):
    s, ids = cell
    # the cabinet stands on the slab (touching, inside the clearance): sliding it east is not a clash with the slab
    out, option = agent._try_move_fix(s, {"title": "east 1 m", "delta_m": [1.0, 0, 0]}, ids["Cabinet"], ids["Fence post"], 0.025)
    assert out.passed and (option.min_clearance_m is None or option.min_clearance_m > 0.025)
