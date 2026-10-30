import json
import threading

import pytest

from fastapi.testclient import TestClient

from sightline import app as app_module
from sightline.chat import Chat, Context
from sightline.fixtures import build_run_fixture
from sightline.service import Workspace

from test_reports import GROUPED


class Scripted:
    """Stands in for Muse Spark: plays tool calls in order, then answers."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.seen = []

    def chat(self, messages, tools):
        self.seen.append(messages[-1])
        step = self.steps.pop(0)
        if isinstance(step, str):
            return {"role": "assistant", "content": step}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(step)]}


def _setup(tmp_path):
    build_run_fixture(tmp_path / "run.ifc")
    (tmp_path / "reports" / "r" / "c7").mkdir(parents=True)
    (tmp_path / "reports" / "r" / "report.xml").write_text(GROUPED)
    for n in ("A-transparent.png", "B-context.png", "C-alternate.png"):
        (tmp_path / "reports" / "r" / "c7" / n).write_bytes(b"\x89PNG")
    ws = Workspace(samples=tmp_path)
    return ws, ws.open(["run.ifc"]), ws.open_report_sample("r").id


def test_tools_run_and_images_reach_the_model(tmp_path):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted([
        [("report_summary", {}), ("list_clashes", {"query": "port"})],
        [("look_at_clash_images", {"clash_id": "c0001"}), ("show_clash", {"clash_id": "c0001"})],
        "Clash7 is a port touching a wall: not a real clash.",
    ])
    events = []
    chat = Chat(ws, model)
    s = chat.session(None)
    answer = chat.turn(s, "What is this one?", Context(sid, rid, "c0001"), events.append)

    assert answer.startswith("Clash7")
    kinds = [e["type"] for e in events]
    assert kinds.count("tool") == 4 and kinds[-1] == "message"
    assert {"type": "ui", "action": "select_clash", "clash_id": "c0001"} in events
    assert "the user has clash c0001 selected" in s.messages[1]["content"]
    images = model.seen[2]  # after the images tool, the next model call starts with the images
    assert images["role"] == "user" and sum(p["type"] == "image_url" for p in images["content"]) == 3


def test_tool_errors_go_back_to_the_model(tmp_path):
    ws, sid, rid = _setup(tmp_path)
    model = Scripted([[("get_clash", {"clash_id": "nope"})], "That clash does not exist."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "Tell me about nope", Context(sid, rid), events.append)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["summary"].startswith("failed")
    assert "error" in model.seen[1]["content"]


def test_chat_endpoint_streams_a_session_then_the_answer(tmp_path, monkeypatch):
    ws, sid, rid = _setup(tmp_path)
    monkeypatch.setattr(app_module, "ws", ws)
    monkeypatch.setattr(app_module, "_chat", Chat(ws, Scripted([[("set_view", {"mode": "xray"})], "Done."])))
    c = TestClient(app_module.app)
    r = c.post("/api/chat", json={"message": "x-ray please", "scene_id": sid, "report_id": rid})
    events = [json.loads(line) for line in r.text.splitlines()]
    assert events[0]["type"] == "session" and events[-1] == {"type": "done"}
    assert {"type": "ui", "action": "set_view", "mode": "xray"} in events
    assert any(e == {"type": "message", "text": "Done."} for e in events)


def test_chat_finds_root_causes_and_builds_a_plan(tmp_path):
    from test_plans import _setup as plan_setup

    ws, sid, rid, main, beam = plan_setup(tmp_path)
    model = Scripted([[("find_root_causes", {})], [("plan_fixes_together", {"clash_ids": ["c0001"]})], "Planned."])
    events = []
    chat = Chat(ws, model)
    chat.turn(chat.session(None), "fix c0001", Context(sid, rid), events.append)
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["kind"] == "batch" and plan["check"]["passed"]
    assert any(e["type"] == "plan_event" for e in events)
    result = next(e for e in events if e["type"] == "tool_result" and e["name"] == "plan_fixes_together")
    assert result["summary"] == "1 of 1 clash fixed, verified together"


@pytest.mark.parametrize('cancel_older', [True, False])
def test_immediate_resume_preserves_newer_history_when_older_model_returns_late(cancel_older):
    entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
    inputs, results, errors, old_events = {}, {}, [], []
    class Model:
        def chat(self, messages, tools):
            question = messages[-1]['content'].split('\n\n')[-1]
            inputs[question] = json.loads(json.dumps(messages))
            if question == 'Older question':
                entered.set()
                assert release.wait(5)
                return dict(role='assistant', content='Older answer')
            return dict(role='assistant', content='Newer answer')
    chat = Chat(Workspace(), Model()); session = chat.session(None)
    def old_turn():
        try:
            results['old'] = chat.turn(session, 'Older question', Context(), old_events.append, cancel=cancel)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=old_turn); thread.start()
    try:
        assert entered.wait(5)
        if cancel_older: cancel.set()
        # A resumed request finishes while the older model request remains blocked.
        results['new'] = chat.turn(session, 'Newer question', Context(), lambda e: None)
        completed = json.loads(json.dumps(session.messages))
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors
    assert results == {'old': '' if cancel_older else 'Older answer', 'new': 'Newer answer'}
    assert session.messages == completed
    assert len(completed) == 3 and completed[-1]['content'] == 'Newer answer'
    assert [m['role'] for m in inputs['Newer question']] == ['system', 'user']
    assert inputs['Newer question'][-1]['content'].endswith('Newer question')
    if cancel_older:
        assert not any(e['type'] == 'message' for e in old_events)


def test_final_emit_cancellation_cannot_publish_or_erase_a_newer_turn():
    cancel, entered, release = threading.Event(), threading.Event(), threading.Event()
    class Model:
        def chat(self, messages, tools):
            if messages[-1]['content'].endswith('Older question'):
                entered.set(); assert release.wait(3)
                return dict(role='assistant', content='Older answer')
            return dict(role='assistant', content='Newer answer')
    chat = Chat(Workspace(), Model()); session = chat.session(None); answers, errors = [], []
    def emit(event):
        if event['type'] == 'message':
            cancel.set()
    def old_turn():
        try:
            answers.append(chat.turn(session, 'Older question', Context(), emit, cancel=cancel))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=old_turn, daemon=True); thread.start()
    try:
        assert entered.wait(3)
        chat.turn(session, 'Newer question', Context(), lambda e: None)
        newer = json.loads(json.dumps(session.messages))
    finally:
        release.set(); thread.join(3)
    assert not thread.is_alive() and not errors and answers == [''] and session.messages == newer
    assert session._published_turn == 2 and session.messages[-1]['content'] == 'Newer answer'
