import json
import threading

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
