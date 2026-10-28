import numpy as np
import pytest
import ifcopenshell.api
import ifcopenshell.util.system

from sightline import edits
from sightline.scene import IfcScene
from sightline.fixtures import build_clash_fixture, build_run_fixture
from sightline.service import Workspace


def fixture(tmp_path):
    scene = IfcScene(build_clash_fixture(tmp_path / 'clash.ifc'))
    return scene, {c: scene.model.by_type(c)[0].GlobalId for c in ('IfcDuctSegment', 'IfcBeam', 'IfcPipeSegment')}


def move(gid, delta):
    return dict(kind='move', element=gid, delta_m=delta, reason='Make room for the objective')


def test_single_blocked_compound_passes_and_snapshot_is_current(tmp_path):
    from sightline.context_eval import evaluate_candidate, commit_candidate
    scene, ids = fixture(tmp_path)
    a, b, c = [ids[k] for k in ('IfcDuctSegment', 'IfcBeam', 'IfcPipeSegment')]
    objective = dict(element_a=a, element_b=b)
    scene.bounds()
    before = scene.model.to_string()
    ops = [move(a, [0, 0, -.4]), move(c, [0, 0, -.4])]
    single = evaluate_candidate(scene, objective, ops[:1])
    assert not single['passed'] and single['checks']['geometry']['hits'][0]['other'] == c
    result = evaluate_candidate(scene, objective, ops)
    assert result['passed'], result
    assert scene.model.to_string() == before and scene.revision == 0 and not scene._edited
    kept = commit_candidate(scene, objective, ops)
    assert kept['passed'] and scene.revision == 1 and scene._edited == {0}
    clone = scene.snapshot()
    assert clone.model.to_string() == scene.model.to_string() and clone.revision == 1
    clone.translate([a], (1, 0, 0))
    assert not np.array_equal(clone.bounds()[a], scene.bounds()[a])


@pytest.mark.parametrize('mm', [False, True])
@pytest.mark.parametrize('lateral', [-.8, .8])
def test_lateral_preserves_external_endpoints_and_profile(tmp_path, mm, lateral):
    scene = IfcScene(build_run_fixture(tmp_path / 'run.ifc', millimetres=mm))
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    run = edits.run_of(scene, main)
    off = edits.apply_offset(scene, main, 2, 4, 0, lateral_m=lateral)
    assert off.lateral_m == lateral and off.corners == 'bends'
    assert edits.run_of(scene, off.pieces[0]).start == pytest.approx(run.start)
    assert edits.run_of(scene, off.pieces[-1]).end == pytest.approx(run.end)
    middle = edits.run_of(scene, off.pieces[len(off.pieces)//2])
    assert middle.start[1] == pytest.approx(lateral)
    assert (middle.depth_m, middle.width_m) == pytest.approx((.3, .4))
    assert scene.placement(edits._ports(scene.entity(off.pieces[0]))[0].GlobalId)[:3,3] == pytest.approx(run.start)
    assert scene.placement(edits._ports(scene.entity(off.pieces[-1]))[-1].GlobalId)[:3,3] == pytest.approx(run.end)


@pytest.mark.parametrize('bad', [
    [move('fabricated', [0, 0, 1])],
    [move('A', [0, float('nan'), 1])],
    [move('A', [0, 1])],
    [move('A', [0, 0, 1]), move('A', [0, 0, 2])],
    [move('A', [0, 0, 1])] * 4,
    [dict(kind='explode', element='A', reason='No')],
    [dict(kind='move', element='A', delta_m=[0,0,1])],
])
def test_invalid_candidates_fail_without_mutation(tmp_path, bad):
    from sightline.context_eval import evaluate_candidate, commit_candidate
    scene, ids = fixture(tmp_path)
    a, b = ids['IfcDuctSegment'], ids['IfcBeam']
    ops = [dict(o, element=a if o['element'] == 'A' else o['element']) for o in bad]
    before = scene.model.to_string()
    result = evaluate_candidate(scene, dict(element_a=a, element_b=b), ops)
    assert not result['passed'] and result['checks']['integrity']['errors']
    with pytest.raises(ValueError):
        commit_candidate(scene, dict(element_a=a, element_b=b), ops)
    assert scene.model.to_string() == before


def test_connected_move_groups_overlap_and_fitting_connection_break(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene = IfcScene(build_run_fixture(tmp_path / 'run.ifc'))
    main, end = scene.model.by_type('IfcDuctSegment')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    objective = dict(element_a=main.GlobalId, element_b=beam)
    r = evaluate_candidate(scene, objective, [move(main.GlobalId, [0,0,-1]), move(end.GlobalId, [0,0,-1])])
    assert not r['passed'] and 'overlap' in str(r['checks']['integrity']['errors']).lower()
    # A real fitting at the run boundary must not be silently excluded from integrity checking.
    fitting = ifcopenshell.api.run('root.create_entity', scene.model, ifc_class='IfcDuctFitting')
    port = ifcopenshell.api.run('system.add_port', scene.model, element=fitting)
    matrix = np.eye(4); matrix[:3, 3] = (7,0,2.8)
    ifcopenshell.api.run('geometry.edit_object_placement', scene.model, product=port, matrix=matrix)
    ifcopenshell.api.run('system.connect_port', scene.model, port1=edits._ports(end)[-1], port2=port)
    r = evaluate_candidate(scene, objective, [move(main.GlobalId, [0,0,-1])])
    assert not r['passed'] and 'connection' in str(r['checks']['integrity']['errors']).lower()


def test_structure_has_review_and_workspace_revisions(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene, ids = fixture(tmp_path)
    a, b = ids['IfcDuctSegment'], ids['IfcBeam']
    r = evaluate_candidate(scene, dict(element_a=a, element_b=b), [move(b, [0,0,1])])
    assert r['passed'] and any('structur' in x['id'] for x in r['review_conditions'])
    ws = Workspace(samples=tmp_path); ws.scenes['s'] = scene
    ws.apply('s', [b], [0,0,1])
    assert scene.revision == 1


@pytest.mark.parametrize('mm', [False, True])
def test_context_offset_checks_every_piece_and_exports(tmp_path, mm):
    from sightline.context_eval import evaluate_candidate, commit_candidate
    scene = IfcScene(build_run_fixture(tmp_path / 'run.ifc', millimetres=mm))
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    objective = dict(element_a=main, element_b=beam)
    op = dict(kind='offset', element=main, split_m=[2,4], delta_m=[0,0,.4], reason='Route over beam')
    original = scene.model.to_string()
    r = evaluate_candidate(scene,objective,[op])
    assert r['passed'], r
    assert scene.model.to_string() == original
    result = commit_candidate(scene,objective,[op])
    out = tmp_path / 'export'; out.mkdir()
    exported = IfcScene(scene.write_edited(out))
    assert len(exported.model.by_type('IfcDuctFitting')) == 4
    assert len(result['edits'][0]['preview']) == 9
    assert edits.run_of(exported,result['pieces'][0][-1]).end == pytest.approx([6,0,2.8])


def test_connected_neighbour_penetration_is_not_excluded(tmp_path):
    from sightline import verify
    scene = IfcScene(build_run_fixture(tmp_path / 'run.ifc'))
    main, end = scene.model.by_type('IfcDuctSegment')
    scene.translate([end.GlobalId],(-.1,0,0))
    v = verify.check(scene,[main.GlobalId],exclude_connected=False,touching={end.GlobalId})
    assert any(h.other == end.GlobalId and h.kind == 'collision' for h in v.hits)


def test_three_groups_and_cross_file_rollback(tmp_path):
    from sightline.context_eval import evaluate_candidate, commit_candidate
    scene = IfcScene([build_clash_fixture(tmp_path / 's.ifc', only=('beam',)),
                      build_clash_fixture(tmp_path / 'm.ifc', millimetres=True, only=('duct','pipe'))])
    a = scene.models[1].by_type('IfcDuctSegment')[0].GlobalId
    b = scene.models[0].by_type('IfcBeam')[0].GlobalId
    c = scene.models[1].by_type('IfcPipeSegment')[0].GlobalId
    objective = dict(element_a=a,element_b=b)
    scene.bounds()
    state = [m.to_string() for m in scene.models]
    boxes = {g:v.copy() for g,v in scene.bounds().items()}
    bad = [move(a,[0,0,-.4]),move(b,[0,0,-.4])]
    with pytest.raises(ValueError):
        commit_candidate(scene,objective,bad)
    assert [m.to_string() for m in scene.models] == state and scene.revision == 0
    assert all(np.array_equal(v,scene.bounds()[g]) for g,v in boxes.items()) and not scene._edited
    three = [move(a,[0,0,-.4]),move(c,[0,0,-.4]),move(b,[0,0,1])]
    assert evaluate_candidate(scene,objective,three)['passed']
    result = commit_candidate(scene,objective,three)
    assert result['files'] == [0,1] and scene.revision == 1
    out = tmp_path/'out'; out.mkdir()
    loaded = IfcScene(scene.write_edited(out))
    assert loaded.placement(a)[:3,3] == pytest.approx(scene.placement(a)[:3,3])


def test_discovery_restriction_and_slender_trim_gate(tmp_path):
    from sightline.context_eval import evaluate_candidate
    from sightline.fixtures import build_joint_fixture
    scene, ids = fixture(tmp_path)
    a,b = ids['IfcDuctSegment'],ids['IfcBeam']
    assert not evaluate_candidate(scene,dict(element_a=a,element_b=b),[move(a,[0,0,-1])],discovered={b})['passed']
    scene = IfcScene(build_joint_fixture(tmp_path/'j.ifc'))
    panel = scene.model.by_type('IfcPlate')[0].GlobalId
    transom = next(e.GlobalId for e in scene.model.by_type('IfcMember') if e.Name.startswith('Transom'))
    r = evaluate_candidate(scene,dict(element_a=panel,element_b=transom),[
        dict(kind='trim',element=panel,end='end',by_m=.5,reason='Unsupported body cut')])
    assert not r['passed'] and 'slender' in str(r['checks']['integrity']['errors'])


def test_three_group_blocker_chain(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene, ids = fixture(tmp_path)
    a,b,c = [ids[k] for k in ('IfcDuctSegment','IfcBeam','IfcPipeSegment')]
    third = ifcopenshell.api.run('root.copy_class',scene.model,product=scene.entity(c))
    third.Representation = scene.entity(c).Representation
    scene.translate([third.GlobalId],(0,0,-.4))
    objective = dict(element_a=a,element_b=b)
    ops = [move(a,[0,0,-.4]),move(c,[0,0,-.4]),move(third.GlobalId,[0,0,-.4])]
    for count in (1,2):
        assert not evaluate_candidate(scene,objective,ops[:count])['passed']
    r = evaluate_candidate(scene,objective,ops)
    assert r['passed'], r


def test_discovered_run_closure_required(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main,end = scene.model.by_type('IfcDuctSegment')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    r = evaluate_candidate(scene,dict(element_a=main.GlobalId,element_b=beam),
                           [move(main.GlobalId,[0,0,-1])],discovered={main.GlobalId,beam})
    assert not r['passed'] and end.GlobalId in str(r['checks']['integrity']['errors'])


def test_exception_after_first_file_edit_leaves_live_models_unchanged(tmp_path):
    from sightline.context_eval import commit_candidate
    scene = IfcScene([build_clash_fixture(tmp_path/'s.ifc',only=('beam',)),build_run_fixture(tmp_path/'m.ifc')])
    main = next(e.GlobalId for e in scene.models[1].by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    beam = scene.models[0].by_type('IfcBeam')[0].GlobalId
    state = [m.to_string() for m in scene.models]
    ops = [move(beam,[0,0,10]),dict(kind='offset',element=main,split_m=[.01,4],delta_m=[0,0,.4],reason='Invalid short piece')]
    with pytest.raises(ValueError,match='shorter'):
        commit_candidate(scene,dict(element_a=main,element_b=beam),ops)
    assert [m.to_string() for m in scene.models] == state and scene.revision == 0 and not scene._edited


def test_joint_system_mismatch_rejects_even_when_geometry_clears(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main,end = scene.model.by_type('IfcDuctSegment')
    for element in (main,end):
        service = ifcopenshell.api.run('system.add_system',scene.model)
        ifcopenshell.api.run('system.assign_system',scene.model,products=[element],system=service)
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    r = evaluate_candidate(scene,dict(element_a=main.GlobalId,element_b=beam),[move(main.GlobalId,[0,0,-1])])
    assert not r['passed'] and 'system mismatch' in str(r['checks']['integrity']['errors'])


@pytest.mark.parametrize('mismatch', ['system', 'flow', 'profile'])
def test_missing_port_placement_does_not_hide_known_incompatibility(tmp_path, mismatch):
    from sightline.context_eval import evaluate_candidate
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main, end = scene.model.by_type('IfcDuctSegment')
    main_far, end_near = edits._ports(main)[-1], edits._ports(end)[0]
    end_near.ObjectPlacement = None
    if mismatch == 'system':
        for element in (main, end):
            service = ifcopenshell.api.run('system.add_system', scene.model)
            ifcopenshell.api.run('system.assign_system', scene.model, products=[element], system=service)
    elif mismatch == 'flow':
        main_far.FlowDirection = end_near.FlowDirection = 'SOURCE'
    else:
        edits._body(end)[1].SweptArea.XDim = .5
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    original = scene.model.to_string()
    result = evaluate_candidate(scene, dict(element_a=main.GlobalId, element_b=beam),
                                [move(main.GlobalId, [0, 0, -1])])
    assert result['checks']['geometry']['target_resolved']
    assert not result['passed'] and not result['checks']['integrity']['passed']
    assert f'{mismatch} mismatch' in str(result['checks']['integrity']['errors'])
    assert any(r['id'] == 'connection_metadata' for r in result['review_conditions'])
    assert scene.model.to_string() == original


def test_missing_port_placement_alone_remains_a_review_condition(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main, end = scene.model.by_type('IfcDuctSegment')
    edits._ports(end)[0].ObjectPlacement = None
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    result = evaluate_candidate(scene, dict(element_a=main.GlobalId, element_b=beam),
                                [move(main.GlobalId, [0, 0, -1])])
    assert result['passed'], result
    assert any(r['id'] == 'connection_metadata' for r in result['review_conditions'])


def test_baseline_conflicts_are_reported_but_target_must_resolve(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene, ids = fixture(tmp_path)
    a,b,c = [ids[k] for k in ('IfcDuctSegment','IfcBeam','IfcPipeSegment')]
    scene.translate([c],(0,0,.45))
    objective = dict(element_a=a,element_b=b)
    r = evaluate_candidate(scene,objective,[move(b,[0,0,1])])
    assert r['passed'] and r['checks']['geometry']['existing_conflicts']
    assert any(x['id'] == 'existing_conflicts' for x in r['review_conditions'])
    r = evaluate_candidate(scene,objective,[move(c,[0,0,-1])])
    assert not r['passed'] and not r['checks']['geometry']['target_resolved']


def test_collision_between_two_changed_groups_rejects(tmp_path):
    from sightline.context_eval import evaluate_candidate
    scene, ids = fixture(tmp_path)
    a,b,c = [ids[k] for k in ('IfcDuctSegment','IfcBeam','IfcPipeSegment')]
    r = evaluate_candidate(scene,dict(element_a=a,element_b=b),[move(a,[0,0,1]),move(c,[0,0,1.4])])
    assert not r['passed']
    assert any({h['element'],h['other']} == {a,c} for h in r['checks']['geometry']['hits'])


def test_workspace_offset_trim_batch_and_trials_revisions(tmp_path):
    from sightline import plans
    from sightline.fixtures import build_joint_fixture
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    ws = Workspace(samples=tmp_path); ws.scenes['s'] = scene
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    ws.check_offset('s',main,beam,[2,4],.4)
    assert scene.revision == 0
    ws.apply_offset('s',main,[2,4],.4)
    assert scene.revision == 1
    plans.apply(ws,'s',[dict(kind='move',moved=[beam],delta_m=[0,0,1])])
    assert scene.revision == 2
    joint = IfcScene(build_joint_fixture(tmp_path/'j.ifc')); ws.scenes['j'] = joint
    transom = next(e.GlobalId for e in joint.model.by_type('IfcMember') if e.Name.startswith('Transom'))
    ws.apply_trim('j',transom,'end',.06)
    assert joint.revision == 1


def test_internal_offset_pieces_are_checked_against_each_other(tmp_path):
    from sightline.context_eval import _findings
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    off = edits.apply_offset(scene,main,2,4,.4)
    # Deliberately corrupt real generated geometry: the middle now penetrates the first.
    middle = off.pieces[len(off.pieces)//2]
    scene.translate([middle],(-1,0,-.4))
    contacts = {frozenset((a,b)) for a,b in zip(off.pieces,off.pieces[1:])}
    hits,_ = _findings(scene,set(off.pieces),contacts)
    assert hits[frozenset((main,middle))]['kind'] == 'collision'


@pytest.mark.parametrize('delta', [[0,0,.1],[0,.5,.4],[.1,0,.4]])
def test_context_rejects_square_fallback_compound_and_along_run_offsets(tmp_path, delta):
    from sightline.context_eval import evaluate_candidate
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    r = evaluate_candidate(scene,dict(element_a=main,element_b=beam),[
        dict(kind='offset',element=main,split_m=[2,4],delta_m=delta,reason='Unsupported detour')])
    assert not r['passed'] and r['checks']['integrity']['errors']
