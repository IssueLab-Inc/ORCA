"""Port checks use exported IFC geometry, independently of the candidate verifier."""
import numpy as np
import pytest
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.system as system

from sightline import edits
from sightline.scene import IfcScene
from sightline.fixtures import build_run_fixture


def prepare(tmp_path, reverse=False, circular=False, mm=False, sideways=False):
    scene = IfcScene(build_run_fixture(tmp_path/'run.ifc', millimetres=mm))
    for element in scene.model.by_type('IfcDuctSegment'):
        if sideways and not circular:
            item = edits._body(element)[1]
            item.SweptArea.XDim, item.SweptArea.YDim = item.SweptArea.YDim, item.SweptArea.XDim
            item.Position.RefDirection = scene.model.createIfcDirection((0.,0.,1.))
        if circular:
            edits._body(element)[1].SweptArea = scene.model.createIfcCircleProfileDef('AREA',None,None,.15/scene.unit_scale)
        run = edits.run_of(scene,element.GlobalId)
        for index, port in enumerate(edits._ports(element)):
            port.FlowDirection = ('SOURCE','SINK')[index] if reverse else ('SINK','SOURCE')[index]
            matrix = np.eye(4)
            matrix[:3,2] = [-1 if reverse else 1,0,0]
            matrix[:3,0] = [0,0,1] if sideways and not circular else [0,1,0]
            matrix[:3,1] = np.cross(matrix[:3,2],matrix[:3,0])
            matrix[:3,3] = (run.start,run.end)[index]
            ifcopenshell.api.run('geometry.edit_object_placement',scene.model,product=port,matrix=matrix,is_si=True)
    return scene


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('lateral',[False,True])
@pytest.mark.parametrize('circular',[False,True])
@pytest.mark.parametrize('mm',[False,True])
@pytest.mark.parametrize('sideways',[False,True])
def test_exported_offset_flow_axes_follow_actual_cap_normals(tmp_path,reverse,lateral,circular,mm,sideways):
    scene = prepare(tmp_path,reverse,circular,mm,sideways)
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    off = edits.apply_offset(scene,main,2,4,0 if lateral else .4,lateral_m=.8 if lateral else 0)
    loaded = IfcScene(scene.write(tmp_path/'out.ifc'))
    settings = ifcopenshell.geom.settings(); settings.set('use-world-coords',True)
    for gid in off.pieces:
        shape = ifcopenshell.geom.create_shape(settings,loaded.entity(gid))
        verts = np.asarray(shape.geometry.verts).reshape(-1,3)
        triangles = verts[np.asarray(shape.geometry.faces).reshape(-1,3)]
        normals = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        normals /= np.linalg.norm(normals,axis=1)[:,None]
        for port in system.get_ports(loaded.entity(gid)):
            matrix = loaded.placement(port.GlobalId)
            outward = matrix[:3,2] * (-1 if port.FlowDirection == 'SINK' else 1)
            cap = np.all(np.abs((triangles-matrix[:3,3]) @ outward)<1e-6,axis=1)
            assert cap.any(), (gid,'axis does not describe a physical cap')
            assert np.all(normals[cap] @ outward > .999), (gid,port.FlowDirection,'wrong effective flow axis')
            if not circular:
                points = np.unique(triangles[cap].reshape(-1,3),axis=0)
                # The source profile X dimension is .4 m (.3 when sideways); cap geometry must
                # retain that dimension along RefDirection, including at bends.
                assert np.ptp(points @ matrix[:3,0]) == pytest.approx(.3 if sideways else .4,abs=1e-5)
            other = system.get_connected_port(port)
            if other is not None:
                partner = loaded.placement(other.GlobalId)
                assert matrix[:3,2] == pytest.approx(partner[:3,2])
                if not circular:
                    assert matrix[:3,0] == pytest.approx(partner[:3,0])


@pytest.mark.parametrize('fault',['none','axis','roll','circular_roll','both_axes','both_roll'])
def test_known_authored_frames_check_signed_axes_and_profile_roll(tmp_path,fault):
    from sightline.context_eval import evaluate_candidate
    scene = prepare(tmp_path,circular=fault=='circular_roll')
    main,end = scene.model.by_type('IfcDuctSegment')
    port = edits._ports(end)[0]
    matrix = scene.placement(port.GlobalId)
    if fault in ('axis','both_axes'):
        matrix[:3,2] *= -1
        matrix[:3,1] *= -1
    elif 'roll' in fault:
        matrix[:3,0],matrix[:3,1] = matrix[:3,1].copy(),-matrix[:3,0].copy()
    ifcopenshell.api.run('geometry.edit_object_placement',scene.model,product=port,matrix=matrix,is_si=True)
    if fault.startswith('both_'):
        peer = system.get_connected_port(port)
        peer_matrix = scene.placement(peer.GlobalId)
        peer_matrix[:3,:3] = matrix[:3,:3]
        ifcopenshell.api.run('geometry.edit_object_placement',scene.model,product=peer,matrix=peer_matrix,is_si=True)
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    result = evaluate_candidate(scene,dict(element_a=main.GlobalId,element_b=beam),[
        dict(kind='move',element=main.GlobalId,delta_m=[0,0,-1],reason='Clear beam')])
    if fault in ('axis','roll','both_axes','both_roll'):
        assert not result['passed'] and 'frame' in str(result['checks']['integrity']['errors'])
    else:
        assert result['passed'],result
        assert not any(r['id']=='port_frames' for r in result['review_conditions'])


@pytest.mark.parametrize('reverse',[False,True])
@pytest.mark.parametrize('circular',[False,True])
def test_generated_frames_pass_independent_verification(tmp_path,reverse,circular):
    from sightline.context_eval import evaluate_candidate
    scene = prepare(tmp_path,reverse,circular)
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag=='SA-1')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    result = evaluate_candidate(scene,dict(element_a=main,element_b=beam),[
        dict(kind='offset',element=main,split_m=[2,4],delta_m=[0,0,.4],reason='Clear beam')])
    assert result['passed'],result


@pytest.mark.parametrize('flow',['NOTDEFINED','SOURCEANDSINK'])
def test_unknown_or_bidirectional_frames_require_review(tmp_path,flow):
    from sightline.context_eval import evaluate_candidate
    scene = prepare(tmp_path)
    for element in scene.model.by_type('IfcDuctSegment'):
        for port in system.get_ports(element):
            port.FlowDirection = flow
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag=='SA-1')
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    result = evaluate_candidate(scene,dict(element_a=main,element_b=beam),[
        dict(kind='offset',element=main,split_m=[2,4],delta_m=[0,0,.4],reason='Clear beam')])
    assert result['passed'],result
    assert any(r['id']=='port_frames' for r in result['review_conditions'])


def test_offset_preserves_both_external_peers_flow_and_frames(tmp_path):
    from sightline.fixtures import build_context_fixture
    scene = IfcScene(build_context_fixture(tmp_path/'context.ifc'))
    main = next(e for e in scene.model.by_type('IfcDuctSegment') if e.Tag=='CTX-DUCT')
    peers = [system.get_connected_port(p) for p in edits._ports(main)]
    original = {p.GlobalId:(p.FlowDirection,scene.placement(p.GlobalId).copy()) for p in peers}
    edits.apply_offset(scene,main.GlobalId,2,4,.4)
    for gid,(flow,matrix) in original.items():
        assert scene.entity(gid).FlowDirection == flow
        assert scene.placement(gid) == pytest.approx(matrix)


@pytest.mark.parametrize('change',['unchanged','frame','endpoint','generated'])
def test_legacy_external_frame_exception_is_strictly_unchanged(tmp_path,change):
    from sightline.fixtures import build_context_fixture
    from sightline.context_eval import _integrity
    before = IfcScene(build_context_fixture(tmp_path/'context.ifc'))
    main = next(e for e in before.model.by_type('IfcDuctSegment') if e.Tag=='CTX-DUCT')
    port = edits._ports(main)[0]
    matrix = before.placement(port.GlobalId)
    matrix[:3,2] *= -1; matrix[:3,1] *= -1
    ifcopenshell.api.run('geometry.edit_object_placement',before.model,product=port,matrix=matrix,is_si=True)
    after = before.snapshot()
    off = edits.apply_offset(after,main.GlobalId,2,4,.4)
    if change in ('frame','endpoint'):
        target = after.entity(port.GlobalId)
        matrix = after.placement(target.GlobalId)
        if change=='frame':
            matrix[:3,0],matrix[:3,1] = matrix[:3,1].copy(),-matrix[:3,0].copy()
        else:
            matrix[0,3] += .05
        ifcopenshell.api.run('geometry.edit_object_placement',after.model,product=target,matrix=matrix,is_si=True)
    elif change=='generated':
        target = edits._ports(after.entity(off.pieces[1]))[0]
        matrix = after.placement(target.GlobalId); matrix[:3,2] *= -1; matrix[:3,1] *= -1
        ifcopenshell.api.run('geometry.edit_object_placement',after.model,product=target,matrix=matrix,is_si=True)
    result = dict(checks=dict(integrity=dict(errors=[],warnings=[])),review_conditions=[])
    _integrity(before,after,{main.GlobalId},{g:main.GlobalId for g in off.pieces},result)
    if change=='unchanged':
        assert result['checks']['integrity']['passed'],result
        assert result['checks']['integrity']['warnings']
        assert any(r['id']=='legacy_port_frames' for r in result['review_conditions'])
    else:
        assert not result['checks']['integrity']['passed'],result


@pytest.mark.parametrize('mismatch',['flow','system','profile'])
def test_legacy_frames_never_exempt_known_independent_constraints(tmp_path,mismatch):
    from sightline.context_eval import evaluate_candidate
    scene = prepare(tmp_path)
    main,end = scene.model.by_type('IfcDuctSegment')
    port = edits._ports(main)[-1]
    matrix = scene.placement(port.GlobalId); matrix[:3,2] *= -1; matrix[:3,1] *= -1
    ifcopenshell.api.run('geometry.edit_object_placement',scene.model,product=port,matrix=matrix,is_si=True)
    if mismatch=='flow':
        edits._ports(end)[0].FlowDirection = 'SOURCE'
    elif mismatch=='profile':
        edits._body(end)[1].SweptArea.XDim = .5
    else:
        for element in (main,end):
            service = ifcopenshell.api.run('system.add_system',scene.model)
            ifcopenshell.api.run('system.assign_system',scene.model,products=[element],system=service)
    beam = scene.model.by_type('IfcBeam')[0].GlobalId
    result = evaluate_candidate(scene,dict(element_a=main.GlobalId,element_b=beam),[
        dict(kind='offset',element=main.GlobalId,split_m=[2,4],delta_m=[0,0,.4],reason='Clear beam')])
    assert not result['passed'] and f'{mismatch} mismatch' in str(result['checks']['integrity']['errors'])


def test_profile_own_reference_direction_is_preserved_in_new_ports(tmp_path):
    import ifcopenshell.util.placement
    scene = prepare(tmp_path)
    for element in scene.model.by_type('IfcDuctSegment'):
        profile = edits._body(element)[1].SweptArea
        profile.Position = scene.model.createIfcAxis2Placement2D(
            scene.model.createIfcCartesianPoint((0.,0.)),scene.model.createIfcDirection((-1.,0.)))
        for port in edits._ports(element):
            matrix = scene.placement(port.GlobalId); matrix[:3,:2] *= -1
            ifcopenshell.api.run('geometry.edit_object_placement',scene.model,product=port,matrix=matrix,is_si=True)
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag=='SA-1')
    off = edits.apply_offset(scene,main,2,4,.4)
    loaded = IfcScene(scene.write(tmp_path/'out.ifc'))
    for gid in off.pieces:
        element = loaded.entity(gid)
        if not element.is_a('IfcDuctSegment'):
            continue
        solid = element.Representation.Representations[0].Items[0]
        world = (ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement) @
                 ifcopenshell.util.placement.get_axis2placement(solid.Position))
        direction = np.array(solid.SweptArea.Position.RefDirection.DirectionRatios)
        expected = world[:3,:2] @ direction
        for port in edits._ports(element):
            assert loaded.placement(port.GlobalId)[:3,0] == pytest.approx(expected)
