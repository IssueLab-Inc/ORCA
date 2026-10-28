import json
import threading

import pytest

from sightline import context_planner as planner
from sightline.fixtures import build_clash_fixture, build_run_fixture
from sightline.service import Workspace


def move(gid, delta):
    return dict(kind='move', element=gid, delta_m=delta, reason='Make space for the clash objective')


def setup(tmp_path):
    build_clash_fixture(tmp_path / 'clash.ifc')
    ws = Workspace(samples=tmp_path)
    sid = ws.open(['clash.ifc'])
    scene = ws.scene(sid)
    a, b, c = [scene.model.by_type(k)[0].GlobalId for k in ('IfcDuctSegment', 'IfcBeam', 'IfcPipeSegment')]
    return ws, sid, dict(element_a=a, element_b=b), c


class Scripted:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.messages = []
        self.timeouts = []

    def chat(self, messages, tools, *, timeout_s):
        self.messages.append(json.loads(json.dumps(messages)))
        self.timeouts.append(timeout_s)
        step = next(self.steps)
        if callable(step):
            step = step(messages)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, dict):
            return step
        if isinstance(step, str):
            return dict(role='assistant', content=step)
        return dict(role='assistant', tool_calls=[dict(id=f't{i}', type='function', function=dict(name=n, arguments=json.dumps(a)))
                                                  for i, (n, a) in enumerate(step)])


def evaluate(ops, title='Coordinated fix'):
    return ('evaluate_proposal', dict(title=title, operations=ops))


def test_real_blocker_feedback_compound_search_is_isolated(tmp_path):
    ws, sid, objective, c = setup(tmp_path)
    a = objective['element_a']
    before = ws.scene(sid).model.to_string()
    model = Scripted([[evaluate([move(a, [0, 0, -.4])])],
                      [('inspect_element', {'element': c})],
                      [evaluate([move(a, [0, 0, -.4]), move(c, [0, 0, -.4])])], 'Finished'])
    events = []
    result = planner.build(ws, sid, objective, events.append, model=model)
    assert result['type'] == 'context_result' and result['trials'] == 2 and result['model_calls'] == 4
    [proposal] = result['proposals']
    assert proposal['passed'] and len(proposal['edits']) == 2 and proposal['scene_revision'] == 0
    feedback = json.loads(model.messages[1][-1]['content'])
    assert not feedback['passed'] and c in feedback['discovered']
    assert c in str(feedback['checks']['geometry']['hits'])
    inspected = json.loads(model.messages[2][-1]['content'])
    assert inspected['global_id'] == c and inspected['bounds_m'] and inspected['capabilities']
    assert any(e['phase'] == 'blocked' for e in events)
    assert 0 < min(model.timeouts) <= max(model.timeouts) <= 120
    assert before == ws.scene(sid).model.to_string() and ws.scene(sid).revision == 0
    assert not ws.scene(sid)._edited


def test_limits_many_calls_dedup_and_structural_ranking(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    a, b = obj['element_a'], obj['element_b']
    service = [move(a, [0, 0, -.8])]
    model = Scripted([[evaluate([move(b, [0, 0, 1])], 'Structure'), evaluate(service, 'Service'),
                       evaluate([dict(service[0], reason='Same geometry')], 'Duplicate'),
                       evaluate([move(a, [0, 0, -1])], 'Untried')], 'Finished'])
    result = planner.build(ws, sid, obj, model=model, limits=planner.Limits(trials=3, model_calls=1))
    assert result['trials'] == 3 and result['model_calls'] == 1
    assert len(result['proposals']) == 2 and result['proposals'][0]['title'] == 'Service'


def test_model_failure_and_deadline_keep_earlier_passing_candidate(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    clock = [0.]
    def expire(messages):
        clock[0] = 121
        return TimeoutError('deadline')
    result = planner.build(ws, sid, obj, model=Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])], expire]),
                           clock=lambda: clock[0])
    assert len(result['proposals']) == 1 and result['model_calls'] == 2
    assert 'no solution' not in result['message'].lower()


def test_unseen_and_overlapping_run_are_rejected(tmp_path):
    build_run_fixture(tmp_path / 'run.ifc')
    ws = Workspace(samples=tmp_path)
    sid = ws.open(['run.ifc']); scene = ws.scene(sid)
    main, end = [e.GlobalId for e in scene.model.by_type('IfcDuctSegment')]
    obj = dict(element_a=main, element_b=scene.model.by_type('IfcBeam')[0].GlobalId)
    script = Scripted([[evaluate([move('fabricated', [0, 0, 1])]),
                        evaluate([move(main, [0, 0, -1]), move(end, [0, 0, -1])])], 'Done'])
    result = planner.build(ws, sid, obj, model=script)
    assert not result['proposals'] and result['trials'] == 2
    assert 'discovered' in script.messages[1][-2]['content']
    assert 'overlap' in script.messages[1][-1]['content']


def test_cancellation_does_not_store_proposals(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    cancel = threading.Event()
    def stop(messages):
        cancel.set()
        return [evaluate([move(obj['element_a'], [0, 0, -.8])])]
    result = planner.build(ws, sid, obj, model=Scripted([stop]), cancel=cancel)
    assert not result['proposals'] and not getattr(ws, '_context_proposals', {})


def test_pagination_and_inspection_expose_run_metadata(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    model = Scripted([[('inspect_neighbourhood', dict(element=obj['element_a'], offset=0, limit=1))], 'Done'])
    planner.build(ws, sid, obj, model=model)
    page = json.loads(model.messages[1][-1]['content'])
    assert page['total'] == 3 and page['next_offset'] == 1 and len(page['elements']) == 1
    item = page['elements'][0]
    assert {'bounds_m', 'run_members', 'systems', 'connections', 'capabilities', 'openings'} <= item.keys()


@pytest.mark.parametrize('profile_class, dimensions, supported', [
    ('IfcRectangleProfileDef', dict(XDim=.4, YDim=.3), True),
    ('IfcCircleProfileDef', dict(Radius=.15), True),
    ('IfcRectangleHollowProfileDef', dict(XDim=.4, YDim=.3, WallThickness=.01), False),
    ('IfcCircleHollowProfileDef', dict(Radius=.15, WallThickness=.01), False),
    ('IfcRoundedRectangleProfileDef', dict(XDim=.4, YDim=.3, RoundingRadius=.03), False),
    ('IfcUShapeProfileDef', dict(Depth=.3, FlangeWidth=.4, WebThickness=.01, FlangeThickness=.01), False),
])
def test_model_inspection_reports_truthful_offset_profile_capability(tmp_path, profile_class, dimensions, supported):
    from sightline import edits
    from sightline.scene import IfcScene

    source = IfcScene(build_run_fixture(tmp_path / 'run.ifc'))
    for element in source.model.by_type('IfcDuctSegment'):
        edits._body(element)[1].SweptArea = source.model.create_entity(
            profile_class, ProfileType='AREA', **dimensions)
    source.write(tmp_path / 'profile.ifc')
    ws = Workspace(samples=tmp_path)
    sid = ws.open(['profile.ifc'])
    scene = ws.scene(sid)
    main = next(e.GlobalId for e in scene.model.by_type('IfcDuctSegment') if e.Tag == 'SA-1')
    objective = dict(element_a=main, element_b=scene.model.by_type('IfcBeam')[0].GlobalId)
    before = scene.model.to_string()
    # Inspect both the initial model context and explicit tool reply, including the
    # complete run/move capability when an offset is known to lose profile topology.
    model = Scripted([[('inspect_element', dict(element=main))], 'Done'])
    result = planner.build(ws, sid, objective, model=model)
    assert not result['proposals']
    initial = json.loads(model.messages[0][1]['content'])['objective_elements'][0]
    reply = json.loads(model.messages[1][-1]['content'])
    for info in (initial, reply):
        assert ('offset' in info['capabilities']) is supported
        assert 'move' in info['capabilities'] and len(info['run_members']) == 2
        assert info['run']['length_m'] == pytest.approx(6)
        reasons = str(info['unsupported'])
        if supported:
            assert 'unsupported offset profile' not in reasons
        else:
            assert f'unsupported offset profile: {profile_class}' in reasons
            assert not info['openings']
    assert scene.model.to_string() == before and scene.revision == 0


def test_remote_blocker_becomes_eligible_only_after_real_geometry_discovers_it(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    ws.scene(sid).translate([c], (0, 0, -12.4))
    a = obj['element_a']
    model = Scripted([[evaluate([move(c, [0, 0, -.4])])],
                      [evaluate([move(a, [0, 0, -12.8])])],
                      [evaluate([move(a, [0, 0, -12.8]), move(c, [0, 0, -.4])])], 'Done'])
    result = planner.build(ws, sid, obj, model=model)
    assert 'not discovered' in model.messages[1][-1]['content']
    assert c in json.loads(model.messages[2][-1]['content'])['discovered']
    assert len(result['proposals']) == 1 and len(result['proposals'][0]['edits']) == 2


def test_complete_run_is_exposed_and_added_to_discovery(tmp_path):
    build_run_fixture(tmp_path / 'run.ifc')
    ws = Workspace(samples=tmp_path); sid = ws.open(['run.ifc']); scene = ws.scene(sid)
    main, end = [e.GlobalId for e in scene.model.by_type('IfcDuctSegment')]
    obj = dict(element_a=main, element_b=scene.model.by_type('IfcBeam')[0].GlobalId)
    inspection = planner.Inspection(scene, obj, .01)
    inspection.discovered = {main, obj['element_b']}
    op = [move(main, [0, 0, -1])]
    assert not planner.context_eval.evaluate_candidate(scene, obj, op, inspection.discovered)['passed']
    info = inspection.element(main)
    assert set(info['run_members']) == {main, end} and end in inspection.discovered
    assert info['connections'] and info['connections'][0]['frame_m'] is not None


def test_all_model_and_geometry_limits_are_enforced_and_no_model_call_holds_lock(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    def reply(messages):
        acquired = []
        def take():
            if ws.lock.acquire(timeout=.2):
                acquired.append(True); ws.lock.release()
        thread = threading.Thread(target=take); thread.start(); thread.join()
        assert acquired == [True]
        return [('inspect_element', {'element': obj['element_a']})]
    six = planner.build(ws, sid, obj, model=Scripted([reply] * 7))
    assert six['model_calls'] == 6 and six['trials'] == 0
    twelve = planner.build(ws, sid, obj, model=Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])] * 2] * 10))
    assert twelve['model_calls'] == 6 and twelve['trials'] == 12


def test_candidate_storage_is_bounded_and_detached_from_public_result(tmp_path, monkeypatch):
    ws, sid, obj, c = setup(tmp_path)
    monkeypatch.setattr(planner, 'MAX_STORED_PROPOSALS', 2)
    ids = []
    for _ in range(3):
        result = planner.build(ws, sid, obj, model=Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])], 'Done']))
        ids.append(result['proposals'][0]['id'])
    assert len(ws._context_proposals[sid]) == 2 and ids[0] not in ws._context_proposals[sid]
    result['proposals'][0]['edits'][0]['delta_m'] = [100, 100, 100]
    result['proposals'][0]['review_conditions'].clear()
    record = ws._context_proposals[sid][ids[-1]]
    assert record['operations'][0]['delta_m'] == [0, 0, -.8] and record['proposal']['review_conditions']


def test_request_timeout_is_local_and_owner_effort_is_preserved():
    import httpx
    from sightline.meta_client import MetaChatModel
    from sightline import owner
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': 'Done'}}]})
    model = MetaChatModel('https://example.invalid/v1', 'unused', 'model', timeout_s=90, reasoning_effort='low')
    model.client = httpx.Client(timeout=90, transport=httpx.MockTransport(respond))
    tokens = owner.enter(True, '{"effort":"high"}')
    try:
        model.chat([], [], timeout_s=2.5)
    finally:
        owner.leave(tokens)
    model.chat([], [])
    assert requests[0].extensions['timeout']['read'] == 2.5
    assert requests[1].extensions['timeout']['read'] == 90 and model.client.timeout.read == 90
    assert json.loads(requests[0].content)['reasoning_effort'] == 'high'
    assert json.loads(requests[1].content)['reasoning_effort'] == 'low'


def test_malformed_model_tool_reply_retains_prior_passing_candidate(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    result = planner.build(ws, sid, obj, model=Scripted([
        [evaluate([move(obj['element_a'], [0, 0, -.8])])],
        dict(role='assistant', tool_calls=[None])]))
    assert len(result['proposals']) == 1 and result['model_calls'] == 2


def test_translating_different_members_of_the_same_run_is_one_alternative(tmp_path):
    build_run_fixture(tmp_path / 'run.ifc')
    ws = Workspace(samples=tmp_path); sid = ws.open(['run.ifc']); scene = ws.scene(sid)
    main, end = [e.GlobalId for e in scene.model.by_type('IfcDuctSegment')]
    obj = dict(element_a=main, element_b=scene.model.by_type('IfcBeam')[0].GlobalId)
    model = Scripted([[evaluate([move(main, [0, 0, 1])]), evaluate([move(end, [0., 0., 1.])])], 'Done'])
    result = planner.build(ws, sid, obj, model=model)
    assert result['trials'] == 2 and len(result['proposals']) == 1


def test_long_seed_initial_pages_keep_the_clash_centre_for_either_objective(tmp_path):
    import ifcopenshell.api
    from sightline.fixtures import _box
    ws, sid, obj, c = setup(tmp_path)
    scene = ws.scene(sid)
    beam = scene.entity(obj['element_b'])
    profile = planner.edits._body(beam)[1].SweptArea
    profile.XDim = 100.
    profile.Position.Location.Coordinates = (50., .1)
    scene.translate([obj['element_a']], (87., 0., 0.))
    body = scene.model.by_type('IfcGeometricRepresentationSubContext')[0]
    for i in range(25):
        item = ifcopenshell.api.run('root.create_entity', scene.model, ifc_class='IfcBuildingElementProxy', name=f'Near {i}')
        _box(scene.model, body, item, (.1, .1, .1), (89.5 + i*.025, 1., 2.5))
    # This element fits the hard default 2.5 m search but must be excluded at the configured 1.25 m radius.
    outside = ifcopenshell.api.run('root.create_entity', scene.model, ifc_class='IfcBuildingElementProxy', name='Outside radius')
    _box(scene.model, body, outside, (.1, .1, .1), (90., 2., 2.5))
    scene._bounds = None
    model = Scripted([[('inspect_neighbourhood', dict(element=obj['element_a'], offset=20)),
                       ('inspect_neighbourhood', dict(element=obj['element_b'], offset=20))], 'Done'])
    planner.build(ws, sid, obj, model=model, limits=planner.Limits(radius_m=1.25))
    first = json.loads(model.messages[0][1]['content'])['neighbourhood']
    pages = [json.loads(m['content']) for m in model.messages[1][-2:]]
    expected = set(scene.bounds()) - {c, outside.GlobalId}
    assert first['total'] == len(expected) == 27 and first['next_offset'] == 20
    for page in pages:
        assert page['total'] == 27 and page['next_offset'] is None
        assert page['center_m'] == first['center_m'] and page['radius_m'] == first['radius_m'] == 1.25
        ids = [e['global_id'] for e in first['elements'] + page['elements']]
        assert len(ids) == len(set(ids)) == 27 and set(ids) == expected


def test_explicit_constraints_filter_only_the_affected_operation_and_run(tmp_path):
    import ifcopenshell.api
    from sightline.fixtures import build_context_fixture
    build_context_fixture(tmp_path / 'context.ifc')
    ws = Workspace(samples=tmp_path); sid = ws.open(['context.ifc']); scene = ws.scene(sid)
    ids = {e.Tag: e.GlobalId for e in scene.products()}
    obj = dict(element_a=ids['CTX-DUCT'], element_b=ids['CTX-BEAM'])
    inspection = planner.Inspection(scene, obj, 2.5)
    fixed = inspection.element(ids['CTX-BEAM'])
    assert fixed['constraints'] == ['KeepFixed'] and fixed['capabilities'] == []
    assert 'KeepFixed' in ' '.join(fixed['unsupported'])
    main = inspection.element(ids['CTX-DUCT'])
    assert 'move' in main['capabilities'] and 'offset' in main['capabilities']
    end = scene.entity(ids['CTX-END'])
    pset = ifcopenshell.api.run('pset.add_pset', scene.model, product=end, name='Pset_SightlineConstraints')
    ifcopenshell.api.run('pset.edit_pset', scene.model, pset=pset, properties={'KeepFixed': True})
    main = inspection.element(ids['CTX-DUCT'])
    assert 'move' not in main['capabilities'] and 'offset' in main['capabilities']
    assert main['run_constraints'][ids['CTX-END']] == ['KeepFixed']
    # Structural classes remain editable when no explicit constraint was authored.
    free_ws, free_sid, free_obj, _ = setup(tmp_path / 'free')
    free = planner.Inspection(free_ws.scene(free_sid), free_obj, 2.5).element(free_obj['element_b'])
    assert free['constraints'] == [] and 'move' in free['capabilities']


def test_cancellation_while_progress_is_backpressured_stops_the_next_expensive_step(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    for phase, expected_calls in [('thinking', 0), ('checking', 1)]:
        cancel = threading.Event()
        model = Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])]])
        def emit(event):
            if event['phase'] == phase: cancel.set()
        result = planner.build(ws, sid, obj, emit, model=model, cancel=cancel)
        assert result['model_calls'] == len(model.messages) == expected_calls and result['trials'] == 0


def test_cancellation_at_storage_boundary_publishes_no_proposal(tmp_path, monkeypatch):
    ws, sid, obj, c = setup(tmp_path)
    cancel = threading.Event(); store = planner._store
    def disconnect(*args, **kwargs):
        cancel.set()
        return store(*args, **kwargs)
    monkeypatch.setattr(planner, '_store', disconnect)
    result = planner.build(ws, sid, obj, model=Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])], 'Done']), cancel=cancel)
    assert not result['proposals'] and not getattr(ws, '_context_proposals', {})
