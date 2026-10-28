import pytest
from sightline.scene import IfcScene
from sightline import context_eval


@pytest.mark.parametrize('mm',[False,True])
def test_constrained_corridor_requires_surrounding_tray_edit(tmp_path,mm):
    from sightline.fixtures import build_context_fixture
    scene = IfcScene(build_context_fixture(tmp_path/'context.ifc',millimetres=mm))
    ids = {e.Tag:e.GlobalId for e in scene.products()}
    main,beam,tray = (ids[k] for k in ('CTX-DUCT','CTX-BEAM','CTX-TRAY'))
    objective = dict(element_a=main,element_b=beam)
    def move(g,d):
        return dict(kind='move',element=g,delta_m=d,reason='Test constrained route')
    def offset(d):
        return dict(kind='offset',element=main,split_m=[2,4],delta_m=d,reason='Pass the beam')
    original = scene.model.to_string()
    candidates = [[move(beam,[0,0,10])], [move(main,[0,0,-1])],
                  [offset([0,0,-.6])], [offset([0,.8,0])], [offset([0,-.8,0])],
                  [offset([0,0,.8])], [offset([0,0,.4])],
                  [dict(kind='trim',element=main,end='end',by_m=3.2,reason='Remove crossing')],
                  [dict(kind='trim',element=main,end='start',by_m=3.2,reason='Remove crossing')]]
    for ops in candidates:
        result = context_eval.evaluate_candidate(scene,objective,ops)
        assert not result['passed'], (ops,result)
        assert scene.model.to_string() == original and scene.revision == 0
    assert context_eval.element_constraints(scene,beam) == ['KeepFixed']
    assert context_eval.element_constraints(scene,main) == []
    passing = [offset([0,0,.4]),move(tray,[0,.35,0])]
    result = context_eval.evaluate_candidate(scene,objective,passing)
    assert result['passed'],result
    assert scene.model.to_string() == original
    committed = context_eval.commit_candidate(scene,objective,passing)
    output = tmp_path/'export'; output.mkdir()
    loaded = IfcScene(scene.write_edited(output))
    assert loaded.entity(tray) and len(committed['pieces'][0]) == 9 and scene.revision == 1
    from sightline import edits, verify
    assert edits.run_of(loaded,committed['pieces'][0][0]).start == pytest.approx([0,0,2.8])
    assert edits.run_of(loaded,committed['pieces'][0][-1]).end == pytest.approx([6,0,2.8])
    for piece in committed['pieces'][0]:
        assert not any(hit.other == beam for hit in verify.check(loaded,[piece]).hits)
    assert context_eval.element_constraints(loaded,beam) == ['KeepFixed']


def test_fixed_constraint_checks_expanded_members_without_class_ban(tmp_path):
    import ifcopenshell.api
    from sightline.fixtures import build_run_fixture
    scene = IfcScene(build_run_fixture(tmp_path/'r.ifc'))
    main,end = scene.model.by_type('IfcDuctSegment')
    beam = scene.model.by_type('IfcBeam')[0]
    pset = ifcopenshell.api.run('pset.add_pset',scene.model,product=end,name='Pset_SightlineConstraints')
    ifcopenshell.api.run('pset.edit_pset',scene.model,pset=pset,properties={'KeepFixed':True})
    objective = dict(element_a=main.GlobalId,element_b=beam.GlobalId)
    op = dict(kind='move',element=main.GlobalId,delta_m=[0,0,-1],reason='Move connected run')
    result = context_eval.evaluate_candidate(scene,objective,[op])
    assert not result['passed'] and 'KeepFixed' in str(result['checks']['integrity']['errors'])
    assert context_eval.element_constraints(scene,beam.GlobalId) == []
    op.update(element=beam.GlobalId,delta_m=[0,0,-1])
    assert context_eval.evaluate_candidate(scene,objective,[op])['passed']
