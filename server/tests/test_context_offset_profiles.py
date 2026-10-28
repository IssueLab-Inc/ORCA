"""Real IFC coverage for the context offset generator's supported source profiles."""
import numpy as np
import pytest

from sightline import context_eval, edits
from sightline.fixtures import build_run_fixture
from sightline.scene import IfcScene


PROFILES = {
    'IfcRectangleProfileDef': dict(XDim=.4, YDim=.3),
    'IfcCircleProfileDef': dict(Radius=.15),
    'IfcRectangleHollowProfileDef': dict(XDim=.4, YDim=.3, WallThickness=.01),
    'IfcCircleHollowProfileDef': dict(Radius=.15, WallThickness=.01),
    'IfcRoundedRectangleProfileDef': dict(XDim=.4, YDim=.3, RoundingRadius=.03),
    'IfcUShapeProfileDef': dict(Depth=.3, FlangeWidth=.4, WebThickness=.01, FlangeThickness=.01),
}
UNSUPPORTED = list(PROFILES)[2:]


def profile_scene(tmp_path, profile_class, mm):
    scene = IfcScene(build_run_fixture(tmp_path / 'run.ifc', millimetres=mm))
    scale = 1000 if mm else 1
    for element in scene.model.by_type('IfcDuctSegment'):
        edits._body(element)[1].SweptArea = scene.model.create_entity(
            profile_class, ProfileType='AREA', **{k: v * scale for k, v in PROFILES[profile_class].items()})
    # Reload real IFC so bounds/geometry use the source profile, without stale caches.
    scene = IfcScene(scene.write(tmp_path / 'profile.ifc'))
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    objective = dict(element_a=main, element_b=scene.model.by_type('IfcBeam')[0].GlobalId)
    return scene, objective


@pytest.mark.parametrize('mm', [False, True])
@pytest.mark.parametrize('profile_class', UNSUPPORTED)
def test_context_offset_rejects_unpreserved_profile_without_mutation(tmp_path, profile_class, mm):
    scene, objective = profile_scene(tmp_path, profile_class, mm)
    main = objective['element_a']
    # These are accepted legacy runs with real geometry, not unsupported body fixtures.
    assert edits.run_of(scene, main).length_m == pytest.approx(6)
    assert edits.meshes(scene, [main])[0]['faces']
    before = scene.model.to_string()
    bounds = {g: box.copy() for g, box in scene.bounds().items()}
    operation = dict(kind='offset', element=main, split_m=[2, 4], delta_m=[0, 0, .4], reason='Clear beam')
    result = context_eval.evaluate_candidate(scene, objective, [operation])
    assert not result['passed'], result
    errors = str(result['checks']['integrity']['errors'])
    assert 'unsupported offset profile' in errors.lower() and profile_class in errors
    assert not result['review_conditions']
    with pytest.raises(ValueError, match=f'unsupported offset profile: {profile_class}'):
        context_eval.commit_candidate(scene, objective, [operation])
    assert scene.model.to_string() == before and scene.revision == 0 and not scene._edited
    assert all(np.array_equal(box, scene.bounds()[g]) for g, box in bounds.items())


@pytest.mark.parametrize('profile_class', UNSUPPORTED)
def test_context_whole_run_move_preserves_profiles_unsupported_for_offsets(tmp_path, profile_class):
    scene, objective = profile_scene(tmp_path, profile_class, False)
    members = scene.connected_run(objective['element_a'])
    profiles = {g: edits._body(scene.entity(g))[1].SweptArea.get_info() for g in members}
    before = scene.model.to_string()
    operation = dict(kind='move', element=objective['element_a'], delta_m=[0, 0, -1], reason='Lower whole run')
    trial = context_eval.evaluate_candidate(scene, objective, [operation])
    assert trial['passed'], trial
    assert scene.model.to_string() == before and scene.revision == 0
    result = context_eval.commit_candidate(scene, objective, [operation])
    assert set(result['edits'][0]['moved']) == set(members) and scene.revision == 1
    loaded = IfcScene(scene.write(tmp_path / 'moved.ifc'))
    for gid in members:
        assert edits._body(loaded.entity(gid))[1].SweptArea.get_info() == profiles[gid]
        assert edits.run_of(loaded, gid).start[2] == pytest.approx(1.8)


@pytest.mark.parametrize('mm', [False, True])
@pytest.mark.parametrize('profile_class', list(PROFILES)[:2])
def test_context_plain_profiles_still_offset_and_export(tmp_path, profile_class, mm):
    scene, objective = profile_scene(tmp_path, profile_class, mm)
    operation = dict(kind='offset', element=objective['element_a'], split_m=[2, 4],
                     delta_m=[0, 0, .4], reason='Clear beam')
    before = scene.model.to_string()
    trial = context_eval.evaluate_candidate(scene, objective, [operation])
    assert trial['passed'], trial
    assert scene.model.to_string() == before and scene.revision == 0
    result = context_eval.commit_candidate(scene, objective, [operation])
    assert result['passed'] and scene.revision == 1
    loaded = IfcScene(scene.write(tmp_path / 'offset.ifc'))
    assert len(loaded.model.by_type('IfcDuctFitting')) == 4
    for element in loaded.model.by_type('IfcDuctSegment'):
        assert edits._body(element)[1].SweptArea.is_a() == profile_class
    assert edits.run_of(loaded, result['pieces'][0][-1]).end == pytest.approx([6, 0, 2.8])
