import json

from fastapi.testclient import TestClient
from sightline import app as api, context_planner as planner, owner
from sightline.chat import Chat, Context
from sightline.limits import ProposeLimit
from test_context_planner import Scripted, setup, move, evaluate
from test_plans import _report_xml


def client_setup(tmp_path, monkeypatch):
    ws, sid, obj, c = setup(tmp_path)
    monkeypatch.setattr(api, 'ws', ws)
    monkeypatch.setattr(api, 'propose_limit', ProposeLimit(6, 0))
    ws._model = Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])], 'Done'] * 3)
    return TestClient(api.app), ws, sid, obj, c


def stream(client, sid, obj):
    r = client.post(f'/api/scenes/{sid}/context/stream', json=obj)
    assert r.status_code == 200, r.text
    assert r.headers['content-encoding'] == 'identity'
    events = [json.loads(line) for line in r.text.splitlines()]
    assert any(e['type'] == 'context_progress' for e in events)
    return events[-1]


def test_stream_charges_three_once_and_preserves_owner_bypass(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    assert stream(client, sid, obj)['proposals']
    assert stream(client, sid, obj)['proposals']
    assert client.post(f'/api/scenes/{sid}/context/stream', json=obj).status_code == 429
    monkeypatch.setenv('SIGHTLINE_OWNER_TOKEN', 'x' * 40)
    owner_client = TestClient(api.app, base_url='https://testserver')
    owner_client.cookies.set(owner.COOKIE, owner.cookie_value())
    assert stream(owner_client, sid, obj)['proposals']


def test_accept_requires_canonical_id_all_acknowledgements_and_fresh_revision(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    proposal = stream(client, sid, obj)['proposals'][0]
    url = f'/api/scenes/{sid}/context/apply'
    assert client.post(url, json={'proposal_id': 'forged', 'acknowledged_conditions': []}).status_code == 404
    assert client.post(url, json={'proposal_id': proposal['id']}).status_code == 422
    assert client.post(url, json={'proposal_id': proposal['id'], 'acknowledged_conditions': []}).status_code == 422
    ack = [r['id'] for r in proposal['review_conditions']]
    assert client.post(url, json={'proposal_id': proposal['id'], 'acknowledged_conditions': ack + ['invented']}).status_code == 422
    assert client.post(url, json={'proposal_id': proposal['id'], 'acknowledged_conditions': ack, 'operations': []}).status_code == 422
    result = client.post(url, json={'proposal_id': proposal['id'], 'acknowledged_conditions': ack})
    assert result.status_code == 200, result.text
    assert result.json()['resolved_pairs'] == [obj] and ws.scene(sid).revision == 1
    assert client.post(url, json={'proposal_id': proposal['id'], 'acknowledged_conditions': ack}).status_code == 409


def test_optional_report_seed_must_match_and_only_confirmed_pairs_resolve(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3),
                                                     (c, obj['element_b'], -.1),
                                                     (obj['element_b'], obj['element_a'], -.3)]))
    rid = ws.open_report_sample('r').id
    before = ws.scene(sid).model.to_string()
    for bad in (dict(report_id=rid), dict(clash_id='c0001'), dict(report_id=rid, clash_id='c0002')):
        assert client.post(f'/api/scenes/{sid}/context/stream', json=obj | bad).status_code == 422
    proposal = stream(client, sid, obj | dict(report_id=rid, clash_id='c0001'))['proposals'][0]
    assert before == ws.scene(sid).model.to_string()
    response = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                           acknowledged_conditions=[r['id'] for r in proposal['review_conditions']]))
    assert response.status_code == 200, response.text
    pairs = response.json()['resolved_pairs']
    assert pairs == [obj]  # the other report pair never involved edited geometry


def test_failed_recheck_leaves_live_model_unchanged(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    proposal = stream(client, sid, obj)['proposals'][0]
    before = ws.scene(sid).model.to_string()
    def fail(*args, **kwargs):
        args[0].translate([obj['element_a']], (100, 0, 0))
        raise ValueError('Fresh geometry failed')
    monkeypatch.setattr(planner.context_eval, 'commit_candidate', fail)
    r = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                    acknowledged_conditions=[x['id'] for x in proposal['review_conditions']]))
    assert r.status_code == 409 and ws.scene(sid).model.to_string() == before
    assert ws.scene(sid).revision == 0


def test_chat_exploration_wraps_events_and_never_applies(tmp_path):
    ws, sid, obj, c = setup(tmp_path)
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3)]))
    rid = ws.open_report_sample('r').id
    ws._model = Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8])])], 'Done'])
    class ChatModel:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls > 1: return dict(role='assistant', content='Review the whole proposal.')
            return dict(role='assistant', tool_calls=[dict(id='wider', function=dict(name='explore_wider_fix', arguments='{"clash_id":"c0001"}'))])
    chat = Chat(ws, ChatModel()); charged = []
    chat.propose_allowed_many = lambda n: charged.append(n)
    events = []; before = ws.scene(sid).model.to_string()
    chat.turn(chat.session(None), 'Move surrounding objects too', Context(sid, rid), events.append)
    wrapped = [e['event'] for e in events if e['type'] == 'context_event']
    assert wrapped[-1]['type'] == 'context_result' and wrapped[-1]['proposals']
    assert charged == [3] and before == ws.scene(sid).model.to_string() and ws.scene(sid).revision == 0


def test_actual_fresh_geometry_failure_is_atomic(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    proposal = stream(client, sid, obj)['proposals'][0]
    scene = ws.scene(sid)
    # Simulate geometry becoming invalid even without relying on revision rejection.
    scene.translate([c], (0, 0, -.4))
    before = scene.model.to_string()
    r = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                    acknowledged_conditions=[x['id'] for x in proposal['review_conditions']]))
    assert r.status_code == 409 and scene.model.to_string() == before and scene.revision == 0


def test_accept_remeasures_additional_report_pairs_and_never_marks_blocked_pair(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3),
                                                     (obj['element_a'], c, -.1)]))
    rid = ws.open_report_sample('r').id
    proposal = stream(client, sid, obj | dict(report_id=rid, clash_id='c0001'))['proposals'][0]
    r = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                   acknowledged_conditions=[x['id'] for x in proposal['review_conditions']]))
    assert r.status_code == 200, r.text
    assert r.json()['resolved_pairs'] == [obj, dict(element_a=obj['element_a'], element_b=c)]


def test_unchanged_baseline_conflict_is_not_marked_resolved(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    ws.scene(sid).translate([c], (0, 0, .5))
    ws._model = Scripted([[evaluate([move(obj['element_a'], [0, 0, -.8]), move(c, [0, 0, -.8])])], 'Done'])
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3),
                                                     (obj['element_a'], c, -.1)]))
    rid = ws.open_report_sample('r').id
    proposal = stream(client, sid, obj | dict(report_id=rid, clash_id='c0001'))['proposals'][0]
    assert proposal['checks']['geometry']['existing_conflicts']
    r = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                   acknowledged_conditions=[x['id'] for x in proposal['review_conditions']]))
    assert r.status_code == 200, r.text
    assert r.json()['resolved_pairs'] == [obj]


def test_supported_butt_trim_marks_the_objective_resolved(tmp_path, monkeypatch):
    from sightline.fixtures import build_joint_fixture
    from sightline.service import Workspace
    build_joint_fixture(tmp_path / 'joint.ifc')
    ws = Workspace(samples=tmp_path); sid = ws.open(['joint.ifc']); scene = ws.scene(sid)
    main = next(e.GlobalId for e in scene.model.by_type('IfcMember') if e.Name.startswith('Transom'))
    other = next(e.GlobalId for e in scene.model.by_type('IfcMember') if e.Name.startswith('Mullion'))
    obj = dict(element_a=main, element_b=other)
    ws._model = Scripted([[evaluate([dict(kind='trim', element=main, end='end', by_m=.06, reason='Tidy the butt joint')])], 'Done'])
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, 'propose_limit', ProposeLimit(0, 0))
    client = TestClient(api.app)
    proposal = stream(client, sid, obj)['proposals'][0]
    response = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                           acknowledged_conditions=[x['id'] for x in proposal['review_conditions']]))
    assert response.status_code == 200, response.text
    assert response.json()['resolved_pairs'] == [obj]


def test_fresh_review_conditions_must_also_be_acknowledged(tmp_path, monkeypatch):
    client, ws, sid, obj, c = client_setup(tmp_path, monkeypatch)
    proposal = stream(client, sid, obj)['proposals'][0]
    original = planner.context_eval.commit_candidate
    def fresh(*args, **kwargs):
        result = original(*args, **kwargs)
        result['review_conditions'].append(dict(id='new_evidence', message='Additional designer review is required'))
        return result
    monkeypatch.setattr(planner.context_eval, 'commit_candidate', fresh)
    before = ws.scene(sid).model.to_string()
    response = client.post(f'/api/scenes/{sid}/context/apply', json=dict(proposal_id=proposal['id'],
                           acknowledged_conditions=[x['id'] for x in proposal['review_conditions']]))
    assert response.status_code == 409 and ws.scene(sid).model.to_string() == before


def test_anchored_corridor_search_inspects_blocker_then_accepts_and_exports(tmp_path, monkeypatch):
    import ifcopenshell.api
    from sightline.fixtures import build_context_fixture
    from sightline.scene import IfcScene
    from sightline.service import Workspace
    build_context_fixture(tmp_path / 'context.ifc')
    ws = Workspace(samples=tmp_path); sid = ws.open(['context.ifc']); scene = ws.scene(sid)
    ids = {e.Tag: e.GlobalId for e in scene.products()}
    obj = dict(element_a=ids['CTX-DUCT'], element_b=ids['CTX-BEAM'])
    # An explicitly retained authored defect must remain visible and acknowledged.
    port = planner.edits._ports(scene.entity(ids['CTX-DUCT']))[0]
    frame = scene.placement(port.GlobalId)
    frame[:3, 2] *= -1; frame[:3, 1] *= -1
    ifcopenshell.api.run('geometry.edit_object_placement', scene.model, product=port, matrix=frame, is_si=True)
    offset = dict(kind='offset', element=ids['CTX-DUCT'], split_m=[2, 4], delta_m=[0, 0, .4],
                  reason='Use the upper route while retaining anchored external endpoints')
    model = Scripted([[('inspect_element', {'element': ids['CTX-DUCT']})], [evaluate([offset])],
                      [('inspect_element', {'element': ids['CTX-TRAY']})],
                      [evaluate([offset, move(ids['CTX-TRAY'], [0, .35, 0])])], 'Done'])
    ws._model = model
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, 'propose_limit', ProposeLimit(0, 0))
    client = TestClient(api.app); before = scene.model.to_string()
    result = stream(client, sid, obj)
    blocked = json.loads(model.messages[2][-1]['content'])
    assert not blocked['passed'] and ids['CTX-TRAY'] in blocked['discovered']
    assert json.loads(model.messages[3][-1]['content'])['global_id'] == ids['CTX-TRAY']
    [proposal] = result['proposals']
    assert proposal['passed'] and len(proposal['edits']) == 2 and proposal['checks']['integrity']['passed']
    assert scene.model.to_string() == before and scene.revision == 0
    ack = [r['id'] for r in proposal['review_conditions']]
    assert 'legacy_port_frames' in ack
    url = f'/api/scenes/{sid}/context/apply'
    assert client.post(url, json=dict(proposal_id=proposal['id'], acknowledged_conditions=[x for x in ack if x != 'legacy_port_frames'])).status_code == 422
    accepted = client.post(url, json=dict(proposal_id=proposal['id'], acknowledged_conditions=ack))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['resolved_pairs'] == [obj] and scene.revision == 1
    exported = client.get(f'/api/scenes/{sid}/export')
    assert exported.status_code == 200
    path = tmp_path / 'accepted.ifc'; path.write_bytes(exported.content)
    loaded = IfcScene(path)
    assert len(loaded.model.by_type('IfcDuctFitting')) == 6
    assert loaded.bounds()[ids['CTX-TRAY']][0][1] > .29


def test_chat_disconnect_cancels_nested_search_before_trials_or_storage(tmp_path, monkeypatch):
    import asyncio
    import threading
    from sightline import owner
    from test_chat import Scripted as ChatScripted
    ws, sid, obj, c = setup(tmp_path)
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3)]))
    rid = ws.open_report_sample('r').id
    entered, release = threading.Event(), threading.Event()
    effort = []
    def waiting(messages):
        effort.append(owner.effort()); entered.set()
        assert release.wait(3)
        return [evaluate([move(obj['element_a'], [0, 0, -.8])])]
    nested = Scripted([waiting]); ws._model = nested
    outer = ChatScripted([[('explore_wider_fix', {'clash_id': 'c0001'})], 'Should never be called'])
    chat = Chat(ws, outer)
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, '_chat', chat)
    threads = []; spawn = owner.spawn
    def tracked(work):
        thread = spawn(work); threads.append(thread); return thread
    monkeypatch.setattr(owner, 'spawn', tracked)
    class Request:
        headers = {}; client = None; disconnected = False
        async def is_disconnected(self): return self.disconnected
    request = Request()
    async def consume():
        response = api.chat_turn(api.ChatTurn(message='Move surrounding objects', scene_id=sid, report_id=rid), request)
        iterator = response.body_iterator
        while not entered.is_set():
            await asyncio.wait_for(anext(iterator), 3)
        request.disconnected = True
        try:
            await asyncio.wait_for(anext(iterator), 3)
        except StopAsyncIteration:
            pass
        release.set()
    tokens = owner.enter(True, '{"effort":"high"}')
    try:
        asyncio.run(consume())
    finally:
        release.set(); owner.leave(tokens)
    for thread in threads: thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert effort == ['high'] and len(nested.messages) == 1 and len(outer.seen) == 1
    assert not getattr(ws, '_context_proposals', {}) and not ws.scene(sid)._edited
    assert len(chat.sessions[next(iter(chat.sessions))].messages) == 1


def test_chat_disconnect_unblocks_a_producer_with_a_full_event_queue(tmp_path, monkeypatch):
    import asyncio
    import threading
    from sightline import owner
    from test_chat import Scripted as ChatScripted
    ws, sid, obj, c = setup(tmp_path)
    outer = ChatScripted([[('set_view', {'mode': 'xray'})] * 100, 'Should never be called'])
    chat = Chat(ws, outer)
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, '_chat', chat)
    full, captured, threads = threading.Event(), [], []
    event_type, spawn = api._RequestEvents, owner.spawn
    class Events(event_type):
        def __init__(self, request):
            super().__init__(request); captured.append(self)
        def put(self, event):
            if self.queue.full(): full.set()
            return super().put(event)
    def tracked(work):
        thread = spawn(work); threads.append(thread); return thread
    monkeypatch.setattr(api, '_RequestEvents', Events)
    monkeypatch.setattr(owner, 'spawn', tracked)
    class Request:
        headers = {}; client = None; disconnected = False
        async def is_disconnected(self): return self.disconnected
    request = Request()
    async def disconnect():
        response = api.chat_turn(api.ChatTurn(message='Show x-ray', scene_id=sid), request)
        assert await asyncio.to_thread(full.wait, 3)
        request.disconnected = True
        try:
            await asyncio.wait_for(anext(response.body_iterator), 3)
        except StopAsyncIteration:
            pass
    asyncio.run(disconnect())
    for thread in threads: thread.join(3)
    assert all(not thread.is_alive() for thread in threads) and len(outer.seen) == 1
    assert captured[0].cancel.is_set() and captured[0].queue.maxsize == 64
    assert not event_type(request).cancel.is_set()  # independent requests have independent cancellation
