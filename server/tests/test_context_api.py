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
