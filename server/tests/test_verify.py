from pathlib import Path

import pytest

from sightline.fixtures import build_clash_fixture
from sightline.scene import IfcScene
from sightline import verify


@pytest.fixture
def scene(tmp_path: Path) -> IfcScene:
    return IfcScene(build_clash_fixture(tmp_path / "fixture.ifc"))


def duct(scene: IfcScene) -> str:
    return scene.model.by_type("IfcDuctSegment")[0].GlobalId


def test_original_position_collides_with_beam(scene):
    v = verify.check(scene, [duct(scene)])
    assert not v.passed
    assert [h.other_class for h in v.hits] == ["IfcBeam"]
    assert v.hits[0].kind == "collision"


def test_first_drop_clears_beam_but_lands_on_pipe(scene):
    scene.translate([duct(scene)], (0, 0, -0.40))
    v = verify.check(scene, [duct(scene)])
    assert not v.passed
    assert [h.other_class for h in v.hits] == ["IfcPipeSegment"]


def test_deeper_drop_passes_and_reports_true_gap(scene):
    scene.translate([duct(scene)], (0, 0, -0.82))
    v = verify.check(scene, [duct(scene)])
    assert v.passed
    assert v.min_clearance_m == pytest.approx(0.12, abs=0.005)


def test_moves_survive_write_and_reload(scene, tmp_path):
    gid = duct(scene)
    scene.translate([gid], (0.6, 0, 0))
    reloaded = IfcScene(scene.write(tmp_path / "edited.ifc"))
    assert reloaded.placement(gid)[:3, 3] == pytest.approx([3.4, -2.0, 2.65])


def test_millimetre_projects_work_in_metres(tmp_path):
    # Placements, moves and clearances are always metres, whatever the project unit.
    s = IfcScene(build_clash_fixture(tmp_path / "mm.ifc", millimetres=True))
    assert s.unit_scale == pytest.approx(0.001)
    assert s.placement(duct(s))[2, 3] == pytest.approx(2.65)
    s.translate([duct(s)], (0, 0, -0.82))
    reloaded = IfcScene(s.write(tmp_path / "mm-edited.ifc"))
    assert reloaded.placement(duct(reloaded))[2, 3] == pytest.approx(1.83)
    v = verify.check(reloaded, [duct(reloaded)])
    assert v.passed
    assert v.min_clearance_m == pytest.approx(0.12, abs=0.005)


def test_federated_files_clash_across_disciplines(tmp_path):
    structure = build_clash_fixture(tmp_path / "structure.ifc", millimetres=True, only=("beam",))
    services = build_clash_fixture(tmp_path / "services.ifc", only=("duct", "pipe"))
    s = IfcScene([structure, services])
    gid = s.models[1].by_type("IfcDuctSegment")[0].GlobalId
    assert s.element(gid).source == "services.ifc"
    assert [h.other_class for h in verify.check(s, [gid]).hits] == ["IfcBeam"]

    s.translate([gid], (0, 0, -0.82))
    s.mark_edited(gid)  # kept (trials move and move back without marking)
    v = verify.check(s, [gid])
    assert v.passed and v.min_clearance_m == pytest.approx(0.12, abs=0.005)
    written = s.write_edited(tmp_path)
    assert [p.name for p in written] == ["services.sightline.ifc"]  # the structure file is untouched


def test_neighbourhood_check_skips_far_elements(tmp_path):
    s = IfcScene(build_clash_fixture(tmp_path / "f.ifc"))
    gid = duct(s)
    s.translate([gid], (50, 0, 0))  # far from everything
    v = verify.check(s, [gid])
    assert v.passed and v.checked_against == 0 and v.min_clearance_m is None
