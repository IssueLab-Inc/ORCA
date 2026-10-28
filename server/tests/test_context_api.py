import json

import pytest

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


def test_failed_private_copy_commit_is_not_published(tmp_path, monkeypatch):
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


def test_chat_disconnect_cancels_history_after_progress_queue_saturates(tmp_path, monkeypatch):
    import asyncio
    import threading
    from sightline import owner
    ws, sid, obj, c = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    class Model:
        calls = 0
        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return dict(role='assistant', tool_calls=[dict(id=f't{i}', function=dict(
                    name='get_clash', arguments='{"clash_id":"missing"}')) for i in range(100)])
            entered.set(); assert release.wait(3)
            return dict(role='assistant', content='Cancelled answer must not be published')
    outer = Model()
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
        assert await asyncio.to_thread(entered.wait, 3)
        assert not captured[0].cancel.is_set()  # progress saturation alone does not cancel
        request.disconnected = True
        try:
            await asyncio.wait_for(anext(response.body_iterator), 3)
        except StopAsyncIteration:
            pass
    try:
        asyncio.run(disconnect())
    finally:
        release.set()
    for thread in threads: thread.join(3)
    assert all(not thread.is_alive() for thread in threads) and outer.calls == 2
    assert captured[0].cancel.is_set() and captured[0].queue.maxsize == 64
    assert len(next(iter(chat.sessions.values())).messages) == 1
    assert not event_type(request).cancel.is_set()  # independent requests have independent cancellation


def test_saturated_chat_trial_emits_release_workspace_lock_and_preserve_results(tmp_path, monkeypatch):
    import asyncio
    import threading
    from test_chat import Scripted as ChatScripted
    ws, sid, obj, _ = setup(tmp_path)
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3)]))
    rid = ws.open_report_sample('r').id
    class Request:
        async def is_disconnected(self): return False
    events = api._RequestEvents(Request())
    def propose(*args, on_event, **kwargs):
        with ws.lock:
            for i in range(1000):
                on_event(dict(type='trial', index=i, pieces=[]))
        return dict(options=[], attempts=[], understanding='Checked')
    monkeypatch.setattr(ws, 'propose', propose)
    chat = Chat(ws, ChatScripted([[('propose_fixes', {'clash_id': 'c0001'})], 'Finished']))
    def work():
        chat.turn(chat.session(None), 'Propose', Context(sid, rid), events.put, cancel=events.cancel)
        events.put(dict(type='context_event', event=dict(type='context_result', proposals=[])))
        events.put(dict(type='error', detail='Retained error'))
        events.put(dict(type='done')); events.put(None)
    thread = threading.Thread(target=work, daemon=True); thread.start(); thread.join(.5)
    # No consumer has started: real chat -> propose -> trial callbacks must not hold the lock.
    acquired = ws.lock.acquire(timeout=.5)
    if acquired: ws.lock.release()
    try:
        assert acquired and not thread.is_alive()
        assert events.queue.qsize() <= 64 and not events.cancel.is_set()
        async def drain(): return [json.loads(line) async for line in events.stream()]
        drained = asyncio.run(drain())
        assert [e['type'] for e in drained if e['type'] in {'proposal', 'message', 'context_event', 'error', 'done'}] == [
            'proposal', 'message', 'context_event', 'error', 'done']
        assert drained[-3]['event']['type'] == 'context_result'
    finally:
        events.cancel.set(); thread.join(2)


def test_canonical_event_overflow_explicitly_cancels_and_completes():
    import asyncio
    import threading
    class Request:
        async def is_disconnected(self): return False
    events = api._RequestEvents(Request())
    thread = threading.Thread(target=lambda: [events.put(dict(type='proposal', id=i)) for i in range(100)], daemon=True)
    thread.start(); thread.join(.5)
    try:
        assert not thread.is_alive() and events.cancel.is_set() and events.queue.qsize() <= 64
        async def drain(): return [json.loads(line) async for line in events.stream()]
        drained = asyncio.run(drain())
        assert drained[-1]['type'] == 'error' and 'cancel' in drained[-1]['detail'].lower()
    finally:
        events.cancel.set(); thread.join(2)


@pytest.mark.parametrize('views, overflow_at', [(60, None), (61, 'end'), (62, 'done'), (63, 'message')])
def test_chat_completion_overflow_never_publishes_cancelled_history(monkeypatch, views, overflow_at):
    import asyncio
    from sightline.service import Workspace
    from test_chat import Scripted as ChatScripted
    ws = Workspace()
    chat = Chat(ws, ChatScripted([[('set_view', {'mode': 'xray'})] * views, 'Finished']))
    session = chat.session(None); before = list(session.messages)
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, '_chat', chat)
    monkeypatch.setattr(api, 'chat_limit', ProposeLimit())
    captured, threads, event_type, spawn = [], [], api._RequestEvents, owner.spawn
    class Events(event_type):
        overflow_at = None
        def __init__(self, request):
            super().__init__(request); captured.append(self)
        def put(self, event):
            was_cancelled = self.cancel.is_set()
            super().put(event)
            if not was_cancelled and self.cancel.is_set():
                self.overflow_at = 'end' if event is None else event['type']
    def tracked(work):
        thread = spawn(work); threads.append(thread); return thread
    monkeypatch.setattr(api, '_RequestEvents', Events); monkeypatch.setattr(owner, 'spawn', tracked)
    class Request:
        headers = {}; client = None
        async def is_disconnected(self): return False
    response = api.chat_turn(api.ChatTurn(message='Update views', session_id=session.id), Request())
    for thread in threads: thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    events = captured[0]
    assert events.overflow_at == overflow_at and events.queue.qsize() <= 64
    assert events.cancel.is_set() is (overflow_at is not None)
    async def drain(): return [json.loads(line) async for line in response.body_iterator]
    wire = asyncio.run(drain())
    if overflow_at:
        assert wire == [dict(type='error', detail='Request cancelled: too many unread result events. Please retry.')]
        assert session.messages == before and session._published_turn == 0
    else:
        assert [e['type'] for e in wire[-2:]] == ['message', 'done']
        assert session.messages[-1] == dict(role='assistant', content='Finished') and session._published_turn == 1


def test_successful_stream_can_drain_before_chat_history_publication(monkeypatch):
    import asyncio
    from sightline.service import Workspace
    from test_chat import Scripted as ChatScripted
    ws = Workspace(); chat = Chat(ws, ChatScripted(['Finished'])); session = chat.session(None)
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, '_chat', chat)
    monkeypatch.setattr(api, 'chat_limit', ProposeLimit())
    observed, wire, event_type = [], [], api._RequestEvents
    class Events(event_type):
        def put(self, event):
            super().put(event)
            if event is None and not observed:
                observed.append(session._published_turn)
                async def drain(): return [json.loads(line) async for line in self.stream()]
                wire.extend(asyncio.run(drain()))
                observed.append(self.cancel.is_set())
    monkeypatch.setattr(api, '_RequestEvents', Events)
    monkeypatch.setattr(owner, 'spawn', lambda work: work())
    class Request:
        headers = {}; client = None
        async def is_disconnected(self): return False
    api.chat_turn(api.ChatTurn(message='Hello', session_id=session.id), Request())
    assert observed == [0, False]
    assert [e['type'] for e in wire[-2:]] == ['message', 'done']
    assert session._published_turn == 1 and session.messages[-1]['content'] == 'Finished'


def test_immediate_followup_after_wire_completion_reads_the_completed_exchange():
    import asyncio
    import threading
    from sightline.service import Workspace
    inputs, errors = {}, []
    class Model:
        def chat(self, messages, tools):
            question = messages[-1]['content'].split('\n\n')[-1]
            inputs[question] = json.loads(json.dumps(messages))
            return dict(role='assistant', content='First answer' if question == 'First question' else 'Second answer')
    chat = Chat(Workspace(), Model()); session = chat.session(None)
    attempted = threading.Event()
    class SnapshotLock:
        # Expose the follow-up's actual snapshot-lock attempt without delaying a
        # lock holder. If free, retain the acquired lock until its snapshot is made.
        def __init__(self, lock): self.lock = lock
        def __enter__(self):
            acquired = self.lock.acquire(blocking=False)
            if threading.current_thread() is followup:
                attempted.set()
            if not acquired: self.lock.acquire()
        def __exit__(self, *args): self.lock.release()
    session._history_lock = SnapshotLock(session._history_lock)
    def resume():
        try:
            chat.turn(session, 'Follow up', Context(), lambda e: None)
        except Exception as exc:
            errors.append(exc)
    followup = threading.Thread(target=resume, daemon=True)
    class Request:
        async def is_disconnected(self): return False
    events = api._RequestEvents(Request()); wire = []
    def finish():
        events.put(dict(type='done')); events.put(None)
        async def drain(): return [json.loads(line) async for line in events.stream()]
        wire.extend(asyncio.run(drain()))
        assert wire[-2:] == [dict(type='message', text='First answer'), dict(type='done')]
        followup.start()
        assert attempted.wait(3)
    chat.turn(session, 'First question', Context(), events.put, cancel=events.cancel, before_publish=finish)
    followup.join(3)
    assert not followup.is_alive() and not errors and not events.cancel.is_set()
    prior = inputs['Follow up'][1:-1]
    assert len(prior) == 2 and prior[0]['content'].endswith('First question')
    assert prior[1] == dict(role='assistant', content='First answer')
    assert session._published_turn == 2 and len(session.messages) == 5
    assert session.messages[-1] == dict(role='assistant', content='Second answer')


@pytest.mark.parametrize('tool, args, units', [
    ('propose_fixes', {'clash_id': 'c0001'}, 1),
    ('explore_wider_fix', {'clash_id': 'c0001'}, 3),
    ('plan_fixes_together', {'clash_ids': ['c0001']}, 2),
    ('plan_root_cause', {'hub': 'hub'}, 3),
])
@pytest.mark.parametrize('owner_first', [False, True])
def test_interleaved_chat_requests_keep_their_own_allowance(tmp_path, monkeypatch, tool, args, units, owner_first):
    import asyncio
    import threading
    from types import SimpleNamespace
    from sightline import plans
    ws, sid, obj, _ = setup(tmp_path)
    root = tmp_path / 'reports' / 'r'; root.mkdir(parents=True)
    root.joinpath('report.xml').write_text(_report_xml([(obj['element_a'], obj['element_b'], -.3)]))
    rid = ws.open_report_sample('r').id
    entered, release = threading.Event(), threading.Event()
    class Model:
        def chat(self, messages, tools):
            if messages[-1]['role'] == 'tool':
                return dict(role='assistant', content='Finished')
            if messages[-1]['content'].endswith('First'):
                entered.set(); assert release.wait(3)
            return dict(role='assistant', tool_calls=[dict(id='charge', function=dict(name=tool, arguments=json.dumps(args)))])
    chat = Chat(ws, Model()); defaults = (chat.propose_allowed, chat.propose_allowed_many)
    monkeypatch.setattr(api, 'ws', ws); monkeypatch.setattr(api, '_chat', chat)
    allowance = ProposeLimit(6, 0); allowance.take_many('first', 6)
    monkeypatch.setattr(api, 'propose_limit', allowance); monkeypatch.setattr(api, 'chat_limit', ProposeLimit())
    monkeypatch.delenv('SIGHTLINE_TRUST_FORWARDED', raising=False)
    monkeypatch.setattr(ws, 'propose', lambda *a, **kw: dict(options=[], attempts=[], understanding='Checked'))
    monkeypatch.setattr(planner, 'build', lambda *a, **kw: dict(type='context_result', proposals=[]))
    monkeypatch.setattr(plans, 'pairs_for', lambda *a: ([(obj['element_a'], obj['element_b'])] * 2, []))
    plan = SimpleNamespace(root_cause='Cause', strategy='fix_partners', check={'passed': True}, items=[])
    monkeypatch.setattr(plans, 'build_batch', lambda *a: plan)
    def root_cause(*a, charge, **kw):
        assert charge(2) is None  # delayed edit charge must use the same visitor as the initial unit
        return plan
    monkeypatch.setattr(plans, 'build_root_cause', root_cause)
    monkeypatch.setattr(plans, 'to_json', lambda p: '{}')
    threads, spawn = [], owner.spawn
    def tracked(work):
        thread = spawn(work); threads.append(thread); return thread
    monkeypatch.setattr(owner, 'spawn', tracked)
    class Request:
        headers = {}
        def __init__(self, host): self.client = SimpleNamespace(host=host)
        async def is_disconnected(self): return False
    tokens = owner.enter(owner_first, '{"effort":"high"}')
    try:
        first = api.chat_turn(api.ChatTurn(message='First', scene_id=sid, report_id=rid), Request('first'))
    finally:
        owner.leave(tokens)
    try:
        assert entered.wait(3)
        second = api.chat_turn(api.ChatTurn(message='Second', scene_id=sid, report_id=rid), Request('second'))
        threads[1].join(3); assert not threads[1].is_alive()
    finally:
        release.set()
        for thread in threads: thread.join(3)
    async def drain(response): return [json.loads(line) async for line in response.body_iterator]
    first_events, second_events = asyncio.run(drain(first)), asyncio.run(drain(second))
    assert not any(thread.is_alive() for thread in threads)
    assert len(allowance._clients['first']) == 6 and len(allowance._clients['second']) == units
    assert (chat.propose_allowed, chat.propose_allowed_many) == defaults
    first_result = next(e for e in first_events if e['type'] == 'tool_result')
    assert first_result['summary'].startswith('refused') is not owner_first
    assert not next(e for e in second_events if e['type'] == 'tool_result')['summary'].startswith('refused')
