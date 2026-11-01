"""Adding and removing models in an open scene (docs/add-and-remove-models.md): the scene's own file list first."""
from pathlib import Path

import pytest

from sightline.fixtures import build_detection_fixtures
from sightline.scene import IfcScene


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
