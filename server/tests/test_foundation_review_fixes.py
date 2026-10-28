"""Review reproductions use real IFC shapes, placements and exported port graphs."""
import ifcopenshell.api
import ifcopenshell.util.system as system
import numpy as np
import pytest

from sightline import context_eval, edits, verify
from sightline.fixtures import build_run_fixture
from sightline.scene import IfcScene
from sightline.service import Workspace


def run_scene(tmp_path, mm=False):
    scene = IfcScene(build_run_fixture(tmp_path / 'run.ifc', millimetres=mm))
    main = next(e for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    beam = scene.model.by_type('IfcBeam')[0]
    scene.translate([beam.GlobalId], (0, 10, 0))
    scene.translate([scene.model.by_type('IfcSlab')[0].GlobalId], (0, 10, 0))
    return scene, main, dict(element_a=main.GlobalId, element_b=beam.GlobalId)


def offset(gid, delta):
    return dict(kind='offset', element=gid, split_m=[2, 4], delta_m=delta, reason='Route around obstacle')


@pytest.mark.parametrize('delta,pipe', [([0, 0, .36], False), ([0, 0, -.36], False),
                                      ([0, .45, 0], False), ([0, 0, .12], True),
                                      ([0, 0, .31], False)])
def test_tight_generated_bends_pass_without_blanket_chain_exclusion(tmp_path, delta, pipe):
    scene, main, objective = run_scene(tmp_path)
    if pipe:
        main_id = main.GlobalId
        for duct in list(scene.model.by_type('IfcDuctSegment')):
            duct = ifcopenshell.api.run('root.reassign_class', scene.model, product=duct, ifc_class='IfcPipeSegment')
            edits._body(duct)[1].SweptArea = scene.model.create_entity('IfcCircleProfileDef', ProfileType='AREA', Radius=.05)
        main = scene.entity(main_id)
        scene.refresh_bounds([e.GlobalId for e in scene.model.by_type('IfcPipeSegment')])
    private = scene.snapshot()
    raw = edits.apply_offset(private, main.GlobalId, 2, 4, delta[2], lateral_m=delta[1])
    contacts = {frozenset((a, b)) for a, b in zip(raw.pieces, raw.pieces[1:])}
    raw_hits, _ = context_eval._findings(private, set(raw.pieces), contacts)
    assert raw_hits and all(hit['kind'] == 'clearance' for hit in raw_hits.values())
    result = context_eval.evaluate_candidate(scene, objective, [offset(main.GlobalId, delta)])
    assert result['passed'], result


@pytest.mark.parametrize('corruption', ['penetration_across_bend', 'unrelated_internal_clearance'])
def test_bend_allowance_keeps_hard_hits_and_unrelated_internal_clearances(tmp_path, corruption):
    scene, main, _ = run_scene(tmp_path)
    before = scene.snapshot()
    off = edits.apply_offset(scene, main.GlobalId, 2, 4, .36)
    result = dict(checks=dict(integrity=dict(passed=False, errors=[], warnings=[])), review_conditions=[])
    sources = {g: main.GlobalId for g in off.pieces}
    contacts = context_eval._integrity(before, scene, {main.GlobalId}, sources, result)
    allowed = contacts | context_eval._bend_clearances(scene, [off.pieces], contacts)
    assert frozenset((off.pieces[0], off.pieces[2])) in allowed
    if corruption == 'penetration_across_bend':
        other = off.pieces[2]
        scene.translate([other], (-.03, 0, -.03))
        kind = 'collision'
    else:
        other = off.pieces[4]
        scene.translate([other], (-1, 0, -.05))
        kind = 'clearance'
        assert frozenset((off.pieces[0], other)) not in allowed
    findings, _ = context_eval._findings(scene, set(off.pieces), allowed)
    assert findings[frozenset((off.pieces[0], other))]['kind'] == kind


def test_tight_offset_rejects_new_clearance_to_unrelated_external_service(tmp_path):
    scene, main, objective = run_scene(tmp_path)
    peer = next(e for e in scene.model.by_type('IfcDuctSegment') if e != main)
    obstacle = ifcopenshell.api.run('root.copy_class', scene.model, product=peer)
    obstacle.Representation = peer.Representation
    scene.translate([obstacle.GlobalId], (-3.5, .41, .36))
    result = context_eval.evaluate_candidate(scene, objective, [offset(main.GlobalId, [0, 0, .36])])
    assert not result['passed']
    assert any(h['other'] == obstacle.GlobalId and h['kind'] == 'clearance'
               for h in result['checks']['geometry']['hits'])


@pytest.mark.parametrize('delta', [[0, 1e-12, .4], [0, 1e-10, -.4], [0, .8, 1e-12], [1e-7, 0, .4]])
def test_negligible_offset_axis_noise_is_normalized(tmp_path, delta):
    scene, main, objective = run_scene(tmp_path)
    result = context_eval.evaluate_candidate(scene, objective, [offset(main.GlobalId, delta)])
    assert result['passed'], result
    assert result['edits'][0]['delta_m'] == [0, delta[1] if abs(delta[1]) > 1e-9 else 0,
                                          delta[2] if abs(delta[2]) > 1e-9 else 0]
    off = edits.apply_offset(scene, main.GlobalId, 2, 4, delta[2], lateral_m=delta[1])
    assert off.dz_m == (delta[2] if abs(delta[2]) > 1e-9 else 0)
    assert off.lateral_m == (delta[1] if abs(delta[1]) > 1e-9 else 0)
    middle = edits.run_of(scene, off.pieces[len(off.pieces) // 2])
    assert (middle.width_m, middle.depth_m) == pytest.approx((.4, .3))


@pytest.mark.parametrize('delta', [[1e-4, 0, .4], [0, 1e-5, .4], [0, .8, 1e-5]])
def test_meaningful_unrepresentable_offset_components_still_reject(tmp_path, delta):
    scene, main, objective = run_scene(tmp_path)
    result = context_eval.evaluate_candidate(scene, objective, [offset(main.GlobalId, delta)])
    assert not result['passed'] and result['checks']['integrity']['errors']


def single_port_scene(tmp_path, mm, endpoint, flow, reverse=False):
    scene, main, objective = run_scene(tmp_path, mm)
    model = scene.model
    peer_element = next(e for e in model.by_type('IfcDuctSegment') if e != main)
    ports = edits._ports(main)
    for port in ports:
        ifcopenshell.api.run('system.disconnect_port', model, port=port)
    if reverse:
        item = edits._body(main)[1]
        item.Position = model.createIfcAxis2Placement3D(
            model.createIfcCartesianPoint((6 / scene.unit_scale, 0., 2.8 / scene.unit_scale)),
            model.createIfcDirection((-1., 0., 0.)), model.createIfcDirection((0., -1., 0.)))
    run = edits.run_of(scene, main.GlobalId)
    target = np.array(run.start if endpoint == 'start' else run.end)
    kept = min(ports, key=lambda p: np.linalg.norm(scene.placement(p.GlobalId)[:3, 3] - target))
    discarded = next(p for p in ports if p != kept)
    ifcopenshell.api.run('root.remove_product', model, product=discarded)
    peer_ports = edits._ports(peer_element)
    # Put the external peer at the same endpoint, retaining its authored frame.
    peer = peer_ports[-1] if target[0] < 3 else peer_ports[0]
    shift = target - scene.placement(peer.GlobalId)[:3, 3]
    scene.translate([peer_element.GlobalId], tuple(shift))
    ifcopenshell.api.run('system.connect_port', model, port1=kept, port2=peer, direction=flow)
    kept.FlowDirection = flow
    peer.FlowDirection = {'SOURCE': 'SINK', 'SINK': 'SOURCE'}.get(flow, 'NOTDEFINED')
    kept.PredefinedType = peer.PredefinedType = 'DUCT'
    kept.SystemType = peer.SystemType = 'VENTILATION'
    scene.refresh_bounds([main.GlobalId])
    return scene, main, kept, peer, objective


@pytest.mark.parametrize('mm', [False, True])
@pytest.mark.parametrize('endpoint,flow,reverse', [('start', 'SINK', False), ('end', 'SOURCE', False),
                                                 ('start', 'NOTDEFINED', False), ('end', 'NOTDEFINED', False),
                                                 ('start', 'SOURCE', True), ('end', 'SINK', True)])
def test_single_authored_port_survives_legacy_offset_and_export(tmp_path, mm, endpoint, flow, reverse):
    scene, main, port, peer, _ = single_port_scene(tmp_path, mm, endpoint, flow, reverse)
    port_id, peer_id = port.GlobalId, peer.GlobalId
    frame, peer_frame = scene.placement(port_id).copy(), scene.placement(peer_id).copy()
    peer_flow = peer.FlowDirection
    relationships = {rel.GlobalId for rel in list(port.ConnectedTo) + list(port.ConnectedFrom)}
    ws = Workspace(samples=tmp_path); ws.scenes['s'] = scene
    ws.apply_offset('s', main.GlobalId, [2, 4], .4)
    assert scene.revision == 1
    loaded = IfcScene(scene.write(tmp_path / 'offset.ifc'))
    authored, external = loaded.entity(port_id), loaded.entity(peer_id)
    assert authored.FlowDirection == flow and external.FlowDirection == peer_flow
    assert (authored.PredefinedType, authored.SystemType) == ('DUCT', 'VENTILATION')
    assert (external.PredefinedType, external.SystemType) == ('DUCT', 'VENTILATION')
    assert system.get_connected_port(authored) == external
    assert {rel.GlobalId for rel in list(authored.ConnectedTo) + list(authored.ConnectedFrom)} == relationships
    np.testing.assert_allclose(loaded.placement(port_id), frame, atol=1e-9)
    np.testing.assert_allclose(loaded.placement(peer_id), peer_frame, atol=1e-9)
    owner = system.get_port_element(authored)
    run = edits.run_of(loaded, owner.GlobalId)
    assert frame[:3, 3] == pytest.approx(run.start if endpoint == 'start' else run.end)


def test_single_middle_port_rejects_without_changing_model(tmp_path):
    scene, main, port, _, _ = single_port_scene(tmp_path, False, 'end', 'SOURCE')
    frame = scene.placement(port.GlobalId); frame[0, 3] = 3
    ifcopenshell.api.run('geometry.edit_object_placement', scene.model, product=port, matrix=frame)
    original = scene.model.to_string()
    with pytest.raises(edits.Unsupported, match='endpoint'):
        edits.apply_offset(scene, main.GlobalId, 2, 4, .4)
    assert scene.model.to_string() == original


@pytest.mark.parametrize('endpoint', ['start', 'end'])
def test_context_single_port_offset_preserves_real_external_connection(tmp_path, endpoint):
    scene, main, port, peer, objective = single_port_scene(
        tmp_path, False, endpoint, 'SINK' if endpoint == 'start' else 'SOURCE')
    original = scene.model.to_string()
    result = context_eval.commit_candidate(scene, objective, [offset(main.GlobalId, [0, 0, .4])])
    assert result['passed'], result
    loaded = IfcScene(scene.write(tmp_path / 'context.ifc'))
    assert system.get_connected_port(loaded.entity(port.GlobalId)).GlobalId == peer.GlobalId
    assert scene.model.to_string() != original


@pytest.mark.parametrize('port_count', [0, 2])
def test_zero_and_two_port_sources_retain_generated_chain_behavior(tmp_path, port_count):
    scene, main, _ = run_scene(tmp_path)
    if not port_count:
        for port in list(system.get_ports(main)):
            ifcopenshell.api.run('root.remove_product', scene.model, product=port)
    off = edits.apply_offset(scene, main.GlobalId, 2, 4, .4)
    assert len(off.pieces) == 9
    for a, b in zip(off.pieces, off.pieces[1:]):
        assert b in scene.element(a).connected
    assert edits.run_of(scene, off.pieces[0]).start == pytest.approx([0, 0, 2.8])
    assert edits.run_of(scene, off.pieces[-1]).end == pytest.approx([6, 0, 2.8])


@pytest.mark.parametrize('profile', ['IfcRectangleHollowProfileDef', 'IfcRoundedRectangleProfileDef'])
def test_sat_fallback_requires_exact_plain_rectangle(tmp_path, profile):
    scene, main, _ = run_scene(tmp_path)
    sleeve = next(e for e in scene.model.by_type('IfcDuctSegment') if e != main)
    main_solid, sleeve_solid = edits._body(main)[1], edits._body(sleeve)[1]
    sleeve_solid.Position = main_solid.Position
    sleeve_solid.Depth = .5
    dims = dict(XDim=.8, YDim=.7, WallThickness=.02) if 'Hollow' in profile else dict(XDim=.8, YDim=.7, RoundingRadius=.1)
    sleeve_solid.SweptArea = scene.model.create_entity(profile, ProfileType='AREA', **dims)
    scene.refresh_bounds([sleeve.GlobalId])
    assert verify._rectangular_penetration(scene, main.GlobalId, sleeve.GlobalId) is None
    if 'Hollow' in profile:
        verdict = verify.check(scene, [main.GlobalId], exclude_connected=False)
        assert verdict.passed, verdict
        assert verdict.min_clearance_m == pytest.approx(.18, abs=.005)


def test_exact_solid_sat_still_detects_coplanar_penetration(tmp_path):
    scene, main, _ = run_scene(tmp_path)
    peer = next(e for e in scene.model.by_type('IfcDuctSegment') if e != main)
    scene.translate([peer.GlobalId], (-.1, 0, 0))
    assert verify._rectangular_penetration(scene, main.GlobalId, peer.GlobalId) == pytest.approx(.1)
    verdict = verify.check(scene, [main.GlobalId], exclude_connected=False)
    assert any(h.other == peer.GlobalId and h.kind == 'collision' for h in verdict.hits)
